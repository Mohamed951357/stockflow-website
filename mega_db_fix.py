import sqlite3
import os
import sys

def fix_database(db_path):
    if not os.path.exists(db_path):
        print(f"❌ قاعدة البيانات غير موجودة في: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print(f"🔄 البدء في فحص وتحديث قاعدة البيانات: {db_path}")

    # 1. إنشاء جداول المخازن إذا كانت مفقودة (لحل مشكلة Warehouse)
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS warehouse (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(200) NOT NULL,
                description TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS warehouse_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                warehouse_id INTEGER NOT NULL,
                permission_key VARCHAR(100) NOT NULL,
                is_enabled BOOLEAN DEFAULT 1,
                FOREIGN KEY(warehouse_id) REFERENCES warehouse(id)
            )
        """)
        print("✅ تم فحص/إنشاء جداول المخازن (Warehouse).")
    except Exception as e:
        print(f"⚠️ خطأ أثناء إنشاء الجداول: {e}")

    # 2. إضافة الأعمدة المفقودة لجدول الشركات (Company)
    company_columns = [
        ("google_id", "VARCHAR(100) UNIQUE"),
        ("deactivation_reason", "TEXT"),
        ("deactivated_at", "DATETIME"),
        ("force_password_change", "BOOLEAN DEFAULT 0"),
        ("invite_code_used", "VARCHAR(50)"),
        ("is_premium", "BOOLEAN DEFAULT 0"),
        ("premium_activation_date", "DATETIME"),
        ("premium_end_date", "DATETIME"),
        ("last_community_visit", "DATETIME"),
        ("avatar", "VARCHAR(100) DEFAULT 'male-1'"),
        ("premium_trial_prompted", "BOOLEAN DEFAULT 0"),
        ("premium_trial_active", "BOOLEAN DEFAULT 0"),
        ("premium_trial_start", "DATETIME"),
        ("premium_trial_end", "DATETIME"),
        ("allow_messages_from_companies", "BOOLEAN DEFAULT 1"),
        ("messaging_blocked", "BOOLEAN DEFAULT 0"),
        ("messaging_block_reason", "TEXT"),
        ("receive_messages_enabled", "BOOLEAN DEFAULT 1"),
        ("expo_push_token", "VARCHAR(255)"),
        ("last_active", "DATETIME"),
        ("is_typing", "BOOLEAN DEFAULT 0"),
        ("monthly_search_count", "INTEGER DEFAULT 0")
    ]

    cursor.execute("PRAGMA table_info(company)")
    existing_company_cols = {row[1] for row in cursor.fetchall()}

    for col_name, col_def in company_columns:
        if col_name not in existing_company_cols:
            try:
                cursor.execute(f"ALTER TABLE company ADD COLUMN {col_name} {col_def}")
                print(f"➕ إضافة عمود جديد لـ Company: {col_name}")
            except Exception as e:
                print(f"⚠️ لم يتم إضافة {col_name}: {e}")

    # 3. إضافة warehouse_id للجداول الأخرى
    other_tables = ["admin", "product_item", "appointment"]
    for table in other_tables:
        cursor.execute(f"PRAGMA table_info({table})")
        existing_cols = {row[1] for row in cursor.fetchall()}
        if "warehouse_id" not in existing_cols:
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN warehouse_id INTEGER REFERENCES warehouse(id)")
                print(f"➕ إضافة warehouse_id لجدول: {table}")
            except Exception as e:
                print(f"⚠️ خطأ في جدول {table}: {e}")

    conn.commit()
    conn.close()
    print("🎉 تم تحديث قاعدة البيانات بنجاح!")

if __name__ == "__main__":
    # افتراضاً المسار هو database.db في نفس المجلد، أو سيحتاج المستخدم لتمريره
    default_db = "instance/site.db" if os.path.exists("instance/site.db") else "database.db"
    
    db_arg = sys.argv[1] if len(sys.argv) > 1 else default_db
    fix_database(db_arg)
