# KAFKAM — CCTV Monitoring System

A web-based CCTV monitoring dashboard built with Flask. Supports live IP camera feeds via RTSP or HTTP snapshot, with a built-in demo mode when no hardware is connected.

## Features

- Login / logout with session management and audit logging
- Live camera feed — RTSP (real CCTV), HTTP snapshot (phone IP cam), or animated demo
- Activity logs with device detection and Philippine Standard Time timestamps
- Account settings (change username and password)
- Deployable to Railway (PostgreSQL) or local (SQLite)

## Camera modes

| Mode | Set this env var | Use case |
|---|---|---|
| RTSP | `CAMERA_RTSP_URL` | Hikvision, Dahua, Reolink, TP-Link, any RTSP cam |
| HTTP snapshot | `CAMERA_URL` | Android IP Webcam app, basic cameras |
| Demo | *(neither set)* | No hardware — animated test pattern |

## Quick start (local)

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in your values
python run.py
# visit http://localhost:5000
# first run: visit http://localhost:5000/setup-database-xyz
# login: admin / admin123  ← change password immediately
```

## Railway deployment

1. Push this repo to GitHub
2. Connect to Railway → New Project → Deploy from GitHub repo
3. Add environment variables in Railway dashboard:
   - `SECRET_KEY` — random string (`python -c "import secrets; print(secrets.token_hex(32))"`)
   - `CAMERA_RTSP_URL` or `CAMERA_URL` — your camera source (optional, demo mode works without)
   - `CAMERA_NAME` — display name (e.g. "Main Entrance")
4. Railway auto-detects `nixpacks.toml` (includes ffmpeg) and `Procfile`
5. After first deploy, visit `https://<your-app>.railway.app/setup-database-xyz` once to init the DB

## Phone as IP camera (no hardware needed yet)

1. Install **IP Webcam** (Android, free) or **EpocCam** (iOS)
2. Start the server in the app and note the IP (e.g. `192.168.1.50:8080`)
3. Set `CAMERA_URL=http://192.168.1.50:8080/shot.jpg`
4. For Railway access (phone not on same network), run `ngrok http 8080` on your phone and use the ngrok URL

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | Flask session secret — use a long random string |
| `DATABASE_URL` | Auto (Railway) | PostgreSQL URL — Railway sets this automatically |
| `CAMERA_RTSP_URL` | Optional | RTSP stream URL for real CCTV cameras |
| `CAMERA_URL` | Optional | HTTP snapshot URL for phone/basic cameras |
| `CAMERA_NAME` | Optional | Display name shown in the dashboard |

## Tech stack

- Backend: Python, Flask, SQLAlchemy, Flask-Login, ffmpeg
- Frontend: Jinja2, Tailwind CSS
- Database: SQLite (local) / PostgreSQL (Railway)
- Deployment: Railway (nixpacks + gunicorn)
