"""Tuneshine local HTTP API client with mDNS auto-discovery."""

from __future__ import annotations

import io
import json
import logging
import socket
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

MDNS_SERVICE = "_tuneshine._tcp.local."


def _resolve_ipv4(hostname: str) -> str:
    """Return IPv4 address for *hostname*, avoiding IPv6 for .local mDNS names."""
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_INET)
        if results:
            return results[0][4][0]
    except socket.gaierror:
        pass
    return hostname
def _fetch_as_webp(url: str, width: int = 64, height: int = 64) -> Optional[bytes]:
    """Download image from *url* and return it as a WebP-encoded bytes object."""
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed — falling back to URL push (pip install Pillow)")
        return None
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA").resize((width, height))
        buf = io.BytesIO()
        img.save(buf, "WEBP")
        return buf.getvalue()
    except Exception as exc:
        logger.warning("Failed to fetch/convert image: %s", exc)
        return None


DEFAULT_PORT = 80
CONNECT_TIMEOUT = 3
REQUEST_TIMEOUT = 8


def _discover_via_mdns(timeout: float = 10.0) -> Optional[tuple[str, int]]:
    """Return (host, port) of the first Tuneshine found via mDNS, or None."""
    try:
        from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf  # type: ignore
    except ImportError:
        logger.warning(
            "zeroconf not installed — mDNS discovery unavailable. "
            "Install with: pip install zeroconf"
        )
        return None

    found: list[tuple[str, int]] = []

    class _Listener:
        def add_service(self, zc: "Zeroconf", type_: str, name: str) -> None:
            info = zc.get_service_info(type_, name)
            if info and info.addresses:
                try:
                    addr = socket.inet_ntoa(info.addresses[0])
                except Exception:
                    addr = info.server  # fall back to hostname
                port = info.port or DEFAULT_PORT
                logger.debug("mDNS discovered Tuneshine: %s:%s (%s)", addr, port, name)
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
    """Wrapper around the Tuneshine local HTTP API (firmware 2.3.0+)."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        offline_retry_interval: int = 30,
    ) -> None:
        self._host = host
        self._host_pinned = host is not None  # True = user set it in config, don't re-discover
        self._port = port or DEFAULT_PORT
        self._offline_retry_interval = offline_retry_interval
        self._online = False
        self._last_offline_check = -offline_retry_interval  # allow immediate first attempt
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
                logger.warning(
                    "Tuneshine not found via mDNS. Will retry in %ss.",
                    self._offline_retry_interval,
                )
                return False

        # Resolve hostname → IPv4 (avoids IPv6 failures on .local names)
        self._host = _resolve_ipv4(self._host)
        self._online = self._ping()
        return self._online

    def push_image(
        self,
        image_url: str,
        track_name: Optional[str] = None,
        artist_name: Optional[str] = None,
        album_name: Optional[str] = None,
        zone_name: Optional[str] = None,
        service_name: str = "Roon",
        image_width: int = 64,
        image_height: int = 64,
    ) -> bool:
        """
        Download artwork, convert to WebP, and push binary directly to Tuneshine.

        Falls back to URL-based push if Pillow is not installed.
        Returns True on success.
        """
        if not self.ensure_connected():
            return False

        if image_url == self._current_image_url:
            return True  # same track, nothing to do

        webp_bytes = _fetch_as_webp(image_url, image_width, image_height)

        metadata: dict = {"serviceName": service_name, "imageUrl": image_url}
        if track_name:
            metadata["trackName"] = track_name
        if artist_name:
            metadata["artistName"] = artist_name
        if album_name:
            metadata["albumName"] = album_name
        if zone_name:
            metadata["zoneName"] = zone_name

        try:
            if webp_bytes is not None:
                resp = requests.post(
                    self._url("/image"),
                    files={"image": ("artwork.webp", webp_bytes, "image/webp")},
                    data={"metadata": json.dumps(metadata)},
                    timeout=REQUEST_TIMEOUT,
                )
            else:
                # Fallback: let the device fetch the image itself
                resp = requests.post(
                    self._url("/image"),
                    json=metadata,
                    timeout=REQUEST_TIMEOUT,
                )
            resp.raise_for_status()
            self._current_image_url = image_url
            logger.debug("Pushed image to Tuneshine: %s", image_url)
            return True
        except requests.RequestException as exc:
            logger.warning("Failed to push image to Tuneshine: %s", exc)
            self._mark_offline()
            return False

    def clear_image(self) -> bool:
        """Remove the locally-provided image, reverting Tuneshine to its idle display."""
        if not self.ensure_connected():
            return False

        if self._current_image_url is None:
            return True  # already clear

        try:
            resp = requests.delete(self._url("/image"), timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            self._current_image_url = None
            logger.debug("Cleared Tuneshine image")
            return True
        except requests.RequestException as exc:
            logger.warning("Failed to clear Tuneshine image: %s", exc)
            self._mark_offline()
            return False

    def get_state(self) -> Optional[dict]:
        """Return the raw /state dict, or None on error."""
        if not self.ensure_connected():
            return None
        try:
            resp = requests.get(self._url("/state"), timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning("Failed to get Tuneshine state: %s", exc)
            self._mark_offline()
            return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"http://{self._host}:{self._port}{path}"

    def _ping(self) -> bool:
        try:
            resp = requests.get(self._url("/health"), timeout=CONNECT_TIMEOUT)
            return resp.status_code < 500
        except requests.RequestException:
            return False

    def _mark_offline(self) -> None:
        self._online = False
        self._current_image_url = None
        self._last_offline_check = time.monotonic()
        if not self._host_pinned:
            self._host = None  # force mDNS re-discovery in case IP changed
        logger.info("Tuneshine marked offline. Will retry in %ss.", self._offline_retry_interval)
