import os, re

fixed = []
for root, dirs, files in os.walk('templates'):
    for f in files:
        if f.endswith('.html'):
            p = os.path.join(root, f)
            with open(p, 'r', encoding='utf-8', errors='ignore') as fp:
                content = fp.read()
            # Fix: {% include \'something.html\' %} -> {% include 'something.html' %}
            new_content = re.sub(r"\{%-?\s*include\s+\\'([^']+)\\'\s*-?%\}", r"{{% include '\1' %}}", content)
            if new_content != content:
                with open(p, 'w', encoding='utf-8') as fp:
                    fp.write(new_content)
                fixed.append(p)
                print('FIXED:', p)

if not fixed:
    print('No broken include statements found.')
else:
    print(f'Fixed {len(fixed)} files.')
