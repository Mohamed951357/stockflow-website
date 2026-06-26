"""
Migration: إضافة أعمدة الميديا (media_file_ids, media_types, media_preview_urls)
لجدول community_post لدعم نشر الصور والفيديوهات في المجتمع.

شغّل هذا السكريبت مرة واحدة على السيرفر:
    python migrate_posts_media_columns.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db
from sqlalchemy import text
import re

def run_migration():
    with app.app_context():
        print("🚀 بدء migration: إضافة أعمدة الميديا لجدول community_post")
        
        # الأعمدة المطلوب إضافتها
        columns_to_add = [
            ('media_file_ids', 'TEXT'),
            ('media_types', 'TEXT'),
            ('media_preview_urls', 'TEXT'),
        ]
        
        # Get existing columns once to avoid interpolating into SQL
        result = db.session.execute(text('PRAGMA table_info("community_post")'))
        existing = {row[1] for row in result.fetchall()}

        for col_name, col_type in columns_to_add:
            try:
                if col_name in existing:
                    print(f"  ✅ العمود '{col_name}' موجود بالفعل — تخطي")
                    continue

                if not re.match(r'^[A-Za-z0-9_]+$', col_name):
                    print(f"  ✖️ تخطي اسم عمود غير صالح: {col_name}")
                    continue

                alter_sql = text(f'ALTER TABLE "community_post" ADD COLUMN "{col_name}" {col_type}')
                db.session.execute(alter_sql)
                db.session.commit()
                print(f"  ✅ تمت إضافة العمود '{col_name}' بنجاح")
            except Exception as e:
                db.session.rollback()
                print(f"  ⚠️ خطأ أثناء إضافة '{col_name}': {e}")
        
        print("\n✅ Migration اكتمل بنجاح!")
        
        # عرض البنية الحالية للتأكد
        print("\n📋 البنية الحالية لجدول community_post:")
        result = db.session.execute(text('PRAGMA table_info("community_post")'))
        for row in result:
            print(f"    {row[1]} ({row[2]})")

if __name__ == '__main__':
    run_migration()
