import logging
import os
from pathlib import Path
from typing import Any, Callable, Generator, List, Literal, Protocol, Tuple, TypeAlias

import pytest

from openwpm.config import BrowserParams, ManagerParams
from openwpm.mp_logger import MPLogger
from openwpm.storage.sql_provider import SQLiteStorageProvider
from openwpm.task_manager import TaskManager

from . import utilities
from .openwpmtest import NUM_BROWSERS

pytest_plugins = "test.storage.fixtures"

_BROWSER_CMDLINE_TOKENS = (
    "ms-playwright",
    "headless_shell",
    "playwright/driver",
    "chrome-linux",
    "Xvfb",
)


def _reap_leftover_browsers() -> None:
    """Kill Playwright/Chromium/Xvfb children left after a crashed manager.

    GitHub-hosted runners keep a step open until the job cgroup is idle, so a
    leaked browser after pytest has printed results looks like a 30m timeout.
    """
    try:
        import psutil
    except ImportError:
        return
    try:
        children = psutil.Process().children(recursive=True)
    except psutil.Error:
        return
    victims = []
    for child in children:
        try:
            blob = f"{child.name() or ''} {' '.join(child.cmdline() or [])}"
        except psutil.Error:
            continue
        if any(token in blob for token in _BROWSER_CMDLINE_TOKENS):
            victims.append(child)
    for child in victims:
        try:
            child.kill()
        except psutil.Error:
            pass
    if victims:
        psutil.wait_procs(victims, timeout=5)


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    _reap_leftover_browsers()


@pytest.fixture(scope="session", autouse=True)
def enable_subprocess_coverage():
    """Enable coverage collection in child processes when running under coverage."""
    try:
        import coverage

        # Only set this if we're actually measuring coverage
        if coverage.Coverage.current() is not None:
            project_root = Path(__file__).parent.parent
            os.environ["COVERAGE_PROCESS_START"] = str(project_root / "pyproject.toml")
            # Ensure child processes write .coverage files to the project
            # root where pytest-cov can find and combine them.
            os.environ["COVERAGE_FILE"] = str(project_root / ".coverage")
    except ImportError:
        pass


@pytest.fixture(scope="session", autouse=True)
def chromium_installed():
    from openwpm.browser_bin import require_chromium

    require_chromium()


@pytest.fixture(scope="session")
def server():
    """Run an HTTP server during the tests."""
    print("Starting local_http_server")
    server, server_thread = utilities.start_server()
    yield
    print("\nClosing server thread...")
    server.shutdown()
    server_thread.join()


FullConfig: TypeAlias = tuple[ManagerParams, list[BrowserParams]]


@pytest.fixture()
def default_params(tmp_path: Path, num_browsers: int = NUM_BROWSERS) -> FullConfig:
    """Just a simple wrapper around task_manager.load_default_params"""

    manager_params = ManagerParams(
        num_browsers=num_browsers
    )  # num_browsers is necessary to let TaskManager know how many browsers to spawn

    browser_params = [
        BrowserParams(display_mode="headless") for _ in range(num_browsers)
    ]
    manager_params.data_directory = tmp_path
    manager_params.log_path = tmp_path / "openwpm.log"
    manager_params.testing = True
    return manager_params, browser_params


TaskManagerCreator: TypeAlias = Callable[[FullConfig], Tuple[TaskManager, Path]]


@pytest.fixture()
def task_manager_creator(server: None, chromium_installed: None) -> TaskManagerCreator:
    """We create a callable that returns a TaskManager that has
    been configured with the Manager and BrowserParams"""

    # We need to create the fixtures like this because usefixtures doesn't work on fixtures
    def _create_task_manager(params: FullConfig) -> Tuple[TaskManager, Path]:
        manager_params, browser_params = params
        db_path = manager_params.data_directory / "crawl-data.sqlite"
        structured_provider = SQLiteStorageProvider(db_path)
        manager = TaskManager(
            manager_params,
            browser_params,
            structured_provider,
            None,
        )
        return manager, db_path

    return _create_task_manager


class HttpParams(Protocol):
    def __call__(
        self, display_mode: Literal["headless", "xvfb"] = "headless"
    ) -> FullConfig: ...


@pytest.fixture()
def http_params(
    default_params: FullConfig,
) -> HttpParams:
    manager_params, browser_params = default_params
    for browser_param in browser_params:
        browser_param.http_instrument = True

    def parameterize(
        display_mode: Literal["headless", "xvfb"] = "headless",
    ) -> FullConfig:
        for browser_param in browser_params:
            browser_param.display_mode = display_mode
        return manager_params, browser_params

    return parameterize


@pytest.fixture()
def mp_logger(tmp_path: Path) -> Generator[MPLogger, Any, None]:
    log_path = tmp_path / "openwpm.log"
    logger = MPLogger(log_path, log_level_console=logging.DEBUG)
    yield logger
    logger.close()
    # The performance hit for this might be unacceptable but it might help us discover bugs
    with log_path.open("r") as f:
        for line in f:
            assert "ERROR" not in line
