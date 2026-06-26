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

def run_migration():
    with app.app_context():
        print("🚀 بدء migration: إضافة أعمدة الميديا لجدول community_post")
        
        # الأعمدة المطلوب إضافتها
        columns_to_add = [
            ('media_file_ids', 'TEXT'),
            ('media_types', 'TEXT'),
            ('media_preview_urls', 'TEXT'),
        ]
        
        for col_name, col_type in columns_to_add:
            try:
                # تحقق إذا العمود موجود بالفعل
                result = db.session.execute(
                    text(f"""
                        SELECT COUNT(*) FROM pragma_table_info('community_post') 
                        WHERE name = '{col_name}'
                    """)
                )
                exists = result.scalar()
                
                if exists:
                    print(f"  ✅ العمود '{col_name}' موجود بالفعل — تخطي")
                else:
                    alter_sql = text(f"ALTER TABLE community_post ADD COLUMN {col_name} {col_type}")
                    db.session.execute(alter_sql)
                    db.session.commit()
                    print(f"  ✅ تمت إضافة العمود '{col_name}' بنجاح")
            except Exception as e:
                db.session.rollback()
                print(f"  ⚠️ خطأ أثناء إضافة '{col_name}': {e}")
        
        print("\n✅ Migration اكتمل بنجاح!")
        
        # عرض البنية الحالية للتأكد
        print("\n📋 البنية الحالية لجدول community_post:")
        result = db.session.execute(text("PRAGMA table_info(community_post)"))
        for row in result:
            print(f"    {row[1]} ({row[2]})")

if __name__ == '__main__':
    run_migration()
