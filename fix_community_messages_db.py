# fix_community_messages_db.py
import sqlite3
import os

def fix_database():
    # المسار الخاص بـ PythonAnywhere هو الأهم
    db_paths = [
        '/home/Bonuspharma1/db.sqlite3',
        'db.sqlite3',
        'site.db',
        'instance/site.db',
        '../instance/site.db'
    ]
    
    db_path = None
    for path in db_paths:
        if os.path.exists(path):
            db_path = path
            break

    if not db_path:
        print("❌ لم يتم العثور على قاعدة البيانات!")
        return

    print(f"✅ جاري تحديث قاعدة البيانات في: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # قائمة بالأعمدة المفقودة في جدول community_message
    columns_to_add = [
        ("is_deleted", "BOOLEAN DEFAULT 0"),
        ("deleted_at", "DATETIME"),
        ("deleted_by", "INTEGER")
    ]

    cursor.execute("PRAGMA table_info(community_message)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    if not existing_cols:
        print("⚠️ جدول community_message غير موجود!")
        conn.close()
        return

    for col_name, col_def in columns_to_add:
        if col_name not in existing_cols:
            try:
                cursor.execute(f"ALTER TABLE community_message ADD COLUMN {col_name} {col_def}")
                print(f"➕ تم إضافة العمود: {col_name}")
            except Exception as e:
                print(f"⚠️ خطأ أثناء إضافة {col_name}: {e}")
        else:
            print(f"✔️ العمود {col_name} موجود بالفعل.")

    conn.commit()
    conn.close()
    print("🚀 تم تحديث جدول community_message بنجاح!")

if __name__ == "__main__":
    fix_database()
