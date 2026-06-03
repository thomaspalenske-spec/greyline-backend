from pathlib import Path
from urllib.parse import urlparse, parse_qs
from dotenv import set_key

url = input("Paste full localhost redirect URL here: ").strip()
code = parse_qs(urlparse(url).query).get("code", [""])[0]

if not code:
    raise SystemExit("No code found in URL.")

set_key(".env", "TRADESTATION_AUTH_CODE", code)
print("TRADESTATION_AUTH_CODE saved.")
