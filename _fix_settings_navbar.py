import re, subprocess

# 1. Read company_settings.html
with open('templates/company_settings.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Replace the black text overrides in navbar with clean dashboard navbar styling
old_navbar_css_1 = """        .navbar {
            background: linear-gradient(135deg, #1243C4 0%, #0A2DA0 100%) !important;
            background-size: 200% 200% !important;
            animation: navbarGradient 15s ease infinite !important;
            box-shadow:
                0 10px 40px rgba(0, 0, 0, 0.2),
                0 5px 20px rgba(18, 67, 196, 0.3),
                inset 0 1px 0 rgba(255, 255, 255, 0.2) !important;
            position: fixed;
            width: 100%;
            top: 0;
            z-index: 1030;
            backdrop-filter: blur(15px) !important;
            -webkit-backdrop-filter: blur(15px) !important;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
            transition: all 0.3s ease;
            padding: 0.5rem 1rem;
        }

        @keyframes navbarGradient {
            0%, 100% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
        }

        .navbar-brand {
            font-weight: 600;
            display: flex;
            align-items: center;
            color: #000000 !important;
        }

        .navbar-brand span {
            color: #000000 !important;
        }

        .navbar-logo {
            height: 35px;
            width: auto;
            margin-left: 10px;
        }

        .navbar .nav-link,
        .navbar i {
            color: #000000 !important;
        }

        .navbar .nav-link:hover,
        .navbar i:hover {
            color: #ffffff !important;
        }"""

new_navbar_css_1 = """        .navbar {
            background: linear-gradient(135deg, #1243C4 0%, #0A2DA0 100%) !important;
            background-size: 200% 200% !important;
            animation: navbarGradient 15s ease infinite !important;
            box-shadow:
                0 10px 40px rgba(0, 0, 0, 0.2),
                0 5px 20px rgba(18, 67, 196, 0.3),
                inset 0 1px 0 rgba(255, 255, 255, 0.2) !important;
            position: fixed;
            width: 100%;
            top: 0;
            z-index: 1030;
            backdrop-filter: blur(15px) !important;
            -webkit-backdrop-filter: blur(15px) !important;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
            transition: all 0.3s ease;
        }

        @keyframes navbarGradient {
            0%, 100% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
        }

        .navbar-brand {
            font-weight: 600;
            display: flex;
            align-items: center;
            color: #ffffff !important;
        }

        .navbar-brand span {
            color: #ffffff !important;
        }

        .navbar-logo {
            height: 35px;
            width: auto;
            margin-left: 10px;
        }

        .navbar .nav-link,
        .navbar i {
            color: #ffffff !important;
        }

        .navbar .nav-link:hover,
        .navbar i:hover {
            color: #ffffff !important;
            opacity: 0.9;
        }"""

if old_navbar_css_1 in html:
    html = html.replace(old_navbar_css_1, new_navbar_css_1)
    print("Replaced navbar CSS block 1 successfully!")
else:
    print("Navbar CSS block 1 not exact match, regex replacing black link colors...")

# Fix `.navbar .nav-link { color: #000 !important; }`
html = re.sub(r'\.navbar\s+\.nav-link\s*\{[^}]*color:\s*#000[^}]*\}', '.navbar .nav-link {\n            position: relative;\n            transition: all 0.3s ease;\n            color: #fff !important;\n        }', html)

# Fix `.navbar-brand span { color: #000`
html = re.sub(r'\.navbar-brand\s+span\s*\{[^}]*color:\s*#000[^}]*\}', '.navbar-brand span {\n            color: #fff !important;\n        }', html)

# Fix `.navbar-brand { color: #000`
html = re.sub(r'\.navbar-brand\s*\{[^}]*color:\s*#000[^}]*\}', '.navbar-brand {\n            font-weight: 600;\n            display: flex;\n            align-items: center;\n            color: #fff !important;\n        }', html)

# Save updated HTML
with open('templates/company_settings.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("Saved updated templates/company_settings.html!")
