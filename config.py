import os
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
    WTF_CSRF_ENABLED = False
    TEMPLATES_AUTO_RELOAD = True
