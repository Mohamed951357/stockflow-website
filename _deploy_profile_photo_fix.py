"""Deploy profile photo fix to DigitalOcean and sync permissions."""
import paramiko
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
KEY = Path(r"D:\StockFlow_Collection\temp_id_ed25519")
HOST = "134.209.182.8"
REMOTE = "/var/www/stock_flow"

uploads = [
    (ROOT / "views.py", f"{REMOTE}/views.py"),
    (ROOT / "templates" / "company_settings.html", f"{REMOTE}/templates/company_settings.html"),
    (ROOT / "templates" / "company_profile.html", f"{REMOTE}/templates/company_profile.html"),
    (ROOT / "templates" / "company_dashboard.html", f"{REMOTE}/templates/company_dashboard.html"),
]

key = paramiko.Ed25519Key.from_private_key_file(str(KEY))
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username="root", pkey=key, timeout=30)
print("Connected")

sftp = client.open_sftp()
for local, remote in uploads:
    with open(local, "rb") as f:
        data = f.read()
    with sftp.open(remote, "wb") as rf:
        rf.write(data)
    print(f"Uploaded {local.name} -> {remote}")
sftp.close()

post_cmds = (
    f"chown -R www-data:www-data {REMOTE}/media/avatars "
    f"{REMOTE}/static/images/profile_photos 2>/dev/null; "
    f"chmod 775 {REMOTE}/media/avatars {REMOTE}/static/images/profile_photos 2>/dev/null; "
    "systemctl restart stock_flow && systemctl is-active stock_flow"
)
_, out, err = client.exec_command(post_cmds)
print(out.read().decode("utf-8", errors="replace"))
e = err.read().decode("utf-8", errors="replace")
if e:
    print("stderr:", e)
client.close()
print("Done.")
