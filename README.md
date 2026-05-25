#                                                                       ..                   ..    
         .xHL                                                    x .d88"              . uW8"      
      .-`8888hxxx~           u.      ..    .     :                5888R               `t888       
   .H8X  `%888*"       ...ue888b   .888: x888  x888.       .u     '888R         u      8888   .   
   888X     ..x..      888R Y888r ~`8888~'888X`?888f`   ud8888.    888R      us888u.   9888.z88N  
  '8888k .x8888888x    888R I888>   X888  888X '888>  :888'8888.   888R   .@88 "8888"  9888  888E 
   ?8888X    "88888X   888R I888>   X888  888X '888>  d888 '88%"   888R   9888  9888   9888  888E 
    ?8888X    '88888>  888R I888>   X888  888X '888>  8888.+"      888R   9888  9888   9888  888E 
 H8H %8888     `8888> u8888cJ888    X888  888X '888>  8888L        888R   9888  9888   9888  888E 
'888> 888"      8888   "*888*P"    "*88%""*88" '888!` '8888c. .+  .888B . 9888  9888  .8888  888" 
 "8` .8" ..     88*      'Y"         `~    "    `"`    "88888%    ^*888%  "888*""888"  `%888*%"   
    `  x8888h. d*"                                       "YP'       "%     ^Y"   ^Y'      "`      
      !""*888%~                                                                                   
      !   `"  .                                                                                   
      '-....:~                                                                                    

![screenshot](screenshot.jpg)

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
- **Agent Chat Bus** (SQLite DB, default at `~/agent-chat-web/chat.db`)
- **BirdNET** (SQLite DB at `~/.sentience/sentience.db`)
- **FoxESS dongle** accessible on LAN (solar data polled directly, no cloud)
- **Bambu P1S** on LAN (MQTT, port 8883)
- **NetAlertX** or equivalent MQTT publisher for network devices
- **WireGuard** (`sudo wg show` — passwordless sudo required for VPN status)

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
- `~/.sentience/sentience.db` — BirdNET + system journal (or your equivalent)
- `~/agent-chat-web/chat.db` — agent bus messages (optional)
- `~/rig-dashboard/fox_history.json` — solar history ring buffer
- `~/rig-dashboard/sparkline_history.json` — CPU/RAM/disk history
- `~/rig-dashboard/assets/` — pixel GIF icons and background images
- Paths for FoxESS cache, river level, Tailscale peers can be configured in `dashboard.py`

### Network
- **Port 8701** open on LAN (or exposed via Tailscale)
- MQTT broker at your broker IP:1883 (set `MQTT_BROKER` env var or edit dashboard.py)
- FoxESS dongle accessible on LAN (polled via a separate cron job, not directly from dashboard)
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

# Create asset directory and add your own GIF icons
mkdir -p assets
# Required: your 64x64 pixel GIFs — resources_tube.gif, weather.gif, solar.gif,
# security.gif, frigate.gif, agents_bus.gif, p1sprinter.gif, flipper.gif,
# birds.gif, news.gif, journal.gif, services.gif
# Plus: bg-rain.gif, hlab.gif, logo-text.png

# Create state files (or let your cron jobs do it):
touch ~/rig-dashboard/fox_history.json
touch ~/rig-dashboard/sparkline_history.json

# Set env vars for your setup:
export MQTT_BROKER="your.mqtt.broker.ip"
export MQTT_PORT="1883"
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
WorkingDirectory=%h/rig-dashboard
ExecStart=%h/rig-dashboard/venv/bin/python3 dashboard.py
Environment=MQTT_BROKER=192.168.1.253
Environment=MQTT_PORT=1883
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
# Serve on your tailnet (replace with your MagicDNS name and port)
tailscale serve --bg --https=8443 http://127.0.0.1:8701
# Then visit: https://your-hostname.tailxxxxx.ts.net:8443
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
