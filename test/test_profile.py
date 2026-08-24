import logging
import tarfile
import time
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from openwpm.command_sequence import CommandSequence
from openwpm.commands.profile_commands import load_profile
from openwpm.commands.types import BaseCommand
from openwpm.config import BrowserParamsInternal
from openwpm.errors import CommandExecutionError, ProfileLoadError
from openwpm.utilities import db_utils

from . import openwpmtest
from .utilities import BASE_TEST_URL

# TODO update these tests to make use of blocking commands


def test_saving(default_params, task_manager_creator):
    manager_params, browser_params = default_params
    manager_params.num_browsers = 1
    browser_params[0].profile_archive_dir = (
        manager_params.data_directory / "browser_profile"
    )
    manager, _ = task_manager_creator((manager_params, browser_params[:1]))
    manager.get(BASE_TEST_URL)
    manager.close()
    tar_path = browser_params[0].profile_archive_dir / "profile.tar.gz"
    assert tar_path.is_file()
    # Test that the archived profile contains some basic items
    profile_items = [
        "Default/Preferences",
        "Local State",
    ]
    with tarfile.open(tar_path, "r:gz") as tar:
        archive_items = tar.getnames()
    for item in profile_items:
        assert item in archive_items or any(
            name == item or name.startswith(item + "/") for name in archive_items
        )


def test_save_incomplete_profile_error(default_params, task_manager_creator):
    manager_params, browser_params = default_params
    manager_params.num_browsers = 1
    browser_params[0].profile_archive_dir = (
        manager_params.data_directory / "browser_profile"
    )
    manager, _ = task_manager_creator((manager_params, browser_params[:1]))
    manager.get(BASE_TEST_URL)
    (manager.browsers[0].current_profile_path / "Default" / "Preferences").unlink()
    with pytest.raises(RuntimeError) as error:
        manager.close()
    assert str(error.value) == "Profile dump not successful"


def test_crash_profile(default_params, task_manager_creator):
    manager_params, browser_params = default_params
    manager_params.num_browsers = 1
    manager_params.failure_limit = 2
    browser_params[0].profile_archive_dir = (
        manager_params.data_directory / "browser_profile"
    )
    manager, _ = task_manager_creator((manager_params, browser_params[:1]))
    try:
        manager.get(BASE_TEST_URL)  # So we have a profile
        manager.get("example.com")  # Selenium requires scheme prefix
        manager.get("example.com")  # Selenium requires scheme prefix
        manager.get("example.com")  # Selenium requires scheme prefix
        manager.get("example.com")  # Requires two commands to shut down
    except CommandExecutionError:
        pass
    assert (browser_params[0].profile_archive_dir / "profile.tar.gz").is_file()


def test_profile_error(default_params, task_manager_creator):
    manager_params, browser_params = default_params
    manager_params.num_browsers = 1
    browser_params[0].seed_tar = Path("/tmp/NOTREAL")
    with pytest.raises(ProfileLoadError):
        task_manager_creator((manager_params, browser_params[:1]))


def test_profile_saved_when_launch_crashes(
    monkeypatch, default_params, task_manager_creator
):
    manager_params, browser_params = default_params
    manager_params.num_browsers = 1
    browser_params[0].profile_archive_dir = (
        manager_params.data_directory / "browser_profile"
    )
    manager, _ = task_manager_creator((manager_params, browser_params[:1]))
    manager.get(BASE_TEST_URL)

    # This will cause browser restarts to fail
    monkeypatch.setenv("OPENWPM_CHROMIUM_EXECUTABLE", "/tmp/NOTREAL")
    manager.browsers[0]._SPAWN_TIMEOUT = 2  # Have timeout occur quickly
    manager.browsers[0]._UNSUCCESSFUL_SPAWN_LIMIT = 2  # Quick timeout
    manager.get("example.com")  # Cause a selenium crash to force browser to restart

    try:
        manager.get(BASE_TEST_URL)
    except CommandExecutionError:
        pass
    manager.close()
    assert (browser_params[0].profile_archive_dir / "profile.tar.gz").is_file()


@pytest.mark.skip(reason="Firefox seed profile fixture retired with the Selenium stack")
def test_seed_persistence(default_params, task_manager_creator):
    pass


class AssertTitleCommand(BaseCommand):
    """Sanity command used by recovery tests — asserts the page loaded."""

    def execute(
        self,
        webdriver,
        browser_params,
        manager_params,
        extension_socket,
    ):
        assert webdriver.current_url


def test_dump_profile_command(default_params, task_manager_creator):
    """Test saving the browser profile using a command."""
    manager_params, browser_params = default_params
    manager_params.num_browsers = 1
    manager, _ = task_manager_creator((manager_params, browser_params[:1]))
    cs = CommandSequence(url=BASE_TEST_URL)
    cs.get()
    tar_path = manager_params.data_directory / "profile.tar.gz"
    cs.dump_profile(tar_path, True)
    manager.execute_command_sequence(cs)
    manager.close()
    assert tar_path.is_file()


def test_load_tar_file(tmp_path):
    """Test that load_profile does not delete or modify the tar file."""
    src = tmp_path / "seed_dir"
    src.mkdir()
    (src / "marker.txt").write_text("ok")
    tar_path = tmp_path / "profile.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(src, arcname="")
    profile_path = tmp_path / "browser_profile"
    browser_params = BrowserParamsInternal(browser_id=1)
    modified_time_before_load = tar_path.stat().st_mtime
    load_profile(profile_path, browser_params, tar_path)
    assert modified_time_before_load == tar_path.stat().st_mtime
    assert (profile_path / "marker.txt").read_text() == "ok"


def test_crash_during_init(default_params, task_manager_creator):
    """Test that no profile is saved when Task Manager initialization crashes."""
    manager_params, browser_params = default_params
    manager_params.num_browsers = 1
    browser_params[0].profile_archive_dir = (
        manager_params.data_directory / "browser_profile"
    )
    # This will cause the browser launch to fail
    browser_params[0].seed_tar = Path("/tmp/NOTREAL")
    with pytest.raises(ProfileLoadError):
        manager, _ = task_manager_creator((manager_params, browser_params[:1]))
    tar_path = browser_params[0].profile_archive_dir / "profile.tar.gz"
    assert not tar_path.is_file()


@pytest.mark.parametrize("stateful", [True, False], ids=["stateful", "stateless"])
@pytest.mark.parametrize(
    "testcase",
    ["on_normal_operation", "on_crash", "on_timeout"],
)
def test_profile_recovery(default_params, task_manager_creator, testcase, stateful):
    """Test browser profile dump after recovery scenarios."""
    manager_params, browser_params = default_params
    manager_params.num_browsers = 1
    manager, db = task_manager_creator((manager_params, browser_params[:1]))
    manager.get(BASE_TEST_URL, reset=not stateful)

    if testcase == "on_crash":
        manager.get("example.com", reset=not stateful)
    elif testcase == "on_timeout":
        manager.get(BASE_TEST_URL, reset=not stateful, timeout=0.1)

    cs = CommandSequence(BASE_TEST_URL, reset=not stateful)
    cs.get()
    tar_directory = manager_params.data_directory / "browser_profile"
    tar_path = tar_directory / "profile.tar.gz"
    cs.dump_profile(tar_path, True)
    manager.execute_command_sequence(cs)
    manager.close()
    assert tar_path.is_file()
