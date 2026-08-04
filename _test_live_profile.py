"""Verify live company_profile HTML and browser-like set_avatar."""
import paramiko
import sys

sys.stdout.reconfigure(encoding="utf-8")

KEY = r"D:\StockFlow_Collection\temp_id_ed25519"
REMOTE = "/var/www/stock_flow"

script = r"""
import os, re
os.chdir('/var/www/stock_flow')
from dotenv import load_dotenv
load_dotenv('/var/www/stock_flow/.env')
from app import create_app
from models import Company

app = create_app()
with app.test_client() as client:
    with app.app_context():
        co = Company.query.filter(Company.avatar == 'male-1').first()
        uid = co.get_id()
    with client.session_transaction() as sess:
        sess['user_type'] = 'company'
        sess['_user_id'] = uid
        sess['_fresh'] = True

    r = client.get('/company_profile')
    html = r.get_data(as_text=True)
    print('GET company_profile status:', r.status_code)
    checks = [
        ("fetch('/set_avatar'", "fetch set_avatar present"),
        ('window.hasCustomPhoto', 'hasCustomPhoto flag'),
        ('function selectAvatar', 'selectAvatar function'),
        ('female-1', 'female-1 in page'),
        ('has_custom_photo', 'has_custom_photo template var'),
    ]
    for needle, label in checks:
        print(label + ':', needle in html)

    # simulate click female
    r2 = client.post('/set_avatar', json={'avatar': 'female-1'})
    print('set_avatar response:', r2.status_code, r2.get_json())

    r3 = client.get('/company_profile')
    html3 = r3.get_data(as_text=True)
    print('selected-avatar value female after set:', 'value="female-1"' in html3 or "value='female-1'" in html3)
    m = re.search(r'id="selected-avatar"\s+value="([^"]+)"', html3)
    print('hidden avatar value:', m.group(1) if m else 'NOT FOUND')

    # revert
    client.post('/set_avatar', json={'avatar': 'male-1'})

    # company_settings page too
    r4 = client.get('/company_settings')
    html4 = r4.get_data(as_text=True)
    print('GET company_settings status:', r4.status_code)
    print('setPresetAvatar present:', 'function setPresetAvatar' in html4)
    print('has_custom_photo block present:', '{% if not has_custom_photo %}' not in html4 and 'has_custom_photo' in html4)
"""

key = paramiko.Ed25519Key.from_private_key_file(KEY)
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("134.209.182.8", username="root", pkey=key, timeout=30)
sftp = client.open_sftp()
with sftp.open(REMOTE + "/_tmp_live.py", "w") as f:
    f.write(script)
sftp.close()
_, out, err = client.exec_command(f"cd {REMOTE} && venv/bin/python3 _tmp_live.py; rm -f _tmp_live.py")
print(out.read().decode("utf-8", errors="replace"))
e = err.read().decode("utf-8", errors="replace")
if e:
    print("STDERR:", e)
client.close()
