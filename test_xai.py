import os
import urllib.request
import json
import urllib.error

url = 'https://api.x.ai/v1/models'
_key = os.environ.get("LLM_API_KEY", "")
try:
    r = urllib.request.Request(url, headers={'Authorization': f'Bearer {_key}'})
    resp = urllib.request.urlopen(r)
    print("Success")
except urllib.error.HTTPError as e:
    print(f"Error {e.code}:")
    print(e.read().decode())
except Exception as e:
    print("Other error:", e)
