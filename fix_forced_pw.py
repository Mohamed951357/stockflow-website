import paramiko
import sys
sys.stdout.reconfigure(encoding='utf-8')

SERVER_IP = '134.209.182.8'
SSH_USER  = 'root'
SSH_KEY   = r'D:\StockFlow_Collection\temp_id_ed25519'

key = paramiko.Ed25519Key.from_private_key_file(SSH_KEY)
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SERVER_IP, username=SSH_USER, pkey=key, timeout=30)
print("Connected")

sftp = client.open_sftp()

# Upload the fixed local HTML file directly to server
local_html = r'D:\StockFlow_Collection\ملفات الموقع\templates\change_password_forced.html'
remote_html = '/var/www/stock_flow/templates/change_password_forced.html'

with open(local_html, 'rb') as f:
    local_content = f.read()

with sftp.open(remote_html, 'wb') as f:
    f.write(local_content)

print("Uploaded change_password_forced.html to server")

# Verify: check for old_password in the uploaded file
_, stdout, _ = client.exec_command('grep -c "old_password" /var/www/stock_flow/templates/change_password_forced.html')
count = stdout.read().decode().strip()
print(f"old_password occurrences in server HTML: {count} (should be 0)")

sftp.close()
client.close()
print("DONE!")
