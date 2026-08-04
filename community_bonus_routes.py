from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, current_app
from flask_login import login_required, current_user
from models import db, Company, CommunityPost, PostComment, PostLike, CommunityNotification, PostView, CompanyFollow
from datetime import datetime
import json
import pytz
from api_mobile import send_push_notification

CAIRO_TIMEZONE = pytz.timezone('Africa/Cairo')

def format_cairo_time(dt):
    if not dt:
        return ''
    return dt.replace(tzinfo=pytz.utc).astimezone(CAIRO_TIMEZONE).strftime('%Y-%m-%d %H:%M')

# Create blueprint
community_bonus_bp = Blueprint('community_bonus', __name__)


def _community_post_visible(post):
    """يظهر المنشور ما لم يُخفَّ صراحةً (False أو 0). NULL يُعامل كظاهر (بيانات قديمة)."""
    v = getattr(post, 'is_active', None)
    if v is None:
        return True
    if v is False:
        return False
    try:
        return int(v) != 0
    except (TypeError, ValueError):
        return bool(v)


def _safe_post_view_count(post_id):
    """إذا جدول post_view غير موجود أو فشل الاستعلام لا نُسقط كل المنشورات."""
    try:
        return PostView.query.filter_by(post_id=post_id).count()
    except Exception:
        return 0


def _post_media_list(value):
    """Read a JSON media column safely, including rows created before media support."""
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _latest_comment_data(post_id):
    """أحدث تعليق نشط على المنشور (لعرضه أسفل البوست في الصفحة الرئيسية)."""
    try:
        c = PostComment.query.filter_by(post_id=post_id, is_active=True).order_by(PostComment.created_at.desc()).first()
        if not c:
            return None
        is_anon = bool(getattr(c, 'is_anonymous', False))
        try:
            name = 'مستخدم مجهول' if is_anon else (c.company.company_name if c.company else 'مستخدم')
        except Exception:
            name = 'مستخدم'
        try:
            created_at_str = format_cairo_time(c.created_at)
        except Exception:
            created_at_str = ''
        return {
            'id': c.id,
            'company_name': name,
            'content': c.content or '',
            'created_at': created_at_str,
            'is_anonymous': is_anon
        }
    except Exception:
        return None


def _avatar_url(avatar_value, is_anon=False):
    """يُعيد رابط الصورة الصحيح سواء كان avatar مفتاحاً (male-1) أو صورة مخصصة أو رابطاً كاملاً."""
    if is_anon:
        return '/static/images/avatars/male-1.jpg'
    if not avatar_value:
        return '/static/images/avatars/male-1.jpg'

    avatar_val = str(avatar_value).strip()
    if not avatar_val:
        return '/static/images/avatars/male-1.jpg'

    if avatar_val.startswith('custom-photo:'):
        fn = avatar_val[len('custom-photo:'):]
        return f'/static/images/profile_photos/{fn}'

    if avatar_val.startswith(('http://', 'https://')):
        return avatar_val

    if avatar_val.startswith('/'):
        return avatar_val

    if avatar_val in ('male-1', 'female-1', 'default-male'):
        av = 'male-1' if avatar_val == 'default-male' else avatar_val
        return f'/static/images/avatars/{av}.jpg'

    return f'/static/images/avatars/{avatar_val}.jpg'


def _cover_url(cover_value):
    """يُعيد رابط صورة الغلاف الصحيح."""
    if not cover_value:
        return ''
    cv = str(cover_value).strip()
    if not cv:
        return ''
    if cv.startswith(('http://', 'https://')):
        return cv
    if cv.startswith('/'):
        return cv
    return f'/uploads/{cv}'


def _serialize_post(post, current_company_id):
    """تحويل منشور إلى JSON بنفس شكل get_posts (مُستخدم أيضاً في صفحة تفاصيل المنشور)."""
    company = post.company
    is_anon = bool(getattr(post, 'is_anonymous', False))
    display_name = 'مستخدم مجهول' if is_anon else (company.company_name if company else 'Unknown')
    try:
        likes_count = PostLike.query.filter_by(post_id=post.id).count()
        comments_count = PostComment.query.filter_by(post_id=post.id, is_active=True).count()
        views_count = PostView.query.filter_by(post_id=post.id).count()
        is_liked = PostLike.query.filter_by(post_id=post.id, company_id=current_company_id).first() is not None

        # Extract media arrays
        media_preview_urls = []
        media_types = []
        media_file_ids = []
        if getattr(post, 'media_preview_urls', None):
            try:
                media_preview_urls = json.loads(post.media_preview_urls) if isinstance(post.media_preview_urls, str) else post.media_preview_urls
            except Exception:
                media_preview_urls = []

        if getattr(post, 'media_types', None):
            try:
                media_types = json.loads(post.media_types) if isinstance(post.media_types, str) else post.media_types
            except Exception:
                media_types = []

        if getattr(post, 'media_file_ids', None):
            try:
                media_file_ids = json.loads(post.media_file_ids) if isinstance(post.media_file_ids, str) else post.media_file_ids
            except Exception:
                media_file_ids = []

        return {
            'id': post.id,
            'company_id': post.company_id,
            'company_name': display_name,
            'content': post.content or '',
            'created_at': post.created_at.strftime('%Y-%m-%d %H:%M:%S') if post.created_at else '',
            'is_pinned': bool(getattr(post, 'is_pinned', False)),
            'is_anonymous': is_anon,
            'is_mine': post.company_id == current_company_id,
            'likes_count': likes_count,
            'comments_count': comments_count,
            'views_count': views_count,
            'is_liked': is_liked,
            'media_file_ids': media_file_ids,
            'media_types': media_types,
            'media_preview_urls': media_preview_urls,
            'audio_file_id': getattr(post, 'audio_file_id', None),
            'audio_url': getattr(post, 'audio_url', None),
            'is_premium': company.is_premium if company and hasattr(company, 'is_premium') and not is_anon else False,
            'avatar': _avatar_url(company.avatar if company and hasattr(company, 'avatar') else None, is_anon),
            'avatar_key': ('male-1' if is_anon else (company.avatar if company and hasattr(company, 'avatar') else 'male-1')),
            'latest_comment': _latest_comment_data(post.id)
        }
    except Exception as e:
        current_app.logger.error('Error serializing post %s: %s', getattr(post, 'id', 'unknown'), str(e))
        return {
            'id': getattr(post, 'id', 0),
            'company_id': getattr(post, 'company_id', 0),
            'company_name': display_name,
            'content': getattr(post, 'content', '') or '',
            'created_at': post.created_at.strftime('%Y-%m-%d %H:%M:%S') if getattr(post, 'created_at', None) else '',
            'is_pinned': False,
            'is_anonymous': is_anon,
            'is_mine': getattr(post, 'company_id', 0) == current_company_id,
            'likes_count': 0,
            'comments_count': 0,
            'views_count': 0,
            'is_liked': False,
            'media_types': [],
            'media_preview_urls': [],
            'audio_file_id': None,
            'audio_url': None,
            'is_premium': False,
            'avatar': _avatar_url(None, is_anon),
            'avatar_key': 'male-1',
            'latest_comment': None
        }

@community_bonus_bp.route('/community_bonus')
@login_required
def community_bonus():
    """المجتمع الرئيسي"""
    if session.get('user_type') != 'company':
        flash('غير مصرح لك بالوصول', 'error')
        return redirect(url_for('logout'))

    return render_template('community_bonus.html')

@community_bonus_bp.route('/community_bonus/get_posts')
@login_required
def get_posts():
    """Get community posts with filtering"""
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403
    
    filter_type = request.args.get('filter', 'all')
    
    try:
        # جلب ثم تصفية في بايثون: SQLite/MySQL غالباً يخزّنون BOOLEAN كـ 0/1 فيفشل OR مع NULL أحياناً
        candidates = CommunityPost.query.order_by(CommunityPost.created_at.desc()).limit(500).all()
        posts = [p for p in candidates if _community_post_visible(p)]

        if filter_type == 'my_posts':
            posts = [p for p in posts if p.company_id == current_user.id]
        elif filter_type == 'liked':
            # This would require a join with likes table - simplified for now
            pass

        posts_data = []
        for post in posts:
            try:
                posts_data.append(_serialize_post(post, current_user.id))
            except Exception as e:
                current_app.logger.warning('get_posts: تخطي منشور بسبب خطأ: %s', e)
                continue

        return jsonify({'posts': posts_data})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@community_bonus_bp.route('/community_bonus/post/<int:post_id>')
@login_required
def post_detail(post_id):
    """صفحة منفصلة لعرض المنشور بكل تعليقاته بنفس شكل المجتمع"""
    if session.get('user_type') != 'company':
        flash('غير مصرح لك بالوصول', 'error')
        return redirect(url_for('logout'))

    post = CommunityPost.query.get_or_404(post_id)
    if not _community_post_visible(post):
        flash('هذا المنشور غير متاح', 'error')
        return redirect(url_for('community_bonus.community_bonus'))

    return render_template('community_post_detail.html', post_id=post_id)

@community_bonus_bp.route('/community_bonus/get_post/<int:post_id>')
@login_required
def get_post(post_id):
    """جلب منشور واحد بنفس شكل get_posts (لصفحة تفاصيل المنشور)"""
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        post = CommunityPost.query.get_or_404(post_id)
        if not _community_post_visible(post):
            return jsonify({'error': 'المنشور غير متاح'}), 404
        return jsonify({'post': _serialize_post(post, current_user.id)})
    except Exception as e:
        current_app.logger.error('get_post error for post %s: %s', post_id, str(e))
        return jsonify({'error': str(e)}), 500

@community_bonus_bp.route('/community_bonus/company/<int:company_id>')
@login_required
def company_profile_community(company_id):
    """صفحة البروفايل العامة لشركة داخل سياق المجتمع"""
    if session.get('user_type') != 'company':
        flash('غير مصرح لك بالوصول', 'error')
        return redirect(url_for('logout'))

    company = Company.query.get_or_404(company_id)
    if not company.is_active:
        flash('هذا الحساب غير متاح', 'error')
        return redirect(url_for('community_bonus.community_bonus'))

    return render_template('community_company_profile.html',
                           profile_company_id=company_id,
                           is_own_profile=(company_id == current_user.id))

@community_bonus_bp.route('/community_bonus/api/company/<int:company_id>')
@login_required
def api_company_profile(company_id):
    """API: بيانات الشركة ومنشوراتها العامة في المجتمع"""
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        company = Company.query.get_or_404(company_id)
        if not company.is_active:
            return jsonify({'error': 'الشركة غير متاحة'}), 404

        is_own = (company_id == current_user.id)

        if is_own:
            posts_query = CommunityPost.query.filter(
                CommunityPost.company_id == company_id,
                CommunityPost.is_active == True
            )
        else:
            posts_query = CommunityPost.query.filter(
                CommunityPost.company_id == company_id,
                CommunityPost.is_active == True,
                db.or_(CommunityPost.is_anonymous == False, CommunityPost.is_anonymous.is_(None))
            )

        posts_count = posts_query.count()

        likes_received = 0
        try:
            public_posts = posts_query.all()
            for p in public_posts:
                likes_received += PostLike.query.filter_by(post_id=p.id).count()
        except Exception:
            pass

        followers_count = 0
        following_count = 0
        is_following = False
        try:
            followers_count = CompanyFollow.query.filter_by(followed_id=company_id).count()
            following_count = CompanyFollow.query.filter_by(follower_id=company_id).count()
            is_following = CompanyFollow.query.filter_by(
                follower_id=current_user.id, followed_id=company_id
            ).first() is not None
        except Exception:
            pass

        # تاريخ الانضمام
        joined_at = ''
        try:
            if company.created_at:
                joined_at = company.created_at.replace(tzinfo=pytz.utc).astimezone(
                    CAIRO_TIMEZONE
                ).strftime('%Y-%m-%d')
        except Exception:
            pass

        company_data = {
            'id': company.id,
            'company_name': company.company_name,
            'avatar': _avatar_url(getattr(company, 'avatar', None)),
            'cover_photo_url': _cover_url(getattr(company, 'cover_photo_url', None)),
            'is_premium': bool(getattr(company, 'is_premium', False)),
            'bio': getattr(company, 'bio', '') or '',
            'joined_at': joined_at,
            'posts_count': posts_count,
            'likes_received': likes_received,
            'followers_count': followers_count,
            'following_count': following_count,
            'is_following': is_following,
            'is_own': is_own,
        }

        raw_posts = posts_query.order_by(CommunityPost.created_at.desc()).limit(50).all()

        posts_data = []
        for post in raw_posts:
            try:
                posts_data.append(_serialize_post(post, current_user.id))
            except Exception:
                continue

        return jsonify({'company': company_data, 'posts': posts_data})

    except Exception as e:
        current_app.logger.error('api_company_profile error: %s', str(e))
        return jsonify({'error': str(e)}), 500

@community_bonus_bp.route('/community_bonus/toggle_follow/<int:company_id>', methods=['POST'])
@login_required
def toggle_follow(company_id):
    """متابعة / إلغاء متابعة شركة"""
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403

    if company_id == current_user.id:
        return jsonify({'error': 'لا يمكنك متابعة نفسك'}), 400

    try:
        existing = CompanyFollow.query.filter_by(
            follower_id=current_user.id, followed_id=company_id
        ).first()

        if existing:
            db.session.delete(existing)
            following = False
        else:
            follow = CompanyFollow(follower_id=current_user.id, followed_id=company_id)
            db.session.add(follow)
            following = True

        db.session.commit()

        followers_count = CompanyFollow.query.filter_by(followed_id=company_id).count()
        return jsonify({'success': True, 'following': following, 'followers_count': followers_count})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error('toggle_follow error: %s', str(e))
        return jsonify({'error': str(e)}), 500

@community_bonus_bp.route('/community_bonus/create_post', methods=['POST'])
@login_required
def create_post():
    """Create a new community post"""
    if not hasattr(current_user, 'company_name'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        content = (request.form.get('content') or '').strip()
        is_anonymous_raw = request.form.get('is_anonymous')
        is_anonymous = False
        if isinstance(is_anonymous_raw, str):
            is_anonymous = is_anonymous_raw.lower() in {'1', 'true', 'yes', 'on'}
        elif isinstance(is_anonymous_raw, bool):
            is_anonymous = is_anonymous_raw
        
        if not content and 'images' not in request.files and 'video' not in request.files and 'audio' not in request.files:
            return jsonify({'error': 'Content or media is required'}), 400
        
        if len(content) > 500:
            return jsonify({'error': 'Content too long'}), 400
        
        import json as _json
        import os
        from werkzeug.utils import secure_filename
        
        media_file_ids = None
        media_types = None
        media_preview_urls = None
        audio_file_id = None
        audio_url = None
        
        # Handle image uploads
        if 'images' in request.files:
            images = request.files.getlist('images')
            if images and len(images) > 0:
                uploaded_ids = []
                uploaded_types = []
                uploaded_urls = []
                
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'community')
                os.makedirs(upload_folder, exist_ok=True)
                
                for img in images:
                    if img and img.filename:
                        filename = secure_filename(img.filename)
                        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
                        unique_filename = f"{current_user.id}_{timestamp}_{filename}"
                        filepath = os.path.join(upload_folder, unique_filename)
                        
                        img.save(filepath)
                        
                        file_url = f"/static/uploads/community/{unique_filename}"
                        uploaded_ids.append(unique_filename)
                        uploaded_types.append('image')
                        uploaded_urls.append(file_url)
                
                if uploaded_ids:
                    media_file_ids = _json.dumps(uploaded_ids)
                    media_types = _json.dumps(uploaded_types)
                    media_preview_urls = _json.dumps(uploaded_urls)
        
        # Handle video upload
        if 'video' in request.files:
            video = request.files['video']
            if video and video.filename:
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'community')
                os.makedirs(upload_folder, exist_ok=True)
                
                filename = secure_filename(video.filename)
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
                unique_filename = f"{current_user.id}_{timestamp}_{filename}"
                filepath = os.path.join(upload_folder, unique_filename)
                
                video.save(filepath)
                
                file_url = f"/static/uploads/community/{unique_filename}"
                media_file_ids = _json.dumps([unique_filename])
                media_types = _json.dumps(['video'])
                media_preview_urls = _json.dumps([file_url])
        
        # Handle audio upload
        if 'audio' in request.files:
            audio = request.files['audio']
            if audio and audio.filename:
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'community')
                os.makedirs(upload_folder, exist_ok=True)
                
                filename = secure_filename(audio.filename)
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
                unique_filename = f"{current_user.id}_{timestamp}_{filename}"
                filepath = os.path.join(upload_folder, unique_filename)
                
                audio.save(filepath)
                
                audio_file_id = unique_filename
                audio_url = f"/static/uploads/community/{unique_filename}"

        new_post = CommunityPost(
            company_id=current_user.id,
            content=content,
            created_at=datetime.utcnow(),
            is_active=True,
            is_anonymous=is_anonymous,
            media_file_ids=media_file_ids,
            media_types=media_types,
            media_preview_urls=media_preview_urls,
            audio_file_id=audio_file_id,
            audio_url=audio_url
        )
        
        db.session.add(new_post)
        db.session.commit()
        
        return jsonify({'success': True, 'post_id': new_post.id})
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error creating post: {str(e)}')
        return jsonify({'error': str(e)}), 500

@community_bonus_bp.route('/community_bonus/get_companies')
@login_required
def get_companies():
    """Get list of companies for admin"""
    if session.get('user_type') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        companies = Company.query.filter_by(is_active=True).all()
        companies_data = [{
            'id': company.id,
            'company_name': company.company_name
        } for company in companies]
        
        return jsonify({'companies': companies_data})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@community_bonus_bp.route('/community_bonus/get_company_count')
@login_required
def get_company_count():
    """Get count of active companies"""
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        count = Company.query.filter_by(is_active=True).count()
        return jsonify({'success': True, 'count': count})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@community_bonus_bp.route('/community_bonus/record_view/<int:post_id>', methods=['POST'])
@login_required
def record_view(post_id):
    """Record a view for a post"""
    if not hasattr(current_user, 'company_name'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        post = CommunityPost.query.get_or_404(post_id)
        exists = PostView.query.filter_by(post_id=post_id, company_id=current_user.id).first()
        if not exists:
            view = PostView(post_id=post_id, company_id=current_user.id)
            db.session.add(view)
            db.session.commit()
        return jsonify({'success': True})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@community_bonus_bp.route('/community_bonus/toggle_like', methods=['POST'])
@login_required
def toggle_like():
    """Toggle like for a post"""
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        post_id = request.json.get('post_id')
        post = CommunityPost.query.get_or_404(post_id)
        
        # Check if user already liked the post
        from models import PostLike
        existing_like = PostLike.query.filter_by(
            post_id=post_id,
            company_id=current_user.id
        ).first()
        
        liked = False
        if existing_like:
            # Unlike
            db.session.delete(existing_like)
            liked = False
        else:
            # Like
            new_like = PostLike(
                post_id=post_id,
                company_id=current_user.id
            )
            db.session.add(new_like)
            liked = True
            
            # Create notification if not own post
            if post.company_id != current_user.id:
                notif = CommunityNotification(
                    company_id=post.company_id,
                    post_id=post.id,
                    from_company_id=current_user.id,
                    message=f'أعجب {current_user.company_name} بمنشورك.',
                    notification_type='like'
                )
                db.session.add(notif)
            
        db.session.commit()
        
        # Send push notification
        if liked and post.company_id != current_user.id:
            send_push_notification(
                post.company_id, 
                "إعجاب جديد", 
                f"أعجب {current_user.company_name} بمنشورك.",
                {"type": "like", "post_id": post_id}
            )
        
        # احسب عدد الإعجابات الفعلي من قاعدة البيانات
        actual_likes_count = PostLike.query.filter_by(post_id=post_id).count()
        
        return jsonify({
            'success': True, 
            'likes_count': actual_likes_count,
            'liked': liked
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@community_bonus_bp.route('/community_bonus/get_comments/<int:post_id>')
@login_required
def get_comments(post_id):
    """Get comments for a post"""
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        post = CommunityPost.query.get_or_404(post_id)
        comments = PostComment.query.filter_by(post_id=post_id, is_active=True).order_by(PostComment.created_at.asc()).all()
        
        comments_data = []
        for comment in comments:
            try:
                is_anon = bool(getattr(comment, 'is_anonymous', False))
                # حماية من فشل العلاقة أو بيانات ناقصة
                try:
                    company_name = 'مستخدم مجهول' if is_anon else (comment.company.company_name if comment.company else 'مستخدم')
                except Exception:
                    company_name = 'مستخدم'
                # حماية من created_at = None
                try:
                    created_at_str = format_cairo_time(comment.created_at)
                except Exception:
                    created_at_str = ''
                is_my_comment = comment.company_id == current_user.id
                comments_data.append({
                    'id': comment.id,
                    'company_name': company_name,
                    'content': comment.content or '',
                    'created_at': created_at_str,
                    'company_id': comment.company_id,
                    'can_delete': is_my_comment,
                    'can_edit': is_my_comment,
                    'is_anonymous': is_anon
                })
            except Exception as ce:
                current_app.logger.warning('get_comments: تخطي تعليق بسبب خطأ: %s', ce)
                continue
        
        return jsonify({'comments': comments_data})
    
    except Exception as e:
        current_app.logger.error('get_comments error for post %s: %s', post_id, str(e))
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@community_bonus_bp.route('/community_bonus/add_comment', methods=['POST'])
@login_required
def add_comment():
    """Add a comment to a post"""
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        data = request.get_json(silent=True) or {}
        post_id = data.get('post_id')
        content = (data.get('content') or '').strip()
        is_anonymous = bool(data.get('is_anonymous', False))
        
        if not post_id:
            return jsonify({'error': 'post_id مطلوب'}), 400
        if not content:
            return jsonify({'error': 'محتوى التعليق مطلوب'}), 400
        
        post = CommunityPost.query.get_or_404(post_id)
        
        new_comment = PostComment(
            post_id=post_id,
            company_id=current_user.id,
            content=content,
            created_at=datetime.utcnow(),
            is_active=True,
            is_anonymous=is_anonymous
        )
        
        db.session.add(new_comment)
        db.session.flush()  # احصل على new_comment.id من قاعدة البيانات قبل استخدامه
        
        # اسم المعلق - معرَّف هنا لاستخدامه خارج الـ if block
        commenter_name = 'مستخدم مجهول' if is_anonymous else current_user.company_name
        
        # Create notification if not own post
        if post.company_id != current_user.id:
            notif = CommunityNotification(
                company_id=post.company_id,
                post_id=post.id,
                comment_id=new_comment.id,
                from_company_id=current_user.id,
                message=f'علق {commenter_name} على منشورك.',
                notification_type='comment'
            )
            db.session.add(notif)
            
        db.session.commit()
        
        # Send push notification (خارج الـ try/commit لتجنب rollback غير مقصود)
        try:
            if post.company_id != current_user.id:
                send_push_notification(
                    post.company_id,
                    "تعليق جديد",
                    f"علق {commenter_name} على منشورك: {content[:30]}",
                    {"type": "comment", "post_id": post_id}
                )
        except Exception as push_err:
            current_app.logger.warning('push notification failed: %s', push_err)
        
        # احسب عدد التعليقات الحالي لإعادته للفرونت إند
        comments_count = PostComment.query.filter_by(post_id=post_id, is_active=True).count()
        
        return jsonify({'success': True, 'comment_id': new_comment.id, 'comments_count': comments_count})
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('add_comment error: %s', str(e))
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@community_bonus_bp.route('/community_bonus/delete_comment/<int:comment_id>', methods=['DELETE'])
@login_required
def delete_comment(comment_id):
    """Delete a comment"""
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        comment = PostComment.query.get_or_404(comment_id)
        
        # Check if user owns the comment
        if comment.company_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403
            
        comment.is_active = False
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@community_bonus_bp.route('/community_bonus/edit_comment/<int:comment_id>', methods=['PUT'])
@login_required
def edit_comment(comment_id):
    """Edit a comment content"""
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        comment = PostComment.query.get_or_404(comment_id)

        if comment.company_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403

        data = request.get_json(silent=True) or {}
        new_content = (data.get('content') or '').strip()

        if not new_content:
            return jsonify({'error': 'محتوى التعليق مطلوب'}), 400

        if len(new_content) > 200:
            return jsonify({'error': 'التعليق طويل جداً (الحد الأقصى 200 حرف)'}), 400

        comment.content = new_content
        db.session.commit()

        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error('edit_comment error: %s', str(e))
        return jsonify({'error': str(e)}), 500

@community_bonus_bp.route('/community_bonus/edit_post/<int:post_id>', methods=['PUT'])
@login_required
def edit_post(post_id):
    """Edit a post content"""
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        post = CommunityPost.query.get_or_404(post_id)

        if post.company_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403

        data = request.get_json(silent=True) or {}
        new_content = (data.get('content') or '').strip()

        if not new_content:
            return jsonify({'error': 'محتوى المنشور مطلوب'}), 400

        if len(new_content) > 500:
            return jsonify({'error': 'المنشور طويل جداً (الحد الأقصى 500 حرف)'}), 400

        post.content = new_content
        db.session.commit()

        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error('edit_post error: %s', str(e))
        return jsonify({'error': str(e)}), 500

@community_bonus_bp.route('/community_bonus/delete_post/<int:post_id>', methods=['DELETE', 'POST'])
@login_required
def delete_post(post_id):
    """Delete a post (soft delete)"""
    is_admin = (session.get('user_type') == 'admin')
    if not is_admin and not hasattr(current_user, 'company_name'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        post = CommunityPost.query.get_or_404(post_id)
        
        # Check if the user owns the post or is admin
        if post.company_id != getattr(current_user, 'id', None) and not is_admin:
            return jsonify({'error': 'Unauthorized'}), 403
        
        post.is_active = False
        db.session.commit()
        
        return jsonify({'success': True})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@community_bonus_bp.route('/community_bonus/report_post/<int:post_id>', methods=['POST'])
@login_required
def report_post(post_id):
    """Report a post"""
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        post = CommunityPost.query.get_or_404(post_id)
        
        # In a real implementation, you would create a report record
        # For now, we'll just return success
        
        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@community_bonus_bp.route('/community_bonus/get_notification_count')
@login_required
def get_notification_count():
    """Get notification count for the current user"""
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        # Count unread notifications
        count = CommunityNotification.query.filter_by(
            company_id=current_user.id,
            is_read=False
        ).count()
        
        return jsonify({'success': True, 'count': count})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@community_bonus_bp.route('/community_bonus/debug_comments/<int:post_id>')
@login_required
def debug_comments(post_id):
    """endpoint مؤقت للتشخيص - يظهر التفاصيل الكاملة للخطأ"""
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        import traceback, sys
        results = {'post_id': post_id, 'steps': []}

        # خطوة 1: جلب المنشور
        try:
            post = CommunityPost.query.get(post_id)
            results['steps'].append({'step': 'get_post', 'ok': post is not None, 'id': post_id})
        except Exception as e:
            results['steps'].append({'step': 'get_post', 'ok': False, 'error': str(e)})
            return jsonify(results), 500

        # خطوة 2: جلب التعليقات
        try:
            comments = PostComment.query.filter_by(post_id=post_id, is_active=True).all()
            results['steps'].append({'step': 'get_comments', 'ok': True, 'count': len(comments)})
        except Exception as e:
            results['steps'].append({'step': 'get_comments', 'ok': False, 'error': str(e), 'tb': traceback.format_exc()})
            return jsonify(results), 500

        # خطوة 3: تسلسل كل تعليق
        comments_out = []
        for c in comments:
            try:
                is_anon = bool(getattr(c, 'is_anonymous', False))
                try:
                    cname = 'مجهول' if is_anon else (c.company.company_name if c.company else '?')
                except Exception as ce:
                    cname = f'ERROR: {ce}'
                created = c.created_at.strftime('%Y-%m-%d %H:%M') if c.created_at else ''
                comments_out.append({'id': c.id, 'author': cname, 'created': created, 'content': c.content[:20]})
            except Exception as ce:
                comments_out.append({'id': getattr(c, 'id', '?'), 'error': str(ce)})
        results['comments'] = comments_out
        results['current_user_id'] = current_user.id

        # خطوة 4: جرب إضافة تعليق تجريبي
        try:
            from datetime import datetime
            test_c = PostComment(
                post_id=post_id,
                company_id=current_user.id,
                content='__debug_test__',
                created_at=datetime.utcnow(),
                is_active=False,
                is_anonymous=False
            )
            db.session.add(test_c)
            db.session.flush()
            test_id = test_c.id
            db.session.rollback()  # لا نحفظ
            results['steps'].append({'step': 'test_insert', 'ok': True, 'got_id': test_id})
        except Exception as e:
            db.session.rollback()
            results['steps'].append({'step': 'test_insert', 'ok': False, 'error': str(e), 'tb': traceback.format_exc()})

        return jsonify(results)
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'tb': traceback.format_exc()}), 500
