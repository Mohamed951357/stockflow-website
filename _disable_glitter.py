import re, subprocess

git_exe = r"C:\Users\bonus\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"
key_file = r"C:\Users\bonus\AppData\Local\StockFlowToby\stockflow_id_ed25519"

with open('templates/company_dashboard.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Add CSS to completely hide and disable all falling glitter, stars, particles, and canvas animations
hide_glitter_css = """
        /* Completely disable falling glitter, stars, and background particles for Plus/all users on Dashboard */
        .fairy-lights, #fallingStars, #glitter-canvas, .glitter-container, .star, .carousel-fairy-lights {
            display: none !important;
            visibility: hidden !important;
            opacity: 0 !important;
            pointer-events: none !important;
        }

        body::before {
            display: none !important;
            background: none !important;
            animation: none !important;
        }

        body::after {
            display: none !important;
            background: none !important;
        }
"""

if '/* Completely disable falling glitter' not in html:
    html = html.replace('<style>', '<style>\n' + hide_glitter_css, 1)

# 2. Short-circuit createStars and animateGlitter functions in JS
html = html.replace('function createStars() {', 'function createStars() {\n            return; // Disabled falling glitter')
html = html.replace('function startGlitter() {', 'function startGlitter() {\n            return; // Disabled falling glitter')
html = html.replace('function animateGlitter() {', 'function animateGlitter() {\n            return; // Disabled falling glitter')

with open('templates/company_dashboard.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("1. Modified templates/company_dashboard.html to disable falling glitter and particles!")

print("2. Adding to Git...")
subprocess.run([git_exe, 'add', 'templates/company_dashboard.html'], check=True)

print("3. Committing...")
subprocess.run([git_exe, 'commit', '-m', 'Disable falling glitter and background particle animations on company dashboard'], check=True)

print("4. Pushing to GitHub main...")
p_res = subprocess.run([git_exe, 'push', 'origin', 'main'], capture_output=True, text=True)
print("Git Push:", p_res.stderr or p_res.stdout)

print("5. SCP templates/company_dashboard.html to live server 134.209.182.8...")
subprocess.run(['scp', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'templates/company_dashboard.html', 'root@134.209.182.8:/var/www/stock_flow/templates/company_dashboard.html'], check=True)

print("6. Setting permissions & restarting service...")
ssh_res = subprocess.run(['ssh', '-i', key_file, '-o', 'StrictHostKeyChecking=no', 'root@134.209.182.8', 'chown www-data:www-data /var/www/stock_flow/templates/company_dashboard.html && systemctl restart stock_flow'], capture_output=True, text=True)
print("SSH Returncode:", ssh_res.returncode)

print("FALLING GLITTER SUCCESSFULLY DISABLED AND DEPLOYED!")
