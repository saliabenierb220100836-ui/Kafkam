import os
import subprocess
import threading
import time
from flask import (Response, stream_with_context, render_template,
                   redirect, url_for, request, flash, Blueprint,
                   make_response, session, jsonify)
from flask_login import login_user, logout_user, login_required, current_user
from app.models.user import User
from app.models.log import AuditLog
from app import db
import requests

main = Blueprint('main', __name__)

# ─── Camera source resolution ─────────────────────────────────────────────────
def get_camera_mode():
    rtsp = os.environ.get('CAMERA_RTSP_URL', '').strip()
    snap = os.environ.get('CAMERA_URL', '').strip()
    mode = os.environ.get('CAMERA_MODE', '').strip().lower()
    
    if mode == 'mjpeg' and snap:
        return 'snapshot', snap
    if rtsp:
        return 'rtsp', rtsp
    if snap:
        return 'snapshot', snap
    return 'demo', None


def check_camera_live(camera_url, timeout=3):
    if not camera_url:
        return False
    try:
        # Inject bypass headers so LocalTunnel skips the IP verification landing screen
        headers = {
            "Bypass-Tunnel-Reminder": "true",
            "User-Agent": "KafkamCCTV/1.0",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8"
        }
        response = requests.get(camera_url, headers=headers, timeout=timeout, stream=True)
        return response.status_code == 200
    except Exception:
        return False


# ─── MJPEG stream generators ──────────────────────────────────────────────────

def _generate_rtsp(rtsp_url):
    """Pull RTSP with ffmpeg and emit MJPEG multipart frames."""
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
            start = data.find(b'\xff\xd8')
            end = data.find(b'\xff\xd9')
            if start != -1 and end != -1 and end > start:
                frame = data[start:end + 2]
                data = data[end + 2:]
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    finally:
        process.kill()


def _generate_snapshot(snapshot_url):
    """Poll an HTTP snapshot URL/Stream and emit MJPEG multipart frames."""
    headers = {
        "Bypass-Tunnel-Reminder": "true",
        "User-Agent": "KafkamCCTV/1.0"
    }
    
    # Check if we are pointing directly to an MJPEG streaming endpoint (/video)
    if snapshot_url.endswith('/video'):
        try:
            # Stream directly from the proxy tunnel to save processing overhead
            with requests.get(snapshot_url, headers=headers, stream=True, timeout=10) as r:
                for chunk in r.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
        except Exception:
            time.sleep(1)
    else:
        # Fallback to standard snapshot frame-by-frame polling loop
        while True:
            try:
                response = requests.get(snapshot_url, headers=headers, timeout=5)
                if response.status_code == 200:
                    frame = response.content
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
            start = data.find(b'\xff\xd8')
            end = data.find(b'\xff\xd9')
            if start != -1 and end != -1 and end > start:
                frame = data[start:end + 2]
                data = data[end + 2:]
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
    entry = AuditLog(
        action=action,
        ip_address=request.remote_addr,
        device=get_device(),
        user_id=current_user.id
    )
    db.session.add(entry)
    db.session.commit()


# ─── Public routes ────────────────────────────────────────────────────────────

@main.route('/')
def home():
    return redirect(url_for('main.login'))


@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session.permanent = False
            login_user(user, remember=False)
            entry = AuditLog(
                action='Login',
                ip_address=request.remote_addr,
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
    return response


# ─── Protected routes ─────────────────────────────────────────────────────────

@main.route('/dashboard')
@login_required
def dashboard():
    mode, source = get_camera_mode()

    if mode == 'snapshot':
        camera_online = check_camera_live(source)
    elif mode == 'rtsp':
        camera_online = True
    else:
        camera_online = True

    camera_name = os.environ.get('CAMERA_NAME', 'Main Entrance')

    return render_template(
        'dashboard.html',
        camera_name=camera_name,
        camera_online=camera_online,
        camera_mode=mode,
        camera_source=source or '',
    )


@main.route('/camera-feed')
@login_required
def camera_feed():
    """Single MJPEG endpoint that handles RTSP, snapshot, and demo modes."""
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
    """JSON endpoint for live status polling from the dashboard."""
    mode, source = get_camera_mode()
    if mode == 'snapshot':
        online = check_camera_live(source)
    else:
        online = True
    return jsonify({'online': online, 'mode': mode})


@main.route('/logs')
@login_required
def logs():
    all_logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).all()
    return render_template('logs.html', logs=all_logs)


@main.route('/settings')
@login_required
def settings():
    return render_template('settings.html')


@main.route('/update-username', methods=['POST'])
@login_required
def update_username():
    new_username = request.form.get('username', '').strip()
    if not new_username:
        flash('Username cannot be empty.', 'error')
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
def update_password():
    current_pw = request.form.get('current_password', '')
    new_pw = request.form.get('new_password', '')
    confirm_pw = request.form.get('confirm_password', '')

    if not current_user.check_password(current_pw):
        flash('Current password is incorrect.', 'error')
        return redirect(url_for('main.settings'))

    if new_pw != confirm_pw:
        flash('New passwords do not match.', 'error')
        return redirect(url_for('main.settings'))

    if len(new_pw) < 6:
        flash('Password must be at least 6 characters.', 'error')
        return redirect(url_for('main.settings'))

    current_user.set_password(new_pw)
    db.session.commit()
    log_action('Changed Password')
    flash('Password updated successfully.', 'success')
    return redirect(url_for('main.settings'))


@main.route('/logout')
@login_required
def logout():
    log_action('Logout')
    logout_user()
    return redirect(url_for('main.login'))


# ─── One-time setup ───────────────────────────────────────────────────────────

@main.route('/setup-database-xyz')
def setup_database():
    if not os.environ.get('SECRET_KEY'):
        return '<h1>Disabled</h1><p>Set SECRET_KEY env var to enable setup.</p>', 403
    try:
        db.drop_all()
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
        return '<h1>SUCCESS</h1><p>Database ready. Login: admin / admin123 — change password immediately.</p>'
    except Exception as e:
        return f'<h1>ERROR</h1><p>{str(e)}</p>'