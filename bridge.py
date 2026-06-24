"""
Ties RoonClient and TuneshineClient together.

Receives now-playing events from Roon and pushes the corresponding
artwork URL to the Tuneshine device.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from roonapi import RoonApi

from roon_client import RoonClient
from tuneshine_client import TuneshineClient

logger = logging.getLogger(__name__)

# Re-push the current artwork this often so the Tuneshine cloud feed
# can't reclaim the display between track changes.
REPUSH_INTERVAL = 30  # seconds


class Bridge:
    def __init__(
        self,
        roon: RoonClient,
        tuneshine: TuneshineClient,
        image_width: int = 128,
        image_height: int = 128,
        image_scale: str = "fit",
        clear_on_stop: bool = True,
        clear_delay: float = 3.0,
    ) -> None:
        self._roon = roon
        self._tuneshine = tuneshine
        self._image_width = image_width
        self._image_height = image_height
        self._image_scale = image_scale
        self._clear_on_stop = clear_on_stop
        self._clear_delay = clear_delay
        self._clear_timer: Optional[threading.Timer] = None
        self._repush_timer: Optional[threading.Timer] = None
        self._last_push_kwargs: Optional[dict] = None
        self._stopped = False

    def start(self) -> None:
        self._roon._on_now_playing = self._handle_now_playing  # type: ignore[assignment]
        self._roon._on_stopped = self._handle_stopped
        self._roon.connect()
        logger.info("Bridge running. Watching Roon for playback…")

    def stop(self) -> None:
        self._stopped = True
        self._cancel_clear_timer()
        self._cancel_repush_timer()
        self._roon.stop()

    # ------------------------------------------------------------------

    def _handle_now_playing(self, now_playing: dict, zone: dict, api: RoonApi) -> None:
        self._cancel_clear_timer()

        image_key = now_playing.get("image_key")
        if not image_key:
            logger.debug("No image_key in now_playing — nothing to push")
            return

        url = api.get_image(
            image_key,
            scale=self._image_scale,
            width=self._image_width,
            height=self._image_height,
        )

        two_line = now_playing.get("two_line", {})
        three_line = now_playing.get("three_line", {})
        track = two_line.get("line1") or three_line.get("line1", "")
        artist = two_line.get("line2") or three_line.get("line2", "")
        album = three_line.get("line3", "")
        zone_name = zone.get("display_name", "")

        logger.info("Now playing: %s — %s → pushing artwork", track, artist)

        kwargs = dict(
            image_url=url,
            track_name=track or None,
            artist_name=artist or None,
            album_name=album or None,
            zone_name=zone_name or None,
        )
        self._last_push_kwargs = kwargs
        self._push_async(kwargs, force=True)
        self._schedule_repush()

    def _handle_stopped(self) -> None:
        self._cancel_repush_timer()
        self._last_push_kwargs = None
        if not self._clear_on_stop:
            return
        if self._clear_delay > 0:
            self._clear_timer = threading.Timer(self._clear_delay, self._do_clear)
            self._clear_timer.start()
        else:
            self._do_clear()

    def _do_clear(self) -> None:
        logger.info("Playback stopped — clearing Tuneshine display")
        self._tuneshine.clear_image()

    def _push_async(self, kwargs: dict, force: bool = False) -> None:
        """Push in a background thread. force=True bypasses the URL-dedup cache."""
        def _run():
            if force:
                self._tuneshine._current_image_url = None
            self._tuneshine.push_image(**kwargs)
        threading.Thread(target=_run, daemon=True).start()

    def _schedule_repush(self) -> None:
        self._cancel_repush_timer()
        if self._stopped:
            return
        self._repush_timer = threading.Timer(REPUSH_INTERVAL, self._do_repush)
        self._repush_timer.daemon = True
        self._repush_timer.start()

    def _do_repush(self) -> None:
        if self._last_push_kwargs and not self._stopped:
            logger.debug("Re-pushing artwork to reclaim display from cloud feed")
            self._push_async(self._last_push_kwargs, force=True)
            self._schedule_repush()

    def _cancel_clear_timer(self) -> None:
        if self._clear_timer:
            self._clear_timer.cancel()
            self._clear_timer = None

    def _cancel_repush_timer(self) -> None:
        if self._repush_timer:
            self._repush_timer.cancel()
            self._repush_timer = None
