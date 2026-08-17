# -*- coding: utf-8 -*-
"""
Migration script to create phone_verification_request table if not exists.
"""
from app import create_app
from models import db, PhoneVerificationRequest
from sqlalchemy import inspect, text

def migrate():
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)
        if not inspector.has_table('phone_verification_request'):
            print("Creating phone_verification_request table...")
            db.create_all()
            print("[OK] phone_verification_request table created successfully.")
        else:
            print("[OK] phone_verification_request table already exists.")

if __name__ == '__main__':
    migrate()
