"""Roon Core connection, discovery, and zone-state subscription."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional

from roonapi import RoonApi, RoonDiscovery

logger = logging.getLogger(__name__)

APP_INFO = {
    "extension_id": "com.github.roon-tuneshine",
    "display_name": "Tuneshine Artwork Bridge",
    "display_version": "1.0.0",
    "publisher": "roon-tuneshine",
    "email": "",
    "website": "https://github.com/setugarg/roon-tuneshine",
}

NowPlayingInfo = dict  # zone sub-dict from roonapi


def _load_token(token_file: Path) -> Optional[str]:
    if token_file.exists():
        token = token_file.read_text().strip()
        return token or None
    return None


def _save_token(token_file: Path, token: str) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(token)
    token_file.chmod(0o600)


class RoonClient:
    """Manages connection to a Roon Core and delivers now-playing callbacks."""

    def __init__(
        self,
        on_now_playing: Callable[[NowPlayingInfo, "RoonApi"], None],
        on_stopped: Callable[[], None],
        host: Optional[str] = None,
        port: Optional[int] = None,
        core_id: Optional[str] = None,
        token_file: str = "~/.roon-tuneshine-token",
        zone_filter: Optional[list[str]] = None,
    ) -> None:
        self._on_now_playing = on_now_playing
        self._on_stopped = on_stopped
        self._host = host
        self._port = port
        self._core_id = core_id or None
        self._token_file = Path(token_file).expanduser()
        self._zone_filter = zone_filter or []
        self._api: Optional[RoonApi] = None
        self._playing_zone_ids: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Discover (if needed) then connect and register callbacks. Blocks until auth."""
        host, port = self._resolve_host()

        token = _load_token(self._token_file)
        if token:
            logger.info("Using saved Roon token from %s", self._token_file)
        else:
            logger.info("No saved token — Roon will prompt for extension approval in the app.")

        self._api = RoonApi(
            appinfo=APP_INFO,
            token=token,
            host=host,
            port=int(port),
            blocking_init=True,
        )

        if self._api.token and self._api.token != token:
            _save_token(self._token_file, self._api.token)
            logger.info("Roon token saved to %s", self._token_file)

        self._api.register_state_callback(
            self._state_callback, event_filter="zones_changed"
        )
        logger.info("Connected to Roon Core '%s' at %s:%s",
                    self._api.core_name, host, port)

    def stop(self) -> None:
        if self._api:
            self._api.stop()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_host(self) -> tuple[str, int]:
        if self._host and self._port:
            return self._host, self._port

        logger.info("Discovering Roon Core on local network…")
        disc = RoonDiscovery(self._core_id)
        host, port = disc.first()
        if not host:
            raise RuntimeError(
                "No Roon Core found on the network. "
                "Make sure Roon Server is running on this machine or LAN."
            )
        logger.info("Discovered Roon Core at %s:%s", host, port)
        return host, int(port)

    def _state_callback(self, event: str, changed_ids: list[str]) -> None:
        if self._api is None:
            return

        now_playing_zones: list[dict] = []
        playing_ids: set[str] = set()

        for zone_id, zone in self._api.zones.items():
            if self._zone_filter and zone["display_name"] not in self._zone_filter:
                continue

            state = zone.get("state", "")
            if state == "playing":
                playing_ids.add(zone_id)
                np = zone.get("now_playing")
                if np:
                    now_playing_zones.append((zone_id, zone, np))

        # Trigger now-playing callback for changed zones that are playing
        for zone_id, zone, np in now_playing_zones:
            if zone_id in changed_ids or zone_id not in self._playing_zone_ids:
                logger.debug("Zone '%s' now playing: %s — %s",
                             zone.get("display_name"),
                             np.get("one_line", {}).get("line1", ""),
                             np.get("two_line", {}).get("line1", ""))
                self._on_now_playing(np, self._api)

        # Detect zones that stopped
        stopped = self._playing_zone_ids - playing_ids
        if stopped and not playing_ids:
            logger.debug("All watched zones stopped playing")
            self._on_stopped()

        self._playing_zone_ids = playing_ids
