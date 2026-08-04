"""Debug avatar switching on remote server."""
import paramiko
import sys

sys.stdout.reconfigure(encoding="utf-8")

KEY = r"D:\StockFlow_Collection\temp_id_ed25519"
HOST = "134.209.182.8"
REMOTE = "/var/www/stock_flow"

key = paramiko.Ed25519Key.from_private_key_file(KEY)
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username="root", pkey=key, timeout=30)

cmds = [
    f"grep -n 'selectAvatar\\|set_avatar\\|has_custom_photo' {REMOTE}/templates/company_profile.html | head -25",
    f"grep -n 'setPresetAvatar\\|has_custom_photo' {REMOTE}/templates/company_settings.html | head -15",
    f"cd {REMOTE} && python3 <<'PY'\n"
    "import os\n"
    "os.chdir('/var/www/stock_flow')\n"
    "from app import app\n"
    "rules = sorted(r.rule for r in app.url_map.iter_rules() if 'avatar' in r.rule)\n"
    "print('avatar routes:', rules)\n"
    "PY",
    f"cd {REMOTE} && python3 <<'PY'\n"
    "import os\n"
    "os.chdir('/var/www/stock_flow')\n"
    "from app import app\n"
    "from models import db, Company\n"
    "with app.app_context():\n"
    "    rows = Company.query.with_entities(Company.id, Company.company_name, Company.avatar).limit(15).all()\n"
    "    for r in rows:\n"
    "        print(r.id, repr(r.avatar), r.company_name[:30] if r.company_name else '')\n"
    "PY",
]

for cmd in cmds:
    print("\n=== CMD ===")
    print(cmd[:120].replace("\n", " "))
    _, out, err = client.exec_command(cmd)
    o = out.read().decode("utf-8", errors="replace")
    e = err.read().decode("utf-8", errors="replace")
    if o:
        print(o)
    if e:
        print("STDERR:", e)

client.close()
