"""Playwright browser lifecycle with bounded retries and challenge detection."""

import json
import logging
import socket
import time
import urllib.request
from typing import Optional
from urllib.parse import urlparse, urlunparse

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, TimeoutError, sync_playwright

from config import settings

logger = logging.getLogger(__name__)

CHALLENGE_MARKERS = (
    "verify you are human",
    "checking your browser",
    "attention required",
    "captcha",
    "access denied",
    "请稍候",
)


class AccessBlockedError(RuntimeError):
    pass


class BrowserManager:
    def __init__(self):
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.owns_browser = False
        self.owns_context = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def start(self):
        if self.browser and self.browser.is_connected():
            return
        self.playwright = sync_playwright().start()
        if settings.browser_backend == "cdp":
            logger.info("Connecting to persistent Chrome over CDP: %s", settings.cdp_url)
            self.browser = self.playwright.chromium.connect_over_cdp(
                self._cdp_websocket_url(),
                timeout=settings.browser_timeout_ms,
            )
            self.context = self.browser.contexts[0] if self.browser.contexts else None
            if self.context is None:
                raise RuntimeError("Persistent Chrome has no browser context")
            self.owns_browser = False
            self.owns_context = False
            self.page = self._available_page()
        elif settings.browser_backend == "chromium":
            logger.info("Launching managed Playwright Chromium")
            self.browser = self.playwright.chromium.launch(headless=settings.headless)
            self.context = self.browser.new_context(
                viewport={"width": 1440, "height": 1000},
                locale="en-US",
            )
            self.owns_browser = True
            self.owns_context = True
            self.page = self.context.new_page()
        else:
            raise ValueError(f"Unsupported browser backend: {settings.browser_backend}")
        self.context.set_default_timeout(settings.browser_timeout_ms)

    def _cdp_websocket_url(self) -> str:
        endpoint = f"{settings.cdp_url.rstrip('/')}/json/version"
        request = urllib.request.Request(endpoint, headers={"Host": "localhost"})
        with urllib.request.urlopen(request, timeout=settings.browser_timeout_ms / 1000) as response:
            websocket_url = json.load(response)["webSocketDebuggerUrl"]
        endpoint = urlparse(settings.cdp_url)
        endpoint_ip = socket.gethostbyname(endpoint.hostname)
        endpoint_host = f"{endpoint_ip}:{endpoint.port}" if endpoint.port else endpoint_ip
        parsed_websocket = urlparse(websocket_url)
        return urlunparse(parsed_websocket._replace(netloc=endpoint_host))

    def _available_page(self) -> Page:
        pages = [page for page in self.context.pages if not page.is_closed()]
        return pages[0] if pages else self.context.new_page()

    def close(self):
        if self.owns_context and self.context:
            try:
                self.context.close()
            except Exception:
                pass
        if self.owns_browser and self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass
        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None
        self.owns_browser = False
        self.owns_context = False

    def ensure_page(self) -> Page:
        if not self.browser or not self.browser.is_connected():
            self.close()
            self.start()
        if self.page is None or self.page.is_closed():
            self.page = self.context.new_page()
        return self.page

    def reset_page(self) -> Page:
        previous_page = self.page
        self.page = self.context.new_page()
        if previous_page and not previous_page.is_closed():
            try:
                previous_page.close()
            except Exception:
                pass
        return self.page

    def navigate(self, url: str, required_selector: Optional[str] = None) -> Page:
        last_error = None
        for attempt in range(1, settings.max_retries + 1):
            page = self.ensure_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=settings.browser_timeout_ms)
                page.bring_to_front()
                if required_selector:
                    page.wait_for_selector(required_selector, state="attached", timeout=settings.browser_timeout_ms)
                else:
                    page.wait_for_selector("body", state="attached", timeout=settings.browser_timeout_ms)
                page.wait_for_timeout(settings.page_load_wait_ms)
                self._raise_if_blocked(page)
                return page
            except AccessBlockedError:
                raise
            except (TimeoutError, Exception) as error:
                last_error = error
                logger.warning("Navigation attempt %s failed for %s: %s", attempt, url, error)
                if attempt < settings.max_retries:
                    self.reset_page()
                    time.sleep(min(2 ** (attempt - 1), 8))
        raise RuntimeError(f"Navigation failed after {settings.max_retries} attempts: {last_error}")

    def _raise_if_blocked(self, page: Page):
        title = (page.title() or "").lower()
        try:
            body = page.locator("body").inner_text(timeout=3000)[:1500].lower()
        except Exception:
            body = ""
        combined = f"{title} {body}"
        marker = next((value for value in CHALLENGE_MARKERS if value in combined), None)
        if marker:
            raise AccessBlockedError(f"Access challenge detected: {marker}")
