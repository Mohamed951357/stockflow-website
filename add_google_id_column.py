import sqlite3
import sys
import os

# سكريبت بسيط لتحديث جدول company وإضافة عمود google_id في قاعدة بيانات SQLite
# الاستخدام:
#   python add_google_id_column.py path/to/site.db
# مثال (من مجلد المشروع):
#   python add_google_id_column.py instance/site.db

COLUMNS_TO_ADD = [
    ("google_id", "VARCHAR(100) UNIQUE"),
]

def main(db_path: str):
    if not os.path.exists(db_path):
        print(f"❌ ملف قاعدة البيانات غير موجود: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # قراءة أعمدة جدول company الحالية
    cur.execute("PRAGMA table_info(company)")
    existing_cols = {row[1] for row in cur.fetchall()}  # row[1] هو اسم العمود

    print("📋 الأعمدة الحالية في جدول company:")
    print(", ".join(sorted(existing_cols)))

    for col_name, col_def in COLUMNS_TO_ADD:
        if col_name in existing_cols:
            print(f"✅ العمود '{col_name}' موجود بالفعل - لن يتم تعديله")
            continue
        try:
            ddl = f"ALTER TABLE company ADD COLUMN {col_name} {col_def}"
            print(f"➕ إضافة العمود '{col_name}' باستخدام: {ddl}")
            cur.execute(ddl)
            print(f"🎉 تمت الإضافة بنجاح.")
        except Exception as e:
            print(f"❌ حدث خطأ أثناء إضافة العمود {col_name}: {e}")

    conn.commit()
    conn.close()
    print("✅ اكتمل الفحص والتحديث.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("الاستخدام: python add_google_id_column.py path/to/site.db")
        sys.exit(1)
    main(sys.argv[1])
