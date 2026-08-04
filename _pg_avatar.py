import paramiko, sys
sys.stdout.reconfigure(encoding='utf-8')
KEY = r'D:\StockFlow_Collection\temp_id_ed25519'
key = paramiko.Ed25519Key.from_private_key_file(KEY)
c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy()); c.connect('134.209.182.8', username='root', pkey=key, timeout=30)
cmd = "sudo -u postgres psql -d stock_flow -t -c \"SELECT avatar, count(*) FROM company GROUP BY avatar ORDER BY count(*) DESC LIMIT 25;\""
_, o, e = c.exec_command(cmd)
print(o.read().decode())
print(e.read().decode())
c.close()
