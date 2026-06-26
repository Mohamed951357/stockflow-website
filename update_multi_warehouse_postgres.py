import os

from sqlalchemy import create_engine, text


def get_database_url():
    database_url = (os.environ.get('DATABASE_URL') or '').strip()
    if not database_url:
        try:
            from config import Config
            database_url = (getattr(Config, 'SQLALCHEMY_DATABASE_URI', '') or '').strip()
        except Exception:
            database_url = ''

    if not database_url:
        raise RuntimeError('DATABASE_URL is not configured.')

    if database_url.startswith('postgres://'):
        database_url = 'postgresql://' + database_url[len('postgres://'):]

    if not database_url.startswith(('postgresql://', 'postgresql+psycopg2://')):
        raise RuntimeError('This updater is intended for PostgreSQL only.')

    return database_url


def main():
    engine = create_engine(get_database_url(), pool_pre_ping=True)
    statements = [
        """
        ALTER TABLE product_stock_history
        ADD COLUMN IF NOT EXISTS warehouse_id INTEGER REFERENCES warehouse(id)
        """,
        """
        ALTER TABLE search_log
        ADD COLUMN IF NOT EXISTS warehouse_id INTEGER REFERENCES warehouse(id)
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_product_stock_history_warehouse_date_name
        ON product_stock_history (warehouse_id, record_date, product_name)
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_search_log_warehouse_date
        ON search_log (warehouse_id, search_date)
        """,
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    print('PostgreSQL multi-warehouse update completed.')


if __name__ == '__main__':
    main()
