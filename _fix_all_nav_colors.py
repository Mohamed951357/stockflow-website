import glob, re, subprocess

git_exe = r"C:\Users\bonus\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"
key_file = r"C:\Users\bonus\AppData\Local\StockFlowToby\stockflow_id_ed25519"

def fix_template(fpath):
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Replace `.navbar .nav-link { ... color: #000 !important; }` with `#fff !important`
    content = content.replace('color: #000 !important;', 'color: #ffffff !important;')
    content = content.replace('color: #000;', 'color: #ffffff;')
    content = content.replace('color: #000000 !important;', 'color: #ffffff !important;')
    content = content.replace('color: #000000;', 'color: #ffffff;')

    # Ensure .navbar-collapse .nav-link has white color with important
    content = content.replace(
        'color: rgba(255, 255, 255, 0.9);',
        'color: rgba(255, 255, 255, 0.95) !important;'
    )

    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Fixed navbar colors in {fpath}")

# Fix company_dashboard.html and company_settings.html
fix_template('templates/company_dashboard.html')
fix_template('templates/company_settings.html')
fix_template('templates/search_products.html')
fix_template('templates/search.html')

print("1. Adding to Git...")
subprocess.run([git_exe, 'add', 'templates/company_dashboard.html', 'templates/company_settings.html', 'templates/search_products.html', 'templates/search.html'], check=True)

print("2. Committing...")
subprocess.run([git_exe, 'commit', '-m', 'Fix navbar mobile dropdown text color to white across company templates'], check=True)

print("3. Pushing to GitHub...")
p_res = subprocess.run([git_exe, 'push', 'origin', 'main'], capture_output=True, text=True)
print("Git Push:", p_res.stderr or p_res.stdout)

print("4. Uploading via SCP to live server...")
for tfile in ['templates/company_dashboard.html', 'templates/company_settings.html', 'templates/search_products.html', 'templates/search.html']:
    subprocess.run(['scp', '-i', key_file, '-o', 'StrictHostKeyChecking=no', tfile, f'root@134.209.182.8:/var/www/stock_flow/{tfile}'], check=True)

print("5. Restarting stock_flow service on server...")
ssh_res = subprocess.run(['ssh', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'root@134.209.182.8', 'chown -R www-data:www-data /var/www/stock_flow/templates && systemctl restart stock_flow'], capture_output=True, text=True)
print("SSH Returncode:", ssh_res.returncode)

print("SUCCESSFULLY FIXED AND DEPLOYED ALL NAVBAR DROPDOWN COLORS!")
