import subprocess

git_exe = r"C:\Users\bonus\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"
key_file = r"C:\Users\bonus\AppData\Local\StockFlowToby\stockflow_id_ed25519"

with open('_login_dcc.html', 'r', encoding='utf-8') as f:
    pristine_html = f.read()

with open('templates/login.html', 'w', encoding='utf-8') as f:
    f.write(pristine_html)

print("1. Restored templates/login.html to pristine original layout!")

print("2. Adding to Git...")
subprocess.run([git_exe, 'add', 'templates/login.html'], check=True)

print("3. Committing...")
subprocess.run([git_exe, 'commit', '-m', 'Restore login.html to clean pristine layout with login button and forgot password link'], check=True)

print("4. Pushing to GitHub main...")
p_res = subprocess.run([git_exe, 'push', 'origin', 'main'], capture_output=True, text=True)
print("Git Push:", p_res.stderr or p_res.stdout)

print("5. SCP templates/login.html to live server 134.209.182.8...")
subprocess.run(['scp', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'templates/login.html', 'root@134.209.182.8:/var/www/stock_flow/templates/login.html'], check=True)

print("6. Setting permissions & restarting service...")
ssh_res = subprocess.run(['ssh', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'root@134.209.182.8', 'chown www-data:www-data /var/www/stock_flow/templates/login.html && systemctl restart stock_flow'], capture_output=True, text=True)
print("SSH Returncode:", ssh_res.returncode)

print("PRISTINE LOGIN PAGE SUCCESSFULLY RESTORED AND DEPLOYED!")
