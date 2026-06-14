import os
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse

CLIENT_ID = os.environ["TS_CLIENT_ID"]
CLIENT_SECRET = os.environ["TS_CLIENT_SECRET"]
REDIRECT_URI = "http://localhost:8000"

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = urllib.parse.urlparse(self.path).query
        code = urllib.parse.parse_qs(qs).get("code", [None])[0]

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK - AUTH RECEIVED")

        if not code:
            print("NO CODE RECEIVED")
            return

        print("\nAUTH CODE RECEIVED:", code)

        r = requests.post(
            "https://signin.tradestation.com/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI
            },
            timeout=10
        ).json()

        print("\nTOKEN RESPONSE:\n", r)

        if "access_token" in r:
            print("\nREADY FOR TRADING")

HTTPServer(("localhost", 8000), Handler).serve_forever()
