import os

def replace_theme_colors(directory):
    # الألوان القديمة والجديدة
    replacements = {
        '#667eea': '#1243C4',
        '#764ba2': '#0A2DA0',
        '102, 126, 234': '18, 67, 196',
        '118, 75, 162': '10, 45, 160'
    }
    
    modified_files = []
    
    # البحث في المجلد الحالي وكل المجلدات الفرعية
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.html') or file.endswith('.css'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    original_content = content
                    for old, new in replacements.items():
                        content = content.replace(old, new)
                    
                    if content != original_content:
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(content)
                        modified_files.append(file_path)
                except Exception as e:
                    print(f"Error processing {file_path}: {e}")
                    
    return modified_files

if __name__ == '__main__':
    # تحديد المسار الحالي الذي يوجد فيه هذا الملف (السرفر)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"جاري تغيير الثيم في المجلد: {current_dir}")
    print("------------------------------------------")
    modified = replace_theme_colors(current_dir)
    print(f"\nتم بنجاح! عدد الملفات التي تم تعديلها: {len(modified)}")
    for m in modified:
        rel_path = os.path.relpath(m, current_dir)
        print(f"- {rel_path}")
