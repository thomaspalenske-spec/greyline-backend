from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

class CallbackHandler(BaseHTTPRequestHandler):

    # shared storage for captured code
    auth_code = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            CallbackHandler.auth_code = params["code"][0]

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"TradeStation Auth Complete. You can close this window.")

        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing auth code")


def run_server(port=8000):
    server = HTTPServer(("localhost", port), CallbackHandler)
    print(f"OAuth callback running on http://localhost:{port}")
    server.handle_request()
    return CallbackHandler.auth_code
