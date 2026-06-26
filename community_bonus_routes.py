from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, current_app
from flask_login import login_required, current_user
from models import db, Company, CommunityPost, PostComment, PostLike, CommunityNotification, PostView
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

@community_bonus_bp.route('/community_bonus')
@login_required
def community_bonus():
    """Main community bonus page"""
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
                company = post.company
                is_anon = bool(getattr(post, 'is_anonymous', False))
                display_name = 'مستخدم مجهول' if is_anon else (company.company_name if company else 'Unknown')
                try:
                    likes_count = PostLike.query.filter_by(post_id=post.id).count()
                except Exception:
                    likes_count = 0
                try:
                    comments_count = PostComment.query.filter_by(post_id=post.id, is_active=True).count()
                except Exception:
                    comments_count = 0
                try:
                    user_liked = PostLike.query.filter_by(
                        post_id=post.id, company_id=current_user.id
                    ).first() is not None
                except Exception:
                    user_liked = False

                vc = _safe_post_view_count(post.id)

                posts_data.append({
                    'id': post.id,
                    'company_name': display_name,
                    'content': post.content,
                    'image_url': getattr(post, 'image_url', None),
                    'created_at': format_cairo_time(post.created_at),
                    'likes': likes_count,
                    'likes_count': likes_count,
                    'comments_count': comments_count,
                    'views': vc,
                    'views_count': vc,
                    'user_liked': user_liked,
                    'is_liked': user_liked,
                    'company_id': post.company_id,
                    'is_pinned': post.is_pinned if hasattr(post, 'is_pinned') else False,
                    'is_anonymous': is_anon,
                    'is_premium': company.is_premium if company and hasattr(company, 'is_premium') and not is_anon else False,
                    'avatar': ('👤' if is_anon else (company.avatar if company and hasattr(company, 'avatar') else 'male-1'))
                })
            except Exception as e:
                current_app.logger.warning('get_posts: تخطي منشور بسبب خطأ: %s', e)
                continue

        return jsonify({'posts': posts_data})
    
    except Exception as e:
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
        
        if not content:
            return jsonify({'error': 'Content is required'}), 400
        if len(content) > 500:
            return jsonify({'error': 'Content too long'}), 400
        
        new_post = CommunityPost(
            company_id=current_user.id,
            content=content,
            created_at=datetime.utcnow(),
            is_active=True,
            is_anonymous=is_anonymous
        )
        
        db.session.add(new_post)
        db.session.commit()
        
        return jsonify({'success': True, 'post_id': new_post.id})
    
    except Exception as e:
        db.session.rollback()
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
                comments_data.append({
                    'id': comment.id,
                    'company_name': company_name,
                    'content': comment.content or '',
                    'created_at': created_at_str,
                    'company_id': comment.company_id,
                    'can_delete': comment.company_id == current_user.id,
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

