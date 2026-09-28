import glob

for fname in glob.glob('tests/test_*.py') + glob.glob('tools/*.py'):
    with open(fname, encoding='utf-8') as f:
        content = f.read()
    fixed = content.replace('\u2192', '->').replace('\u2014', '--').replace('\u2018', "'").replace('\u2019', "'")
    if fixed != content:
        with open(fname, 'w', encoding='utf-8') as f:
            f.write(fixed)
        print(f"  Fixed: {fname}")
    else:
        print(f"  Clean: {fname}")
