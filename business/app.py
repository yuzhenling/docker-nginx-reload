from http.server import BaseHTTPRequestHandler, HTTPServer
import os


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/hello"):
            body = b'{"message":"hello from business"}\n'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, fmt, *args):
        print(f"[business] {self.address_string()} {fmt % args}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"[business] listening on :{port}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
