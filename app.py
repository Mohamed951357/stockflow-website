# -*- coding: utf-8 -*-
# app.py — Stock Flow Flask Application Factory
# ═══════════════════════════════════════════════

from flask import Flask, abort, make_response, request, send_from_directory
from flask_login import LoginManager
from config import Config
from models import db, Admin, Company

login_manager = LoginManager()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = 'يرجى تسجيل الدخول أولاً'

    @app.template_filter('cairo_time')
    def cairo_time_filter(dt):
        if not dt:
            return '—'
        try:
            import pytz
            cairo_tz = pytz.timezone('Africa/Cairo')
            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt)
            return dt.astimezone(cairo_tz).strftime('%Y-%m-%d %I:%M %p')
        except Exception:
            return str(dt)

    @app.before_request
    def redirect_legacy_htmx_boost_requests():
        """Force old HTMX-boosted navigations back to normal page loads."""
        if request.method == 'GET' and request.headers.get('HX-Boosted', '').lower() == 'true':
            target_url = request.full_path.rstrip('?') or '/'
            response = make_response('', 200)
            response.headers['HX-Redirect'] = target_url
            return response

    # User loader — supports both Admin and Company
    @login_manager.user_loader
    def load_user(user_id):
        # Try admin first (prefixed with 'admin:') then company (prefixed with 'company:')
        if str(user_id).startswith('admin:'):
            admin_id = str(user_id).replace('admin:', '')
            return Admin.query.get(int(admin_id))
        elif str(user_id).startswith('company:'):
            company_id = str(user_id).replace('company:', '')
            return Company.query.get(int(company_id))
        else:
            # Fallback for old sessions or integers
            return Company.query.get(int(user_id))

    # ─── Register main views (views.py) ───
    from views import register_views
    register_views(app)

    # ─── Register Blueprint routes ───
    from api_routes import api_bp
    app.register_blueprint(api_bp)

    from api_mobile import api_mobile_bp
    app.register_blueprint(api_mobile_bp)

    from community_bonus_routes import community_bonus_bp
    app.register_blueprint(community_bonus_bp)

    from community_routes import community_bp
    app.register_blueprint(community_bp)

    from survey_routes import survey_bp
    app.register_blueprint(survey_bp)

    from admin_community_routes import admin_community_bp
    app.register_blueprint(admin_community_bp)

    from admin_db_maintenance_routes import admin_db_maintenance_bp
    app.register_blueprint(admin_db_maintenance_bp)

    # ─── Register function-based route modules ───
    from warehouse_routes import register_warehouse_routes
    register_warehouse_routes(app)

    from product_reminder_routes import register_product_reminder_routes
    register_product_reminder_routes(app)

    @app.route('/ad_images/<path:filename>')
    def serve_ad_image(filename):
        if str(filename or '').lower().endswith(('.html', '.htm')):
            abort(404)
        return send_from_directory(app.config['AD_IMAGES_FOLDER'], filename)

    return app


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5001, host='0.0.0.0')
