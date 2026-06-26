"""
Migration script to add last_active and is_typing columns to Company table
"""
from models import db, Company
from datetime import datetime

def migrate():
    """Add new columns to Company table"""
    try:
        # Check if columns already exist
        inspector = db.inspect(db.engine)
        columns = [c['name'] for c in inspector.get_columns('company')]
        
        if 'last_active' not in columns:
            print("Adding last_active column...")
            db.engine.execute('ALTER TABLE company ADD COLUMN last_active DATETIME DEFAULT CURRENT_TIMESTAMP')
            print("✓ last_active column added")
        else:
            print("✓ last_active column already exists")
            
        if 'is_typing' not in columns:
            print("Adding is_typing column...")
            db.engine.execute('ALTER TABLE company ADD COLUMN is_typing BOOLEAN DEFAULT FALSE')
            print("✓ is_typing column added")
        else:
            print("✓ is_typing column already exists")
            
        print("\n✓ Migration completed successfully!")
        
    except Exception as e:
        print(f"✗ Migration failed: {str(e)}")
        raise

if __name__ == "__main__":
    print("=== Adding User Status Columns ===\n")
    migrate()
