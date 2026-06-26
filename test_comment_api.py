#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اختبار مباشر لـ API التعليقات بدون متصفح
"""

from app import app
from models import db, CommunityPost, PostComment, Company
from flask_login import login_user
import json

def test_comments():
    with app.app_context():
        print("=" * 50)
        print("اختبار API التعليقات")
        print("=" * 50)
        
        # 1. أول منشور موجود
        post = CommunityPost.query.filter_by(is_active=True).first()
        if not post:
            print("❌ لا يوجد منشور نشط في قاعدة البيانات!")
            return
        print(f"✓ منشور للاختبار: ID={post.id}, content={post.content[:30]}")
        
        # 2. أول شركة
        company = Company.query.filter_by(is_active=True).first()
        if not company:
            print("❌ لا توجد شركة نشطة!")
            return
        print(f"✓ شركة للاختبار: ID={company.id}, name={company.company_name}")
        
        # 3. جرب إضافة تعليق مباشرة
        print("\n🧪 اختبار إضافة تعليق مباشر...")
        try:
            from datetime import datetime
            new_comment = PostComment(
                post_id=post.id,
                company_id=company.id,
                content="تعليق اختبار للتشخيص",
                created_at=datetime.utcnow(),
                is_active=True,
                is_anonymous=False
            )
            db.session.add(new_comment)
            db.session.flush()
            print(f"✓ comment ID بعد flush: {new_comment.id}")
            db.session.commit()
            print(f"✓ تم حفظ التعليق بنجاح - ID={new_comment.id}")
            
            # 4. جرب جلب التعليقات
            print("\n🧪 اختبار جلب التعليقات...")
            comments = PostComment.query.filter_by(post_id=post.id, is_active=True).all()
            print(f"✓ عدد التعليقات: {len(comments)}")
            for c in comments:
                try:
                    cname = c.company.company_name if c.company else "unknown"
                    created = c.created_at.strftime('%Y-%m-%d') if c.created_at else "?"
                    print(f"  - ID={c.id}, author={cname}, date={created}")
                except Exception as e:
                    print(f"  - ID={c.id}, ERROR: {e}")
            
            # 5. حذف التعليق التجريبي
            db.session.delete(new_comment)
            db.session.commit()
            print("\n✓ تم حذف التعليق التجريبي")
            
        except Exception as e:
            db.session.rollback()
            import traceback
            print(f"❌ خطأ: {e}")
            print(traceback.format_exc())
        
        # 6. اختبار الـ route مباشرة
        print("\n🧪 اختبار route /community_bonus/add_comment...")
        with app.test_client() as client:
            # محاكاة طلب POST
            with client.session_transaction() as sess:
                sess['user_type'] = 'company'
                sess['_user_id'] = str(company.id)
            
            response = client.post(
                '/community_bonus/add_comment',
                data=json.dumps({'post_id': post.id, 'content': 'اختبار route', 'is_anonymous': False}),
                content_type='application/json'
            )
            print(f"HTTP Status: {response.status_code}")
            try:
                data = json.loads(response.data)
                print(f"Response: {data}")
            except:
                print(f"Raw response: {response.data[:200]}")
            
            # حذف التعليق التجريبي
            if response.status_code == 200:
                PostComment.query.filter_by(content='اختبار route').delete()
                db.session.commit()
        
        print("\n" + "=" * 50)
        print("انتهى الاختبار")

if __name__ == '__main__':
    test_comments()
