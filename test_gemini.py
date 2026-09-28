import os
import urllib.request
import json

_key = os.environ.get("LLM_API_KEY", "")
url = f'https://generativelanguage.googleapis.com/v1beta/models?key={_key}'
try:
    r = urllib.request.Request(url)
    resp = urllib.request.urlopen(r)
    data = json.loads(resp.read().decode())
    for m in data['models']:
        if 'gemini-3' in m['name']:
            print(m['name'])
except Exception as e:
    print(e)
