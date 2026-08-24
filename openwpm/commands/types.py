from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from ..config import BrowserParamsInternal, ManagerParamsInternal

if TYPE_CHECKING:
    from ..browser import BrowserSession
    from ..instrumentation.controller import MeasurementController


class BaseCommand(ABC):
    """
    Base class for all Commands in OpenWPM

    See `custom_command.py` for instructions on how
    to implement your own and `openwpm/commands` for
    all commands that are already implemented
    """

    visit_id: Any
    browser_id: Any
    start_time: float

    def set_visit_browser_id(self, visit_id, browser_id):
        self.visit_id = visit_id
        self.browser_id = browser_id

    def set_start_time(self, start_time):
        self.start_time = start_time

    @abstractmethod
    def execute(
        self,
        webdriver: "BrowserSession",
        browser_params: BrowserParamsInternal,
        manager_params: ManagerParamsInternal,
        extension_socket: "MeasurementController",
    ) -> None:
        """This method gets called in the Browser process

        :parameter webdriver: BrowserSession wrapping Playwright Chromium
            (``webdriver.page`` / ``webdriver.context`` are the raw APIs).
        :parameter browser_params: Contains the per browser configuration
            E.g. which instruments are enabled
        :parameter manager_params: Per crawl parameters E.g. where to store files
        :parameter extension_socket: Measurement controller (Initialize/Finalize
            plus storage). Named for historical command compatibility.
        """
        pass


class ShutdownSignal:
    def __repr__(self):
        return "ShutdownSignal()"
