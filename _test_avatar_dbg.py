"""Debug default-male profile POST and /company dashboard avatar."""
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
with app.test_client() as client:
    with app.app_context():
        co = Company.query.filter(Company.avatar.in_(['male-1','default-male'])).first()
        dm = Company.query.filter_by(avatar='default-male').first()
        print('preset company', co.id, co.avatar, co.company_name[:20])
        print('default-male company', dm.id if dm else None, dm.company_name[:20] if dm else None)

    def login(co):
        with client.session_transaction() as sess:
            sess['user_type'] = 'company'
            sess['_user_id'] = co.get_id()
            sess['_fresh'] = True

    login(co)
    client.post('/set_avatar', json={'avatar': 'female-1'})
    r = client.get('/company')
    html = r.get_data(as_text=True)
    print('\n/company status', r.status_code)
    print('female-1 in dashboard:', 'female-1' in html)
    print('avatars/female' in html, 'avatars/female' in html)
    client.post('/set_avatar', json={'avatar': 'male-1'})

    if dm:
        login(dm)
        with app.app_context():
            av = dm.avatar or ''
            is_custom = av.startswith('custom-photo:') or av.startswith('http') or '/media/avatars/' in av
            print('\ndefault-male checks:')
            print(' avatar repr', repr(av))
            print(' is custom', is_custom)
        r2 = client.post('/company_profile', data={
            'company_name': dm.company_name,
            'phone': dm.phone or '',
            'email': dm.email or '',
            'avatar': 'female-1',
        }, follow_redirects=True)
        print('profile POST status', r2.status_code)
        with app.app_context():
            dm2 = Company.query.get(dm.id)
            print('avatar after POST', repr(dm2.avatar))
        login(dm)
        r3 = client.post('/set_avatar', json={'avatar': 'female-1'})
        print('set_avatar on default-male', r3.status_code, r3.get_json())
        with app.app_context():
            print('avatar after set_avatar', repr(Company.query.get(dm.id).avatar))
        client.post('/set_avatar', json={'avatar': 'male-1'})
"""
key = paramiko.Ed25519Key.from_private_key_file(KEY)
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('134.209.182.8', username='root', pkey=key, timeout=30)
sftp = client.open_sftp()
with sftp.open(REMOTE + '/_tmp_dbg.py', 'w') as f: f.write(script)
sftp.close()
_, out, err = client.exec_command(f'cd {REMOTE} && venv/bin/python3 _tmp_dbg.py; rm -f _tmp_dbg.py')
print(out.read().decode('utf-8', errors='replace'))
e = err.read().decode('utf-8', errors='replace')
if e: print('STDERR:', e)
client.close()
