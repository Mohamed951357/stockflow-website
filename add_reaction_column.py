import sqlite3
import sys
import os

# الاستخدام:
# python add_reaction_column.py path/to/site.db
# مثال:
# python add_reaction_column.py instance/site.db

COLUMNS_TO_ADD = [
    ("reaction_type", "VARCHAR(50) DEFAULT 'heart'"),
]

def main(db_path: str):
    if not os.path.exists(db_path):
        print(f"❌ ملف قاعدة البيانات غير موجود: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(post_like)")
    existing_cols = {row[1] for row in cur.fetchall()}

    for col_name, col_def in COLUMNS_TO_ADD:
        if col_name in existing_cols:
            print(f"✅ العمود '{col_name}' موجود بالفعل في جدول post_like")
            continue
        try:
            ddl = f"ALTER TABLE post_like ADD COLUMN {col_name} {col_def}"
            print(f"➕ إضافة العمود '{col_name}': {ddl}")
            cur.execute(ddl)
            print("🎉 تمت الإضافة بنجاح.")
        except Exception as e:
            print(f"❌ حدث خطأ أثناء إضافة العمود {col_name}: {e}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("الاستخدام: python add_reaction_column.py path/to/site.db")
        sys.exit(1)
    main(sys.argv[1])
