import os
import re
import glob

def append_z_to_isoformat(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Match .isoformat() that:
    # 1. Doesn't already have + 'Z' or + "Z" immediately after
    # 2. Is not inside an assignment unpacking maybe, but mostly we want to hit the dictionary creations
    new_content = re.sub(r'\.isoformat\(\)(?!\s*\+\s*[\'"]Z[\'"])', r".isoformat() + 'Z'", content)
    
    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {filepath}")

def fix_backend():
    files = [
        r'e:\الموقع\api_mobile.py',
        r'e:\الموقع\api_routes.py',
        r'e:\الموقع\views.py',
        r'e:\الموقع\community_bonus_routes.py',
        r'e:\الموقع\product_reminder_routes.py'
    ]
    for filepath in files:
        if os.path.exists(filepath):
            append_z_to_isoformat(filepath)

if __name__ == "__main__":
    fix_backend()
