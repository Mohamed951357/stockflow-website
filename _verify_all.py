import glob, re

for fpath in glob.glob('templates/*.html') + glob.glob('*.html'):
    with open(fpath, encoding='utf-8', errors='ignore') as f:
        c = f.read()
    if '&#x627;&#x644;&#x62a;&#x639;&#x644;&#x64a;&#x645;&#x627;&#x62a;' in c:
        print(f"ENCODED INSTRUCTION STILL IN: {fpath}")
    if 'تسجيل الخروج' in c and '_company_navbar.html' in c:
        # Check if logout appears outside _company_navbar.html inclusion
        print(f"LOGOUT APPEARS IN: {fpath}")

print("Verification check done!")
