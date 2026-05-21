from app import db


class CameraConfig(db.Model):
    __tablename__ = 'camera_config'
    id = db.Column(db.Integer, primary_key=True)
    camera_url = db.Column(db.String(512), nullable=True)       # HTTP/MJPEG URL
    camera_rtsp_url = db.Column(db.String(512), nullable=True)  # RTSP URL
    camera_name = db.Column(db.String(100), nullable=True, default='Live Remote Feed')

    @classmethod
    def get(cls):
        """Return the single config row, creating it if it doesn't exist."""
        cfg = cls.query.first()
        if not cfg:
            cfg = cls()
            db.session.add(cfg)
            db.session.commit()
        return cfg
