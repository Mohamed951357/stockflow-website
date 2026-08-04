import subprocess

git_exe = r"C:\Users\bonus\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"
key_file = r"C:\Users\bonus\AppData\Local\StockFlowToby\stockflow_id_ed25519"

print("1. Adding files to Git...")
subprocess.run([git_exe, 'add', 'templates/search_products.html', 'templates/search.html', 'search_products.html', 'search.html'], check=True)

print("2. Committing changes...")
subprocess.run([git_exe, 'commit', '-m', 'Clean orphaned navbar links from search pages'], check=True)

print("3. Pushing to GitHub main...")
p_res = subprocess.run([git_exe, 'push', 'origin', 'main'], capture_output=True, text=True)
print("Git Push stdout:", p_res.stdout)
print("Git Push stderr:", p_res.stderr)

print("4. SCP templates to live server 134.209.182.8...")
s1 = subprocess.run(['scp', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'templates/search_products.html', 'root@134.209.182.8:/var/www/stock_flow/templates/search_products.html'], capture_output=True, text=True)
print("SCP templates/search_products.html:", s1.returncode)

s2 = subprocess.run(['scp', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'templates/search.html', 'root@134.209.182.8:/var/www/stock_flow/templates/search.html'], capture_output=True, text=True)
print("SCP templates/search.html:", s2.returncode)

s3 = subprocess.run(['scp', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'search_products.html', 'root@134.209.182.8:/var/www/stock_flow/search_products.html'], capture_output=True, text=True)
print("SCP search_products.html:", s3.returncode)

s4 = subprocess.run(['scp', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'search.html', 'root@134.209.182.8:/var/www/stock_flow/search.html'], capture_output=True, text=True)
print("SCP search.html:", s4.returncode)

print("5. Fixing ownership & restarting stock_flow service on server...")
ssh_res = subprocess.run(['ssh', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'root@134.209.182.8', 'chown www-data:www-data /var/www/stock_flow/templates/search* /var/www/stock_flow/search* && systemctl restart stock_flow'], capture_output=True, text=True)
print("SSH Restart returncode:", ssh_res.returncode)
print("SSH Restart stdout:", ssh_res.stdout)
print("SSH Restart stderr:", ssh_res.stderr)

print("DEPLOYMENT COMPLETE!")
