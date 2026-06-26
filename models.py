# models.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, date, time, timedelta
import json
from sqlalchemy import func # NEW: Import func from sqlalchemy
import secrets

db = SQLAlchemy()

class Warehouse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    is_processing = db.Column(db.Boolean, default=False)
    last_process_added = db.Column(db.Integer, default=0)
    last_process_updated = db.Column(db.Integer, default=0)
    last_process_reset = db.Column(db.Integer, default=0)
    last_process_status = db.Column(db.String(50), nullable=True) # success, error, processing
    last_process_error = db.Column(db.Text, nullable=True)
    last_process_time = db.Column(db.DateTime, nullable=True)
    last_process_filename = db.Column(db.String(255), nullable=True)
    last_process_data_rows = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def upload_success_percentage(self):
        """نسبة نجاح صفوف الملف في آخر معالجة مكتملة (تقريبية)."""
        if self.last_process_status == 'success':
            dr = self.last_process_data_rows or 0
            if dr <= 0:
                return 100
            ops = (self.last_process_added or 0) + (self.last_process_updated or 0)
            return min(100, int(round(100 * ops / dr)))
        if self.last_process_status == 'error':
            return 0
        return None

    # العلاقات
    admins = db.relationship('Admin', backref='warehouse', lazy=True)
    products = db.relationship('ProductItem', backref='warehouse', lazy=True)
    appointments = db.relationship('Appointment', backref='warehouse', lazy=True)
    permissions = db.relationship('WarehousePermissions', backref='warehouse', cascade="all, delete-orphan", lazy=True)

class WarehousePermissions(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'), nullable=False)
    permission_key = db.Column(db.String(100), nullable=False)
    is_enabled = db.Column(db.Boolean, default=True)

class Company(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False)
    password = db.Column(db.String(150), nullable=False)
    company_name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    force_password_change = db.Column(db.Boolean, default=False)  # إجبار تغيير كلمة السر عند التسجيل القادم
    invite_code_used = db.Column(db.String(50), nullable=True)
    is_premium = db.Column(db.Boolean, default=False)
    subscription_plan = db.Column(db.String(50), default='standard')
    # --- العمودين الجديدين الآن معرفين هنا ---
    premium_activation_date = db.Column(db.DateTime, nullable=True)
    premium_end_date = db.Column(db.DateTime, nullable=True)
    # ------------------------------------
    # الأسطر القديمة التي كانت تسبب المشكلة (لو لسه موجودة) سيبها معطلة كما هي:
    # # premium_start_date = db.Column(db.DateTime, nullable=True)
    # # premium_end_date = db.Column(db.DateTime, nullable=True)
    last_community_visit = db.Column(db.DateTime, nullable=True)
    avatar = db.Column(db.String(100), default='default-male')
    dark_mode_enabled = db.Column(db.Boolean, default=False)  # تفعيل الوضع الليلي
    # حظر المراسلات بين الشركات
    messaging_blocked = db.Column(db.Boolean, default=False)
    messaging_block_reason = db.Column(db.Text, nullable=True)
    # تفضيل استقبال رسائل من الشركات الأخرى (يمكن للشركة إيقافه من الإعدادات)
    receive_messages_enabled = db.Column(db.Boolean, default=True)
    expo_push_token = db.Column(db.String(255), nullable=True) # NEW: لخدمة الإشعارات الفورية
    last_active = db.Column(db.DateTime, default=datetime.utcnow) # NEW: حالة الاتصال
    is_typing = db.Column(db.Boolean, default=False) # NEW: مؤشر الكتابة
    google_id = db.Column(db.String(100), unique=True, nullable=True) # NEW: لربط حساب جوجل
    google_email = db.Column(db.String(200), nullable=True)  # البريد الإلكتروني لحساب جوجل المرتبط
    monthly_search_count = db.Column(db.Integer, default=0) # عداد البحث الشهري
    last_client_type = db.Column(db.String(50), nullable=True)
    last_client_os = db.Column(db.String(50), nullable=True)
    last_client_browser = db.Column(db.String(80), nullable=True)
    last_client_device = db.Column(db.String(80), nullable=True)
    last_client_display_mode = db.Column(db.String(50), nullable=True)
    last_client_is_standalone = db.Column(db.Boolean, default=False)
    last_client_user_agent = db.Column(db.Text, nullable=True)
    last_client_seen_at = db.Column(db.DateTime, nullable=True)
    # ── حقول الملف الشخصي (بروفايل الشركة) ──
    bio = db.Column(db.Text, nullable=True)                          # نبذة عن الشركة
    cover_photo_url = db.Column(db.String(500), nullable=True)       # صورة الغلاف
    # ------------------------------------

    # Method مطلوب لـ Flask-Login لعمل خاصية "تذكرني"
    def get_id(self):
        return f"company:{self.id}"

    # إضافة العلاقات الجديدة
    survey_responses = db.relationship('SurveyResponse', backref='company', lazy=True)
    survey_statuses = db.relationship('CompanySurveyStatus', backref='company', lazy=True)

    # ---- خصائص تجربة الاشتراك المميز (لكل مستخدم) ----
    premium_trial_prompted = db.Column(db.Boolean, default=False)
    premium_trial_active = db.Column(db.Boolean, default=False)
    premium_trial_start = db.Column(db.DateTime, nullable=True)
    premium_trial_end = db.Column(db.DateTime, nullable=True)
    # ---- نهاية خصائص تجربة الاشتراك المميز ----
    
    # حقول إلغاء التفعيل
    deactivation_reason = db.Column(db.Text, nullable=True)
    deactivated_at = db.Column(db.DateTime, nullable=True)


class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    full_name = db.Column(db.String(200), nullable=True)
    email = db.Column(db.String(200), nullable=True)
    role = db.Column(db.String(50), default='editor')
    permissions = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    last_login = db.Column(db.DateTime, nullable=True)
    
    # ربط الأدمن بالمخزن
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'), nullable=True)
    
    # Method مطلوب لـ Flask-Login لعمل خاصية "تذكرني"
    def get_id(self):
        return f"admin:{self.id}"

class ProductFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    original_filename = db.Column(db.String(200), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'), nullable=True) # ربط الملف بالمخزن

class ProductItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_code = db.Column(db.String(100), nullable=True)
    name = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.String(100), nullable=True)
    price = db.Column(db.String(100), nullable=True)
    discount = db.Column(db.String(100), nullable=True)
    
    # ربط الصنف بالمخزن
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'), nullable=True)

class ProductStockHistory(db.Model):
    __table_args__ = (
        db.Index('ix_product_stock_history_record_date_product_name_recorded_at', 'record_date', 'product_name', 'recorded_at'),
        db.Index('ix_product_stock_history_warehouse_date_name', 'warehouse_id', 'record_date', 'product_name'),
    )
    id = db.Column(db.Integer, primary_key=True)
    item_code = db.Column(db.String(100), nullable=True)
    product_name = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    price = db.Column(db.String(100), nullable=True)
    discount = db.Column(db.String(100), nullable=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'), nullable=True)
    record_date = db.Column(db.Date, nullable=False, default=date.today)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)
    warehouse = db.relationship('Warehouse', backref=db.backref('stock_history', lazy=True))

class PrivateMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)
    read_at = db.Column(db.DateTime, nullable=True)
    is_deleted_by_sender = db.Column(db.Boolean, default=False)
    is_deleted_by_receiver = db.Column(db.Boolean, default=False)
    
    # العلاقات
    sender = db.relationship('Company', foreign_keys=[sender_id], backref='sent_messages')
    receiver = db.relationship('Company', foreign_keys=[receiver_id], backref='received_messages')


class MessageBlock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    blocked_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    blocker = db.relationship('Company', foreign_keys=[blocker_id], backref=db.backref('message_blocks_created', lazy=True))
    blocked = db.relationship('Company', foreign_keys=[blocked_id], backref=db.backref('message_blocks_received', lazy=True))

    __table_args__ = (
        db.UniqueConstraint('blocker_id', 'blocked_id', name='uq_message_block_pair'),
    )


class PrivateMessageEditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('private_message.id'), nullable=False)
    old_text = db.Column(db.Text, nullable=False)
    new_text = db.Column(db.Text, nullable=False)
    edited_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    edited_by_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)

    message = db.relationship('PrivateMessage', backref='edit_logs')
    editor = db.relationship('Company')

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    appointment_date = db.Column(db.Date, nullable=False)
    appointment_time = db.Column(db.Time, nullable=False)
    purpose = db.Column(db.Text, nullable=False)
    product_item_name = db.Column(db.String(255), nullable=False)
    notes = db.Column(db.Text)
    status = db.Column(db.String(50), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    admin_response = db.Column(db.Text)
    handled_by = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)
    collection_amount = db.Column(db.Float, nullable=True)
    
    # ربط الموعد بالمخزن
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'), nullable=True)

    company = db.relationship('Company', backref=db.backref('appointments', lazy=True))
    handler = db.relationship('Admin', backref=db.backref('handled_appointments', lazy=True), foreign_keys=[handled_by])

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    target_type = db.Column(db.String(50), nullable=False)
    target_id = db.Column(db.Integer, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    notif_type = db.Column(db.String(50), nullable=True)

    creator = db.relationship('Admin', backref=db.backref('sent_notifications', lazy=True), foreign_keys=[created_by])


class NotificationRead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(db.Integer, db.ForeignKey('notification.id'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    read_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('notification_id', 'company_id', name='uq_notification_read'),
    )

class SearchLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'), nullable=True)
    search_term = db.Column(db.String(200), nullable=False)
    results_count = db.Column(db.Integer, default=0)
    search_date = db.Column(db.DateTime, default=datetime.utcnow)

    company = db.relationship('Company', backref=db.backref('searches', lazy=True))
    warehouse = db.relationship('Warehouse', backref=db.backref('search_logs', lazy=True))

class FavoriteProduct(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    product_name = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.String(100), nullable=True)
    price = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_modified = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = db.relationship('Company', backref=db.backref('favorite_products', lazy=True))

class SystemSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False)
    setting_value = db.Column(db.Text, nullable=True)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PageVisit(db.Model):
    __tablename__ = 'page_visit'

    id = db.Column(db.Integer, primary_key=True)
    page_path = db.Column(db.String(120), nullable=False, index=True)
    visitor_key = db.Column(db.String(160), nullable=False, index=True)
    ip_address = db.Column(db.String(80), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)
    referrer = db.Column(db.Text, nullable=True)
    is_bot = db.Column(db.Boolean, default=False, nullable=False)
    visit_date = db.Column(db.Date, default=date.today, nullable=False, index=True)
    visited_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        db.Index('ix_page_visit_path_visited_at', 'page_path', 'visited_at'),
        db.Index('ix_page_visit_path_visitor', 'page_path', 'visitor_key'),
    )


class AdImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    original_filename = db.Column(db.String(200), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    description = db.Column(db.Text, nullable=True)
    image_type = db.Column(db.String(10), nullable=False, default='free')  # 'free', 'premium', or 'all'

    uploader = db.relationship('Admin', backref=db.backref('uploaded_ad_images', lazy=True))


class AdStory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ad_image_id = db.Column(db.Integer, db.ForeignKey('ad_image.id'), nullable=False)
    created_by_admin_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)
    start_at = db.Column(db.DateTime, default=datetime.utcnow)
    end_at = db.Column(db.DateTime, nullable=True)
    is_pinned = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Keeping old fields for safety if already in database
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=True)
    content = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(255), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    ad_image = db.relationship('AdImage', backref=db.backref('stories', lazy=True))
    creator_admin = db.relationship('Admin', backref=db.backref('created_stories', lazy=True))
    company = db.relationship('Company', backref=db.backref('stories', lazy=True))

class AdStoryView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    story_id = db.Column(db.Integer, db.ForeignKey('ad_story.id'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow)

class AdStoryReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    story_id = db.Column(db.Integer, db.ForeignKey('ad_story.id'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    reaction_type = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CompanyStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    content = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    start_at = db.Column(db.DateTime, default=datetime.utcnow)
    end_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CompanyStatusView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status_id = db.Column(db.Integer, db.ForeignKey('company_status.id'), nullable=False)
    viewer_company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow)

class CompanyStatusReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status_id = db.Column(db.Integer, db.ForeignKey('company_status.id'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    reaction_type = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ProductReportRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    product_name = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='pending')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class PostView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('community_post.id'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow)

class AppDownloadLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)
    downloaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    platform = db.Column(db.String(50), nullable=True)

    company = db.relationship('Company', backref=db.backref('downloads', lazy=True))

class CommunityMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_type = db.Column(db.String(20), nullable=False)  # 'admin', 'company', or 'system'
    sender_id = db.Column(db.Integer, nullable=False)
    message_text = db.Column(db.Text, nullable=False)
    chat_room_id = db.Column(db.String(100), nullable=False)
    attachment_url = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read_by_company = db.Column(db.Boolean, default=False)
    is_read_by_admin = db.Column(db.Boolean, default=False)
    is_to_toby = db.Column(db.Boolean, default=False)
    is_system_message = db.Column(db.Boolean, default=False)
    is_anonymous = db.Column(db.Boolean, default=False)
    
    # Keeping old fields for safety if already in database
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=True)
    message = db.Column(db.Text, nullable=True)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    is_pinned = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by = db.Column(db.Integer, nullable=True)
    
    company = db.relationship('Company', backref=db.backref('community_messages', lazy=True))

class TobyRequestReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    message = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    report_date = db.Column(db.Date, nullable=True, default=date.today)
    request_count = db.Column(db.Integer, default=0)
    last_request_at = db.Column(db.DateTime, default=datetime.utcnow)

    company = db.relationship('Company', backref=db.backref('toby_reports', lazy=True))

class Survey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    questions = db.relationship('SurveyQuestion', backref='survey', lazy=True, cascade="all, delete-orphan")

class SurveyQuestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('survey.id'), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(50), nullable=False)  # 'text', 'choice', 'rating'
    options = db.Column(db.Text, nullable=True)  # JSON string for choices
    is_required = db.Column(db.Boolean, default=True)

class SurveyResponse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('survey.id'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    answers = db.relationship('SurveyAnswer', backref='response', lazy=True, cascade="all, delete-orphan")

class SurveyAnswer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.Integer, db.ForeignKey('survey_response.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('survey_question.id'), nullable=False)
    answer_text = db.Column(db.Text, nullable=False)

class CompanySurveyStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    survey_id = db.Column(db.Integer, db.ForeignKey('survey.id'), nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    last_prompted = db.Column(db.DateTime, nullable=True)

class CommunityPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    content = db.Column(db.Text, nullable=True, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    is_pinned = db.Column(db.Boolean, default=False)
    is_anonymous = db.Column(db.Boolean, default=False)
    # ── أعمدة ميديا تليجرام (صور/فيديوهات مرفقة بالمنشور) ──
    media_file_ids = db.Column(db.Text, nullable=True)       # JSON array of Telegram file IDs
    media_types = db.Column(db.Text, nullable=True)           # JSON array: 'image' | 'video'
    media_preview_urls = db.Column(db.Text, nullable=True)    # JSON array of preview/thumbnail URLs
    audio_file_id = db.Column(db.String(255), nullable=True)  # Telegram file_id for attached audio
    audio_url = db.Column(db.Text, nullable=True)             # Proxy URL for attached audio
    
    # العلاقات
    company = db.relationship('Company', backref=db.backref('community_posts', lazy=True))
    comments = db.relationship('PostComment', backref='post', lazy=True, cascade="all, delete-orphan")
    likes = db.relationship('PostLike', backref='post', lazy=True, cascade="all, delete-orphan")

class PostComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('community_post.id'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    parent_id = db.Column(db.Integer, db.ForeignKey('post_comment.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    is_anonymous = db.Column(db.Boolean, default=False)
    
    # العلاقات
    company = db.relationship('Company', backref=db.backref('post_comments', lazy=True))
    replies = db.relationship('PostComment', backref=db.backref('parent', remote_side=[id]), lazy=True)

class PostLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('community_post.id'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    reaction_type = db.Column(db.String(50), nullable=True, default='heart')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # العلاقات
    company = db.relationship('Company', backref=db.backref('post_likes', lazy=True))
    
    # لضمان عدم تكرار الإعجاب من نفس الشركة على نفس المنشور
    __table_args__ = (db.UniqueConstraint('post_id', 'company_id', name='_post_company_like_uc'),)

class CommunityNotification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('community_post.id'), nullable=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('post_comment.id'), nullable=True)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50), nullable=False)  # 'comment', 'reply', 'new_post'
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    from_company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=True)
    
    # العلاقات
    company = db.relationship('Company', foreign_keys=[company_id], backref=db.backref('community_notifications', lazy=True))
    from_company = db.relationship('Company', foreign_keys=[from_company_id])
    post = db.relationship('CommunityPost', backref=db.backref('notifications', lazy=True))
    comment = db.relationship('PostComment', backref=db.backref('notifications', lazy=True))

# نموذج إبلاغات المنشورات
class PostReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('community_post.id'), nullable=False)
    reporter_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    reason = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_resolved = db.Column(db.Boolean, default=False)
    resolved_by = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    
    # العلاقات
    post = db.relationship('CommunityPost', backref=db.backref('reports', lazy=True))
    reporter = db.relationship('Company', backref=db.backref('post_reports', lazy=True))
    resolver = db.relationship('Admin', backref=db.backref('resolved_reports', lazy=True))
    
    # لضمان عدم تكرار الإبلاغ من نفس الشركة على نفس المنشور
    __table_args__ = (db.UniqueConstraint('post_id', 'reporter_id', name='_post_report_uc'),)

class ProductReminder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    product_name = db.Column(db.String(255), nullable=False)
    last_quantity = db.Column(db.String(100), nullable=True)
    last_price = db.Column(db.String(100), nullable=True)
    last_search_date = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # العلاقة مع الشركة
    company = db.relationship('Company', backref='product_reminders')
    
    # فهرس مركب لضمان عدم تكرار الصنف للشركة الواحدة
    __table_args__ = (db.UniqueConstraint('company_id', 'product_name', name='unique_company_product'),)


# نموذج استعادة كلمة السر
class PasswordResetToken(db.Model):
    """نموذج لتخزين رموز استعادة كلمة السر"""
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    token = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    
    # العلاقة مع الشركة
    company = db.relationship('Company', backref='reset_tokens')
    
    @staticmethod
    def generate_token():
        """توليد رمز عشوائي آمن"""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def create_reset_token(company_id, expires_in_minutes=30):
        """إنشاء رمز استعادة جديد"""
        token = PasswordResetToken.generate_token()
        expires_at = datetime.utcnow() + timedelta(minutes=expires_in_minutes)
        
        reset_token = PasswordResetToken(
            company_id=company_id,
            token=token,
            expires_at=expires_at
        )
        
        db.session.add(reset_token)
        db.session.commit()
        
        return token
    
    def is_valid(self):
        """التحقق من صلاحية الرمز"""
        return not self.used and datetime.utcnow() < self.expires_at
    
    def mark_as_used(self):
        """وضع علامة على أن الرمز تم استخدامه"""
        self.used = True
        db.session.commit()

# نموذج الأصناف المحجوبة
class BlockedProduct(db.Model):
    """نموذج لتخزين الأصناف المحجوبة من الظهور للشركات"""
    id = db.Column(db.Integer, primary_key=True)
    product_name = db.Column(db.String(255), nullable=False, unique=True)
    blocked_at = db.Column(db.DateTime, default=datetime.utcnow)
    blocked_by = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=False)
    reason = db.Column(db.Text, nullable=True)
    
    # العلاقة مع المسؤول
    blocker = db.relationship('Admin', backref=db.backref('blocked_products', lazy=True))


class CompanyNameChangeRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    old_name = db.Column(db.String(200), nullable=False)
    new_name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending, approved, rejected
    admin_comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)

    company = db.relationship('Company', backref=db.backref('name_change_requests', lazy=True))
    reviewer = db.relationship('Admin', backref=db.backref('reviewed_name_change_requests', lazy=True), foreign_keys=[reviewed_by])

class DbMaintenanceLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    performed_by = db.Column(db.String(150), nullable=True)
    action_type = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), default='pending')
    details = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CompanyFollow(db.Model):
    """متابعة شركة لشركة أخرى في المجتمع"""
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    followed_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    follower = db.relationship('Company', foreign_keys=[follower_id], backref=db.backref('following', lazy=True))
    followed = db.relationship('Company', foreign_keys=[followed_id], backref=db.backref('followers', lazy=True))

    __table_args__ = (
        db.UniqueConstraint('follower_id', 'followed_id', name='_follower_followed_uc'),
    )


class CommunityPoll(db.Model):
    """استطلاعات المجتمع — محفوظة في قاعدة البيانات لضمان الاستمرارية"""
    __tablename__ = 'community_poll'

    id = db.Column(db.Integer, primary_key=True)
    firestore_id = db.Column(db.String(100), unique=True, nullable=True)  # معرف Firestore للمزامنة
    creator_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    question = db.Column(db.Text, nullable=False)
    options_json = db.Column(db.Text, nullable=False)        # JSON array للخيارات
    votes_json = db.Column(db.Text, nullable=True, default='{}')  # JSON dict: company_id -> option_index
    is_anonymous = db.Column(db.Boolean, default=False)
    hide_results = db.Column(db.Boolean, default=False)
    allow_change_vote = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('Company', backref=db.backref('community_polls', lazy=True))


class CommunityPollVote(db.Model):
    """تسجيل أصوات الاستطلاعات بشكل منفصل"""
    __tablename__ = 'community_poll_vote'

    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('community_poll.id'), nullable=False)
    voter_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    option_index = db.Column(db.Integer, nullable=False)
    voted_at = db.Column(db.DateTime, default=datetime.utcnow)

    poll = db.relationship('CommunityPoll', backref=db.backref('votes_list', lazy=True))
    voter = db.relationship('Company', backref=db.backref('poll_votes', lazy=True))

    __table_args__ = (
        db.UniqueConstraint('poll_id', 'voter_id', name='_poll_voter_uc'),
    )
