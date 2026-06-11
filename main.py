#!/usr/bin/env python3
"""
roon-tuneshine — Pushes Roon now-playing artwork to a Tuneshine device.

Usage:
    python main.py [--config path/to/config.toml]
"""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config loading (tomllib stdlib in 3.11+, else tomli third-party)
# ---------------------------------------------------------------------------
try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        sys.exit(
            "ERROR: 'tomllib' (Python 3.11+) or 'tomli' package required.\n"
            "Install with:  pip install tomli"
        )

from bridge import Bridge
from roon_client import RoonClient
from tuneshine_client import TuneshineClient


def _load_config(path: Path) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def _setup_logging(level_str: str) -> None:
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Roon → Tuneshine artwork bridge")
    parser.add_argument(
        "--config",
        default=Path(__file__).parent / "config.toml",
        type=Path,
        help="Path to config.toml (default: config.toml next to main.py)",
    )
    args = parser.parse_args()

    cfg = _load_config(args.config)

    behaviour = cfg.get("behaviour", {})
    _setup_logging(behaviour.get("log_level", "INFO"))

    logger = logging.getLogger("roon-tuneshine")
    logger.info("Starting roon-tuneshine (config: %s)", args.config)

    roon_cfg = cfg.get("roon", {})
    tuneshine_cfg = cfg.get("tuneshine", {})
    image_cfg = cfg.get("image", {})

    tuneshine = TuneshineClient(
        host=tuneshine_cfg.get("host"),
        port=tuneshine_cfg.get("port"),
        offline_retry_interval=tuneshine_cfg.get("offline_retry_interval", 30),
    )

    # Placeholder callbacks — Bridge replaces them after construction
    roon = RoonClient(
        on_now_playing=lambda np, api: None,
        on_stopped=lambda: None,
        host=roon_cfg.get("host"),
        port=roon_cfg.get("port"),
        core_id=roon_cfg.get("core_id"),
        token_file=roon_cfg.get("token_file", "~/.roon-tuneshine-token"),
        zone_filter=roon_cfg.get("zone_filter", []),
    )

    bridge = Bridge(
        roon=roon,
        tuneshine=tuneshine,
        image_width=image_cfg.get("width", 128),
        image_height=image_cfg.get("height", 128),
        image_scale=image_cfg.get("scale", "fit"),
        clear_on_stop=behaviour.get("clear_on_stop", True),
        clear_delay=behaviour.get("clear_delay", 3),
    )

    def _shutdown(signum, frame):
        logger.info("Shutting down…")
        bridge.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info(
        "Waiting for Roon approval — open Roon → Settings → Extensions "
        "and enable 'Tuneshine Artwork Bridge' if this is your first run."
    )
    bridge.start()

    # Keep the main thread alive; all work happens in roonapi's daemon threads
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
