import re

with open('tools/local_judge.py', encoding='utf-8') as f:
    content = f.read()

# Find and replace the mangled line 130
old_pat = r"    _section\(\\\"2\. CONTEXT PUSH\\\"\)\\n    _push_all_contexts.*?merchants loaded\"\)"
new_text = """    _section("2. CONTEXT PUSH")
    _push_all_contexts(version_offset=0)

    data, _ = _req("GET", "/v1/healthz")
    counts = data.get("contexts_loaded", {})
    _check(counts.get("category", 0) == 5, f"5 categories loaded ({counts.get('category')})")
    _check(counts.get("merchant", 0) == len(merchants), f"{len(merchants)} merchants loaded")"""

fixed = re.sub(old_pat, new_text, content, flags=re.DOTALL)
if fixed == content:
    # Try simpler approach - find the bad line by splitting
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if '_section(\\"2.' in line or '_push_all_contexts' in line and '\\n' in line:
            print(f"Found bad line {i+1}: {line[:80]}")
    print("Pattern not matched, checking manually...")
    # Print lines around 130
    for i in range(128, 138):
        print(f"  {i+1}: {lines[i][:100]}")
else:
    with open('tools/local_judge.py', 'w', encoding='utf-8') as f:
        f.write(fixed)
    print("Fixed successfully")
    # Verify
    lines = fixed.split('\n')
    for i in range(128, 140):
        print(f"  {i+1}: {lines[i][:100]}")
