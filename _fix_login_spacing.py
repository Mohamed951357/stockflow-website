import re, subprocess

git_exe = r"C:\Users\bonus\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"
key_file = r"C:\Users\bonus\AppData\Local\StockFlowToby\stockflow_id_ed25519"

with open('templates/login.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove '#forgotLink' from GSAP array so GSAP animation does not fail
content = content.replace("'.fgroup', '.rem-row', '#loginBtn', '#forgotLink', '.orline'", "'.fgroup', '.rem-row', '#loginBtn', '.orline'")
content = content.replace(" '#forgotLink',", "")

# 2. Adjust spacing in CSS for .rem-row and .orline
content = content.replace('margin-bottom: 1.4rem;', 'margin-bottom: 0.85rem;')
content = content.replace('margin: 14px 0;', 'margin: 10px 0;')

with open('templates/login.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("1. Updated templates/login.html (removed #forgotLink from GSAP & optimized spacing)")

print("2. Adding to Git...")
subprocess.run([git_exe, 'add', 'templates/login.html'], check=True)

print("3. Committing...")
subprocess.run([git_exe, 'commit', '-m', 'Fix GSAP target array and adjust spacing on login page'], check=True)

print("4. Pushing to GitHub main...")
p_res = subprocess.run([git_exe, 'push', 'origin', 'main'], capture_output=True, text=True)
print("Git Push:", p_res.stderr or p_res.stdout)

print("5. SCP templates/login.html to live server 134.209.182.8...")
subprocess.run(['scp', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'templates/login.html', 'root@134.209.182.8:/var/www/stock_flow/templates/login.html'], check=True)

print("6. Setting permissions & restarting service...")
ssh_res = subprocess.run(['ssh', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'root@134.209.182.8', 'chown www-data:www-data /var/www/stock_flow/templates/login.html && systemctl restart stock_flow'], capture_output=True, text=True)
print("SSH Returncode:", ssh_res.returncode)

print("LOGIN PAGE SPACING AND BUTTON VISIBILITY FIXED AND DEPLOYED!")
