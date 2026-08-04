import paramiko, sys
sys.stdout.reconfigure(encoding='utf-8')
KEY = r'D:\StockFlow_Collection\temp_id_ed25519'
key = paramiko.Ed25519Key.from_private_key_file(KEY)
c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy()); c.connect('134.209.182.8', username='root', pkey=key, timeout=30)
cmds = [
 'ls -la /var/www/stock_flow/static/images/avatars/',
 'test -f /var/www/stock_flow/static/images/avatars/female-1.jpg && echo female_exists || echo female_MISSING',
 'test -f /var/www/stock_flow/static/images/avatars/male-1.jpg && echo male_exists || echo male_MISSING',
]
for cmd in cmds:
 print('===', cmd, '===')
 _,o,e=c.exec_command(cmd)
 print(o.read().decode())
 print(e.read().decode())
c.close()
