import re

def clean_file(fpath):
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Pattern matches {% include '_company_navbar.html' %} followed by orphaned li items and closing nav
    pattern = re.compile(
        r"({% include '_company_navbar\.html' %})\s*<li class=\"nav-item\">\s*<a class=\"nav-link\" href=\"\{\{ url_for\('instructions'\) \}\}\">[\s\S]*?</nav>",
        re.MULTILINE
    )

    if pattern.search(content):
        new_content = pattern.sub(r"\1", content)
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Successfully cleaned orphaned nav code from {fpath}")
    else:
        print(f"No pattern match found in {fpath}")

clean_file('templates/search_products.html')
clean_file('search_products.html')
