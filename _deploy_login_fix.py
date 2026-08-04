import subprocess

git_exe = r"C:\Users\bonus\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"
key_file = r"C:\Users\bonus\AppData\Local\StockFlowToby\stockflow_id_ed25519"

print("1. Adding templates/login.html to Git...")
subprocess.run([git_exe, 'add', 'templates/login.html'], check=True)

print("2. Committing...")
subprocess.run([git_exe, 'commit', '-m', 'Remove duplicate first forgot password link on login page'], check=True)

print("3. Pushing to GitHub main...")
p_res = subprocess.run([git_exe, 'push', 'origin', 'main'], capture_output=True, text=True)
print("Git Push:", p_res.stderr or p_res.stdout)

print("4. Uploading templates/login.html via SCP to live server 134.209.182.8...")
subprocess.run(['scp', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'templates/login.html', 'root@134.209.182.8:/var/www/stock_flow/templates/login.html'], check=True)

print("5. Setting permissions and restarting service...")
ssh_res = subprocess.run(['ssh', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'root@134.209.182.8', 'chown www-data:www-data /var/www/stock_flow/templates/login.html && systemctl restart stock_flow'], capture_output=True, text=True)
print("SSH Returncode:", ssh_res.returncode)

print("LOGIN PAGE FIX SUCCESSFULLY DEPLOYED!")
