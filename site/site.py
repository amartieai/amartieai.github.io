#!/usr/bin/env python3
"""
ORACLE BUSINESS — PUBLIC SITE (step 4 of the locked build).

Serves the customer-facing site with looping background video + corner
watermark stills, and proxies /api/* to the account (8723) and event
(8724) layers. Browser stays single-origin (no CORS). Localhost only.

The site sells the WINDOW. It carries NO engine internals, no direction,
no price targets, no track-record claims. The live turn-clock is the
public proof. We don't know what exactly. But we sure know fucking when.

Static files: /static/video/bg.mp4 (looping background), /static/img/* (watermark stills)
"""
import json, os, sys, urllib.request, urllib.error
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST, PORT = "127.0.0.1", 8725
BASE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(BASE, "index.html")
STATIC = os.path.join(BASE, "static")
UPSTREAM = {"account": "http://127.0.0.1:8723", "event": "http://127.0.0.1:8724"}

# MIME types
MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css",
    ".js": "application/javascript",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
}


def _req(service, path, method="GET", body=None):
    url = UPSTREAM[service] + path
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "Mozilla/5.0")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, payload, ctype="application/json"):
        b = payload if isinstance(payload, bytes) else payload.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path

        # Static files
        if path.startswith("/static/"):
            self._serve_static(path)
            return

        if path in ("/", "/index.html"):
            try:
                with open(INDEX, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(503, b"site not built")
            return
        if path == "/health":
            self._send(200, json.dumps({"ok": True, "service": "oracle-site",
                                        "port": PORT, "upstream": UPSTREAM}))
            return
        if path == "/api/verify":
            code, out = _req("account", "/verify?" + u.query)
            self._send(code, out); return
        if path == "/api/account":
            code, out = _req("account", "/account?" + u.query)
            self._send(code, out); return
        if u.path == "/api/verify-share":
            try:
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from canary_token import verify_click
                body = self._read_json()
                result = verify_click(body.get("token", ""), body.get("verifier", ""))
                self._send(200, json.dumps(result))
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}))
            return
        if u.path == "/api/share-link":
            try:
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from canary_token import get_share_link, get_sharing_stats
                body = self._read_json()
                email = body.get("email", "")
                link = get_share_link(email)
                stats = get_sharing_stats(email)
                self._send(200, json.dumps({"link": link, **stats}))
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}))
            return
        self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        u = urlparse(self.path)
        ln = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(ln) if ln else None
        if u.path == "/api/signup":
            code, out = _req("account", "/signup", "POST", body)
            self._send(code, out); return
        if u.path == "/api/event":
            code, out = _req("event", "/event", "POST", body)
            self._send(code, out); return
        if u.path == "/api/verify-share":
            try:
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from canary_token import verify_click
                body = self._read_json()
                result = verify_click(body.get("token", ""), body.get("verifier", ""))
                self._send(200, json.dumps(result))
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}))
            return
        if u.path == "/api/share-link":
            try:
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from canary_token import get_share_link, get_sharing_stats
                body = self._read_json()
                email = body.get("email", "")
                link = get_share_link(email)
                stats = get_sharing_stats(email)
                self._send(200, json.dumps({"link": link, **stats}))
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}))
            return
        self._send(404, json.dumps({"error": "not found"}))

    def _serve_static(self, path):
        """Serve files from the static/ directory."""
        rel = path[len("/static/"):]
        # Security: prevent path traversal
        if ".." in rel or rel.startswith("/"):
            self._send(403, b"forbidden")
            return
        full = os.path.join(STATIC, rel)
        if not os.path.isfile(full):
            self._send(404, b"not found")
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        try:
            with open(full, "rb") as f:
                data = f.read()
            self._send(200, data, ctype)
        except OSError:
            self._send(500, b"server error")


    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        return json.loads(self.rfile.read(length) or "{}")

if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()