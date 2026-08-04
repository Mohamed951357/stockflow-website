# -*- coding: utf-8 -*-
"""Migration: add hidden_from_sender column to private_message table."""

from models import db


def migrate():
    try:
        inspector = db.inspect(db.engine)
        columns = [c['name'] for c in inspector.get_columns('private_message')]
        dialect = db.engine.dialect.name

        if 'hidden_from_sender' in columns:
            print('✓ hidden_from_sender column already exists')
            return

        print('Adding hidden_from_sender column...')
        if dialect == 'postgresql':
            sql = 'ALTER TABLE private_message ADD COLUMN hidden_from_sender BOOLEAN DEFAULT FALSE'
        else:
            sql = 'ALTER TABLE private_message ADD COLUMN hidden_from_sender BOOLEAN DEFAULT 0'

        with db.engine.begin() as conn:
            conn.execute(db.text(sql))

        print('✓ hidden_from_sender column added')
        print('\n✓ Migration completed successfully!')

    except Exception as e:
        print(f'✗ Migration failed: {str(e)}')
        raise


if __name__ == '__main__':
    from app import create_app

    app = create_app()
    with app.app_context():
        print('=== Adding hidden_from_sender column ===\n')
        migrate()
