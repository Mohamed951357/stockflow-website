"""Query avatar values and test set_avatar on server."""
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

py_script = r"""
import os
os.chdir('/var/www/stock_flow')
from app import create_app
from models import db, Company
from collections import Counter

app = create_app()
with app.app_context():
    rows = Company.query.with_entities(Company.id, Company.company_name, Company.avatar).all()
    c = Counter([r.avatar for r in rows])
    print('Avatar value counts:')
    for k, v in sorted(c.items(), key=lambda x: (-x[1], str(x[0]))):
        print(repr(k), v)

    def is_custom(av):
        av = (av or '').strip()
        return av.startswith('custom-photo:') or av.startswith('http') or '/media/avatars/' in av

    print('\nCompanies with female-1:')
    for r in rows:
        if r.avatar == 'female-1':
            print(r.id, r.company_name[:40])

    print('\nLegacy/non-preset without custom photo (can switch):')
    for r in rows:
        av = r.avatar or ''
        if av not in ('male-1', 'female-1', 'default-male', None, '') and not is_custom(av):
            print(r.id, repr(av), r.company_name[:40])

    print('\nCustom photo companies:')
    for r in rows:
        if is_custom(r.avatar):
            print(r.id, repr(r.avatar)[:60], r.company_name[:30])
"""

remote_py = REMOTE + "/_tmp_avatar_check.py"
sftp = client.open_sftp()
with sftp.open(remote_py, "w") as f:
    f.write(py_script)
sftp.close()

_, out, err = client.exec_command(f"cd {REMOTE} && venv/bin/python3 _tmp_avatar_check.py")
print(out.read().decode("utf-8", errors="replace"))
e = err.read().decode("utf-8", errors="replace")
if e:
    print("STDERR:", e)

# Test set_avatar with flask test client
test_script = r"""
import os
os.chdir('/var/www/stock_flow')
from app import create_app
from models import db, Company

app = create_app()
with app.app_context():
    # find a company with male-1 and no custom photo
    co = Company.query.filter(Company.avatar.in_(['male-1', 'default-male', None, ''])).first()
    if not co:
        co = Company.query.filter(~Company.avatar.like('/media/%')).first()
    print('Test company:', co.id, repr(co.avatar), co.company_name[:30])
    old = co.avatar
    co.avatar = 'female-1'
    db.session.commit()
    co2 = Company.query.get(co.id)
    print('After set female-1:', repr(co2.avatar))
    co2.avatar = old or 'male-1'
    db.session.commit()
    print('Reverted to:', repr(Company.query.get(co.id).avatar))
"""

with sftp.open(REMOTE + "/_tmp_avatar_test.py", "w") as f:
    f.write(test_script)

_, out, err = client.exec_command(f"cd {REMOTE} && venv/bin/python3 _tmp_avatar_test.py")
print("\n=== DB write test ===")
print(out.read().decode("utf-8", errors="replace"))
e = err.read().decode("utf-8", errors="replace")
if e:
    print("STDERR:", e)

client.exec_command(f"rm -f {REMOTE}/_tmp_avatar_check.py {REMOTE}/_tmp_avatar_test.py")
client.close()
