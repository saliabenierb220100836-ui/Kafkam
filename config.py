import os
import secrets
from dotenv import load_dotenv

load_dotenv()


def fix_database_url(url):
    if url and url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql+pg8000://', 1)
    elif url and url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+pg8000://', 1)
    return url


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY environment variable is not set. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    SQLALCHEMY_DATABASE_URI = (
        fix_database_url(os.environ.get('DATABASE_URL'))
        or 'sqlite:///kafkam.db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,      # detect stale connections
        "pool_recycle": 300,        # recycle connections every 5 min
    }

    WTF_CSRF_ENABLED = False        # No WTForms used; forms protected by login_required
    TEMPLATES_AUTO_RELOAD = True

    # Session hardening
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    # Railway always serves HTTPS — enable Secure cookie flag
    SESSION_COOKIE_SECURE = os.environ.get('RAILWAY_ENVIRONMENT') is not None

    # Rate limiter storage (in-memory is fine for single-dyno Railway deployments)
    RATELIMIT_STORAGE_URI = "memory://"
    RATELIMIT_STRATEGY = "fixed-window"
