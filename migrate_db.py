import sqlite3
import os

# Try both possible database locations
db_paths = [
    '/home/Bonuspharma1/instance/site.db',
    '/home/Bonuspharma1/mysite/site.db',
]

db_path = None
for path in db_paths:
    if os.path.exists(path):
        conn = sqlite3.connect(path)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='company'")
        if c.fetchone():
            db_path = path
            conn.close()
            break
        conn.close()

if not db_path:
    print("ERROR: Could not find database with company table!")
    exit(1)

print(f"Using database: {db_path}")

conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute('PRAGMA table_info(company)')
existing_cols = [row[1] for row in c.fetchall()]
print(f"Found {len(existing_cols)} existing columns")

new_columns = [
    ('google_id', 'VARCHAR(200)'),
    ('google_email', 'VARCHAR(200)'),
    ('monthly_search_count', 'INTEGER DEFAULT 0'),
    ('bio', 'TEXT'),
    ('cover_photo_url', 'VARCHAR(500)'),
    ('premium_trial_prompted', 'BOOLEAN DEFAULT 0'),
    ('premium_trial_active', 'BOOLEAN DEFAULT 0'),
    ('premium_trial_start', 'DATETIME'),
    ('premium_trial_end', 'DATETIME'),
    ('deactivation_reason', 'TEXT'),
    ('deactivated_at', 'DATETIME'),
]

added = 0
for col_name, col_type in new_columns:
    if col_name not in existing_cols:
        try:
            c.execute(f'ALTER TABLE company ADD COLUMN {col_name} {col_type}')
            print(f'  [+] Added: {col_name}')
            added += 1
        except Exception as e:
            print(f'  [!] Error adding {col_name}: {e}')
    else:
        print(f'  [=] Already exists: {col_name}')

conn.commit()
conn.close()
print(f"\nDONE! Added {added} new columns.")
print("Now reload your web app on PythonAnywhere!")
