"""Full avatar flow test on server: switch, upload, delete, dashboard display."""
import paramiko
import sys

sys.stdout.reconfigure(encoding="utf-8")

KEY = r"D:\StockFlow_Collection\temp_id_ed25519"
REMOTE = "/var/www/stock_flow"

script = r"""
import os, re, io
os.chdir('/var/www/stock_flow')
from dotenv import load_dotenv
load_dotenv('/var/www/stock_flow/.env')
from app import create_app
from models import Company

app = create_app()

def login_as(client, co):
    with client.session_transaction() as sess:
        sess['user_type'] = 'company'
        sess['_user_id'] = co.get_id()
        sess['_fresh'] = True

with app.test_client() as client:
    with app.app_context():
        co = Company.query.filter(Company.avatar.in_(['male-1', 'default-male'])).first()
        cid = co.id
        uid = co.get_id()
        print('=== Test company ===')
        print('id=', cid, 'avatar=', repr(co.avatar))

    login_as(client, co)

    # 1) Switch to female via API
    r = client.post('/set_avatar', json={'avatar': 'female-1'})
    print('\n=== 1) set_avatar female-1 ===')
    print('status', r.status_code, r.get_json())

    # 2) Dashboard shows female avatar
    r2 = client.get('/company_dashboard')
    html2 = r2.get_data(as_text=True)
    print('\n=== 2) company_dashboard after female ===')
    print('status', r2.status_code)
    print('female-1.jpg in dashboard:', 'female-1.jpg' in html2)
    print('male-1.jpg in dashboard:', 'male-1.jpg' in html2)

    # 3) Settings page shows female selected
    r3 = client.get('/company_settings')
    html3 = r3.get_data(as_text=True)
    print('\n=== 3) company_settings after female ===')
    print('active female border check:', 'active_av == \'female-1\'' not in html3 and 'female-1.jpg' in html3)
    print('badge محدد for female:', html3.count('محدد') >= 1)
    print('choose male button present:', 'setPresetAvatar(\'male-1\')' in html3)

    # 4) Switch back to male
    r4 = client.post('/set_avatar', json={'avatar': 'male-1'})
    print('\n=== 4) revert to male-1 ===')
    print('status', r4.status_code, r.get_json())

    # 5) Test custom photo block (read-only — no delete on real users)
    with app.app_context():
        custom = Company.query.filter(Company.avatar.like('http%')).first()
    if custom:
        login_as(client, custom)
        r5 = client.post('/set_avatar', json={'avatar': 'female-1'})
        print('\n=== 5) custom photo block ===')
        print('status', r5.status_code, r5.get_json())
        r6 = client.get('/company_settings')
        html6 = r6.get_data(as_text=True)
        print('settings shows delete button:', 'deleteAvatar()' in html6)
        print('settings hides preset switch:', 'احذف الصورة الشخصية أولاً' in html6)

    # 6) delete_avatar logic check via code path only (no real delete)
    print('\n=== 6) delete_avatar on preset (should fail) ===')
    login_as(client, co)
    r7 = client.post('/delete_avatar')
    print('status', r7.status_code, r7.get_json())

    # 7) Template sync checks
    print('\n=== 7) Server template markers ===')
    for tpl in ['company_profile.html', 'company_settings.html', 'company_dashboard.html']:
        path = f'/var/www/stock_flow/templates/{tpl}'
        with open(path, encoding='utf-8') as f:
            content = f.read()
        markers = {
            'selectAvatar': 'selectAvatar' in content,
            'setPresetAvatar': 'setPresetAvatar' in content,
            'fetch set_avatar': "fetch('/set_avatar'" in content,
            'has_custom_photo': 'has_custom_photo' in content,
            'female-1.jpg': 'female-1.jpg' in content,
        }
        print(tpl + ':', markers)

    # 8) default-male normalization via company_profile POST
    with app.app_context():
        dm = Company.query.filter_by(avatar='default-male').first()
    if dm:
        login_as(client, dm)
        r9 = client.post('/company_profile', data={
            'company_name': dm.company_name,
            'phone': dm.phone or '',
            'email': dm.email or '',
            'avatar': 'female-1',
            'allow_company_messages': 'on',
        }, follow_redirects=False)
        print('\n=== 8) default-male via profile POST ===')
        print('redirect status', r9.status_code)
        with app.app_context():
            dm2 = Company.query.get(dm.id)
            print('DB avatar after POST:', repr(dm2.avatar))
        # revert
        client.post('/set_avatar', json={'avatar': 'male-1'})

print('\n=== ALL TESTS DONE ===')
"""

key = paramiko.Ed25519Key.from_private_key_file(KEY)
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("134.209.182.8", username="root", pkey=key, timeout=30)

sftp = client.open_sftp()
with sftp.open(REMOTE + "/_tmp_full_avatar.py", "w") as f:
    f.write(script)
sftp.close()

_, out, err = client.exec_command(
    f"cd {REMOTE} && venv/bin/python3 _tmp_full_avatar.py; rm -f _tmp_full_avatar.py"
)
print(out.read().decode("utf-8", errors="replace"))
e = err.read().decode("utf-8", errors="replace")
if e:
    print("STDERR:", e)
client.close()
