import os, re

fixed = []
for root, dirs, files in os.walk('templates'):
    for f in files:
        if f.endswith('.html'):
            p = os.path.join(root, f)
            with open(p, 'r', encoding='utf-8', errors='ignore') as fp:
                content = fp.read()
            # Fix double braces: {{% -> {% and %}} -> %}
            new_content = content
            new_content = new_content.replace('{{% ', '{% ')
            new_content = new_content.replace(' %}}', ' %}')
            if new_content != content:
                with open(p, 'w', encoding='utf-8') as fp:
                    fp.write(new_content)
                fixed.append(p)
                print('FIXED:', p)

if not fixed:
    print('Nothing to fix.')
else:
    print('Fixed', len(fixed), 'files.')
