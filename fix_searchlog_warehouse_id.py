"""
سكريبت إصلاح: إضافة عمود warehouse_id لجدول search_log
يعمل بأمان حتى لو العمود موجود مسبقاً
"""
import sys
import os

# ── إضافة مسار المشروع ──
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from sqlalchemy import text, inspect

def column_exists(table_name, column_name):
    """التحقق من وجود عمود في جدول"""
    with db.engine.connect() as conn:
        inspector = inspect(db.engine)
        columns = [c['name'] for c in inspector.get_columns(table_name)]
        return column_name in columns

def run_migration():
    with app.app_context():
        print("=" * 60)
        print("سكريبت إصلاح: إضافة warehouse_id لجدول search_log")
        print("=" * 60)

        # ── التحقق من جدول search_log ──
        if not column_exists('search_log', 'warehouse_id'):
            print("✗  عمود warehouse_id غير موجود في search_log — جاري الإضافة...")
            with db.engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE search_log ADD COLUMN warehouse_id INTEGER REFERENCES warehouse(id)"
                ))
                conn.commit()
            print("✓  تم إضافة warehouse_id لجدول search_log بنجاح")
        else:
            print("✓  عمود warehouse_id موجود بالفعل في search_log — لا حاجة لتغيير")

        # ── التحقق من جدول product_file ──
        if not column_exists('product_file', 'warehouse_id'):
            print("✗  عمود warehouse_id غير موجود في product_file — جاري الإضافة...")
            with db.engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE product_file ADD COLUMN warehouse_id INTEGER REFERENCES warehouse(id)"
                ))
                conn.commit()
            print("✓  تم إضافة warehouse_id لجدول product_file بنجاح")
        else:
            print("✓  عمود warehouse_id موجود بالفعل في product_file")

        # ── التحقق من جدول appointment ──
        if not column_exists('appointment', 'warehouse_id'):
            print("✗  عمود warehouse_id غير موجود في appointment — جاري الإضافة...")
            with db.engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE appointment ADD COLUMN warehouse_id INTEGER REFERENCES warehouse(id)"
                ))
                conn.commit()
            print("✓  تم إضافة warehouse_id لجدول appointment بنجاح")
        else:
            print("✓  عمود warehouse_id موجود بالفعل في appointment")

        # ── التحقق من جدول product_item ──
        if not column_exists('product_item', 'warehouse_id'):
            print("✗  عمود warehouse_id غير موجود في product_item — جاري الإضافة...")
            with db.engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE product_item ADD COLUMN warehouse_id INTEGER REFERENCES warehouse(id)"
                ))
                conn.commit()
            print("✓  تم إضافة warehouse_id لجدول product_item بنجاح")
        else:
            print("✓  عمود warehouse_id موجود بالفعل في product_item")

        # ── التحقق من جدول admin ──
        if not column_exists('admin', 'warehouse_id'):
            print("✗  عمود warehouse_id غير موجود في admin — جاري الإضافة...")
            with db.engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE admin ADD COLUMN warehouse_id INTEGER REFERENCES warehouse(id)"
                ))
                conn.commit()
            print("✓  تم إضافة warehouse_id لجدول admin بنجاح")
        else:
            print("✓  عمود warehouse_id موجود بالفعل في admin")

        # ── التحقق من جدول product_stock_history ──
        if not column_exists('product_stock_history', 'warehouse_id'):
            print("✗  عمود warehouse_id غير موجود في product_stock_history — جاري الإضافة...")
            with db.engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE product_stock_history ADD COLUMN warehouse_id INTEGER REFERENCES warehouse(id)"
                ))
                conn.commit()
            print("✓  تم إضافة warehouse_id لجدول product_stock_history بنجاح")
        else:
            print("✓  عمود warehouse_id موجود بالفعل في product_stock_history")

        print()
        print("=" * 60)
        print("✓  اكتمل الإصلاح بنجاح")
        print("=" * 60)

if __name__ == '__main__':
    run_migration()
