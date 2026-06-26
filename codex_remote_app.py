# app.py
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, make_response, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user, login_required, logout_user
import os
import sys

# إضافة مسار المشروع الحالي إلى sys.path لضمان استيراد الوحدات في PythonAnywhere
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Debug: Print environment info for PythonAnywhere logs
print(f"DEBUG: Current directory: {os.getcwd()}")
print(f"DEBUG: __file__ path: {os.path.abspath(__file__)}")
print(f"DEBUG: current_dir variable: {current_dir}")
print(f"DEBUG: sys.path: {sys.path}")
print(f"DEBUG: Files in current_dir: {os.listdir(current_dir)}")

from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
import json
from flask_migrate import Migrate
import logging
import rarfile
from groq import Groq
import pytz
from sqlalchemy import or_, and_, func, text, event

# Try to use whitenoise for static files if available
try:
    from whitenoise import WhiteNoise
except ImportError:
    WhiteNoise = None

# Define CAIRO_TIMEZONE locally
CAIRO_TIMEZONE = pytz.timezone('Africa/Cairo')

# تكوين السجل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# استيراد db من models.py
from models import (
    db, Admin, Company, ProductFile, ProductItem, ProductStockHistory,
    Appointment, Notification, NotificationRead, SearchLog, FavoriteProduct, SystemSetting,
    AdImage, CommunityMessage, AppDownloadLog, TobyRequestReport, PrivateMessage, BlockedProduct,
    PrivateMessageEditLog, DbMaintenanceLog, Warehouse, WarehousePermissions,
    Survey, SurveyQuestion, SurveyResponse, SurveyAnswer, CompanySurveyStatus,
    CommunityPost, PostComment, PostLike, CommunityNotification, PostReport,
    ProductReminder, PasswordResetToken, AdStory, CompanyNameChangeRequest
)

# استيراد الإعدادات من config.py
try:
    from config import Config
except ImportError:
    class Config:
        SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')
        SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///database.db')
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(os.getcwd(), 'uploads'))
        STATIC_FOLDER = os.path.join(os.getcwd(), 'static')
        LOGO_FOLDER = os.path.join('static', 'logos')
        AD_IMAGES_FOLDER = os.path.join('static', 'ad_images')
        APK_FOLDER = os.path.join('static', 'apk')

# استيراد الدوال المساعدة
from utils import update_database_schema, load_user, inject_global_data, ADMIN_ROLES, ALL_PERMISSIONS


def _normalize_sqlite_journal_mode(value):
    allowed_modes = {'DELETE', 'WAL', 'TRUNCATE', 'PERSIST', 'MEMORY', 'OFF'}
    journal_mode = (value or 'DELETE').strip().upper()
    return journal_mode if journal_mode in allowed_modes else 'DELETE'


def _is_postgres_uri(database_uri):
    return (database_uri or '').strip().lower().startswith(('postgres://', 'postgresql://'))


def _ensure_page_visit_schema_for_postgres():
    statements = (
        """
        CREATE TABLE IF NOT EXISTS page_visit (
            id SERIAL PRIMARY KEY,
            page_path VARCHAR(120) NOT NULL,
            visitor_key VARCHAR(160) NOT NULL,
            ip_address VARCHAR(80),
            user_agent TEXT,
            referrer TEXT,
            is_bot BOOLEAN NOT NULL DEFAULT false,
            visit_date DATE NOT NULL DEFAULT CURRENT_DATE,
            visited_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_page_visit_page_path ON page_visit (page_path)",
        "CREATE INDEX IF NOT EXISTS ix_page_visit_visitor_key ON page_visit (visitor_key)",
        "CREATE INDEX IF NOT EXISTS ix_page_visit_visit_date ON page_visit (visit_date)",
        "CREATE INDEX IF NOT EXISTS ix_page_visit_visited_at ON page_visit (visited_at)",
        "CREATE INDEX IF NOT EXISTS ix_page_visit_path_visited_at ON page_visit (page_path, visited_at)",
        "CREATE INDEX IF NOT EXISTS ix_page_visit_path_visitor ON page_visit (page_path, visitor_key)",
    )
    for statement in statements:
        db.session.execute(text(statement))
    db.session.commit()

def create_app():
    from views import register_views, trigger_silent_stock_history_cleanup_if_due
    try:
        from warehouse_routes import register_warehouse_routes
    except ImportError as e:
        print(f"DEBUG: Failed to import warehouse_routes: {e}")
        # محاولة استيراد بديلة إذا كان المسار مختلفاً
        import warehouse_routes
        register_warehouse_routes = warehouse_routes.register_warehouse_routes
    from survey_routes import survey_bp
    from community_routes import community_bp
    from admin_community_routes import admin_community_bp
    from community_bonus_routes import community_bonus_bp
    from product_reminder_routes import register_product_reminder_routes
    from admin_db_maintenance_routes import admin_db_maintenance_bp
    from api_mobile import api_mobile_bp
    from api_routes import api_bp

    # القوالب من مجلد templates بجانب app.py (مثلاً community_bonus.html)
    app = Flask(__name__, template_folder='templates')
    app.config.from_object(Config)

    database_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '') or ''
    sqlite_journal_mode = _normalize_sqlite_journal_mode(os.environ.get('SQLITE_JOURNAL_MODE'))
    if database_uri.startswith('sqlite'):
        engine_options = dict(app.config.get('SQLALCHEMY_ENGINE_OPTIONS') or {})
        connect_args = dict(engine_options.get('connect_args') or {})
        connect_args.setdefault('timeout', 60)
        engine_options['connect_args'] = connect_args
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_options

    # Use whitenoise if available
    if WhiteNoise:
        app.wsgi_app = WhiteNoise(app.wsgi_app, root='static/')

    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
    app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024

    ad_images_folder = app.config.get('AD_IMAGES_FOLDER')
    if not os.path.isabs(ad_images_folder):
        ad_images_folder = os.path.join(app.root_path, ad_images_folder)
        app.config['AD_IMAGES_FOLDER'] = ad_images_folder

    # إنشاء المجلدات للتأكد من وجودها
    for folder in [app.config['UPLOAD_FOLDER'], app.config['LOGO_FOLDER'], app.config['AD_IMAGES_FOLDER'], app.config['APK_FOLDER']]:
        if not os.path.exists(folder):
            os.makedirs(folder)

    # تهيئة SQLAlchemy مع التطبيق
    db.init_app(app)

    # Initialize Flask-Migrate
    migrate = Migrate()
    migrate.init_app(app, db, render_as_batch=True)

    # Ensure all tables exist and update schema
    try:
        with app.app_context():
            if database_uri.startswith('sqlite'):
                @event.listens_for(db.engine, "connect")
                def set_sqlite_pragma(dbapi_connection, connection_record):
                    cursor = dbapi_connection.cursor()
                    try:
                        cursor.execute("PRAGMA busy_timeout = 60000;")
                        # DELETE is safer by default for hosted/network filesystems.
                        cursor.execute(f"PRAGMA journal_mode={sqlite_journal_mode};")
                        cursor.execute("PRAGMA synchronous=NORMAL;")
                    finally:
                        cursor.close()

                db.session.execute(text("PRAGMA busy_timeout = 60000;"))
                db.session.execute(text(f"PRAGMA journal_mode={sqlite_journal_mode};"))
                db.session.execute(text("PRAGMA synchronous=NORMAL;"))
                db.session.commit()

            print(f"DEBUG: Using database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
            print("DEBUG: Calling db.create_all()...")
            if _is_postgres_uri(database_uri):
                _ensure_page_visit_schema_for_postgres()
                db.metadata.create_all(bind=db.engine, tables=[
                    table for table in db.metadata.sorted_tables
                    if table.name != 'page_visit'
                ])
            else:
                db.create_all()
            print("DEBUG: Calling update_database_schema()...")
            update_database_schema(app, db)
            print("DEBUG: update_database_schema() completed.")
    except Exception as e:
        print(f"DEBUG ERROR: Error creating/updating tables: {e}")
        import traceback
        traceback.print_exc()
        logger.error(f"Error creating/updating tables: {e}")

    # إعداد نظام تسجيل الدخول
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.remember_cookie_duration = timedelta(days=30)
    login_manager.session_protection = "basic"
    login_manager.remember_cookie_name = "remember_token"
    login_manager.remember_cookie_secure = app.config.get('SESSION_COOKIE_SECURE', True)
    login_manager.remember_cookie_httponly = True
    login_manager.login_message = "يرجى تسجيل الدخول للوصول إلى هذه الصفحة."
    login_manager.login_message_category = "info"

    @app.before_request
    def redirect_legacy_htmx_boost_requests():
        """Force old HTMX-boosted navigations back to normal page loads."""
        if request.method == 'GET' and request.headers.get('HX-Boosted', '').lower() == 'true':
            target_url = request.full_path.rstrip('?') or '/'
            response = make_response('', 200)
            response.headers['HX-Redirect'] = target_url
            return response

    @app.before_request
    def revoke_expired_premium_if_needed():
        try:
            if current_user.is_authenticated and session.get('user_type') == 'company':
                if hasattr(current_user, 'is_premium') and hasattr(current_user, 'premium_end_date'):
                    if current_user.is_premium and current_user.premium_end_date and datetime.utcnow() > current_user.premium_end_date:
                        company = Company.query.get(current_user.id)
                        if company and company.is_premium and company.premium_end_date and datetime.utcnow() > company.premium_end_date:
                            company.is_premium = False
                            db.session.commit()
        except Exception:
            db.session.rollback()

    @app.before_request
    def run_silent_daily_stock_history_cleanup():
        default_auto_cleanup = 'true' if os.name == 'nt' else 'false'
        auto_cleanup_enabled = (os.environ.get('ENABLE_SILENT_STOCK_HISTORY_CLEANUP', default_auto_cleanup) or '').strip().lower() in {'1', 'true', 'yes', 'on'}
        if not auto_cleanup_enabled:
            return
        try:
            trigger_silent_stock_history_cleanup_if_due(app)
        except Exception:
            db.session.rollback()

    @login_manager.user_loader
    def user_loader_callback(user_id):
        return load_user(user_id)

    @app.context_processor
    def inject_global_data_callback():
        global_data = inject_global_data(app, db)

        def has_permission_for_template(permission):
            if not current_user.is_authenticated or not current_user.is_active:
                return False
            if current_user.role == 'super':
                return True
                
            # التحقق من صلاحيات أدمن المخزن
            if current_user.role == 'warehouse_admin' and current_user.warehouse_id:
                try:
                    warehouse_permissions = WarehousePermissions.query.filter_by(
                        warehouse_id=current_user.warehouse_id,
                        is_enabled=True
                    ).all()
                    enabled_permissions = [p.permission_key for p in warehouse_permissions]
                    return permission in enabled_permissions
                except Exception:
                    return False
                    
            user_role_permissions = ADMIN_ROLES.get(current_user.role, {}).get('permissions', [])
            user_specific_permissions = []
            if current_user.permissions:
                try:
                    user_specific_permissions = json.loads(current_user.permissions)
                except json.JSONDecodeError:
                    user_specific_permissions = []
            final_permissions = list(set(user_role_permissions + user_specific_permissions))
            if 'all' in final_permissions:
                return True
            return permission in final_permissions

        global_data['has_permission'] = has_permission_for_template
        global_data['current_user_is_authenticated'] = current_user.is_authenticated
        global_data['current_user'] = current_user
        global_data['user_is_admin'] = (current_user.is_authenticated and session.get('user_type') == 'admin')
        global_data['user_is_company'] = (current_user.is_authenticated and session.get('user_type') == 'company')
        global_data['now'] = datetime.utcnow()
        
        try:
            ramadan_theme_setting = SystemSetting.query.filter_by(setting_key='ramadan_theme_enabled').first()
            global_data['ramadan_theme_enabled'] = (ramadan_theme_setting.setting_value == 'true' if ramadan_theme_setting else False)
        except:
            global_data['ramadan_theme_enabled'] = False

        return global_data

    # ─── Jinja2 filter: UTC → Cairo local time ───────────────────────────────
    @app.template_filter('cairo_time')
    def cairo_time_filter(dt):
        """تحويل datetime UTC إلى توقيت القاهرة وعرضه بشكل مقروء."""
        if not dt:
            return '—'
        try:
            import pytz as _pytz
            cairo_tz = _pytz.timezone('Africa/Cairo')
            if dt.tzinfo is None:
                dt = _pytz.utc.localize(dt)
            dt_cairo = dt.astimezone(cairo_tz)
            return dt_cairo.strftime('%Y-%m-%d %I:%M %p')
        except Exception:
            return dt.strftime('%Y-%m-%d %I:%M %p')
    # ─────────────────────────────────────────────────────────────────────────

    # Register blueprints
    app.register_blueprint(survey_bp, url_prefix='')
    app.register_blueprint(community_bp)
    app.register_blueprint(admin_community_bp)
    app.register_blueprint(community_bonus_bp)
    app.register_blueprint(admin_db_maintenance_bp)
    app.register_blueprint(api_mobile_bp)
    app.register_blueprint(api_bp)

    register_views(app)
    register_warehouse_routes(app)
    register_product_reminder_routes(app)
    
    @app.route('/ad_images/<path:filename>')
    def serve_ad_image(filename):
        return send_from_directory(app.config['AD_IMAGES_FOLDER'], filename)

    return app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
