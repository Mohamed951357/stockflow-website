"""Quick server DB check for companies."""
import paramiko, sys
sys.stdout.reconfigure(encoding='utf-8')
KEY = r"D:\StockFlow_Collection\temp_id_ed25519"
key = paramiko.Ed25519Key.from_private_key_file(KEY)
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('134.209.182.8', username='root', pkey=key, timeout=30)
script = """
import os
os.chdir('/var/www/stock_flow')
from app import create_app
from models import db, Company
app = create_app()
with app.app_context():
    n = Company.query.count()
    print('company count', n)
    for r in Company.query.limit(5).all():
        print('id', r.id, 'name', getattr(r,'company_name',None), 'avatar', repr(getattr(r,'avatar',None)))
"""
sftp = client.open_sftp()
with sftp.open('/var/www/stock_flow/_tmp.py','w') as f: f.write(script)
sftp.close()
_, out, err = client.exec_command('cd /var/www/stock_flow && venv/bin/python3 _tmp.py && rm _tmp.py')
print(out.read().decode())
print(err.read().decode())
client.close()
