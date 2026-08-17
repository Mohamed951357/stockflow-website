"""Create the index required for fast company stock reports.

Run this once after deployment. It supports both the SQLite deployment and
PostgreSQL, creating the PostgreSQL index concurrently to avoid blocking reads.
"""

import os

from sqlalchemy import create_engine, text

from config import Config


INDEX_NAME = 'ix_product_stock_history_product_name_record_date'
INDEX_SQL = (
    f'CREATE INDEX IF NOT EXISTS {INDEX_NAME} '
    'ON product_stock_history (product_name, record_date)'
)


def _database_url():
    database_url = (os.environ.get('DATABASE_URL') or Config.SQLALCHEMY_DATABASE_URI or '').strip()
    if database_url.startswith('postgres://'):
        return 'postgresql://' + database_url[len('postgres://'):]
    if not database_url:
        raise RuntimeError('DATABASE_URL is not configured.')
    return database_url


def main():
    engine = create_engine(_database_url(), pool_pre_ping=True)
    if engine.dialect.name == 'postgresql':
        # PostgreSQL requires autocommit for CREATE INDEX CONCURRENTLY.
        concurrent_sql = INDEX_SQL.replace('CREATE INDEX', 'CREATE INDEX CONCURRENTLY', 1)
        with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
            connection.execute(text(concurrent_sql))
    else:
        with engine.begin() as connection:
            connection.execute(text(INDEX_SQL))

    print(f'Ensured {INDEX_NAME}.')


if __name__ == '__main__':
    main()
