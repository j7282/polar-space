import os
import http.server
import socketserver

PORT = int(os.environ.get("PORT", 5050))

Handler = http.server.SimpleHTTPRequestHandler

with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
    print("arrancando en puerto", PORT)
    httpd.serve_forever()
