# THE SPRAWL

Live homelab dashboard — everything in one place. Solar, battery, security cameras, weather, news, VPN, services, agent chat. Cyberpunk aesthetic.

## What it shows

- **Resources** — CPU, RAM, disk, swap with sparkline charts
- **Weather + Fire + River** — temp, wind, rain, fire danger rating, Hawkesbury/Nepean river level
- **Solar + Battery** — FoxESS inverter live data (solar generation, home load, grid import/export, battery SoC) with animated chart
- **Security + VPN** — SSH hardening status, fail2ban jails, WireGuard VPN with server name & country flag, Tailscale peers
- **Frigate** — security camera detections (person, car, etc.) with confidence scores, live camera snapshot
- **Agent Bus** — inter-agent chat between Hermes, Clawd and other homelab agents
- **P1S Printer** — Bambu Lab P1S status, temps, print progress
- **Flipper + Radio** — Flipper Zero, Baofeng scanner, RTL-SDR, radio chatter stats
- **Birds** — BirdNET species detections in the last hour
- **News** — 8 latest ABC News Australia headlines from RSS
- **Journal** — recent system events (container changes, alerts)
- **Services** — Docker containers and systemd services health

## Requirements

- Python 3.11+
- Running on the homelab server (hardcoded to `localhost` services)
- Access to:
  - MQTT broker (homelab sensor data)
  - Frigate NVR API (port 5000)
  - Agent bus SQLite DB
  - BirdNET/chatter DBs
  - Sudo for `wg show` (VPN status)
  - FoxESS dongle on LAN (solar data)

## Install & Run

```bash
# Clone
git clone https://github.com/defthrets/rig-dashboard.git
cd rig-dashboard

# Install deps
pip install fastapi uvicorn paho-mqtt

# Run
python3 dashboard.py
```

Dashboard at `http://your-server-ip:8701`

API at `http://your-server-ip:8701/api/data`

## How it works

1. **Startup** — connects to the local MQTT broker and subscribes to all `homelab/#` topics, caching sensor data in memory
2. **Background** — periodically polls FoxESS dongle on LAN for solar/battery data, grabs RSS headlines
3. **On request** — hits Frigate API, reads SQLite DBs for bus/birds/chatter/journal, runs `sudo wg show` for VPN, checks Docker/systemd for services
4. **Frontend** — single-page HTML with inline CSS/JS, fetches `/api/data` every 10 seconds, renders everything client-side
5. **Sparklines** — history ring buffers for CPU/RAM/disk seeded from server, updated client-side each poll

## Security notes

- Runs on LAN only (not exposed beyond Tailscale)
- `sudo wg show` requires passwordless sudo for the `wg` command
- No authentication on the dashboard itself — it's internal-only
- API key not required (data comes from local dongle, not FoxESS Cloud)
