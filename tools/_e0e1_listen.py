import http.server, socketserver, urllib.parse, os

LOG = r'C:/Users/AshenZhou/AppData/Local/Temp/e0e1_beacon.log'

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(urllib.parse.unquote(self.path) + '\n')
        body = b'ok'
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.end_headers()

    def log_message(self, *a):
        pass

if __name__ == '__main__':
    try:
        os.remove(LOG)
    except OSError:
        pass
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(('127.0.0.1', 9999), H) as httpd:
        httpd.serve_forever()
