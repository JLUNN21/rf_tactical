#!/usr/bin/env python3
"""Fix ALL non-ASCII characters in .py files that could break Windows cp1252 console."""
import os
import sys

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

replacements = {
    '\u2713': '[OK]',   # ✓
    '\u2714': '[OK]',   # ✔
    '\u2717': '[X]',    # ✗
    '\u2718': '[X]',    # ✘
    '\u274C': '[X]',    # ❌
    '\u26A1': '[!]',    # ⚡
    '\u2192': '->',     # →
    '\u2190': '<-',     # ←
    '\u2014': '--',     # —
    '\u2013': '-',      # –
    '\u2026': '...',    # …
    '\u2022': '*',      # •
}

fixed = 0
for root, dirs, files in os.walk(base):
    dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', 'assets', 'tools')]
    for fn in files:
        if not fn.endswith('.py'):
            continue
        fp = os.path.join(root, fn)
        with open(fp, 'r', encoding='utf-8') as f:
            content = f.read()
        orig = content
        for old, new in replacements.items():
            content = content.replace(old, new)
        if content != orig:
            with open(fp, 'w', encoding='utf-8') as f:
                f.write(content)
            fixed += 1
            sys.stderr.write('Fixed: %s\n' % os.path.relpath(fp, base))

sys.stderr.write('Total fixed: %d files\n' % fixed)
