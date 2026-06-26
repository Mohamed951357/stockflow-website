import os
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import requests


PROJECT_ROOT = Path("/var/www/stock_flow")
BACKUP_WORKDIR = PROJECT_ROOT / "backups" / "telegram-daily"
BACKUP_WORKDIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_STORAGE_CHAT_ID", "").strip()
TELEGRAM_MAX_FILE_SIZE = 45 * 1024 * 1024


def ensure_env(name: str, value: str):
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def build_db_dump(timestamp: str) -> Path:
    ensure_env("DATABASE_URL", DATABASE_URL)
    output_dump = BACKUP_WORKDIR / f"stockflow-postgres-{timestamp}.dump"

    result = subprocess.run(
        [
            "pg_dump",
            "--format=custom",
            "--compress=9",
            f"--file={output_dump}",
            DATABASE_URL,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        try:
            output_dump.unlink(missing_ok=True)
        except Exception:
            pass
        raise RuntimeError(f"pg_dump failed: {result.stderr}")

    return output_dump


def build_site_archive(timestamp: str) -> Path:
    archive_path = BACKUP_WORKDIR / f"stockflow-site-{timestamp}.tar.gz"
    include_paths = [
        "templates",
        "api_routes.py",
        "api_mobile.py",
        "views.py",
        "warehouse_routes.py",
        "models.py",
        "utils.py",
        "upload_control.py",
        "config.py",
        "app.py",
        "run.py",
        "search_functions.js",
        "search_products.html",
        "community_bonus.html",
        "community_bonus_demo.html",
        "manifest.json",
        "pwabuilder-sw.js",
        ".env",
    ]
    with tarfile.open(archive_path, "w:gz") as tar:
        for relative_path in include_paths:
            item = PROJECT_ROOT / relative_path
            if not item.exists():
                continue
            tar.add(item, arcname=relative_path)

    return archive_path


def split_file_if_needed(document_path: Path) -> list[Path]:
    size = document_path.stat().st_size
    if size <= TELEGRAM_MAX_FILE_SIZE:
        return [document_path]

    parts = []
    with document_path.open("rb") as source:
        index = 1
        while True:
            chunk = source.read(TELEGRAM_MAX_FILE_SIZE)
            if not chunk:
                break
            part_path = document_path.with_name(f"{document_path.name}.part{index:02d}")
            with part_path.open("wb") as target:
                target.write(chunk)
            parts.append(part_path)
            index += 1
    return parts


def send_document(document_path: Path, caption: str):
    ensure_env("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
    ensure_env("TELEGRAM_STORAGE_CHAT_ID", TELEGRAM_CHAT_ID)

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    parts = split_file_if_needed(document_path)

    for index, part_path in enumerate(parts, start=1):
        if len(parts) == 1:
            part_caption = caption
        else:
            part_caption = f"{caption}\nPart {index}/{len(parts)}"

        with part_path.open("rb") as fh:
            response = requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": part_caption[:1024],
                    "disable_notification": True,
                },
                files={"document": (part_path.name, fh, "application/octet-stream")},
                timeout=300,
            )

        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram sendDocument failed: {payload}")

    for part_path in parts:
        if part_path != document_path:
            try:
                part_path.unlink(missing_ok=True)
            except Exception:
                pass


def send_message(text: str):
    ensure_env("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
    ensure_env("TELEGRAM_STORAGE_CHAT_ID", TELEGRAM_CHAT_ID)

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text[:4096],
            "disable_notification": True,
        },
        timeout=60,
    )
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram sendMessage failed: {payload}")


def cleanup_old_backups(keep_days: int = 7):
    cutoff = datetime.now(timezone.utc).timestamp() - (keep_days * 86400)
    for path in BACKUP_WORKDIR.glob("*"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except Exception:
            pass


def main():
    timestamp = now_stamp()
    db_dump = None
    site_archive = None

    try:
        db_dump = build_db_dump(timestamp)
        site_archive = build_site_archive(timestamp)

        send_document(
            db_dump,
            f"Stock Flow daily PostgreSQL backup\nUTC: {timestamp}\nServer: stock-flow.site",
        )
        send_document(
            site_archive,
            f"Stock Flow daily site backup\nUTC: {timestamp}\nContains code and core site files",
        )
        send_message(
            "Stock Flow daily backup completed successfully.\n"
            f"UTC time: {timestamp}\n"
            "Files sent: PostgreSQL dump + site archive"
        )
        cleanup_old_backups()
    except Exception as exc:
        try:
            send_message(f"Stock Flow daily backup failed.\nUTC time: {timestamp}\nError: {str(exc)[:3000]}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
