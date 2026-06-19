import urllib.request
import json

try:
    url = "http://127.0.0.1:8001/conversations"
    print("Connecting to", url)
    response = urllib.request.urlopen(url, timeout=5)
    data = json.loads(response.read().decode('utf-8'))
    print("API is running! Stored conversations count:", len(data.get("conversations", [])))
except Exception as e:
    print("API is not reachable:", e)
