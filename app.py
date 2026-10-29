"""Local API gateway and static FE server. Run: python3 app.py (no Streamlit)."""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

BASE = Path(__file__).resolve().parent
DATA = BASE / 'data'
FE = BASE / 'FE'
PID = DATA / 'crawler_app.pid'
LOG = DATA / 'crawler_app.log'
PROCESS_LOCK = threading.Lock()
CACHE_LOCK = threading.Lock()
LINK_CACHE = {'signature': None, 'rows': []}
CHILDREN: list[subprocess.Popen] = []
SEARCH_URL = os.environ.get('SEARCH_URL', 'http://127.0.0.1:8080').rstrip('/')


def clean_url(value):
    value = str(value or '').strip()
    match = re.fullmatch(r'\[.*?\]\((https?://.*?)\)', value)
    return match.group(1) if match else value


def crawler_pid():
    # Reap only children owned by this gateway, and validate persisted PIDs before signalling.
    CHILDREN[:] = [child for child in CHILDREN if child.poll() is None]
    try:
        pid = int(PID.read_text().strip())
        if pid <= 1:
            return None
        result = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True, timeout=2)
        if result.returncode == 0 and 'crawler_hust.py' in result.stdout:
            return pid
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def load_links():
    path = DATA / 'links.csv'
    with CACHE_LOCK:
        if not path.exists():
            return []
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        if signature != LINK_CACHE['signature']:
            with path.open(encoding='utf-8-sig', newline='') as file:
                rows = list(csv.DictReader(file))
            for row in rows:
                row['url'] = clean_url(row.get('url'))
            LINK_CACHE.update(signature=signature, rows=rows)
        return LINK_CACHE['rows']


def snapshot():
    rows = load_links()
    report = {}
    try:
        report = json.loads((DATA / 'report.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass  # Crawler may be replacing report while the dashboard refreshes.
    decisions, statuses = {}, {}
    for row in rows:
        for key, target in [('decision', decisions), ('status_code', statuses)]:
            value = row.get(key) or 'Không rõ'
            target[value] = target.get(value, 0) + 1
    pid = crawler_pid()
    return {'running': pid is not None, 'pid': pid,
            'processed': report.get('processed_urls', len(rows)),
            'kept': report.get('kept', decisions.get('KEEP', 0)),
            'dropped': report.get('discarded', decisions.get('DROP', 0)),
            'pending': report.get('pending_urls', 0), 'updatedAt': report.get('updated_at', ''),
            'decisions': decisions, 'statuses': statuses,
            'types': sorted({row.get('type', '') for row in rows} - {''})}


def filtered_links(params):
    q = params.get('q', [''])[0].casefold().strip()
    decision = params.get('decision', [''])[0]
    kind = params.get('type', [''])[0]
    return [r for r in load_links() if (not decision or r.get('decision') == decision)
            and (not kind or r.get('type') == kind)
            and (not q or q in r.get('url', '').casefold() or q in r.get('title', '').casefold())]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FE), **kwargs)

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def send_data(self, status, data, content_type='application/json; charset=utf-8'):
        body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, (dict, list)) else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def proxy_search(self):
        try:
            req = Request(SEARCH_URL + self.path, method=self.command)
            with urlopen(req, timeout=300) as response:
                self.send_data(response.status, response.read())
        except HTTPError as exc:
            self.send_data(exc.code, exc.read())
        except (URLError, TimeoutError, OSError):
            self.send_data(502, {'error': 'Không kết nối được Java searcher. Hãy khởi chạy searcher trên cổng 8080.'})

    def do_GET(self):
        path = urlsplit(self.path).path
        params = parse_qs(urlsplit(self.path).query)
        try:
            if path in ('/api/search', '/api/index'):
                self.proxy_search()
            elif path == '/api/crawler/status':
                self.send_data(200, snapshot())
            elif path in ('/api/crawler/links', '/api/crawler/export'):
                rows = filtered_links(params)
                if path.endswith('/export'):
                    output = io.StringIO()
                    fields = ['url', 'status_code', 'type', 'title', 'decision', 'reason', 'downloaded_file']
                    writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
                    writer.writeheader()
                    # Prevent spreadsheet formula execution in exported untrusted web content.
                    writer.writerows({k: "'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v for k, v in r.items()} for r in rows)
                    self.send_data(200, ('\ufeff' + output.getvalue()).encode(), 'text/csv; charset=utf-8')
                else:
                    page = max(0, int(params.get('page', ['0'])[0]))
                    size = min(100, max(1, int(params.get('size', ['25'])[0])))
                    self.send_data(200, {'total': len(rows), 'page': page, 'size': size, 'rows': rows[page * size:(page + 1) * size]})
            elif path.startswith('/api/'):
                self.send_data(404, {'error': 'API không tồn tại.'})
            else:
                super().do_GET()
        except ValueError:
            self.send_data(400, {'error': 'Tham số không hợp lệ.'})
        except OSError:
            self.send_data(500, {'error': 'Không đọc được dữ liệu crawler.'})

    def do_POST(self):
        # Local control endpoints must not be triggered by pages from another origin.
        origin = self.headers.get('Origin')
        if self.headers.get('Sec-Fetch-Site') == 'cross-site' or (origin and origin != f'http://{self.headers.get("Host")}'):
            self.send_data(403, {'error': 'Cross-origin request rejected.'})
            return
        path = urlsplit(self.path).path
        if path == '/api/index/rebuild':
            self.proxy_search()
            return
        try:
            with PROCESS_LOCK:
                pid = crawler_pid()
                if path == '/api/crawler/start':
                    if pid:
                        self.send_data(409, {'error': 'Crawler đang chạy.'})
                        return
                    DATA.mkdir(exist_ok=True)
                    python = BASE / '.venv' / 'bin' / 'python'
                    with LOG.open('a', encoding='utf-8') as log:
                        process = subprocess.Popen([str(python) if python.exists() else sys.executable, '-u', str(BASE / 'crawler_hust.py')],
                                                   cwd=BASE, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                    CHILDREN.append(process)
                    PID.write_text(str(process.pid))
                    self.send_data(202, {'message': 'Đã khởi chạy crawler.', 'pid': process.pid})
                elif path == '/api/crawler/stop':
                    if pid:
                        # Crawler installs a SIGINT handler that writes its checkpoint.
                        os.kill(pid, signal.SIGINT)
                    self.send_data(202, {'message': 'Đã yêu cầu dừng an toàn; chờ crawler lưu tiến độ.' if pid else 'Crawler đã dừng.'})
                else:
                    self.send_data(404, {'error': 'API không tồn tại.'})
        except OSError as exc:
            self.send_data(500, {'error': f'Không điều khiển được crawler: {exc}'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='HUST FE + crawler API gateway')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'HUST FE: http://localhost:{args.port} (Java API: {SEARCH_URL})', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
