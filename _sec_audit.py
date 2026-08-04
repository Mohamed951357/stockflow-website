import re, io, sys
content = open('api_mobile.py', encoding='utf-8').read()
lines = content.split('\n')
out = []
for i, l in enumerate(lines):
    if '@api_mobile_bp.route' in l:
        prot = any(('@login_required' in lines[j] or 'require_' in lines[j] or 'verify_session' in lines[j] or '_permission' in lines[j]) for j in range(i, min(i+6, len(lines))))
        out.append((i+1, prot, l.strip()))
unp = [(ln, txt) for ln, p, txt in out if not p]
with open('_sec_tmp.txt', 'w', encoding='utf-8') as f:
    f.write('TOTAL ROUTES: %d\n' % len(out))
    f.write('UNPROTECTED: %d\n' % len(unp))
    f.write('=====\n')
    for ln, txt in unp:
        f.write('L%d: %s\n' % (ln, txt))
print('done')
