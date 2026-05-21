from app import db
from datetime import datetime, timezone, timedelta

PHT = timezone(timedelta(hours=8))

def get_pht_now():
    return datetime.now(PHT)

class AuditLog(db.Model):
    __tablename__ = 'audit_log'
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(50), nullable=False)
    ip_address = db.Column(db.String(50), nullable=False)
    device = db.Column(db.String(100), nullable=False, default='Unknown')
    timestamp = db.Column(db.DateTime, default=get_pht_now)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref=db.backref('activity_logs', lazy=True))

    def __repr__(self):
        return f"<Log {self.action} by {self.user_id} at {self.timestamp}>"
