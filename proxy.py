import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

RTSP_URL = "rtsp://192.168.1.2:8080/h264_aac.sdp"  # ← paste your RTSP URL here
PORT = 8765


def generate_frames():
    cmd = [
        "ffmpeg",
        "-rtsp_transport", "tcp",
        "-i", RTSP_URL,
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "-r", "15",
        "-q:v", "4",
        "pipe:1"
    ]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    data = b""
    while True:
        chunk = process.stdout.read(4096)
        if not chunk:
            break
        data += chunk
        start = data.find(b"\xff\xd8")
        end = data.find(b"\xff\xd9")
        if start != -1 and end != -1 and end > start:
            frame = data[start:end + 2]
            data = data[end + 2:]
            yield frame


class MJPEGHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silence access logs

    def do_GET(self):
        if self.path == "/shot.jpg":
            # Single snapshot — for CAMERA_URL snapshot mode
            for frame in generate_frames():
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(frame)))
                self.end_headers()
                self.wfile.write(frame)
                return
        elif self.path == "/video":
            # MJPEG stream
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                for frame in generate_frames():
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    print(f"MJPEG proxy running on http://localhost:{PORT}")
    print(f"  Snapshot: http://localhost:{PORT}/shot.jpg")
    print(f"  Stream:   http://localhost:{PORT}/video")
    HTTPServer(("0.0.0.0", PORT), MJPEGHandler).serve_forever()