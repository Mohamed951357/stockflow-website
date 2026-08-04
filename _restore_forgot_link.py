import re, subprocess

git_exe = r"C:\Users\bonus\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"
key_file = r"C:\Users\bonus\AppData\Local\StockFlowToby\stockflow_id_ed25519"

with open('templates/login.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Update CSS for .rem-row to space-between
html = html.replace('.rem-row { display: flex; align-items: center; gap: 8px; margin-bottom: 0.85rem; justify-content: flex-end; }', '.rem-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.85rem; }')
html = html.replace('.rem-row { display: flex; align-items: center; gap: 8px; margin-bottom: 1.4rem; justify-content: flex-end; }', '.rem-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.85rem; }')

# 2. Update HTML for REMEMBER & FORGOT row
old_rem_html = """            <!-- REMEMBER -->
            <div class="rem-row">
                <label class="rem-lbl" for="rem">تذكرني</label>
                <input class="rem-chk" id="rem" type="checkbox" checked>
            </div>"""

new_rem_html = """            <!-- REMEMBER & FORGOT -->
            <div class="rem-row">
                <a href="https://wa.me/201554077727?text=نسيت اسم المستخدم أو كلمة السر" target="_blank" class="forgot" id="forgotLink">هل نسيت كلمة المرور؟</a>
                <div style="display:flex; align-items:center; gap:8px;">
                    <label class="rem-lbl" for="rem">تذكرني</label>
                    <input class="rem-chk" id="rem" type="checkbox" checked>
                </div>
            </div>"""

if old_rem_html in html:
    html = html.replace(old_rem_html, new_rem_html)
else:
    # Regex fallback
    html = re.sub(
        r'<div class="rem-row">\s*<label class="rem-lbl" for="rem">تذكرني</label>\s*<input class="rem-chk" id="rem" type="checkbox" checked>\s*</div>',
        new_rem_html,
        html
    )

# 3. Add #forgotLink back to GSAP animation array
html = html.replace("'.fgroup', '.rem-row', '#loginBtn', '.orline'", "'.fgroup', '.rem-row', '#forgotLink', '#loginBtn', '.orline'")

with open('templates/login.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("1. Restored 'هل نسيت كلمة المرور؟' link neatly in the rem-row line in templates/login.html!")

print("2. Adding to Git...")
subprocess.run([git_exe, 'add', 'templates/login.html'], check=True)

print("3. Committing...")
subprocess.run([git_exe, 'commit', '-m', 'Place forgot password link nicely on the remember me row on login page'], check=True)

print("4. Pushing to GitHub main...")
p_res = subprocess.run([git_exe, 'push', 'origin', 'main'], capture_output=True, text=True)
print("Git Push:", p_res.stderr or p_res.stdout)

print("5. SCP templates/login.html to live server 134.209.182.8...")
subprocess.run(['scp', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'templates/login.html', 'root@134.209.182.8:/var/www/stock_flow/templates/login.html'], check=True)

print("6. Setting permissions & restarting service...")
ssh_res = subprocess.run(['ssh', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'root@134.209.182.8', 'chown www-data:www-data /var/www/stock_flow/templates/login.html && systemctl restart stock_flow'], capture_output=True, text=True)
print("SSH Returncode:", ssh_res.returncode)

print("LOGIN PAGE FORGOT PASSWORD LINK RESTORED & DEPLOYED SUCCESSFULLY!")
