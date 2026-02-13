import ast, os, sys
base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
errors = 0
checked = 0
for root, dirs, files in os.walk(base):
    dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', 'assets', 'tools')]
    for fn in files:
        if not fn.endswith('.py'):
            continue
        fp = os.path.join(root, fn)
        checked += 1
        try:
            ast.parse(open(fp, encoding='utf-8').read())
        except SyntaxError as e:
            errors += 1
            sys.stderr.write('SYNTAX ERROR: %s: %s\n' % (os.path.relpath(fp, base), e))
sys.stderr.write('Checked %d files, %d errors\n' % (checked, errors))
