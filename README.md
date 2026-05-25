# THE SPRAWL

Live homelab dashboard — solar, battery, cameras, weather, security, services, agent chat. Dark cyberpunk aesthetic, single Python file, no build step.

## What's on it

- **Resources** — CPU, RAM, disk, swap with 60-point sparkline charts
- **Weather + Fire + River** — temp, wind, rain, fire danger rating (NSW RFS), Hawkesbury River level (WaterNSW)
- **Power** — FoxESS inverter live from LAN dongle (no cloud). Solar, home load, grid import/export, battery SOC with animated history chart
- **Security + VPN** — SSH hardening, fail2ban jails, WireGuard peer list with country flags, Tailscale status
- **Frigate** — NVR camera detections with confidence %, live cam snapshot
- **Agent Bus** — last 3 messages between homelab agents (Hermes, Clawd)
- **Bambu P1S** — printer temps, print progress, filament type, error count
- **SIGINT** — Flipper Zero, Baofeng scanner, RTL-SDR, radio chatter DB
- **Birds** — BirdNET detections last hour
- **News** — 8 latest ABC News RSS headlines
- **Journal** — recent system events from sentience DB
- **Services** — Docker containers and systemd services, running/dead

## Prerequisites

### System
- **OS:** Linux (tested on Debian Trixie)
- **Python:** 3.11+
- **User with sudo** for `wg show` (WireGuard VPN status)
- **Docker** accessible without sudo (or add user to `docker` group)
- **MQTT broker** (EMQX, Mosquitto, etc.) with `homelab/#` topic namespace
- **systemctl --user** available for user service checks

### Services (all on localhost unless noted)
- **Frigate NVR** on port 5000
- **Agent Chat Bus** (SQLite DB at `/home/spitmux/agent-chat-web/chat.db`)
- **BirdNET** (SQLite DB at `~/.sentience/sentience.db`)
- **FoxESS dongle** accessible on LAN (solar data polled directly, no cloud)
- **Bambu P1S** on LAN (MQTT, port 8883)
- **NetAlertX** or equivalent MQTT publisher for network devices
- **Changedetection.io** (Docker container) for website monitoring
- **OpenClaw gateway** for Tailscale peer info

### Python Packages
```bash
pip install fastapi uvicorn paho-mqtt psutil requests
```

Full dependency list:
| Package | Why |
|---------|-----|
| `fastapi` | Web framework |
| `uvicorn` | ASGI server |
| `paho-mqtt` | MQTT client (sensor data) |
| `psutil` | CPU/RAM/disk metrics |
| `requests` | Frigate API calls |

### Filesystem
The dashboard reads from these paths — create symlinks or adjust in `dashboard.py`:
- `~/.sentience/sentience.db` — BirdNET + system journal
- `~/agent-chat-web/chat.db` — agent bus messages
- `~/.openclaw/workspace/data/foxess_cache.json` — solar data cache
- `~/.openclaw/workspace/data/river_level_state.json` — river level
- `~/.openclaw/workspace/data/tailscale_peers.json` — Tailscale peers
- `~/rig-dashboard/fox_history.json` — solar history ring buffer
- `~/rig-dashboard/sparkline_history.json` — CPU/RAM/disk history
- `~/rig-dashboard/assets/` — pixel GIF icons and background images

### Network
- **Port 8701** open on LAN (or exposed via Tailscale)
- MQTT broker at `192.168.1.253:1883` (edit `MQTT_BROKER` in dashboard.py if different)
- FoxESS dongle accessible (polled via `foxess_poll.py` cron, not direct from dashboard)
- Frigate API at `localhost:5000`

### Optional (some cards hide gracefully if unavailable)
- Flipper Zero (MQTT topic `homelab/flipper`)
- RTL-SDR radio scanner (MQTT topic `homelab/radio`)
- WireGuard (`sudo wg show` — requires passwordless sudo)
- systemctl user services (checked via `systemctl --user is-active`)

## Install

```bash
# Clone
git clone https://github.com/defthrets/rig-dashboard.git
cd rig-dashboard

# Create venv (recommended)
python3 -m venv venv
source venv/bin/activate

# Install deps
pip install fastapi uvicorn paho-mqtt psutil requests

# Create asset directory and add your GIF icons
mkdir -p assets
# Drop your 64x64 pixel GIFs: resources_tube.gif, weather.gif, solar.gif,
# security.gif, frigate.gif, agents_bus.gif, p1sprinter.gif, flipper.gif,
# birds.gif, news.gif, journal.gif, services.gif
# Plus: bg-rain.gif, hlab.gif, resources.gif, logo.gif, logo-text.png

# Create state files (or point cron jobs at them):
touch ~/.openclaw/workspace/data/foxess_cache.json
touch ~/.openclaw/workspace/data/river_level_state.json
touch ~/.openclaw/workspace/data/tailscale_peers.json
```

## Run

```bash
# Direct
python3 dashboard.py

# Or with systemd user service
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/sprawl-dashboard.service << 'EOF'
[Unit]
Description=The Sprawl Dashboard
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/spitmux/rig-dashboard
ExecStart=/home/spitmux/rig-dashboard/venv/bin/python3 dashboard.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now sprawl-dashboard
```

Dashboard at `http://your-server:8701`  
API at `http://your-server:8701/api/data`

## Expose via Tailscale

```bash
# Serve on tailnet at https://homelab.tailcffbd6.ts.net:8443
tailscale serve --bg --https=8443 http://127.0.0.1:8701
```

## How it works

1. **MQTT listener** connects to local broker on startup, subscribes to `homelab/#`, caches everything in memory
2. **FoxESS** data comes from a separate cron job (`foxess_poll.py` every 15min) that writes to `foxess_cache.json`
3. **On page load** — fetches Frigate events, reads SQLite DBs (agent bus, birds, journal), runs `sudo wg show`, queries Docker and systemd
4. **Frontend** — single HTML/CSS/JS file served inline. Polls `/api/data` every 10 seconds. No React, no webpack, no 47MB of `node_modules`
5. **Sparklines** — 60-point ring buffers for CPU/RAM/disk, seeded from disk on load, updated in-browser each poll
6. **Power chart** — 90-point solar history from `fox_history.json`, shows solar/home/grid as overlapping lines

## Security

- LAN only by default — not exposed to the internet
- Tailscale serve for remote access (tailnet only, not funneled)
- Needs passwordless sudo for `wg show` only
- No auth on dashboard — it's internal
- Solar data from LAN dongle, not FoxESS Cloud — no API key, no data leaving the house

## Responsive

- **Desktop (>900px):** Multi-column auto-fill grid, triple-row stays 3-column
- **Tablet (600-899px):** 2-column layout
- **Mobile (<600px):** Single column, compact headers
