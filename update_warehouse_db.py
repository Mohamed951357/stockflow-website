# update_warehouse_db.py
import sqlite3
import os
import re

def update_warehouse_table():
    # Try multiple common paths for the DB, including PythonAnywhere's specific path
    db_paths = [
        '/home/Bonuspharma1/db.sqlite3',  # PythonAnywhere path from config.py
        'site.db', 
        'instance/site.db', 
        '../instance/site.db',
        'db.sqlite3'
    ]
    
    db_path = None
    for path in db_paths:
        if os.path.exists(path):
            db_path = path
            break

    if not db_path:
        print("Database not found! Tried paths: " + ", ".join(db_paths))
        return

    print(f"Updating database at: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # List of all columns that SHOULD be in the warehouse table
    columns_to_add = [
        ("is_processing", "BOOLEAN DEFAULT 0"),
        ("last_process_added", "INTEGER DEFAULT 0"),
        ("last_process_updated", "INTEGER DEFAULT 0"),
        ("last_process_reset", "INTEGER DEFAULT 0"),
        ("last_process_status", "VARCHAR(50)"),
        ("last_process_error", "TEXT"),
        ("last_process_time", "DATETIME"),
        ("last_process_filename", "VARCHAR(255)"),
        ("last_process_data_rows", "INTEGER DEFAULT 0")
    ]

    cursor.execute('PRAGMA table_info("warehouse")')
    existing_cols = {row[1] for row in cursor.fetchall()}

    for col_name, col_def in columns_to_add:
        if col_name not in existing_cols:
            try:
                # Validate column name before running ALTER
                if not re.match(r'^[A-Za-z0-9_]+$', col_name):
                    print(f"Skipping invalid column name: {col_name}")
                    continue
                cursor.execute(f'ALTER TABLE "warehouse" ADD COLUMN "{col_name}" {col_def}')
                print(f"Added column: {col_name}")
            except Exception as e:
                print(f"Error adding {col_name}: {e}")
        else:
            print(f"Column {col_name} already exists.")

    conn.commit()
    conn.close()
    print("Database update completed!")

if __name__ == "__main__":
    update_warehouse_table()
