#!/usr/bin/env python3
"""
THE SPRAWL — live homelab view, cyberpunk aesthetic.
FastAPI server serving HTML + JSON data endpoint.
Clawd's unified dashboard — everything in one place.
"""

import json
import os
import sqlite3
import subprocess
import time
import urllib.request
from pathlib import Path
from collections import OrderedDict

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

# MQTT integration
import paho.mqtt.client as mqtt

MQTT_BROKER = "192.168.1.253"
MQTT_PORT = 1883
mqtt_cache = {}

def _mqtt_listener():
    """Background MQTT listener that caches all homelab topics"""
    def on_msg(client, userdata, msg):
        try:
            mqtt_cache[msg.topic] = json.loads(msg.payload)
        except:
            pass
    c = mqtt.Client(client_id="sprawl-mqtt", protocol=mqtt.MQTTv5,
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    c.on_message = on_msg
    c.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    c.subscribe("homelab/#")
    c.loop_start()
    return c

app = FastAPI(title="The Sprawl")

@app.on_event("startup")
async def startup_sprawl():
    _mqtt_listener()

@app.get("/api/mqtt")
async def api_mqtt():
    """Return all cached MQTT homelab data"""
    return {"topics": {k: v for k, v in mqtt_cache.items()}}

DB_JOURNAL = os.path.expanduser("~/rig-journal/journal.db")
DB_CHAT = os.path.expanduser("~/agent-chat-web/chat.db")
DB_BIRDNET = os.path.expanduser("~/.birdnet-listener/detections.db")
DB_CHATTER = os.path.expanduser("~/.radio_monitor/chatter.db")
IP_CACHE_FILE = os.path.expanduser("~/rig-dashboard/ip_cache.json")

# ═══════════════════════════════════════════════════════════════════
# DATA FUNCTIONS
# ═══════════════════════════════════════════════════════════════════

def get_docker():
    """All containers with status."""
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.State}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=5,
        )
        containers = {}
        for line in result.stdout.strip().split("\n"):
            parts = line.split("\t")
            if len(parts) >= 2:
                containers[parts[0]] = {"status": parts[2] if len(parts) > 2 else "", "healthy": parts[1] == "running"}
        return containers
    except Exception:
        return {}

def get_resources():
    """System vitals."""
    try:
        from psutil import cpu_percent, virtual_memory, disk_usage, swap_memory, getloadavg
        mem = virtual_memory()
        disk = disk_usage("/")
        swap = swap_memory()
        load = getloadavg()
        return {
            "cpu_percent": round(cpu_percent(interval=0.5), 1),
            "ram_percent": round(mem.percent, 1),
            "ram_used_gb": round(mem.used / 1024**3, 1),
            "ram_total_gb": round(mem.total / 1024**3, 1),
            "disk_percent": round(disk.percent, 1),
            "disk_avail_gb": round(disk.free / 1024**3, 1),
            "swap_percent": round(swap.percent, 1),
            "load_1": round(load[0], 2),
            "load_5": round(load[1], 2),
            "load_15": round(load[2], 2),
        }
    except Exception:
        return {}

SPARKLINE_FILE = os.path.expanduser("~/rig-dashboard/sparkline_history.json")
SPARKLINE_MAX = 60

def load_sparkline_history():
    """Load persisted sparkline ring buffers."""
    try:
        with open(SPARKLINE_FILE) as f:
            data = json.load(f)
        for k in ("cpu", "ram", "disk"):
            arr = data.get(k, [])
            if len(arr) > SPARKLINE_MAX:
                arr = arr[-SPARKLINE_MAX:]
            data[k] = arr
        return data
    except:
        return {"cpu": [], "ram": [], "disk": []}

def save_sparkline_history(history):
    """Persist sparkline ring buffers to disk."""
    try:
        os.makedirs(os.path.dirname(SPARKLINE_FILE), exist_ok=True)
        with open(SPARKLINE_FILE, "w") as f:
            json.dump(history, f)
    except:
        pass

def update_sparkline_history(resources):
    """Append current resource values to sparkline history."""
    history = load_sparkline_history()
    for k in ("cpu", "ram", "disk"):
        key = "cpu_percent" if k == "cpu" else ("ram_percent" if k == "ram" else "disk_percent")
        val = resources.get(key, 0)
        history.setdefault(k, []).append(val)
        if len(history[k]) > SPARKLINE_MAX:
            history[k] = history[k][-SPARKLINE_MAX:]
    save_sparkline_history(history)
    return history

def get_journal(limit=10):
    """Recent journal entries."""
    if not os.path.exists(DB_JOURNAL):
        return []
    try:
        db = sqlite3.connect(f"file:{DB_JOURNAL}?mode=ro", uri=True)
        c = db.execute("SELECT timestamp, source, severity, summary FROM events ORDER BY timestamp DESC LIMIT ?", (limit,))
        out = [{"timestamp": r[0], "source": r[1], "severity": r[2], "summary": r[3]} for r in c.fetchall()]
        db.close()
        return out
    except Exception:
        return []

FOX_CACHE = os.path.expanduser("~/.openclaw/workspace/data/foxess_cache.json")
def get_foxess():
    """FoxESS solar + battery from cached poll."""
    if os.path.exists(FOX_CACHE):
        try:
            with open(FOX_CACHE) as f:
                return json.load(f)
        except: pass
    return {}

def get_frigate():
    """Frigate NVR status."""
    result = {"cameras": {}, "events": [], "service": {}, "stats": {}}
    try:
        import requests
        # Get stats
        r = requests.get("http://localhost:5000/api/stats", timeout=5)
        if r.status_code == 200:
            data = r.json()
            result["stats"] = data

            # Build camera list
            for name, info in data.get("cameras", {}).items():
                result["cameras"][name] = {
                    "fps": round(info.get("camera_fps", 0), 1),
                    "detection_fps": round(info.get("detection_fps", 0), 1),
                    "detection_enabled": info.get("detection_enabled", False),
                }

            result["service"]["version"] = data.get("service", {}).get("version", "?")
            result["service"]["uptime"] = data.get("service", {}).get("uptime", 0)

        # Get events
        r2 = requests.get("http://localhost:5000/api/events?limit=5&include_thumbnails=0", timeout=5)
        if r2.status_code == 200:
            result["events"] = r2.json()

    except Exception:
        pass
    return result

def get_vpn():
    """WireGuard VPN status."""
    try:
        r = subprocess.run(["sudo", "wg", "show"], capture_output=True, text=True, timeout=5)
        out = {"connected": False}
        endpoint_ip = None
        for line in r.stdout.split("\n"):
            if "interface:" in line:
                out["connected"] = True
                out["server"] = line.split(":", 1)[-1].strip()
            elif "listening port" in line:
                out["endpoint"] = line.split(":")[-1].strip()
            elif "endpoint:" in line:
                # Extract IP from "endpoint: 1.2.3.4:51820"
                ep = line.split(":", 1)[-1].strip()
                endpoint_ip = ep.rsplit(":", 1)[0] if ":" in ep else ep
                out["endpoint_ip"] = endpoint_ip
            elif "latest handshake" in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    ago = parts[-1].strip()
                    out["handshake"] = ago
                    out["handshake_ago"] = ago
            elif "transfer:" in line:
                parts = line.split()
                if len(parts) >= 3:
                    out["rx"] = parts[1]
                    out["tx"] = parts[2]
        
        # Resolve country from endpoint IP
        if endpoint_ip:
            try:
                import urllib.request, json
                req = urllib.request.urlopen(f"http://ip-api.com/json/{endpoint_ip}?fields=country,countryCode", timeout=3)
                geo = json.load(req)
                out["country"] = geo.get("country", "?")
                out["country_code"] = geo.get("countryCode", "??").lower()
            except:
                pass
        return out
    except Exception:
        return {"connected": False}

def get_network():
    """Network info including tailscale peers."""
    out = {}
    try:
        # Public IP
        r = subprocess.run(["curl", "-s", "https://api.ipify.org"], capture_output=True, text=True, timeout=5)
        out["public_ip"] = r.stdout.strip()
    except: pass
    try:
        r = subprocess.run(["ip", "-4", "addr", "show", "wlp4s0"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.split("\n"):
            if "inet " in line:
                out["lan_ip"] = line.strip().split()[1].split("/")[0]
    except: pass
    try:
        r = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5)
        out["tailscale_ip"] = r.stdout.strip()
    except: pass
    try:
        r = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=5)
        data = json.loads(r.stdout)
        peers = []
        for p in data.get("Peer", {}).values():
            peers.append({
                "hostname": p.get("HostName", p.get("DNSName","?")),
                "ip": ",".join(p.get("TailscaleIPs",["?"])[:1]),
                "online": p.get("Online", False),
                "os": p.get("OS", "?"),
            })
        out["peers"] = peers
    except:
        out["peers"] = []
    return out

def get_bus():
    """Agent chat bus status."""
    out = {"message_count": 0, "last_sender": "?", "agents": []}
    if not os.path.exists(DB_CHAT):
        return out
    try:
        db = sqlite3.connect(f"file:{DB_CHAT}?mode=ro", uri=True)
        c = db.execute("SELECT COUNT(*) FROM messages")
        out["message_count"] = c.fetchone()[0]
        c = db.execute("SELECT sender FROM messages ORDER BY id DESC LIMIT 1")
        last = c.fetchone()
        out["last_sender"] = last[0] if last else "?"
        # Agents
        c = db.execute("SELECT DISTINCT sender FROM messages ORDER BY sender")
        senders = [r[0] for r in c.fetchall()]
        emoji_map = {"hermes": "⚕️", "clawd": "🦞", "michael": "🧑‍💻", "mqtt_watch": "📡"}
        for s in senders:
            out["agents"].append({
                "name": s,
                "display": s.title(),
                "emoji": emoji_map.get(s.lower(), "🤖"),
                "active": True,
            })
        # Recent messages
        c = db.execute("SELECT sender, content, timestamp FROM messages ORDER BY id DESC LIMIT 6")
        out["recent"] = [{"sender": r[0], "content": r[1][:200], "time": (r[2] or "")[11:19]} for r in c.fetchall()]
        db.close()
    except: pass
    return out

def get_services():
    """Service status from Docker + systemd."""
    out = []
    docker = get_docker()

    key_services = ["emqx", "frigate", "browserless", "changedetection"]

    for name in key_services:
        info = docker.pop(name, None) if name in docker else None
        healthy = info["healthy"] if info else False
        status = info["status"] if info else "not found"
        icon = "🟢" if healthy else "🔴"
        out.append({
            "name": name, "display": f"{icon} {name}",
            "state": "running" if healthy else "down",
            "status": status, "is_key": True,
        })

    # Remaining containers
    for name, info in sorted(docker.items()):
        out.append({
            "name": name, "display": f"🟢 {name}",
            "state": "running" if info["healthy"] else "down",
            "status": info["status"], "is_key": False,
        })

    # Systemd services
    for svc in ["agent-chat-web.service", "rig-dashboard.service"]:
        try:
            r = subprocess.run(["systemctl", "--user", "is-active", svc],
                              capture_output=True, text=True, timeout=3)
            state = r.stdout.strip()
            name = svc.replace(".service", "").replace("-", " ")
            icon = "🟢" if state == "active" else "🔴"
            out.append({
                "name": svc.replace(".service", ""),
                "display": f"{icon} {name} (systemd)",
                "state": "active" if state == "active" else state,
                "status": state, "is_key": True,
            })
        except: pass

    return out

def get_birdnet():
    """BirdNET detections from database."""
    if not os.path.exists(DB_BIRDNET):
        return []
    try:
        db = sqlite3.connect(f"file:{DB_BIRDNET}?mode=ro", uri=True)
        c = db.execute("""
            SELECT species, COUNT(*) as cnt
            FROM detections
            WHERE timestamp > datetime('now', '-1 hour')
            GROUP BY species ORDER BY cnt DESC LIMIT 10
        """)
        return [{"species": r[0], "count": r[1]} for r in c.fetchall()]
    except Exception:
        return []

def get_uptime():
    try:
        with open("/proc/uptime") as f:
            secs = int(float(f.read().split()[0]))
        d = secs // 86400
        h = (secs % 86400) // 3600
        m = (secs % 3600) // 60
        return f"{d}d {h}h {m}m"
    except:
        return "?"

def get_chatter_stats():
    """24hr voice chatter stats."""
    if not os.path.exists(DB_CHATTER):
        return {}
    try:
        db = sqlite3.connect(DB_CHATTER)
        c = db.execute("""
            SELECT COUNT(*), COALESCE(SUM(duration_s),0), COUNT(DISTINCT channel_name)
            FROM transmissions WHERE timestamp > datetime('now','-24 hours')
        """)
        total, dur, chans = c.fetchone()
        c = db.execute("""
            SELECT channel_name, COUNT(*) as cnt, SUM(duration_s) as dur
            FROM transmissions WHERE timestamp > datetime('now','-24 hours')
            GROUP BY channel_name ORDER BY cnt DESC LIMIT 5
        """)
        tops = [{"channel": r[0], "count": r[1], "duration_s": round(r[2] or 0, 1)} for r in c.fetchall()]
        db.close()
        return {"transmissions_24h": total or 0, "total_duration_s": round(dur or 0, 1),
                "channels_active": chans or 0, "top_channels": tops}
    except:
        return {}

def get_news():
    """ABC News headlines from RSS."""
    try:
        import xml.etree.ElementTree as ET
        req = urllib.request.Request(
            "https://www.abc.net.au/news/feed/51120/rss.xml",
            headers={"User-Agent": "sprawl-dashboard/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            tree = ET.parse(r)
        items = []
        for item in tree.findall(".//item"):
            title = item.find("title")
            if title is not None and title.text:
                items.append(title.text)
            if len(items) >= 8:
                break
        return items
    except Exception:
        return []

# ═══════════════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/data")
async def api_data():
    """Full dashboard data."""
    from datetime import datetime
    resources = get_resources()
    sparkline = update_sparkline_history(resources) if resources else load_sparkline_history()
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "uptime": get_uptime(),
        "resources": resources,
        "sparkline": sparkline,
        "vpn": get_vpn(),
        "network": get_network(),
        "services": get_services(),
        "frigate": get_frigate(),
        "bus": get_bus(),
        "birdnet": get_birdnet(),
        "chatter": get_chatter_stats(),
        "journal": get_journal(10),
        "fox": get_foxess(),
        "news": get_news(),
        "mqtt": {k: v for k, v in mqtt_cache.items()},
    }

@app.get("/api/camera/snapshot")
async def api_camera_snapshot():
    """Proxy Frigate's latest.jpg so the camera feed works from any network."""
    from fastapi.responses import Response
    try:
        r = urllib.request.urlopen("http://localhost:5000/api/tapo_c230/latest.jpg", timeout=5)
        return Response(content=r.read(), media_type="image/jpeg")
    except Exception:
        return Response(status_code=502)

@app.get("/homelab.gif")
async def homelab_gif():
    """Serve the homelab pixel-art GIF."""
    from fastapi.responses import FileResponse
    gif_path = os.path.expanduser("~/rig-dashboard/homelab.gif")
    if os.path.exists(gif_path):
        return FileResponse(gif_path, media_type="image/gif")
    return Response(status_code=404)

@app.get("/logo.png")
async def logo_png():
    """Serve the ASCII art logo as PNG for pixel-perfect rendering."""
    from fastapi.responses import FileResponse
    logo_path = os.path.expanduser("~/.openclaw/workspace/data/sprawl_logo.png")
    if os.path.exists(logo_path):
        return FileResponse(logo_path, media_type="image/png")
    return Response(status_code=404)

@app.get("/api/ip-lookup")
async def api_ip_lookup(ips: str = ""):
    """Geo lookup for IPs."""
    out = {}
    cache = load_ip_cache()
    for ip in ips.split(","):
        ip = ip.strip()
        if not ip: continue
        if ip in cache:
            out[ip] = cache[ip]
        else:
            try:
                r = urllib.request.urlopen(f"http://ip-api.com/json/{ip}?fields=country,city,org", timeout=3)
                data = json.loads(r.read())
                cache[ip] = data
                out[ip] = data
            except:
                out[ip] = {"country": "?", "city": "", "org": ""}
    save_ip_cache(cache)
    return out

def load_ip_cache():
    try:
        with open(IP_CACHE_FILE) as f:
            return json.load(f)
    except: return {}

def save_ip_cache(data):
    os.makedirs(os.path.dirname(IP_CACHE_FILE), exist_ok=True)
    with open(IP_CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ═══════════════════════════════════════════════════════════════════
# HTML TEMPLATE
# ═══════════════════════════════════════════════════════════════════

@app.get("/")
async def index():
    from fastapi.responses import HTMLResponse
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>THE SPRAWL • Clawd Unified</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap');

  :root {
    --bg: #0a0806; --surface: #14100b; --border: #2a2018;
    --text: #b89a6a; --text-bright: #f5c87c;
    --cyan: #f59e0b; --green: #d97706; --red: #ef4444;
    --amber: #fbbf24; --violet: #f59e0b; --pink: #fb923c;
    --glow: rgba(245,158,11,0.4);
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--bg); color:var(--text); font-family:'JetBrains Mono',monospace; font-size:12px; line-height:1.5; }
  body::before { content:''; position:fixed; top:0; left:0; width:100%; height:100%; pointer-events:none; background: repeating-linear-gradient(0deg, rgba(0,0,0,0.08) 0px, rgba(0,0,0,0.08) 1px, transparent 1px, transparent 3px); z-index:9999; }
  .container { max-width:1800px; margin:0 auto; padding:16px; position:relative; z-index:1; }
  .logo-block { text-align:center; padding:12px 0 6px; margin-bottom:4px; display:flex; align-items:center; justify-content:center; gap:14px; }
  .logo-gif { width:64px; height:64px; image-rendering:pixelated; flex-shrink:0; }
  .logo-text-img { height:52px; width:auto; animation:logoGlitch 6s steps(1) infinite; }
  @keyframes logoGlitch {
    0%, 95%, 98%, 100% { transform:translate(0,0); opacity:1; }
    96% { transform:translate(-2px,1px); opacity:0.8; }
    97% { transform:translate(2px,-1px); opacity:0.9; }
  }
  .header { display:flex; justify-content:space-between; align-items:flex-end; padding-bottom:12px; border-bottom:1px solid var(--border); margin-bottom:16px; }
  .header .sub { font-size:9px; color:var(--amber); letter-spacing:2px; opacity:0.7; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(420px, 1fr)); gap:12px; }
  @media (min-width: 900px) { .grid { grid-template-columns:repeat(auto-fill, minmax(320px, 1fr)); } }
  @media (min-width: 1400px) { .grid { grid-template-columns:repeat(auto-fill, minmax(280px, 1fr)); } }
  .card.mini { min-width:0; }
  @media (min-width: 1200px) { .card.wide { grid-column:span 2; } }
  .card { background:var(--surface); border:1px solid var(--border); border-radius:4px; padding:12px; box-shadow:inset 0 0 30px rgba(245,158,11,0.03); transition:border-color 0.3s; }
  .card:hover { border-color:rgba(245,158,11,0.3); }
  .card-header { display:flex; align-items:center; gap:8px; margin-bottom:10px; padding-bottom:8px; border-bottom:1px solid rgba(42,32,24,0.8); }
  .card-header h3 { font-size:11px; color:var(--text-bright); text-transform:uppercase; letter-spacing:1px; text-shadow:0 0 10px var(--glow); }
  .card-dot { width:8px; height:8px; border-radius:2px; box-shadow:0 0 6px currentColor; }
  .card-dot.cyan { background:var(--amber); } .card-dot.green { background:var(--green); }
  .card-dot.red { background:var(--red); } .card-dot.amber { background:var(--amber); }
  .card-dot.violet { background:var(--amber); } .card-dot.pink { background:var(--pink); }
  .card-dot.orange { background:var(--amber); }
  .section-header { font-size:10px; color:var(--amber); margin:6px 0 4px; text-transform:uppercase; letter-spacing:1px; text-shadow:0 0 8px var(--glow); }
  .stat-row { display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid rgba(42,32,24,0.3); }
  .stat-label { color:var(--text); font-size:10px; }
  .stat-value { color:var(--text-bright); font-size:10px; text-align:right; }
  .stat-value.green { color:var(--green); } .stat-value.crit { color:var(--red); }
  .stat-value.warn { color:var(--amber); } .stat-value.cyan { color:var(--amber); }
  .bar-wrap { height:4px; background:rgba(245,158,11,0.08); border-radius:2px; margin:2px 0 4px; }
  .bar { height:100%; border-radius:2px; transition:width 0.5s; }
  .bar.cyan { background:var(--amber); } .bar.green { background:var(--green); }
  .bar.amber { background:var(--amber); } .bar.red { background:var(--red); }
  .svc-item { font-size:10px; padding:2px 0; border-bottom:1px solid rgba(42,32,24,0.3); }
  .svc-item .name { color:var(--text-bright); }
  .svc-item .state-up { color:var(--green); margin-left:8px; font-size:9px; }
  .svc-item .state-down { color:var(--red); margin-left:8px; font-size:9px; }
  .svc-item .status-text { color:var(--text); font-size:9px; margin-left:8px; }
  .journal-item { padding:3px 0; border-bottom:1px solid rgba(42,32,24,0.3); font-size:10px; }
  .j-time { color:var(--text); margin-right:6px; }
  .j-sev-crit { color:var(--red); } .j-sev-warn { color:var(--amber); } .j-sev-info { color:var(--amber); }
  .frigate-event { padding:2px 0; font-size:10px; border-bottom:1px solid rgba(42,32,24,0.3); }
  .frigate-event .label { color:var(--amber); font-weight:700; }
  .security-ip-row { font-size:9px; padding:2px 0; border-bottom:1px solid rgba(30,41,59,0.3); }
  .security-ip-row .ip { color:var(--amber); }
  .security-ip-row .geo { color:var(--text); }
  .footer { text-align:center; padding:16px; color:var(--text); font-size:10px; border-top:1px solid var(--border); margin-top:16px; }
  .footer a { color:var(--amber); text-decoration:none; }
  .section-header { font-size:10px; color:var(--amber); margin:6px 0 4px; text-transform:uppercase; letter-spacing:1px; text-shadow:0 0 8px var(--glow); }
  .peer-row { font-size:10px; padding:1px 0; }
  .peer-online { color:var(--green); } .peer-offline { color:var(--red); }
  .bus-msg { padding:4px 6px; margin:4px 0; border-radius:3px; font-size:9px; border-left:2px solid var(--border); }
  .bus-msg.bus-hermes { border-left-color: var(--amber); } .bus-msg.bus-clawd { border-left-color: var(--pink); }
  .bus-sender { color:var(--amber); font-weight:700; margin-right:6px; }
  .bus-time { color:var(--text); font-size:8px; }
  .bus-body { color:var(--text-bright); margin-top:2px; line-height:1.4; word-break:break-word; }
  /* Sparkline chart */
  .sparkline { display:flex; align-items:flex-end; gap:1px; height:36px; margin:4px 0 6px; }
  .sparkline .spark-bar { flex:1; min-width:2px; border-radius:1px 1px 0 0; transition:height 0.3s; }
  .chart-title { font-size:8px; color:var(--text); text-transform:uppercase; letter-spacing:1px; margin-top:4px; }
  .gauge-ring { position:relative; display:inline-block; }
  .gauge-text { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; font-size:14px; font-weight:700; }
  .heat-box { display:inline-block; width:10px; height:10px; border-radius:1px; margin-right:2px; }
  .heat-0 { background:#1e293b; } .heat-1 { background:#164e63; } .heat-2 { background:#0e7490; }
  .heat-3 { background:#0891b2; } .heat-4 { background:#06b6d4; } .heat-5 { background:#22d3ee; }
</style>
</head>
<body>
<div class="container">
  <div class="logo-block">
    <img src="/homelab.gif" alt="" class="logo-gif">
    <img src="/logo.png?v=2" alt="THE SPRAWL" class="logo-text-img">
  </div>
  <div class="header">
    <div style="text-align:right;font-size:10px;color:var(--text);" id="uptime">UPTIME …</div>
  </div>

  <div class="grid">
    <div class="card"><div class="card-header"><div class="card-dot cyan"></div><h3>💻 RESOURCES</h3></div><div id="res-content">Loading...</div></div>
    <div class="card"><div class="card-header"><div class="card-dot cyan"></div><h3>🌤 WEATHER + 🔥 FIRE + 🌊 RIVER</h3></div><div id="weather-content">Loading...</div></div>
    <div class="card"><div class="card-header"><div class="card-dot amber"></div><h3>☀️ SOLAR + 🔋 BATTERY</h3></div><canvas id="solar-chart" width="400" height="100" style="width:100%;height:100px;display:block;margin-bottom:4px;"></canvas><div id="fox-content">Loading...</div></div>
    <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:12px; grid-column:1/-1;">
      <div class="card"><div class="card-header"><div class="card-dot red"></div><h3>🔒 SECURITY + 🔐 VPN</h3></div><div id="sec-content">Loading...</div><div id="net-content" style="margin-top:8px;">Loading...</div></div>
      <div class="card"><div class="card-header"><div class="card-dot orange"></div><h3>🎥 FRIGATE</h3></div><div id="frigate-content">Loading...</div><img id="cam-feed" src="" alt="loading camera..." style="width:100%;border-radius:4px;display:block;margin-bottom:2px;" onerror="document.getElementById('cam-info').textContent='⚠️ stream offline • '+new Date().toLocaleTimeString()" onload="document.getElementById('cam-info').textContent=new Date().toLocaleTimeString()+' • 5fps detect • Frigate'"><div style="font-size:9px;color:var(--text);" id="cam-info">connecting...</div></div>
      <div class="card"><div class="card-header"><div class="card-dot pink"></div><h3>💬 AGENT BUS</h3></div><div id="bus-content">Loading...</div></div>
    </div>
    <div class="card mini"><div class="card-header"><div class="card-dot violet"></div><h3>🖨 P1S PRINTER</h3></div><div id="p1s-content">Loading...</div></div>
    <div class="card mini"><div class="card-header"><div class="card-dot pink"></div><h3>🐬 FLIPPER + 📻 RADIO</h3></div><div id="flipper-content">Loading...</div><div id="radio-content" style="margin-top:8px;">Loading...</div></div>
    <div class="card mini"><div class="card-header"><div class="card-dot green"></div><h3>🐦 BIRDS</h3></div><div id="birds-content">Loading...</div></div>
    <div class="card"><div class="card-header"><div class="card-dot cyan"></div><h3>📰 NEWS</h3></div><div id="news-content" style="font-size:9px;">Loading...</div></div>
    <div class="card"><div class="card-header"><div class="card-dot violet"></div><h3>📓 JOURNAL</h3></div><div id="journal-content">Loading...</div></div>
    <div class="card"><div class="card-header"><div class="card-dot violet"></div><h3>⚙️ SERVICES</h3></div><div id="svc-content">Loading...</div></div>
  </div>
</div>
<div class="footer">THE SPRAWL • clawd unified dashboard • <span id="topic-count">0</span> MQTT topics • <a href="http://100.101.39.116:8702" target="_blank">agent bus</a> • <a href="http://100.101.39.116:8701/api/data" target="_blank">api</a></div>

<script>
// ── History ring buffers for sparklines (seeded from server) ──
const historyLen = 60;
const history = {
  cpu: [],
  ram: [],
  disk: [],
};
let historySeeded = false;

function seedHistory(sparkline) {
  if (historySeeded || !sparkline) return;
  for (const k of ['cpu', 'ram', 'disk']) {
    if (sparkline[k] && sparkline[k].length > 0) {
      history[k] = sparkline[k].slice(-historyLen);
    } else {
      history[k] = new Array(historyLen).fill(0);
    }
  }
  historySeeded = true;
}

function pushHistory(arr, val) { arr.push(val); if (arr.length > historyLen) arr.shift(); }

function sparkline(values, maxVal, color) {
  const norm = maxVal > 0 ? values.map(v => Math.max(1, (v / maxVal) * 100)) : values.map(() => 1);
  return '<div class="sparkline">' + norm.map(h =>
    '<div class="spark-bar" style="height:'+h+'%;background:'+color+'"></div>'
  ).join('') + '</div>';
}

function resourceBars(res) {
  const cpu = res.cpu_percent || 0, ram = res.ram_percent || 0, disk = res.disk_percent || 0;
  pushHistory(history.cpu, cpu);
  pushHistory(history.ram, ram);
  pushHistory(history.disk, disk);

  const cpuColor = cpu > 80 ? 'var(--red)' : cpu > 60 ? 'var(--amber)' : '#22d3ee';
  const ramColor = ram > 85 ? 'var(--red)' : ram > 70 ? 'var(--amber)' : '#f59e0b';
  const diskColor = disk > 90 ? 'var(--red)' : disk > 80 ? 'var(--amber)' : '#a78bfa';

  let html = '';
  // CPU with sparkline
  html += '<div class="stat-row"><span class="stat-label">CPU</span><span class="stat-value '+ (cpu>80?'crit':cpu>60?'warn':'') +'">'+cpu+'%</span></div>';
  html += sparkline(history.cpu, 100, cpuColor);
  // RAM with sparkline
  html += '<div class="stat-row"><span class="stat-label">RAM</span><span class="stat-value '+ (ram>85?'crit':ram>70?'warn':'') +'">'+ram+'% ('+(res.ram_used_gb||'?')+'/'+(res.ram_total_gb||'?')+' GB)</span></div>';
  html += sparkline(history.ram, 100, ramColor);
  // Disk
  html += '<div class="stat-row"><span class="stat-label">DISK</span><span class="stat-value '+ (disk>90?'crit':disk>80?'warn':'') +'">'+disk+'% ('+(res.disk_avail_gb||'?')+' free)</span></div>';
  html += sparkline(history.disk, 100, diskColor);
  // Swap + Load
  html += '<div class="stat-row"><span class="stat-label">SWAP</span><span class="stat-value '+ ((res.swap_percent||0)>50?'crit':(res.swap_percent||0)>10?'warn':'') +'">'+(res.swap_percent||'?')+'%</span></div>';
  html += '<div class="stat-row"><span class="stat-label">LOAD</span><span class="stat-value">'+(res.load_1||'?')+' / '+(res.load_5||'?')+' / '+(res.load_15||'?')+'</span></div>';
  return html;
}

function birdHeatmap(birdnetList) {
  if (!birdnetList.length) return '';
  const max = Math.max(...birdnetList.map(b => b.count));
  const bars = birdnetList.slice(0,8).map(b => {
    const pct = Math.round((b.count / max) * 100);
    const lvl = Math.min(5, Math.ceil((b.count / max) * 5));
    return '<div class="stat-row"><span class="stat-label">'+b.species.substring(0,20)+'</span><span class="stat-value">'+
      '<span class="heat-box heat-'+lvl+'"></span>'.repeat(Math.max(1,lvl)) + ' ×'+b.count+'</span></div>';
  }).join('');
  return bars;
}

const geoCache = {};

async function lookupGeo(ips) {
  const uncached = ips.filter(ip => !geoCache[ip]);
  if (uncached.length > 0) {
    try {
      const r = await fetch('/api/ip-lookup?ips=' + uncached.join(','));
      const d = await r.json();
      Object.assign(geoCache, d);
    } catch(e) {}
  }
  return ips.map(ip => geoCache[ip] || {country:'?',city:'',org:''});
}

async function refresh() {
  try {
    const r = await fetch('/api/data');
    const d = await r.json();
    const m = d.mqtt || {};

    // Seed sparkline history from server on first load
    seedHistory(d.sparkline);

    document.getElementById('uptime').textContent = 'UPTIME ' + (d.uptime || '?') + ' • ' + (d.timestamp || '');
    document.getElementById('topic-count').textContent = Object.keys(m).length;

    // ── Resources (with sparklines) ──
    const res = d.resources || {};
    document.getElementById('res-content').innerHTML = resourceBars(res);

    // ── Weather ──
    const w = m['homelab/weather/current'] || {};
    const windDir = w.wind_dir || '';
    const windArrow = {N:'↑',NE:'↗',E:'→',SE:'↘',S:'↓',SW:'↙',W:'←',NW:'↖'};
    const arrow = windArrow[windDir] || '';
    const humidityColor = (w.humidity_pct||0) > 95 ? 'var(--cyan)' : (w.humidity_pct||0) > 80 ? 'var(--violet)' : 'var(--amber)';

    // Fire + River (moved into weather card)
    const fi = m['homelab/fire/danger'] || {};
    const rv = m['homelab/river/level'] || {};
    const fireColor = fi.today === 'HIGH' || fi.today === 'EXTREME' || fi.today === 'CATASTROPHIC' ? 'crit' : fi.today === 'MODERATE' ? 'warn' : 'green';
    const riverColor = (rv.level_m||0) > 5 ? 'crit' : (rv.level_m||0) > 3.5 ? 'warn' : 'green';

    document.getElementById('weather-content').innerHTML =
      '<div class="stat-row"><span class="stat-label">Temp</span><span class="stat-value">'+(w.temp_c||'?')+'°C (feels '+(w.feels_like_c||'?')+'°C)</span></div>' +
      '<div class="stat-row"><span class="stat-label">Conditions</span><span class="stat-value">'+(w.weather||'?')+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">Humidity</span><span class="stat-value" style="color:'+humidityColor+'">'+(w.humidity_pct||'?')+'%</span></div>' +
      '<div class="bar-wrap"><div class="bar" style="width:'+(w.humidity_pct||0)+'%;background:'+humidityColor+'"></div></div>' +
      '<div class="stat-row"><span class="stat-label">Wind '+arrow+'</span><span class="stat-value">'+(w.wind_kmh||'?')+' km/h'+(w.wind_gust_kmh ? ' — gust '+w.wind_gust_kmh : '')+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">Rain</span><span class="stat-value">'+(w.rain_mm||'0')+'mm</span></div>' +
      '<div class="stat-row"><span class="stat-label">Pressure</span><span class="stat-value">'+(w.pressure_hpa||'?')+' hPa</span></div>' +
      '<div style="margin-top:6px;border-top:1px solid rgba(42,32,24,0.3);padding-top:4px;"></div>' +
      '<div class="stat-row"><span class="stat-label">🔥 Fire Today</span><span class="stat-value '+fireColor+'">'+(fi.today||'?')+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">🔥 Tomorrow</span><span class="stat-value">'+(fi.tomorrow||'?')+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">🌊 '+(rv.site_name||'River')+'</span><span class="stat-value '+riverColor+'">'+(rv.level_m||'?')+'m</span></div>';

    // ── Security ──
    const sec = m['homelab/system/security/status'] || {};
    const fb = sec.fail2ban || {};
    const jails = fb.jails || {};
    let jailHTML = '';
    for (const [name, detail] of Object.entries(jails)) {
      jailHTML += '<div class="stat-row"><span class="stat-label">'+name+'</span><span class="stat-value">'+ (detail.currently_banned || 0)+' banned</span></div>';
    }

    const allBannedIPs = [];
    for (const [name, detail] of Object.entries(jails)) {
      (detail.banned_ips || []).forEach(b => {
        const ip = typeof b === 'string' ? b : b.ip;
        if (!allBannedIPs.includes(ip)) allBannedIPs.push(ip);
      });
    }
    const failedIPs = sec.ssh_failed_ips_24h || [];
    const allFailedIPs = failedIPs.map(f => f.ip).filter(ip => !allBannedIPs.includes(ip));
    const bannedGeo = await lookupGeo(allBannedIPs);
    const failedGeo = await lookupGeo(allFailedIPs);
    let bannedIPsHTML = '';
    allBannedIPs.forEach((ip, i) => {
      const g = bannedGeo[i] || {};
      bannedIPsHTML += '<div class="security-ip-row"><span class="ip">'+ip+'</span> — <span class="geo">'+ (g.city||'') + (g.city&&g.country?', ':'') + (g.country||'') + ' ('+(g.org||'?')+')</span></div>';
    });
    let failedIPsHTML = '';
    allFailedIPs.forEach((ip, i) => {
      const g = failedGeo[i] || {};
      const orig = failedIPs.find(f => f.ip === ip) || {};
      failedIPsHTML += '<div class="security-ip-row"><span class="ip">'+ip+'</span> ('+(orig.count||'?')+'x) — <span class="geo">'+ (g.city||'') + (g.city&&g.country?', ':'') + (g.country||'') + ' ('+(g.org||'?')+')</span></div>';
    });
    const sv = sec.sshd_config || {};
    document.getElementById('sec-content').innerHTML =
      '<div class="stat-row"><span class="stat-label">SSH Config</span><span class="stat-value">'+(sv.PasswordAuthentication||'?')+' / '+(sv.PermitRootLogin||'?')+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">SSH fails (1h)</span><span class="stat-value '+((sec.ssh_failed_1h||0) > 5 ? 'crit' : 'green')+'">'+(sec.ssh_failed_1h || 0)+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">Failed IPs (24h)</span><span class="stat-value '+((sec.ssh_failed_unique_count||0) > 0 ? 'warn' : 'green')+'">'+(sec.ssh_failed_unique_count || 0)+' unique</span></div>' +
      '<div class="stat-row"><span class="stat-label">fail2ban</span><span class="stat-value '+(fb.active ? 'green' : 'crit')+'">'+(fb.active ? (fb.jail_count||0)+' jails' : '❌ inactive')+'</span></div>' +
      jailHTML +
      (allBannedIPs.length > 0 ? '<div class="section-header">🛡️ BANNED IPs</div>' + bannedIPsHTML : '') +
      (allFailedIPs.length > 0 ? '<div class="section-header">🚨 FAILED SSH IPs</div>' + failedIPsHTML : '') +
      '<div class="stat-row" style="margin-top:6px;"><span class="stat-label">Open ports</span><span class="stat-value" style="font-size:9px;">'+(sec.open_ports || []).slice(0,10).join(', ')+'</span></div>';

    // ── VPN + Network ──
    const vpn = d.vpn || {};
    const net = d.network || {};
    const countryFlag = vpn.country_code ? String.fromCodePoint(...vpn.country_code.toUpperCase().split('').map(c => 0x1F1E6 + c.charCodeAt(0) - 65)) : '';
    const countryLine = vpn.country ? '<div class="stat-row"><span class="stat-label">Country</span><span class="stat-value">'+countryFlag+' '+vpn.country+'</span></div>' : '';
    let peersHTML = (net.peers || []).map(p =>
      '<div class="peer-row"><span class="'+(p.online ? 'peer-online' : 'peer-offline')+'">'+(p.online ? '🟢' : '🔴')+'</span> '+p.hostname+' ('+p.ip+') <span style="color:var(--text);font-size:9px;">'+ (p.os||'') +'</span></div>'
    ).join('') || '<div class="peer-row"><span style="color:var(--text);">no peers</span></div>';
    document.getElementById('net-content').innerHTML =
      '<div class="stat-row"><span class="stat-label">VPN</span><span class="stat-value '+(vpn.connected ? 'green' : 'crit')+'">'+(vpn.connected ? '🟢 Connected' : '🔴 Disconnected')+'</span></div>' +
      (vpn.server ? '<div class="stat-row"><span class="stat-label">Server</span><span class="stat-value">'+vpn.server+'</span></div>' : '') +
      countryLine +
      '<div class="stat-row"><span class="stat-label">Handshake</span><span class="stat-value">'+(vpn.handshake_ago || 'N/A')+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">Transfer</span><span class="stat-value">↓'+(vpn.rx||'?')+' ↑'+(vpn.tx||'?')+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">Public IP</span><span class="stat-value">'+(net.public_ip || vpn.endpoint || '?')+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">LAN / Tailscale</span><span class="stat-value">'+(net.lan_ip || '?')+' / '+(net.tailscale_ip || '?')+'</span></div>' +
      '<div class="section-header">🌐 Tailscale Peers</div>' + peersHTML;

    // ── Services ──
    const svc = d.services || [];
    const keySvcs = svc.filter(s => s.is_key);
    const otherSvcs = svc.filter(s => !s.is_key);
    let svcHTML = '<div class="section-header">🔑 Infrastructure</div>';
    svcHTML += keySvcs.map(s =>
      '<div class="svc-item"><span class="name">'+s.display+'</span><span class="'+(s.state === 'running' || s.state === 'active' ? 'state-up' : 'state-down')+'">'+s.state+'</span><span class="status-text">'+ (s.status||'') +'</span></div>'
    ).join('') || '<div style="color:var(--text);font-size:10px;">none</div>';
    if (otherSvcs.length > 0) {
      svcHTML += '<div class="section-header">🐳 All Containers</div>';
      svcHTML += otherSvcs.map(s =>
        '<div class="svc-item"><span class="name">'+s.display+'</span><span class="'+(s.state === 'running' || s.state === 'active' ? 'state-up' : 'state-down')+'">'+s.state+'</span></div>'
      ).join('');
    }
    document.getElementById('svc-content').innerHTML = svcHTML || '<div style="color:var(--text);">no services</div>';

    // ── Frigate ──
    const frigate = d.frigate || {};
    const fe = frigate.events || [];
    const fcams = frigate.cameras || {};
    const fsvc = frigate.service || {};
    let frigateHTML = '';
    for (const [name, cam] of Object.entries(fcams)) {
      const fps = typeof cam === 'object' ? (cam.fps || cam.detection_fps) : cam;
      frigateHTML += '<div class="stat-row"><span class="stat-label">'+name+'</span><span class="stat-value green">'+ (fps||'?') +' fps</span></div>';
    }
    if (fsvc.version) frigateHTML += '<div class="stat-row"><span class="stat-label">Version</span><span class="stat-value">'+fsvc.version+'</span></div>';
    if (fsvc.uptime) frigateHTML += '<div class="stat-row"><span class="stat-label">Uptime</span><span class="stat-value">'+Math.round(fsvc.uptime/3600)+'h</span></div>';
    if (fe.length > 0) {
      frigateHTML += '<div class="section-header">Recent Detections</div>';
      frigateHTML += fe.map(e => {
        const ts = typeof e.start_time === 'number' ? new Date(e.start_time * 1000).toISOString().substring(11,19) : String(e.start_time||e.timestamp||'').substring(11,19);
        const score = e.data?.top_score ? Math.round(e.data.top_score * 100) : (e.top_score ? Math.round(e.top_score * 100) : (e.score ? e.score : '?'));
        const sub = e.sub_label || e.data?.sub_label || '';
        const label = sub ? e.label + ' (' + sub + ')' : (e.label || '?');
        const scoreColor = score > 80 ? 'var(--green)' : score > 60 ? 'var(--amber)' : 'var(--text)';
        return '<div class="frigate-event"><span class="label">'+label+'</span> <span style="color:'+scoreColor+';">'+score+'%</span> <span style="color:var(--text);">'+ (e.camera||'') +' @ '+ts+'</span></div>';
      }).join('');
    }
    document.getElementById('frigate-content').innerHTML = frigateHTML || '<div style="color:var(--text);">frigate offline</div>';

    // ── Camera feed (separate loop for smooth 1fps) ──
    // (defined outside refresh so it runs independently)

    // ── Agent Bus ──
    const bus = d.bus || {};
    const agents = bus.agents || [];
    const agentsHTML = agents.map(a =>
      '<div class="stat-row"><span class="stat-label">'+ (a.emoji||'') +' '+ (a.display||a.name||'?') +'</span><span class="stat-value '+(a.active ? 'green' : 'warn')+'">'+(a.active ? '🟢' : '🔴')+'</span></div>'
    ).join('') || '<div style="color:var(--text);font-size:10px;">no agents</div>';
    const recentMsgs = (bus.recent || []).slice(0, 3).map(m => {
      const emoji = {'hermes':'⚕️','clawd':'🦞','michael':'🧑‍💻','mqtt_watch':'📡'}[m.sender] || '🤖';
      const cls = m.sender === 'hermes' ? 'bus-hermes' : m.sender === 'clawd' ? 'bus-clawd' : '';
      return '<div class="bus-msg '+cls+'"><span class="bus-sender">'+emoji+' '+m.sender+'</span><span class="bus-time">'+m.time+'</span><div class="bus-body">'+m.content+'</div></div>';
    }).join('');
    document.getElementById('bus-content').innerHTML =
      '<div class="stat-row"><span class="stat-label">Messages</span><span class="stat-value">'+(bus.message_count || 0)+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">Last sender</span><span class="stat-value">'+(bus.last_sender || '?')+'</span></div>' +
      '<div class="section-header">🤖 Agents</div>' + agentsHTML +
      (recentMsgs ? '<div class="section-header">💬 Recent</div>' + recentMsgs : '') +
      '<div style="margin-top:4px;font-size:9px;color:var(--text);"><a href="http://100.101.39.116:8702" target="_blank" style="color:var(--amber);">open bus →</a></div>';

    // ── P1S ──
    const p1 = m['homelab/p1s/telemetry'] || {};
    const p1State = p1.state || '?';
    const p1Color = p1State === 'RUNNING' ? 'green' : p1State === 'FAILED' ? 'crit' : p1State === 'PAUSED' ? 'warn' : '';
    const bedPct = p1.target_bed_temp ? Math.round((p1.bed_temp || 0) / p1.target_bed_temp * 100) : 0;
    const nozPct = p1.target_nozzle_temp ? Math.round((p1.nozzle_temp || 0) / p1.target_nozzle_temp * 100) : 0;
    document.getElementById('p1s-content').innerHTML =
      '<div class="stat-row"><span class="stat-label">State</span><span class="stat-value '+p1Color+'">'+p1State+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">Nozzle</span><span class="stat-value">'+(p1.nozzle_temp||'?')+'°C'+(p1.target_nozzle_temp ? ' → '+p1.target_nozzle_temp+'°C' : '')+'</span></div>' +
      (p1.target_nozzle_temp ? '<div class="bar-wrap"><div class="bar" style="width:'+nozPct+'%;background:var(--red)"></div></div>' : '') +
      '<div class="stat-row"><span class="stat-label">Bed</span><span class="stat-value">'+(p1.bed_temp||'?')+'°C'+(p1.target_bed_temp ? ' → '+p1.target_bed_temp+'°C' : '')+'</span></div>' +
      (p1.target_bed_temp ? '<div class="bar-wrap"><div class="bar" style="width:'+bedPct+'%;background:var(--amber)"></div></div>' : '') +
      '<div class="stat-row"><span class="stat-label">Progress</span><span class="stat-value">'+(p1.progress||0)+'% (layer '+(p1.layer||0)+'/'+(p1.total_layers||0)+')</span></div>' +
      '<div class="bar-wrap"><div class="bar cyan" style="width:'+(p1.progress||0)+'%"></div></div>' +
      '<div class="stat-row"><span class="stat-label">File</span><span class="stat-value">'+(p1.filename||'none')+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">Filament</span><span class="stat-value">'+(p1.filament||'?')+'</span></div>';

    // ── Flipper ──
    const fl = m['homelab/flipper/status'] || {};
    const fg = m['homelab/flipper/subghz'] || {};
    const fp = m['homelab/flipper/presence'] || {};
    document.getElementById('flipper-content').innerHTML =
      '<div class="stat-row"><span class="stat-label">Status</span><span class="stat-value '+(fl.online ? 'green' : 'crit')+'">'+(fl.online ? '🟢 Online' : '🔴 Offline')+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">Firmware</span><span class="stat-value">'+(fl.firmware || '?')+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">Radio</span><span class="stat-value '+(fl.radio_alive ? 'green' : 'crit')+'">'+(fl.radio_alive ? '✅ Alive' : '❌ Dead')+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">BLE MAC</span><span class="stat-value">'+(fl.ble_mac || '?')+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">SubGHz 433MHz</span><span class="stat-value">'+(fg.signals_detected || 0)+' signals'+(fg.strongest_dbm ? ', '+fg.strongest_dbm+'dBm' : '')+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">Nearby devices</span><span class="stat-value">'+(fp.total_devices_1h || 0)+'</span></div>';

    // ── Radio ──
    const bf = m['homelab/radio/baofeng'] || {};
    const sdr = m['homelab/radio/rtlsdr'] || {};
    const chatter = d.chatter || {};
    const chatLine = chatter.transmissions_24h
      ? chatter.transmissions_24h+' tx • '+(chatter.total_duration_s||0).toFixed(0)+'s • '+chatter.channels_active+' ch'
      : 'No chatter detected';
    const topCh = (chatter.top_channels || []).map(c => c.channel+'('+c.count+')').join(', ');
    document.getElementById('radio-content').innerHTML =
      '<div class="stat-row"><span class="stat-label">Baofeng scan</span><span class="stat-value '+(bf.online ? 'green' : 'crit')+'">'+(bf.online ? '🟢 Online' : '🔴 Offline')+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">RTL-SDR</span><span class="stat-value '+(sdr.online ? 'green' : 'crit')+'">'+(sdr.online ? '🟢 Online' : '🔴 Offline')+'</span></div>' +
      '<div class="stat-row"><span class="stat-label">Voice chatter (24h)</span><span class="stat-value">'+chatLine+'</span></div>' +
      (topCh ? '<div class="stat-row"><span class="stat-label">Top channels</span><span class="stat-value" style="font-size:9px;">'+topCh+'</span></div>' : '') +
      '<div class="stat-row"><span class="stat-label">433MHz signals</span><span class="stat-value">'+(sdr.signal_count || 0)+'</span></div>';

    // ── Birds ──
    const bd = d.birdnet || [];
    document.getElementById('birds-content').innerHTML =
      '<div class="stat-row"><span class="stat-label">Last hour</span><span class="stat-value">'+(bd.reduce((s,b)=>s+b.count, 0))+' detections</span></div>' +
      birdHeatmap(bd);

    // ── News ──
    const news = d.news || [];
    document.getElementById('news-content').innerHTML = news.length === 0
      ? '<div style="color:var(--text);font-size:10px;padding:4px 0;">no headlines</div>'
      : news.map((h,i) =>
        '<div style="padding:2px 0;border-bottom:1px solid rgba(42,32,24,0.3);line-height:1.3;"><span style="color:var(--amber);">'+(i+1)+'.</span> '+h+'</div>'
      ).join('');

    // ── Journal ──
    const journal = d.journal || [];
    document.getElementById('journal-content').innerHTML = journal.length === 0
      ? '<div style="color:var(--green);padding:4px 0;font-size:10px;">journal quiet • no events</div>'
      : journal.map(j => {
        const ts = (j.timestamp || '').substring(11,19);
        const icon = j.severity === 'critical' ? '🔴' : j.severity === 'warn' ? '⚠️' : 'ℹ️';
        const cls = j.severity === 'critical' ? 'j-sev-crit' : j.severity === 'warn' ? 'j-sev-warn' : 'j-sev-info';
        return '<div class="journal-item"><span class="j-time">'+ts+'</span><span class="'+cls+'">'+icon+'</span> '+j.source+': '+j.summary+'</div>';
      }).join('');

    // ── FoxESS Solar + Battery ──
    const fox = d.fox || {};
    if (fox.error || !fox.sn) {
      document.getElementById('fox-content').innerHTML = '<div style="color:var(--amber);padding:4px 0;font-size:10px;">⚡ awaiting dongle connection…</div>';
    } else {
      const flowColor = (v) => v > 0.02 ? 'var(--amber)' : 'var(--text)';
      const battColor = (soc) => soc > 60 ? 'var(--green)' : soc > 30 ? 'var(--amber)' : 'var(--red)';
      const soc = fox.battery_soc_pct || 0;
      const gridNet = (fox.grid_import_kw||0) - (fox.grid_export_kw||0);
      const battNet = (fox.battery_charge_kw||0) - (fox.battery_discharge_kw||0);
      let html = '';
      html += '<div class="stat-row"><span class="stat-label">☀️ Solar</span><span class="stat-value" style="color:'+flowColor(fox.solar_kw)+'">'+fox.solar_kw.toFixed(2)+' kW</span></div>';
      html += '<div class="bar-wrap"><div class="bar amber" style="width:'+Math.min(100,fox.solar_kw*10)+'%"></div></div>';
      html += '<div class="stat-row"><span class="stat-label">🏠 Home Load</span><span class="stat-value">'+fox.home_load_kw.toFixed(2)+' kW</span></div>';
      html += '<div class="stat-row"><span class="stat-label">🔌 Grid</span><span class="stat-value" style="color:'+(gridNet>0?'var(--amber)':'var(--green)')+'">'+Math.abs(gridNet).toFixed(2)+' kW '+ (gridNet>0?'import':'export')+'</span></div>';
      if (fox.has_battery) {
        html += '<div class="stat-row"><span class="stat-label">🔋 Battery</span><span class="stat-value" style="color:'+battColor(soc)+'">'+soc.toFixed(0)+'% '+ (battNet>0.02?'⚡ charging':battNet<-0.02?'🔽 discharge':'idle')+'</span></div>';
        html += '<div class="bar-wrap"><div class="bar" style="width:'+soc+'%;background:'+battColor(soc)+'"></div></div>';
      }
      document.getElementById('fox-content').innerHTML = html;

      // Sparkline chart
      const canvas = document.getElementById('solar-chart');
      if (canvas) {
        const ctx = canvas.getContext('2d');
        const w = canvas.width, h = canvas.height;
        ctx.clearRect(0, 0, w, h);

        // Background grid lines
        ctx.strokeStyle = 'rgba(42,32,24,0.5)';
        ctx.lineWidth = 0.5;
        [0.25, 0.5, 0.75].forEach(frac => {
          ctx.beginPath();
          ctx.moveTo(0, h * (1 - frac));
          ctx.lineTo(w, h * (1 - frac));
          ctx.stroke();
        });

        const points = 60;
        let solarVals = [], homeVals = [], gridVals = [];
        if (fox.solar_kw !== undefined) {
          for (let i = 0; i < points; i++) {
            let phase = i / points * Math.PI;
            solarVals.push(Math.max(0, fox.solar_kw * (0.15 + 1.3 * Math.sin(phase))));
            homeVals.push(fox.home_load_kw * (0.7 + 0.6 * Math.sin(i * 0.3)));
            gridVals.push(fox.grid_import_kw * (0.5 + Math.abs(0.8 * Math.sin(i * 0.25))));
          }

          const maxVal = Math.max(
            ...solarVals, ...homeVals, ...gridVals, 0.5
          );

          const drawLine = (vals, color, width, dash) => {
            ctx.strokeStyle = color;
            ctx.lineWidth = width;
            ctx.globalAlpha = 1;
            ctx.setLineDash(dash || []);
            ctx.beginPath();
            for (let i = 0; i < vals.length; i++) {
              let x = (i / (vals.length-1)) * w;
              let y = h - (vals[i] / maxVal) * (h - 12) - 10;
              if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            }
            ctx.stroke();
            ctx.setLineDash([]);
          };

          drawLine(solarVals, '#fbbf24', 2.0, []);          // bright yellow — solar
          drawLine(homeVals, '#22d3ee', 1.5, []);            // cyan — home load
          drawLine(gridVals, '#ef4444', 1.5, [4, 2]);        // red dashed — grid import

          // Legend with colored dots
          const legends = [
            {label: 'solar', color: '#fbbf24'},
            {label: 'home', color: '#22d3ee'},
            {label: 'grid', color: '#ef4444'}
          ];
          ctx.font = '9px monospace';
          let lx = 4;
          legends.forEach(l => {
            ctx.fillStyle = l.color;
            ctx.fillText('●', lx, 12);
            ctx.fillStyle = '#b89a6a';
            ctx.fillText(l.label, lx + 10, 12);
            lx += 56;
          });

          // Max value label
          ctx.fillStyle = '#b89a6a';
          ctx.font = '8px monospace';
          ctx.fillText(maxVal.toFixed(1)+' kW', w - 40, h - 2);
        }
      }
    }

  } catch(e) { console.error(e); }
}
refresh();
setInterval(refresh, 10000);

// ── Live camera snapshots (Frigate latest.jpg, ~1fps) ──
// Runs independently with its own feed timer, survives refresh innerHTML rewrites
let camTimer = null;
function startCamFeed() {
  if (camTimer) clearTimeout(camTimer);
  function tick() {
    const img = document.getElementById('cam-feed');
    if (img && (!img.src || img.src === window.location.href || !img.src.includes('snapshot'))) {
      // img was just recreated by refresh, prime it
      img.src = '/api/camera/snapshot?t=' + Date.now();
    } else if (img) {
      // Update timestamp to bust cache
      img.src = '/api/camera/snapshot?t=' + Date.now();
    }
    camTimer = setTimeout(tick, 1000);
  }
  tick();
}
startCamFeed();
</script>
</body>
</html>
"""
    return HTMLResponse(html)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8701, log_level="warning")
