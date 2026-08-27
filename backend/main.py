import requests

with open("sample.png", "rb") as f:
    r = requests.post("http://localhost:8001/extract-text", files={"file": f}, timeout=30)

print(r.status_code)
print(r.json())