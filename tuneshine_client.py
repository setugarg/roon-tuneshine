"""Tuneshine local HTTP API client with mDNS auto-discovery."""

from __future__ import annotations

import logging
import socket
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

MDNS_SERVICE = "_tuneshine._tcp.local."
DEFAULT_PORT = 80
CONNECT_TIMEOUT = 3
REQUEST_TIMEOUT = 5


def _discover_via_mdns(timeout: float = 8.0) -> Optional[tuple[str, int]]:
    """Return (host, port) of first Tuneshine found via mDNS, or None."""
    try:
        from zeroconf import ServiceBrowser, Zeroconf  # type: ignore
    except ImportError:
        logger.warning("zeroconf not installed — mDNS discovery unavailable. "
                       "Install with: pip install zeroconf")
        return None

    found: list[tuple[str, int]] = []

    class _Listener:
        def add_service(self, zc: "Zeroconf", type_: str, name: str) -> None:  # noqa: D102
            info = zc.get_service_info(type_, name)
            if info:
                addr = socket.inet_ntoa(info.addresses[0])
                port = info.port or DEFAULT_PORT
                logger.debug("mDNS found Tuneshine: %s:%s", addr, port)
                found.append((addr, port))

        def remove_service(self, *_):
            pass

        def update_service(self, *_):
            pass

    zc = Zeroconf()
    ServiceBrowser(zc, MDNS_SERVICE, _Listener())
    deadline = time.monotonic() + timeout
    while not found and time.monotonic() < deadline:
        time.sleep(0.1)
    zc.close()
    return found[0] if found else None


class TuneshineClient:
    """Thin wrapper around the Tuneshine local HTTP API."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        offline_retry_interval: int = 30,
    ) -> None:
        self._host = host
        self._port = port or DEFAULT_PORT
        self._offline_retry_interval = offline_retry_interval
        self._online = False
        self._last_offline_check = 0.0
        self._current_image_url: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ensure_connected(self) -> bool:
        """Return True if device is reachable (discovers via mDNS if needed)."""
        if self._online:
            return True

        now = time.monotonic()
        if now - self._last_offline_check < self._offline_retry_interval:
            return False
        self._last_offline_check = now

        if not self._host:
            result = _discover_via_mdns()
            if result:
                self._host, self._port = result
                logger.info("Tuneshine discovered at %s:%s", self._host, self._port)
            else:
                logger.warning("Tuneshine not found via mDNS. Will retry in %ss.",
                               self._offline_retry_interval)
                return False

        self._online = self._ping()
        return self._online

    def push_image_url(self, url: str) -> bool:
        """
        Tell Tuneshine to display artwork at *url*.

        Returns True on success.
        """
        if not self.ensure_connected():
            return False

        if url == self._current_image_url:
            return True  # nothing to do

        try:
            resp = requests.post(
                self._base_url("/api/image/url"),
                json={"url": url},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            self._current_image_url = url
            logger.debug("Pushed image URL to Tuneshine: %s", url)
            return True
        except requests.RequestException as exc:
            logger.warning("Failed to push image to Tuneshine: %s", exc)
            self._mark_offline()
            return False

    def clear_image(self) -> bool:
        """Remove the current API-provided image from Tuneshine."""
        if not self.ensure_connected():
            return False

        if self._current_image_url is None:
            return True

        try:
            resp = requests.delete(
                self._base_url("/api/image"),
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            self._current_image_url = None
            logger.debug("Cleared Tuneshine image")
            return True
        except requests.RequestException as exc:
            logger.warning("Failed to clear Tuneshine image: %s", exc)
            self._mark_offline()
            return False

    def get_state(self) -> Optional[dict]:
        """Return the raw /state response dict, or None on error."""
        if not self.ensure_connected():
            return None
        try:
            resp = requests.get(self._base_url("/state"), timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning("Failed to get Tuneshine state: %s", exc)
            self._mark_offline()
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _base_url(self, path: str) -> str:
        return f"http://{self._host}:{self._port}{path}"

    def _ping(self) -> bool:
        try:
            resp = requests.get(self._base_url("/state"), timeout=CONNECT_TIMEOUT)
            return resp.status_code < 500
        except requests.RequestException:
            return False

    def _mark_offline(self) -> None:
        self._online = False
        self._current_image_url = None
        self._last_offline_check = time.monotonic()
        logger.info("Tuneshine marked offline. Will retry in %ss.",
                    self._offline_retry_interval)
