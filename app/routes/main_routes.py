import os
import re
import subprocess
import time
import logging
from flask import (Response, stream_with_context, render_template,
                   redirect, url_for, request, flash, Blueprint,
                   make_response, session, jsonify)
from flask_login import login_user, logout_user, login_required, current_user
from app.models.user import User
from app.models.log import AuditLog
from app import db, limiter
import requests

logger = logging.getLogger(__name__)
main = Blueprint('main', __name__)

# ─── Allowed camera URL schemes ───────────────────────────────────────────────
_ALLOWED_SNAPSHOT_SCHEMES = re.compile(r'^https?://', re.IGNORECASE)
_ALLOWED_RTSP_SCHEMES = re.compile(r'^rtsps?://', re.IGNORECASE)

def _validate_camera_url(url: str, mode: str) -> bool:
    """Reject anything that isn't a plain http/https/rtsp URL."""
    if not url:
        return False
    if mode == 'snapshot':
        return bool(_ALLOWED_SNAPSHOT_SCHEMES.match(url))
    if mode == 'rtsp':
        return bool(_ALLOWED_RTSP_SCHEMES.match(url))
    return False


# ─── Camera source resolution ─────────────────────────────────────────────────
def get_camera_mode():
    # DB config takes priority over env vars so the Settings page works
    try:
        from app.models.camera_config import CameraConfig
        cfg = CameraConfig.get()
        rtsp = (cfg.camera_rtsp_url or '').strip()
        snap = (cfg.camera_url or '').strip()
    except Exception:
        rtsp = ''
        snap = ''

    # Fall back to env vars if DB has nothing
    if not rtsp:
        rtsp = os.environ.get('CAMERA_RTSP_URL', '').strip()
    if not snap:
        snap = os.environ.get('CAMERA_URL', '').strip()

    mode = os.environ.get('CAMERA_MODE', '').strip().lower()

    if mode == 'mjpeg' and snap and _validate_camera_url(snap, 'snapshot'):
        return 'snapshot', snap
    if rtsp and _validate_camera_url(rtsp, 'rtsp'):
        return 'rtsp', rtsp
    if snap and _validate_camera_url(snap, 'snapshot'):
        return 'snapshot', snap
    return 'demo', None


def get_camera_name():
    try:
        from app.models.camera_config import CameraConfig
        cfg = CameraConfig.get()
        if cfg.camera_name:
            return cfg.camera_name
    except Exception:
        pass
    return os.environ.get('CAMERA_NAME', 'Live Remote Feed')


def check_camera_live(camera_url, timeout=3):
    if not camera_url or not _validate_camera_url(camera_url, 'snapshot'):
        return False
    try:
        headers = {"User-Agent": "KafkamCCTV/1.0", "Accept": "*/*"}
        response = requests.get(
            camera_url, headers=headers, timeout=timeout,
            stream=True, allow_redirects=False   # don't follow open-redirect chains
        )
        return response.status_code == 200
    except Exception:
        return False


# ─── MJPEG stream generators ──────────────────────────────────────────────────

def _generate_rtsp(rtsp_url):
    """Pull RTSP with ffmpeg and emit MJPEG multipart frames."""
    if not _validate_camera_url(rtsp_url, 'rtsp'):
        logger.error("Blocked invalid RTSP URL: %s", rtsp_url)
        return

    cmd = [
        'ffmpeg',
        '-rtsp_transport', 'tcp',
        '-i', rtsp_url,
        '-f', 'image2pipe',
        '-vcodec', 'mjpeg',
        '-r', '15',
        '-q:v', '4',
        'pipe:1'
    ]
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    data = b''
    try:
        while True:
            chunk = process.stdout.read(4096)
            if not chunk:
                break
            data += chunk
            # Prevent unbounded memory growth if JPEG markers never appear
            if len(data) > 10 * 1024 * 1024:
                data = b''
                continue
            start = data.find(b'\xff\xd8')
            end   = data.find(b'\xff\xd9')
            if start != -1 and end != -1 and end > start:
                frame = data[start:end + 2]
                data  = data[end + 2:]
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    finally:
        process.kill()


def _generate_snapshot(snapshot_url):
    """Relay a remote MJPEG/snapshot stream securely."""
    if not _validate_camera_url(snapshot_url, 'snapshot'):
        logger.error("Blocked invalid snapshot URL: %s", snapshot_url)
        return

    headers = {"User-Agent": "KafkamCCTV/1.0"}
    is_mjpeg_stream = any(
        tok in snapshot_url
        for tok in ('bore.pub', 'cam1', '/video', '/stream', '/mjpeg')
    )

    if is_mjpeg_stream:
        while True:
            try:
                with requests.get(
                    snapshot_url, headers=headers,
                    stream=True, timeout=5,
                    allow_redirects=False
                ) as r:
                    if r.status_code == 200:
                        for chunk in r.iter_content(chunk_size=64 * 1024):
                            if chunk:
                                yield chunk
            except Exception as e:
                logger.debug("Stream reconnect: %s", e)
                time.sleep(2)
    else:
        while True:
            try:
                response = requests.get(
                    snapshot_url, headers=headers,
                    timeout=5, allow_redirects=False
                )
                if response.status_code == 200:
                    # Enforce a 10 MB frame size cap to prevent memory exhaustion
                    frame = response.content[:10 * 1024 * 1024]
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            except Exception:
                pass
            time.sleep(0.1)  # ~10 fps


def _generate_demo():
    """Generate a live demo test pattern via ffmpeg (no hardware needed)."""
    cmd = [
        'ffmpeg',
        '-f', 'lavfi',
        '-i', 'testsrc2=size=1280x720:rate=15',
        '-vf', "drawtext=text='KAFKAM DEMO MODE — No camera connected'"
               ":fontsize=28:fontcolor=white:x=(w-text_w)/2:y=40:"
               "box=1:boxcolor=black@0.5:boxborderw=8,"
               "drawtext=text='%{localtime\\:%Y-%m-%d %H\\:%M\\:%S}'"
               ":fontsize=22:fontcolor=yellow:x=(w-text_w)/2:y=90",
        '-f', 'image2pipe',
        '-vcodec', 'mjpeg',
        '-r', '15',
        '-q:v', '4',
        'pipe:1'
    ]
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    data = b''
    try:
        while True:
            chunk = process.stdout.read(4096)
            if not chunk:
                break
            data += chunk
            if len(data) > 10 * 1024 * 1024:
                data = b''
                continue
            start = data.find(b'\xff\xd8')
            end   = data.find(b'\xff\xd9')
            if start != -1 and end != -1 and end > start:
                frame = data[start:end + 2]
                data  = data[end + 2:]
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    finally:
        process.kill()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_device():
    ua = request.user_agent.string.lower()
    if 'iphone' in ua:
        return 'iPhone'
    elif 'ipad' in ua:
        return 'iPad'
    elif 'android' in ua and 'mobile' in ua:
        return 'Android Phone'
    elif 'android' in ua:
        return 'Android Tablet'
    elif 'windows' in ua:
        return 'Windows'
    elif 'macintosh' in ua or 'mac os' in ua:
        return 'Mac'
    elif 'linux' in ua:
        return 'Linux'
    return 'Unknown Device'


def log_action(action):
    # Truncate action string to prevent oversized audit entries
    entry = AuditLog(
        action=str(action)[:50],
        ip_address=request.remote_addr or '0.0.0.0',
        device=get_device(),
        user_id=current_user.id
    )
    db.session.add(entry)
    db.session.commit()


# ─── Security headers helper ──────────────────────────────────────────────────

def _secure_response(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=()'
    return response


# ─── Public routes ────────────────────────────────────────────────────────────

@main.route('/')
def home():
    return redirect(url_for('main.login'))


@main.route('/login', methods=['GET', 'POST'])
@limiter.limit("20 per minute")
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        # Basic input size guards to prevent oversized payloads
        if len(username) > 150 or len(password) > 256:
            flash('Invalid credentials.', 'error')
            return redirect(url_for('main.login'))

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session.permanent = False
            login_user(user, remember=False)
            entry = AuditLog(
                action='Login',
                ip_address=request.remote_addr or '0.0.0.0',
                device=get_device(),
                user_id=user.id
            )
            db.session.add(entry)
            db.session.commit()
            return redirect(url_for('main.dashboard'))
        else:
            flash('Invalid username or password.', 'error')

    response = make_response(render_template('login.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return _secure_response(response)


# ─── Protected routes ─────────────────────────────────────────────────────────

@main.route('/dashboard')
@login_required
def dashboard():
    mode, source = get_camera_mode()

    if mode == 'snapshot' and source:
        camera_online = check_camera_live(source)
    elif mode == 'rtsp' and source:
        camera_online = True
    else:
        camera_online = True
        mode = 'demo'

    log_action('Viewed Dashboard')

    return render_template(
        'dashboard.html',
        camera_online=camera_online,
        camera_mode=mode,
        camera_raw_url=source,
        camera_name=get_camera_name()
    )


@main.route('/camera-feed')
@login_required
def camera_feed():
    """Single secure server-side mirror endpoint."""
    mode, source = get_camera_mode()

    if mode == 'rtsp':
        generator = _generate_rtsp(source)
    elif mode == 'snapshot':
        generator = _generate_snapshot(source)
    else:
        generator = _generate_demo()

    return Response(
        stream_with_context(generator),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@main.route('/camera-status')
@login_required
def camera_status():
    mode, source = get_camera_mode()
    if mode == 'snapshot':
        online = check_camera_live(source)
    else:
        online = True
    return jsonify({'online': online, 'mode': mode})


@main.route('/logs')
@login_required
def logs():
    page = request.args.get('page', 1, type=int)
    all_logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).paginate(
        page=page, per_page=100, error_out=False
    )
    return render_template('logs.html', logs=all_logs.items)


@main.route('/settings')
@login_required
def settings():
    mode, source = get_camera_mode()
    return render_template('settings.html',
                           camera_mode=mode,
                           camera_source=source or '',
                           camera_name=get_camera_name())


@main.route('/update-username', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def update_username():
    new_username = request.form.get('username', '').strip()
    if not new_username or len(new_username) > 150:
        flash('Username is invalid or too long.', 'error')
        return redirect(url_for('main.settings'))

    taken = User.query.filter_by(username=new_username).first()
    if taken and taken.id != current_user.id:
        flash('Username is already taken.', 'error')
        return redirect(url_for('main.settings'))

    current_user.username = new_username
    db.session.commit()
    log_action('Changed Username')
    flash('Username updated successfully.', 'success')
    return redirect(url_for('main.settings'))


@main.route('/update-password', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def update_password():
    current_pw  = request.form.get('current_password', '')
    new_pw      = request.form.get('new_password', '')
    confirm_pw  = request.form.get('confirm_password', '')

    if not current_user.check_password(current_pw):
        flash('Current password is incorrect.', 'error')
        return redirect(url_for('main.settings'))

    if new_pw != confirm_pw:
        flash('New passwords do not match.', 'error')
        return redirect(url_for('main.settings'))

    if len(new_pw) < 8:
        flash('Password must be at least 8 characters.', 'error')
        return redirect(url_for('main.settings'))

    if len(new_pw) > 256:
        flash('Password is too long.', 'error')
        return redirect(url_for('main.settings'))

    current_user.set_password(new_pw)
    db.session.commit()
    log_action('Changed Password')
    flash('Password updated successfully.', 'success')
    return redirect(url_for('main.settings'))


@main.route('/update-camera', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def update_camera():
    from app.models.camera_config import CameraConfig

    source_type  = request.form.get('source_type', 'http').strip()
    camera_url   = request.form.get('camera_url', '').strip()
    camera_rtsp  = request.form.get('camera_rtsp_url', '').strip()
    camera_name  = request.form.get('camera_name', '').strip()[:100]

    # Validate URLs
    if camera_url and not _validate_camera_url(camera_url, 'snapshot'):
        flash('Camera URL must start with http:// or https://', 'error')
        return redirect(url_for('main.settings'))
    if camera_rtsp and not _validate_camera_url(camera_rtsp, 'rtsp'):
        flash('RTSP URL must start with rtsp://', 'error')
        return redirect(url_for('main.settings'))

    cfg = CameraConfig.get()
    if source_type == 'rtsp':
        cfg.camera_rtsp_url = camera_rtsp or None
        cfg.camera_url = None
    else:
        cfg.camera_url = camera_url or None
        cfg.camera_rtsp_url = None
    cfg.camera_name = camera_name or 'Live Remote Feed'
    db.session.commit()
    log_action('Updated Camera Config')
    flash('Camera source updated.', 'success')
    return redirect(url_for('main.settings'))


@main.route('/clear-camera', methods=['POST'])
@login_required
def clear_camera():
    from app.models.camera_config import CameraConfig
    cfg = CameraConfig.get()
    cfg.camera_url = None
    cfg.camera_rtsp_url = None
    db.session.commit()
    log_action('Cleared Camera Config')
    flash('Camera source cleared. Now showing demo mode.', 'success')
    return redirect(url_for('main.settings'))



@login_required
def logout():
    log_action('Logout')
    logout_user()
    return redirect(url_for('main.login'))


# ─── One-time setup ───────────────────────────────────────────────────────────

@main.route('/setup-database-xyz')
def setup_database():
    """
    Protected setup route. Requires SECRET_KEY env var AND the route can only
    be called when no admin user exists yet (first-run guard).
    """
    if not os.environ.get('SECRET_KEY'):
        return '<h1>Disabled</h1>', 403

    # First-run guard: once an admin exists, block this route entirely.
    if User.query.filter_by(username='admin').first():
        return '<h1>Already initialised</h1>', 403

    try:
        db.create_all()   # removed drop_all — never nuke prod data via HTTP
        admin = User(username='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        return ('<h1>SUCCESS</h1>'
                '<p>Database ready. Login: admin / admin123 — '
                '<strong>change password immediately.</strong></p>')
    except Exception as e:
        logger.exception("Setup failed")
        return '<h1>ERROR</h1><p>Check server logs.</p>', 500
