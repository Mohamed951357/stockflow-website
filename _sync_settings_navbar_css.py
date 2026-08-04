import re, subprocess

# 1. Read company_dashboard.html to get exact navbar CSS lines 564 to 828
with open('templates/company_dashboard.html', 'r', encoding='utf-8') as f:
    d_lines = f.readlines()

navbar_css_lines = d_lines[563:828] # 0-indexed: 563 to 828
navbar_css_text = "".join(navbar_css_lines)

# 2. Read company_settings.html
with open('templates/company_settings.html', 'r', encoding='utf-8') as f:
    s_html = f.read()

# Replace style block in company_settings.html
# Find the start of style in company_settings.html
style_tag_pos = s_html.find('<style>')
if style_tag_pos != -1:
    end_style_pos = s_html.find('.settings-container', style_tag_pos)
    if end_style_pos != -1:
        # Construct new style block
        new_style_header = "<style>\n        body {\n            font-family: 'Cairo', sans-serif;\n            background: linear-gradient(135deg, #1243C4 0%, #0A2DA0 100%);\n            min-height: 100vh;\n            padding-top: 70px;\n        }\n\n"
        new_s_html = s_html[:style_tag_pos] + new_style_header + navbar_css_text + "\n\n        " + s_html[end_style_pos:]
        
        # Remove secondary duplicate navbar overrides in company_settings.html below line 180
        sec_nav_pos = new_s_html.find('.navbar {', end_style_pos)
        if sec_nav_pos != -1:
            sec_end_pos = new_s_html.find('.settings-page-container', sec_nav_pos)
            if sec_end_pos != -1:
                # Remove duplicate .navbar block in settings shell CSS
                new_s_html = new_s_html[:sec_nav_pos] + new_s_html[sec_end_pos:]

        with open('templates/company_settings.html', 'w', encoding='utf-8') as f_out:
            f_out.write(new_s_html)
        print("Updated templates/company_settings.html with exact dashboard navbar CSS!")
    else:
        print("Could not find .settings-container position")
else:
    print("Could not find <style> tag position")

