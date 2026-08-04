import glob, re, subprocess

git_exe = r"C:\Users\bonus\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"
key_file = r"C:\Users\bonus\AppData\Local\StockFlowToby\stockflow_id_ed25519"

def set_icons_black(fpath):
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Set .navbar .nav-link color to black (#000000 !important)
    # Set .navbar i color to black (#000000 !important)
    # Set .navbar-brand color to black (#000000 !important)
    
    # 1. Replace top-level .navbar .nav-link color
    content = re.sub(
        r'(\.navbar\s+\.nav-link\s*\{[^}]*color:\s*)#[a-fA-F0-9]{3,6}(\s*!important;)',
        r'\1#000000\2',
        content
    )

    # 2. Add or ensure .navbar i { color: #000000 !important; }
    if '.navbar i {' in content:
        content = re.sub(
            r'(\.navbar\s+i\s*\{[^}]*color:\s*)[^;]+(;)',
            r'\1#000000 !important\2',
            content
        )
    else:
        content = content.replace(
            '.navbar .nav-link {',
            '.navbar .nav-link,\n        .navbar i,\n        .navbar-brand,\n        .navbar-brand span {\n            color: #000000 !important;\n        }\n\n        .navbar .nav-link {'
        )

    # 3. Ensure navbar brand span is black
    content = re.sub(
        r'(\.navbar-brand(?:\s+span)?\s*\{[^}]*color:\s*)#[a-fA-F0-9]{3,6}(\s*!important;)',
        r'\1#000000\2',
        content
    )

    # 4. Make sure mobile collapsed menu (.navbar-collapse .nav-link) stays white for readability
    if '.navbar-collapse .nav-link {' in content:
        content = re.sub(
            r'(\.navbar-collapse\s+\.nav-link\s*\{[^}]*color:\s*)[^;]+(;)',
            r'\1rgba(255, 255, 255, 0.95) !important\2',
            content
        )

    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Updated navbar icons to BLACK in {fpath}")

# Run on all key company templates
templates_to_update = [
    'templates/company_dashboard.html',
    'templates/company_settings.html',
    'templates/search_products.html',
    'templates/search.html',
    'search_products.html',
    'search.html'
]

for t in templates_to_update:
    set_icons_black(t)

print("1. Adding to Git...")
subprocess.run([git_exe, 'add'] + templates_to_update, check=True)

print("2. Committing...")
subprocess.run([git_exe, 'commit', '-m', 'Set navbar top bar icons and links to black across company pages'], check=True)

print("3. Pushing to GitHub...")
p_res = subprocess.run([git_exe, 'push', 'origin', 'main'], capture_output=True, text=True)
print("Git Push:", p_res.stderr or p_res.stdout)

print("4. Uploading via SCP to live server...")
for tfile in templates_to_update:
    remote_path = f'root@134.209.182.8:/var/www/stock_flow/{tfile}'
    subprocess.run(['scp', '-i', key_file, '-o', 'StrictHostKeyChecking=no', tfile, remote_path], check=True)

print("5. Setting permissions and restarting service on server...")
ssh_res = subprocess.run(['ssh', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'root@134.209.182.8', 'chown -R www-data:www-data /var/www/stock_flow/templates /var/www/stock_flow/search* && systemctl restart stock_flow'], capture_output=True, text=True)
print("SSH Returncode:", ssh_res.returncode)

print("BLACK ICONS SUCCESSFULLY DEPLOYED TO ALL COMPANY PAGES AND LIVE SERVER!")
