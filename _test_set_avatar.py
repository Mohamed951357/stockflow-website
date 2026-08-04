"""Test set_avatar endpoint on server with Flask test client."""
import paramiko
import sys

sys.stdout.reconfigure(encoding="utf-8")

KEY = r"D:\StockFlow_Collection\temp_id_ed25519"
REMOTE = "/var/www/stock_flow"

script = r"""
import os
os.chdir('/var/www/stock_flow')
from dotenv import load_dotenv
load_dotenv('/var/www/stock_flow/.env')

from app import create_app
from models import db, Company

app = create_app()

with app.app_context():
    co = Company.query.filter(Company.avatar.in_(['male-1', 'default-male'])).first()
    print('Test company id=', co.id, 'avatar=', repr(co.avatar), 'get_id=', co.get_id())
    custom = Company.query.filter(Company.avatar.like('http%')).first()
    print('Custom company id=', custom.id if custom else None)

with app.test_client() as client:
    with app.app_context():
        co = Company.query.filter(Company.avatar.in_(['male-1', 'default-male'])).first()
        uid = co.get_id()

    with client.session_transaction() as sess:
        sess['user_type'] = 'company'
        sess['_user_id'] = uid
        sess['_fresh'] = True

    r = client.post('/set_avatar', json={'avatar': 'female-1'})
    print('POST set_avatar female-1:', r.status_code, r.get_json())

    with app.app_context():
        co2 = Company.query.get(co.id)
        print('DB after set:', repr(co2.avatar))

    r2 = client.post('/set_avatar', json={'avatar': 'male-1'})
    print('POST revert male-1:', r2.status_code, r2.get_json())

    with app.app_context():
        print('DB after revert:', repr(Company.query.get(co.id).avatar))

    if custom:
        with app.app_context():
            uid2 = custom.get_id()
        with client.session_transaction() as sess:
            sess['user_type'] = 'company'
            sess['_user_id'] = uid2
            sess['_fresh'] = True
        r3 = client.post('/set_avatar', json={'avatar': 'female-1'})
        print('Custom photo block:', r3.status_code, r3.get_json())
"""

key = paramiko.Ed25519Key.from_private_key_file(KEY)
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("134.209.182.8", username="root", pkey=key, timeout=30)

sftp = client.open_sftp()
with sftp.open(REMOTE + "/_tmp_test_avatar.py", "w") as f:
    f.write(script)
sftp.close()

_, out, err = client.exec_command(f"cd {REMOTE} && venv/bin/python3 _tmp_test_avatar.py; rm -f _tmp_test_avatar.py")
print(out.read().decode("utf-8", errors="replace"))
e = err.read().decode("utf-8", errors="replace")
if e:
    print("STDERR:", e)
client.close()
