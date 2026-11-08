"""Minimal synthetic OIDC IdP server: discovery + JWKS + token endpoint.
Uses the project's own tests/sso_fake_idp.py signing fixture (never used by the app itself).
Serves on 127.0.0.1:9099. Each /token POST looks up the `code` in CODES (set by the test
script before driving the callback) and returns the exact id_token prepared for that code,
so each test case can fully control the token's claims/signature/alg.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, "/mnt/files/projects/builder-backend")
sys.path.insert(0, "/mnt/files/projects/builder-backend/tests")
from sso_fake_idp import discovery_document, jwks, idp_keys  # noqa: E402

PORT = 9099
ISSUER = f"http://127.0.0.1:{PORT}"

CODES: dict[str, str] = {}  # code -> id_token (set by the driving test script)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/.well-known/openid-configuration":
            doc = discovery_document()
            doc["issuer"] = ISSUER
            doc["authorization_endpoint"] = ISSUER + "/authorize"
            doc["token_endpoint"] = ISSUER + "/token"
            doc["jwks_uri"] = ISSUER + "/jwks"
            self._json(doc)
        elif self.path == "/jwks":
            self._json(jwks())
        else:
            self._json({"error": "not_found"}, 404)

    def do_POST(self):
        if self.path == "/token":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode()
            form = dict(p.split("=", 1) for p in raw.split("&") if "=" in p)
            import urllib.parse as up

            code = up.unquote(form.get("code", ""))
            id_token = CODES.get(code)
            if id_token is None:
                self._json({"error": "invalid_grant"}, 400)
                return
            self._json(
                {
                    "access_token": "fake-access-token",
                    "token_type": "Bearer",
                    "id_token": id_token,
                }
            )
        else:
            self._json({"error": "not_found"}, 404)


def run():
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    srv = run()
    print(f"fake OIDC IdP on {ISSUER}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
