import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from config import Config


def resolve_sqlite_path():
    uri = (getattr(Config, 'SQLALCHEMY_DATABASE_URI', '') or '').strip()
    if not uri.startswith('sqlite:///'):
        raise RuntimeError(f"Unsupported database URI for this script: {uri}")
    return Path(uri.replace('sqlite:///', '', 1))


def backup_database(db_path: Path):
    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    backup_path = db_path.with_suffix(f'.backup-{timestamp}{db_path.suffix}')
    shutil.copy2(db_path, backup_path)
    return backup_path


def main():
    parser = argparse.ArgumentParser(description="Emergency SQLite diagnostics for StockFlow.")
    parser.add_argument('--backup', action='store_true', help='Create a timestamped backup copy first.')
    parser.add_argument('--switch-delete', action='store_true', help='Switch journal mode back to DELETE.')
    parser.add_argument('--vacuum', action='store_true', help='Run VACUUM after checks.')
    args = parser.parse_args()

    db_path = resolve_sqlite_path()
    print(f"DB path: {db_path}")
    print(f"Exists: {db_path.exists()}")
    if not db_path.exists():
        raise SystemExit(1)

    print(f"Size MB: {db_path.stat().st_size / (1024 * 1024):.2f}")

    wal_path = Path(f"{db_path}-wal")
    shm_path = Path(f"{db_path}-shm")
    print(f"WAL exists: {wal_path.exists()}")
    print(f"SHM exists: {shm_path.exists()}")
    if wal_path.exists():
        print(f"WAL size MB: {wal_path.stat().st_size / (1024 * 1024):.2f}")
    if shm_path.exists():
        print(f"SHM size KB: {shm_path.stat().st_size / 1024:.2f}")

    if args.backup:
        backup_path = backup_database(db_path)
        print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row

    try:
        cur = conn.cursor()
        cur.execute("PRAGMA busy_timeout = 60000;")
        cur.execute("PRAGMA journal_mode;")
        print(f"Journal mode: {cur.fetchone()[0]}")

        cur.execute("PRAGMA quick_check;")
        print(f"Quick check: {cur.fetchone()[0]}")

        cur.execute("PRAGMA integrity_check;")
        print(f"Integrity check: {cur.fetchone()[0]}")

        if args.switch_delete:
            try:
                cur.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except sqlite3.DatabaseError as exc:
                print(f"WAL checkpoint skipped: {exc}")
            cur.execute("PRAGMA journal_mode=DELETE;")
            print(f"Journal mode switched to: {cur.fetchone()[0]}")

        if args.vacuum:
            print("Running VACUUM...")
            cur.execute("VACUUM;")
            print("VACUUM completed.")

        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    main()
