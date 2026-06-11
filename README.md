# roon-tuneshine

A small Python bridge that watches your Roon playback and pushes album artwork to a [Tuneshine](https://tuneshine.rocks) device in real time.

```
Roon Core ──(zone state)──► roon-tuneshine ──(HTTP API)──► Tuneshine
```

## Requirements

- Python 3.9+
- Roon Core (Roon Server) on the same LAN — this project uses the [Roon Extension API](https://github.com/pavoni/pyroon)
- Tuneshine running firmware **2.3.0+** (required for the local HTTP API)
- The Tuneshine device must be set up first via the Tuneshine app (connect it to Spotify or another service once; the local API then works independently)

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/roon-tuneshine
cd roon-tuneshine
pip install -r requirements.txt
```

## First run

```bash
python main.py
```

On first run the app registers itself as a Roon Extension. **Open Roon → Settings → Extensions** and click **Enable** next to *Tuneshine Artwork Bridge*. The auth token is then saved locally so you only need to do this once.

Both Roon Core and Tuneshine are auto-discovered on your LAN — no manual IP configuration required unless you want to pin them.

## Configuration

All settings live in `config.toml`. Everything has a sensible default; the file is heavily commented.

| Section | Key | Default | Description |
|---|---|---|---|
| `[roon]` | `host` | auto-discover | Roon Core IP/hostname |
| `[roon]` | `port` | auto-discover | Roon Core port |
| `[roon]` | `token_file` | `~/.roon-tuneshine-token` | Where to persist auth token |
| `[roon]` | `zone_filter` | `[]` (all zones) | Only watch these zone names |
| `[tuneshine]` | `host` | auto-discover (mDNS) | Tuneshine IP or `.local` hostname |
| `[tuneshine]` | `offline_retry_interval` | `30` | Seconds between reconnect attempts |
| `[image]` | `width` / `height` | `128` | Artwork size requested from Roon |
| `[image]` | `scale` | `fit` | `fit` \| `fill` \| `stretch` |
| `[behaviour]` | `clear_on_stop` | `true` | Clear Tuneshine when playback stops |
| `[behaviour]` | `clear_delay` | `3` | Seconds grace period before clearing |
| `[behaviour]` | `log_level` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` |

## Running as a background service on macOS

Edit `com.github.roon-tuneshine.plist` — replace `YOURNAME` and the Python path with real values — then:

```bash
# Find your Python
which python3

# Install the plist
cp com.github.roon-tuneshine.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.github.roon-tuneshine.plist

# Check it started
launchctl list | grep roon-tuneshine

# Watch the log
tail -f /tmp/roon-tuneshine.log
```

To stop:

```bash
launchctl unload ~/Library/LaunchAgents/com.github.roon-tuneshine.plist
```

## How it works

1. **Roon discovery** — uses the SOOD multicast protocol (built into `roonapi`) to find your Roon Core automatically.
2. **Extension auth** — registers as a Roon Extension and stores the token for subsequent runs.
3. **Zone subscription** — subscribes to `zones_changed` events. When a zone starts playing, the `now_playing.image_key` is extracted.
4. **Artwork URL** — the Roon Core serves artwork at a local HTTP endpoint; `roonapi.get_image()` builds the URL.
5. **Tuneshine discovery** — uses mDNS (`_tuneshine._tcp`) to find the device automatically.
6. **Push** — sends the artwork URL to the Tuneshine local HTTP API. If the URL is unchanged (same track), no redundant requests are made.
7. **Clear** — when playback stops (with a configurable grace period), the API-provided image is removed so the device returns to its default display.

## Troubleshooting

**"No Roon Core found on the network"**
Make sure Roon Server is running. If it's on a different subnet, set `host` and `port` manually in `config.toml`.

**Tuneshine not found via mDNS**
Set `host` under `[tuneshine]` to the device's IP or `tuneshine-XXXX.local` hostname (shown in the Tuneshine app). Also ensure `zeroconf` is installed (`pip install zeroconf`).

**Extension never gets approved**
Open Roon → Settings → Extensions. If the entry doesn't appear, check firewall settings — Roon uses UDP multicast for discovery.

**Images not updating**
Enable `DEBUG` logging (`log_level = "DEBUG"` in config) and check the output for `image_key` values. Some radio streams don't provide artwork.

## License

MIT
