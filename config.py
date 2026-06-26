import os
import secrets
from pathlib import Path
from datetime import timedelta

class Config:
    # Load SECRET_KEY from environment; do NOT hardcode production secrets in source.
    # If not provided, generate a temporary key for development only.
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    _default_sqlite_path = str(Path(__file__).resolve().parent.joinpath('site.db')).replace('\\', '/')
    _pa_sqlite_path = '/home/Bonuspharma1/db.sqlite3'
    if os.environ.get('DATABASE_URL'):
        SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    else:
        if os.name != 'nt' and os.path.exists(_pa_sqlite_path):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{_pa_sqlite_path}"
        else:
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{_default_sqlite_path}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = 'uploads'
    STATIC_FOLDER = 'static'
    LOGO_FOLDER = 'logos'
    AD_IMAGES_FOLDER = 'ad_images'
    APK_FOLDER = 'apk_files'

    # ===== إعدادات الجلسة والكوكيز - الحل النهائي =====

    # الجلسة تستمر 60 يوم
    PERMANENT_SESSION_LIFETIME = timedelta(days=60)

    # إعدادات الكوكيز
    SESSION_COOKIE_NAME = 'bonus_pharma_session'
    SESSION_COOKIE_HTTPONLY = True

    # مهم جداً لأن PythonAnywhere بيشغّل HTTPS
    SESSION_COOKIE_SECURE = os.environ.get('COOKIE_SECURE', 'false').lower() in ['true', '1', 'yes', 'on']

    # أفضل وضع للجلسات مع HTTPS
    SESSION_COOKIE_SAMESITE = os.environ.get('COOKIE_SAMESITE', 'Lax')
    SESSION_COOKIE_PATH = '/'

    # تجديد الجلسة مع كل طلب
    SESSION_REFRESH_EACH_REQUEST = True

    # Remember Me settings
    REMEMBER_COOKIE_NAME = 'bonus_pharma_remember'
    REMEMBER_COOKIE_DURATION = timedelta(days=60)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = os.environ.get('REMEMBER_COOKIE_SECURE', os.environ.get('COOKIE_SECURE', 'false')).lower() in ['true', '1', 'yes', 'on']
    REMEMBER_COOKIE_SAMESITE = os.environ.get('REMEMBER_COOKIE_SAMESITE', os.environ.get('COOKIE_SAMESITE', 'Lax'))
    REMEMBER_COOKIE_PATH = '/'
    REMEMBER_COOKIE_REFRESH_EACH_REQUEST = True

    # Flask-Mail settings (optional)
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', 'on', '1']
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')

    # File upload settings
    MAX_CONTENT_LENGTH = 64 * 1024 * 1024  # 64MB max file size
    ALLOWED_LOGO_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
    ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'html', 'htm'}

    # Third-party upload keys must stay in the environment, never in browser JavaScript.
    IMGBB_API_KEY = os.environ.get('IMGBB_API_KEY')
    MESSAGE_IMAGE_UPLOAD_MAX_BYTES = int(os.environ.get('MESSAGE_IMAGE_UPLOAD_MAX_BYTES') or (8 * 1024 * 1024))
    IMGBB_IMAGE_EXPIRATION_SECONDS = int(os.environ.get('IMGBB_IMAGE_EXPIRATION_SECONDS') or (30 * 24 * 60 * 60))
