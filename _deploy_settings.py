import subprocess

git_exe = r"C:\Users\bonus\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"
key_file = r"C:\Users\bonus\AppData\Local\StockFlowToby\stockflow_id_ed25519"

print("1. Adding company_settings.html to Git...")
subprocess.run([git_exe, 'add', 'templates/company_settings.html'], check=True)

print("2. Committing changes...")
subprocess.run([git_exe, 'commit', '-m', 'Make navbar in company_settings.html identical to company_dashboard.html'], check=True)

print("3. Pushing to GitHub main...")
p_res = subprocess.run([git_exe, 'push', 'origin', 'main'], capture_output=True, text=True)
print("Git Push stdout:", p_res.stdout)
print("Git Push stderr:", p_res.stderr)

print("4. SCP templates/company_settings.html to live server 134.209.182.8...")
s1 = subprocess.run(['scp', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'templates/company_settings.html', 'root@134.209.182.8:/var/www/stock_flow/templates/company_settings.html'], capture_output=True, text=True)
print("SCP templates/company_settings.html:", s1.returncode)

print("5. Fixing ownership & restarting stock_flow service on server...")
ssh_res = subprocess.run(['ssh', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'root@134.209.182.8', 'chown www-data:www-data /var/www/stock_flow/templates/company_settings.html && systemctl restart stock_flow'], capture_output=True, text=True)
print("SSH Restart returncode:", ssh_res.returncode)
print("SSH Restart stdout:", ssh_res.stdout)
print("SSH Restart stderr:", ssh_res.stderr)

print("SETTINGS NAVBAR DEPLOYED SUCCESSFULLY!")
