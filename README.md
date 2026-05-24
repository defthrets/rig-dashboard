# THE SPRAWL

Live homelab dashboard, everything in one spot. Solar, battery, cams, weather, news, VPN, services, agent chat. Dark cyberpunk vibe.

## What's on it

- **Resources** — CPU, RAM, disk, swap with little sparkline charts
- **Weather + Fire + River** — temp, wind, rain, fire danger rating, Hawkesbury/Nepean river level
- **Solar + Battery** — FoxESS inverter live data pulled straight from the dongle on LAN, none of that cloud API rubbish. Shows solar generation, home load, grid import/export, battery charge. Has an animated chart too
- **Security + VPN** — SSH hardening, fail2ban jails, WireGuard VPN with what server you're on and the country flag, Tailscale peers
- **Frigate** — security camera detections, shows what it actually saw (person, car, etc.) with confidence percentage, live cam snapshot
- **Agent Bus** — last 3 messages between the homelab agents (Hermes, Clawd, etc.)
- **P1S Printer** — Bambu Lab P1S, temps, print progress, what file it's on
- **Flipper + Radio** — Flipper Zero status, Baofeng scanner, RTL-SDR, radio chatter from the last 24h
- **Birds** — what BirdNET picked up in the last hour
- **News** — 8 latest ABC News headlines pulled from RSS
- **Journal** — recent system events, containers going up/down, alerts
- **Services** — Docker containers and systemd services, running or dead

## What you need

- Python 3.11+
- Running on the homelab server (it talks to localhost for everything)
- MQTT broker with homelab sensor data flowing
- Frigate NVR on port 5000  
- Agent bus SQLite DB
- BirdNET and radio chatter DBs
- Sudo for `wg show` (VPN status)
- FoxESS dongle on your LAN (solar data)

## Install & Run

```bash
git clone https://github.com/defthrets/rig-dashboard.git
cd rig-dashboard
pip install fastapi uvicorn paho-mqtt
python3 dashboard.py
```

Dashboard lives at `http://your-server-ip:8701`  
API at `http://your-server-ip:8701/api/data` if you wanna pipe it into something else

## How it actually works

1. Fires up and connects to the local MQTT broker, subscribes to everything under `homelab/#` and caches it in memory. That's where all the sensor data comes from — Flipper, P1S, weather, security scans, the lot
2. Every 15 minutes it hits the FoxESS dongle directly on the LAN — no API key, no cloud, just straight to the hardware. Same way the FoxESS app would talk to it except we're not sending data to China
3. When your browser loads the page it grabs Frigate events from the API, reads the SQLite DBs for agent bus messages, bird detections, radio chatter, and the journal. Runs `sudo wg show` for VPN info, queries Docker and systemd for service status
4. The frontend is a single page — HTML, CSS, and JS all in one file. Fetches `/api/data` every 10 seconds and redraws everything. No React, no build step, no 47MB of node_modules. Just works
5. Sparkline charts for CPU/RAM/disk keep a 60-point ring buffer. Server seeds it with history on first load, then the browser updates it each poll

## Security

- LAN only, not exposed to the internet (Tailscale if you're remote)
- Needs passwordless sudo for `wg show`, nothing else
- No auth on the dashboard, it's internal
- Solar data comes from the dongle, not FoxESS Cloud — API key not needed
