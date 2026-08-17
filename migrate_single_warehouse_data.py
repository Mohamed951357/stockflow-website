"""Assign pre-multi-warehouse records to the only warehouse, safely.

Run a dry check first:
    python migrate_single_warehouse_data.py

Apply only after the report confirms exactly one warehouse:
    python migrate_single_warehouse_data.py --apply

The migration is deliberately opt-in and batched.  It does not delete or
rewrite inventory values; it only fills NULL ``warehouse_id`` values left by
the version that existed before multi-warehouse support.
"""

import argparse
import os

from sqlalchemy import bindparam, create_engine, inspect, text


TABLES_TO_MIGRATE = (
    'product_item',
    'product_stock_history',
    'product_file',
    'search_log',
    'appointment',
)


def get_database_url():
    database_url = (os.environ.get('DATABASE_URL') or '').strip()
    if not database_url:
        from config import Config
        database_url = (Config.SQLALCHEMY_DATABASE_URI or '').strip()

    if not database_url:
        raise RuntimeError('DATABASE_URL is not configured.')

    if database_url.startswith('postgres://'):
        database_url = 'postgresql://' + database_url[len('postgres://'):]
    return database_url


def get_eligible_tables(engine):
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    eligible = []
    for table_name in TABLES_TO_MIGRATE:
        if table_name not in existing_tables:
            continue
        columns = {column['name'] for column in inspector.get_columns(table_name)}
        if {'id', 'warehouse_id'}.issubset(columns):
            eligible.append(table_name)
    return eligible


def count_unassigned(connection, table_name):
    return connection.execute(
        text(f'SELECT COUNT(*) FROM {table_name} WHERE warehouse_id IS NULL')
    ).scalar_one()


def migrate_table(engine, table_name, warehouse_id, batch_size):
    selected_ids = text(
        f'SELECT id FROM {table_name} '
        'WHERE warehouse_id IS NULL ORDER BY id LIMIT :batch_size'
    )
    update_rows = text(
        f'UPDATE {table_name} SET warehouse_id = :warehouse_id '
        'WHERE id IN :row_ids'
    ).bindparams(bindparam('row_ids', expanding=True))

    migrated = 0
    while True:
        with engine.begin() as connection:
            row_ids = connection.execute(
                selected_ids, {'batch_size': batch_size}
            ).scalars().all()
            if not row_ids:
                return migrated

            connection.execute(update_rows, {
                'warehouse_id': warehouse_id,
                'row_ids': row_ids,
            })
            migrated += len(row_ids)
            print(f'  {table_name}: migrated {migrated:,} rows')


def main():
    parser = argparse.ArgumentParser(
        description='Migrate legacy NULL warehouse IDs when exactly one warehouse exists.'
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='perform the migration; without this flag the script only reports counts',
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=10_000,
        help='rows per committed batch (default: 10000)',
    )
    args = parser.parse_args()

    if args.batch_size < 100 or args.batch_size > 100_000:
        parser.error('--batch-size must be between 100 and 100000')

    engine = create_engine(get_database_url(), pool_pre_ping=True)
    tables = get_eligible_tables(engine)
    if not tables:
        raise RuntimeError('No eligible tables with a warehouse_id column were found.')

    with engine.connect() as connection:
        warehouses = connection.execute(
            text('SELECT id, name, is_active FROM warehouse ORDER BY id LIMIT 2')
        ).mappings().all()

        if len(warehouses) != 1:
            raise RuntimeError(
                'Migration stopped: it is allowed only when the database has exactly one warehouse.'
            )

        warehouse = warehouses[0]
        if not warehouse['is_active']:
            raise RuntimeError('Migration stopped: the only warehouse is inactive.')

        warehouse_id = int(warehouse['id'])
        print(f"Target warehouse: {warehouse['name']} (ID {warehouse_id})")
        report = {table_name: count_unassigned(connection, table_name) for table_name in tables}

    print('Legacy rows with no warehouse:')
    for table_name, count in report.items():
        print(f'  {table_name}: {count:,}')

    total = sum(report.values())
    if not args.apply:
        print(f'\nDry run only. {total:,} rows would be updated; rerun with --apply to execute.')
        return

    if total == 0:
        print('\nNothing to migrate.')
        return

    print('\nApplying migration in committed batches...')
    migrated_total = 0
    for table_name, count in report.items():
        if count:
            migrated_total += migrate_table(engine, table_name, warehouse_id, args.batch_size)

    print(f'\nCompleted safely. {migrated_total:,} legacy rows now belong to warehouse {warehouse_id}.')


if __name__ == '__main__':
    main()
