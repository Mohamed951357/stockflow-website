"""Investigate default-male company session and avatar update."""
import paramiko, sys
sys.stdout.reconfigure(encoding='utf-8')
KEY = r"D:\StockFlow_Collection\temp_id_ed25519"
REMOTE = "/var/www/stock_flow"
script = r"""
import os
os.chdir('/var/www/stock_flow')
from dotenv import load_dotenv
load_dotenv('/var/www/stock_flow/.env')
from app import create_app
from models import Company

app = create_app()
with app.app_context():
    dm = Company.query.get(509)
    print('Company 509:')
    print('  name:', repr(dm.company_name))
    print('  avatar:', repr(dm.avatar))
    print('  active:', getattr(dm, 'is_active', 'N/A'))
    print('  deactivated_at:', getattr(dm, 'deactivated_at', 'N/A'))
    print('  get_id:', dm.get_id())

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['user_type'] = 'company'
        sess['_user_id'] = 'company:509'
        sess['_fresh'] = True

    r = client.post('/set_avatar', json={'avatar': 'female-1'})
    print('\nset_avatar status:', r.status_code)
    print('content-type:', r.content_type)
    print('location:', r.headers.get('Location'))
    print('body[:200]:', r.get_data(as_text=True)[:200])

    r2 = client.get('/company_profile')
    print('\ncompany_profile status:', r2.status_code)
    print('logged in page:', 'company_name' in r2.get_data(as_text=True).lower())

    with app.app_context():
        print('DB avatar now:', repr(Company.query.get(509).avatar))

    # revert if changed
    client.post('/set_avatar', json={'avatar': 'male-1'})
    with app.app_context():
        av = Company.query.get(509).avatar
        if av != 'default-male':
            c = Company.query.get(509)
            c.avatar = 'default-male'
            from models import db
            db.session.commit()
            print('Reverted 509 to default-male')
"""
key = paramiko.Ed25519Key.from_private_key_file(KEY)
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('134.209.182.8', username='root', pkey=key, timeout=30)
sftp = client.open_sftp()
with sftp.open(REMOTE + '/_tmp_dm.py', 'w') as f: f.write(script)
sftp.close()
_, out, err = client.exec_command(f'cd {REMOTE} && venv/bin/python3 _tmp_dm.py; rm -f _tmp_dm.py')
print(out.read().decode('utf-8', errors='replace'))
if err.read().decode(): print('STDERR:', err.read().decode())
client.close()
