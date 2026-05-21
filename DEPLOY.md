# Kafkam — Railway Deployment & Camera Setup Guide

## 1. Deploy to Railway

1. Push this repo to GitHub (or use Railway CLI: `railway up`)
2. In Railway dashboard → **New Project → Deploy from GitHub repo**
3. Add a **PostgreSQL** plugin (Railway auto-sets `DATABASE_URL`)
4. Set environment variables (see Section 3)
5. Railway builds automatically via `nixpacks.toml` (ffmpeg is installed)

---

## 2. First-run: create admin account

After deploy, visit once:

```
https://your-app.railway.app/setup-database-xyz
```

This creates `admin / admin123`. **Log in immediately and change your password** in Settings.  
This route is blocked after the first admin is created — it will return 403 forever after.

---

## 3. Required environment variables (Railway → Variables tab)

| Variable | Value |
|---|---|
| `SECRET_KEY` | Run `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | Auto-set by Railway PostgreSQL plugin |
| `CAMERA_NAME` | Display label, e.g. `Front Door` |

Then add ONE camera source:

---

## 4. Camera Setup

### 4A — Phone as IP Camera (DroidCam style)

This works exactly like DroidCam: you type an IP/URL and see the feed anywhere.

**On your phone:**
- **Android:** Install **IP Webcam** (free, no account needed)  
  Start server → note local IP e.g. `192.168.1.50:8080`  
  Stream URL: `http://192.168.1.50:8080/video`
- **Android alternative:** Install **DroidCam** → stream is at `http://192.168.1.50:4747/video`
- **iOS:** Install **EpocCam** or **iVCam**

**On a PC on the same WiFi network — create a public tunnel:**

```bash
# Install bore (one-line):
npx bore local 8080 --to bore.pub
# OR install globally: npm i -g bore-cli

# For DroidCam (port 4747):
npx bore local 4747 --to bore.pub
```

Bore prints something like: `bore.pub:XXXXX`

**In Railway Variables:**
```
CAMERA_URL=http://bore.pub:XXXXX/video
```

> **Alternative tunnel (if bore is blocked):** Use [ngrok](https://ngrok.com):  
> `ngrok http 8080` → copy the https URL → set as `CAMERA_URL`

---

### 4B — CCTV Camera via Router/Switch (RTSP)

Your CCTV camera/NVR is on your home LAN. Kafkam pulls it via RTSP over the internet.

**Step 1: Find your camera's local RTSP URL**

| Brand | URL format |
|---|---|
| Hikvision | `rtsp://admin:PASSWORD@192.168.1.10:554/Streaming/Channels/101` |
| Dahua | `rtsp://admin:PASSWORD@192.168.1.10:554/cam/realmonitor?channel=1&subtype=0` |
| Reolink | `rtsp://admin:PASSWORD@192.168.1.10:554/h264Preview_01_main` |
| Generic | `rtsp://192.168.1.10:554/stream1` |

Test locally with VLC: Media → Open Network Stream → paste RTSP URL.

**Step 2: Port forward on your router**

- Log in to your router (usually `192.168.1.1`)
- Add port forward: **External 554 → Internal [camera IP]:554**
- Find your public IP at [whatismyip.com](https://whatismyip.com)

**Step 3: Set Railway variable**

```
CAMERA_RTSP_URL=rtsp://admin:PASSWORD@YOUR_PUBLIC_IP:554/Streaming/Channels/101
```

**Step 4: Static IP (optional but recommended)**

Your ISP assigns a dynamic public IP. To avoid it changing:
- Use a free DDNS service like [No-IP](https://noip.com) or [DuckDNS](https://duckdns.org)
- Replace `YOUR_PUBLIC_IP` with your DDNS hostname

---

### 4C — Both phone + CCTV

Set both `CAMERA_RTSP_URL` (CCTV, shown by default) and `CAMERA_URL` (phone fallback).  
To switch feeds, comment out `CAMERA_RTSP_URL` in Railway variables and redeploy.

---

## 5. Accessing the feed anywhere

Once deployed, your Kafkam URL is your **permanent public camera portal**:

```
https://your-app.railway.app/login
```

- Anyone with the username/password can log in and see the live feed
- Works on phone, tablet, desktop — anywhere in the world
- The feed is proxied through Railway (your camera IP is never exposed)

---

## 6. Security notes

- Change the default `admin / admin123` password immediately after first login
- Use a strong `SECRET_KEY` (32+ random hex characters)
- Don't share your Railway URL publicly — it's your private camera portal
- RTSP credentials (camera username/password) are stored in Railway env vars, not in code
