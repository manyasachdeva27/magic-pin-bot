import os
import urllib.request
import json

url = 'https://api.groq.com/openai/v1/models'
_key = os.environ.get("LLM_API_KEY", "")
try:
    r = urllib.request.Request(url, headers={
        'Authorization': f'Bearer {_key}',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    resp = urllib.request.urlopen(r)
    data = json.loads(resp.read().decode())
    print([m['id'] for m in data['data']])
except Exception as e:
    print(e)
