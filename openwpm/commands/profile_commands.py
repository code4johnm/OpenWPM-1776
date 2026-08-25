import logging
import tarfile
from pathlib import Path
from typing import Any, Optional

from openwpm.config import BrowserParamsInternal, ManagerParamsInternal

from ..browser import BrowserSession
from ..errors import ProfileLoadError
from .types import BaseCommand
from .utils.firefox_profile import sleep_until_sqlite_checkpoint

logger = logging.getLogger("openwpm")

# Chromium persistent-context markers. Cookies/History appear after first use.
REQUIRED_PROFILE_ITEMS = [
    "Default/Preferences",
    "Local State",
]

# Live (or leftover) Chromium lock/socket files. tarfile treats a unix
# socket as a regular file and read() blocks until GitHub cancels the job.
_SKIP_CHROMIUM_LOCK_FILES = frozenset(
    {
        "SingletonLock",
        "SingletonSocket",
        "SingletonCookie",
        "DevToolsActivePort",
    }
)


def _profile_tar_filter(tarinfo: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
    """Keep regular files and directories; drop locks, sockets, and devices."""
    if Path(tarinfo.name).name in _SKIP_CHROMIUM_LOCK_FILES:
        return None
    if tarinfo.isfile() or tarinfo.isdir():
        return tarinfo
    return None


def dump_profile(
    browser_profile_path: Path,
    tar_path: Path,
    compress: bool,
    browser_params: BrowserParamsInternal,
) -> None:
    """Dump a Chromium user-data-dir to a tar file. Call with the browser closed."""
    assert browser_params.browser_id is not None

    tar_path.parent.mkdir(exist_ok=True, parents=True)

    if tar_path.exists():
        tar_path.unlink()

    if compress:
        tar = tarfile.open(tar_path, "w:gz", errorlevel=1)
    else:
        tar = tarfile.open(tar_path, "w", errorlevel=1)
    logger.debug(
        "BROWSER %i: Backing up full profile from %s to %s"
        % (browser_params.browser_id, browser_profile_path, tar_path)
    )

    tar.add(browser_profile_path, arcname="", filter=_profile_tar_filter)
    archived_items = tar.getnames()
    tar.close()

    for item in REQUIRED_PROFILE_ITEMS:
        if item not in archived_items and not any(
            name == item or name.startswith(item + "/") for name in archived_items
        ):
            logger.critical(
                "BROWSER %i: %s NOT FOUND IN profile folder"
                % (browser_params.browser_id, item)
            )
            raise RuntimeError("Profile dump not successful")


class DumpProfileCommand(BaseCommand):
    def __init__(
        self, tar_path: Path, close_webdriver: bool, compress: bool = True
    ) -> None:
        self.tar_path = tar_path
        self.close_webdriver = close_webdriver
        self.compress = compress

    def __repr__(self) -> str:
        return "DumpProfileCommand({},{},{})".format(
            self.tar_path, self.close_webdriver, self.compress
        )

    def execute(
        self,
        webdriver: BrowserSession,
        browser_params: BrowserParamsInternal,
        manager_params: ManagerParamsInternal,
        extension_socket: Any,
    ) -> None:
        if self.close_webdriver:
            webdriver.close_context()
            sleep_until_sqlite_checkpoint(browser_params.profile_path)

        assert browser_params.profile_path is not None
        dump_profile(
            browser_params.profile_path,
            self.tar_path,
            self.compress,
            browser_params,
        )


def load_profile(
    browser_profile_path: Path,
    browser_params: BrowserParamsInternal,
    tar_path: Path,
) -> None:
    assert browser_params.browser_id is not None
    try:
        assert tar_path.is_file()
        if tar_path.name.endswith("tar.gz"):
            f = tarfile.open(tar_path, "r:gz", errorlevel=1)
        else:
            f = tarfile.open(tar_path, "r", errorlevel=1)
        f.extractall(browser_profile_path)
        f.close()
        logger.debug("BROWSER %i: Tarfile extracted" % browser_params.browser_id)

    except Exception as ex:
        logger.critical(
            "BROWSER %i: Error: %s while attempting to load profile"
            % (browser_params.browser_id, str(ex))
        )
        raise ProfileLoadError("Profile Load not successful")
