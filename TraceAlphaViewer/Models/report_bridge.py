"""Rapport local et navigation bornee vers sa vue source, sans appel Tk."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Queue, Full, Empty
import json
import mimetypes
import secrets
import threading
from urllib.parse import urlsplit, unquote


class ReportBridge:
    def __init__(self):
        self.commands = Queue(maxsize=32)
        self.closed = threading.Event()
        self.token = secrets.token_urlsafe(32)
        self.reports = {}
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, code, value):
                data = json.dumps(value, ensure_ascii=False).encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def route(self):
                parts = unquote(urlsplit(self.path).path).split('/')
                if (len(parts) < 4 or parts[1] != bridge.token or
                        self.headers.get('Host') != bridge.address or bridge.closed.is_set()):
                    return None, None
                return bridge.reports.get(parts[2]), '/'.join(parts[3:])

            def do_GET(self):
                report, route = self.route()
                if report is None:
                    self.reply(404, {'error': 'Rapport indisponible pour cette session.'})
                    return
                if route == 'status':
                    self.reply(200, {'connected': not bridge.closed.is_set()})
                    return
                if route == 'view.html':
                    path = report['path']
                elif route.startswith('_next/'):
                    root = (report['path'].parent / '_next').resolve()
                    path = (report['path'].parent / route).resolve()
                    if not path.is_relative_to(root):
                        self.reply(404, {'error': 'Ressource inconnue.'})
                        return
                else:
                    self.reply(404, {'error': 'Ressource inconnue.'})
                    return
                if not path.is_file():
                    self.reply(404, {'error': 'Ressource absente.'})
                    return
                data = path.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', mimetypes.guess_type(path)[0] or 'application/octet-stream')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_POST(self):
                report, route = self.route()
                if (report is None or route != 'navigate' or
                        self.headers.get('Origin') != 'http://' + bridge.address):
                    self.reply(403, {'error': 'Cette liaison ne correspond pas a la session courante.'})
                    return
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 2048:
                        raise ValueError()
                    request = json.loads(self.rfile.read(size))
                    if not isinstance(request, dict):
                        raise ValueError()
                    target = report['examples'][request['sample_id']]
                except (ValueError, KeyError, TypeError):
                    self.reply(400, {'error': 'Exemple inconnu.'})
                    return
                complete = threading.Event()
                result = {}
                try:
                    bridge.commands.put_nowait((target, complete, result))
                except Full:
                    self.reply(429, {'error': 'Le viewer traite deja plusieurs demandes.'})
                    return
                if not complete.wait(5):
                    result.update(error='Le viewer ne repond plus ; rouvrir le rapport depuis la bonne trace.')
                    complete.set()
                self.reply(200 if result.get('ok') else 409, result)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.address = f'127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def register(self, path):
        path = Path(path).resolve()
        data_path = path.with_name(path.name.replace('diagnostic_report_', 'report_data_')).with_suffix('.json')
        payload = json.loads(data_path.read_text(encoding='utf-8'))
        examples = {}
        for group in payload['groups']:
            for sample in group.get('examples', []):
                examples[sample['id']] = {'line': sample['line'], 'code': group['code'],
                                          'first_line': group['first_line']}
        if self.closed.is_set():
            raise RuntimeError('La vue source est fermee.')
        key = secrets.token_urlsafe(12)
        self.reports[key] = {'path': path, 'examples': examples}
        return f'http://{self.address}/{self.token}/{key}/view.html'

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        while True:
            try:
                _, complete, result = self.commands.get_nowait()
            except Empty:
                break
            result.update(error='La trace source est fermee ou remplacee.')
            complete.set()

        def shutdown():
            self.server.shutdown()
            self.server.server_close()
        threading.Thread(target=shutdown, daemon=True).start()
