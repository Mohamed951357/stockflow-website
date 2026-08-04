import re
from collections import defaultdict

src = 'views.py'
report = 'tools/commit_report.txt'

func_pattern = re.compile(r'^\s*def\s+(\w+)\s*\(')
commit_pattern = re.compile(r'db\.session\.commit\(')

current_func = '<module>'
counts = defaultdict(int)
lines_seen = []

with open(src, 'r', encoding='utf-8') as f:
    for i, line in enumerate(f, start=1):
        lines_seen.append((i, line.rstrip('\n')))
        m = func_pattern.match(line)
        if m:
            current_func = m.group(1)
        if commit_pattern.search(line):
            counts[current_func] += 1

# write report
with open(report, 'w', encoding='utf-8') as rf:
    rf.write('db.session.commit() occurrences per enclosing function:\n\n')
    for func, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        rf.write(f'{cnt:4d}  {func}\n')

print('Report written to', report)
