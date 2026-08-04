import subprocess

# 1. Read company_dashboard.html
with open('templates/company_dashboard.html', 'r', encoding='utf-8') as f:
    d_content = f.read()

# Extract navbar CSS block from company_dashboard.html (lines 682 to 925)
start_idx = d_content.find('.navbar {')
end_idx = d_content.find('.dashboard-content {', start_idx)

if start_idx == -1 or end_idx == -1:
    end_idx = d_content.find('.main-content {', start_idx)

navbar_css_block = d_content[start_idx:end_idx]

# 2. Read company_settings.html
with open('templates/company_settings.html', 'r', encoding='utf-8') as f:
    s_content = f.read()

# Find <style> in company_settings.html
s_start = s_content.find('.navbar {')
if s_start == -1:
    s_start = s_content.find('body {')

s_end = s_content.find('.settings-container {')

if s_start != -1 and s_end != -1:
    base_body = "        body {\n            font-family: 'Cairo', sans-serif;\n            background: linear-gradient(135deg, #1243C4 0%, #0A2DA0 100%);\n            min-height: 100vh;\n            padding-top: 70px;\n        }\n\n"
    new_s_content = s_content[:s_content.find('body {')] + base_body + navbar_css_block + "\n\n        " + s_content[s_end:]
    
    with open('templates/company_settings.html', 'w', encoding='utf-8') as f_out:
        f_out.write(new_s_content)
    print("Successfully copied original dashboard navbar CSS into company_settings.html!")
else:
    print("Could not find start/end positions in company_settings.html")
