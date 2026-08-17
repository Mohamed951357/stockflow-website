# -*- coding: utf-8 -*-
"""
Migration script to add current_session_token column to Company and Admin tables.
Supports SQLite, PostgreSQL, and MySQL.
"""
from app import create_app
from models import db
from sqlalchemy import inspect, text

def migrate():
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)
        is_postgres = db.engine.dialect.name == 'postgresql'
        
        # 1. Update company table
        if inspector.has_table('company'):
            columns = [c['name'] for c in inspector.get_columns('company')]
            if 'current_session_token' not in columns:
                print("Adding current_session_token to company table...")
                if is_postgres:
                    db.session.execute(text('ALTER TABLE "company" ADD COLUMN IF NOT EXISTS "current_session_token" VARCHAR(100)'))
                else:
                    db.session.execute(text('ALTER TABLE "company" ADD COLUMN "current_session_token" VARCHAR(100)'))
                db.session.commit()
                print("[OK] Added current_session_token to company table.")
            else:
                print("[OK] current_session_token already exists in company table.")

        # 2. Update admin table
        if inspector.has_table('admin'):
            columns = [c['name'] for c in inspector.get_columns('admin')]
            if 'current_session_token' not in columns:
                print("Adding current_session_token to admin table...")
                if is_postgres:
                    db.session.execute(text('ALTER TABLE "admin" ADD COLUMN IF NOT EXISTS "current_session_token" VARCHAR(100)'))
                else:
                    db.session.execute(text('ALTER TABLE "admin" ADD COLUMN "current_session_token" VARCHAR(100)'))
                db.session.commit()
                print("[OK] Added current_session_token to admin table.")
            else:
                print("[OK] current_session_token already exists in admin table.")

        print("[OK] Migration complete!")

if __name__ == '__main__':
    migrate()
