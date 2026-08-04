"""Verify avatar switching logic on remote server."""
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
    f"grep -n '_is_custom_company_avatar\\|set_avatar\\|_normalize_preset_avatar' {REMOTE}/views.py | head -40",
    f"sed -n '8752,8912p' {REMOTE}/views.py",
    f"cd {REMOTE} && venv/bin/python3 -c \""
    "import os; os.chdir('/var/www/stock_flow'); "
    "from app import app; "
    "print('avatar routes:', sorted(r.rule for r in app.url_map.iter_rules() if 'avatar' in r.rule))\"",
    f"cd {REMOTE} && venv/bin/python3 -c \""
    "import os; os.chdir('/var/www/stock_flow'); "
    "from app import app; from models import db, Company; "
    "from collections import Counter; "
    "ctx=app.app_context(); ctx.push(); "
    "rows=Company.query.with_entities(Company.id, Company.company_name, Company.avatar).all(); "
    "c=Counter([r.avatar for r in rows]); "
    "print('Avatar value counts:'); "
    "[print(k, v) for k,v in sorted(c.items(), key=lambda x: -x[1])]; "
    "print('Sample female-1:', [(r.id, r.company_name[:30]) for r in rows if r.avatar=='female-1'][:5]); "
    "ctx.pop()\"",
    "curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:5000/set_avatar -H 'Content-Type: application/json' -d '{\"avatar\":\"female-1\"}'",
]

for cmd in cmds:
    print("\n=== CMD ===")
    print(cmd[:150].replace("\n", " "))
    _, out, err = client.exec_command(cmd)
    o = out.read().decode("utf-8", errors="replace")
    e = err.read().decode("utf-8", errors="replace")
    if o:
        print(o)
    if e:
        print("STDERR:", e)

client.close()
