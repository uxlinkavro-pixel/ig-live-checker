import http.server
import socketserver
import json
import urllib.parse
import os
import sys
import threading
import time
import re
import html
import random
import webbrowser
import queue

try:
    import requests
except ImportError:
    print("Error: 'requests' package is not installed. Please run: pip install requests")
    sys.exit(1)

PORT = int(os.environ.get("PORT", 5000))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# User Agents that cause Instagram to return OpenGraph profile meta-data
CRAWLER_USER_AGENTS = [
    'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)',
    'facebookexternalhit/1.1',
    'Twitterbot/1.0',
    'WhatsApp/2.21.12.21 A',
    'TelegramBot (like TwitterBot)'
]

class CheckerState:
    def __init__(self):
        self.lock = threading.RLock()
        self.is_running = False
        self.stop_requested = threading.Event()
        self.total = 0
        self.checked = 0
        self.live_list = []      # list of dicts: {"username": str, "name": str, "info": str, "original": str}
        self.dead_list = []      # list of dicts: {"username": str, "original": str, "reason": str}
        self.error_list = []     # list of dicts: {"username": str, "original": str, "reason": str}
        self.logs = []           # recent log messages
        self.start_time = None
        self.end_time = None
        self.active_workers = 0

    def reset(self):
        with self.lock:
            self.is_running = False
            self.stop_requested.clear()
            self.total = 0
            self.checked = 0
            self.live_list.clear()
            self.dead_list.clear()
            self.error_list.clear()
            self.logs.clear()
            self.start_time = None
            self.end_time = None
            self.active_workers = 0

    def add_log(self, status, username, detail=""):
        with self.lock:
            ts = time.strftime("%H:%M:%S")
            msg = {"time": ts, "status": status, "username": username, "detail": detail}
            self.logs.append(msg)
            if len(self.logs) > 300:
                self.logs.pop(0)

state = CheckerState()

def parse_account_line(line):
    """
    Extracts clean username from various formats:
    - username
    - username:password
    - username:password:email:pass
    - username|password
    - https://www.instagram.com/username/
    - @username
    """
    line = line.strip()
    if not line:
        return None, None
    
    original = line
    
    # If URL
    if "instagram.com" in line:
        match = re.search(r'instagram\.com/([a-zA-Z0-9_\.]+)', line)
        if match:
            username = match.group(1).strip()
            return username, original
            
    # If separated by delimiter (: or | or , or tab)
    for delim in [':', '|', ',', '\t']:
        if delim in line:
            parts = line.split(delim)
            username = parts[0].strip()
            if username.startswith('@'):
                username = username[1:]
            return username, original
            
    # Standalone username
    username = line.strip()
    if username.startswith('@'):
        username = username[1:]
    username = username.split('?')[0].split('/')[0].strip()
    
    return username, original

def format_proxy(proxy_str):
    """Supports ip:port, ip:port:user:pass, http://..., socks5://..."""
    if not proxy_str:
        return None
    proxy_str = proxy_str.strip()
    if not proxy_str:
        return None
    
    if "://" not in proxy_str:
        parts = proxy_str.split(":")
        if len(parts) == 2:
            proxy_url = f"http://{parts[0]}:{parts[1]}"
        elif len(parts) == 4:
            # ip:port:user:pass
            proxy_url = f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
        else:
            proxy_url = f"http://{proxy_str}"
    else:
        proxy_url = proxy_str
        
    return {
        "http": proxy_url,
        "https": proxy_url
    }

def check_instagram_username(username, session=None, proxy=None, timeout=6):
    """
    Checks if an Instagram username is Live, Dead, or Rate Limited.
    Returns: (status, info_dict)
    status: 'LIVE' | 'DEAD' | 'RATE_LIMITED' | 'ERROR'
    """
    clean_user = username.strip().lower()
    url = f"https://www.instagram.com/{clean_user}/"
    ua = random.choice(CRAWLER_USER_AGENTS)
    headers = {
        'User-Agent': ua,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    
    client = session if session is not None else requests
    
    try:
        resp = client.get(
            url,
            headers=headers,
            proxies=proxy,
            timeout=timeout,
            allow_redirects=True
        )
    except requests.exceptions.ProxyError:
        return 'ERROR', {'reason': 'Proxy Connection Failed'}
    except requests.exceptions.Timeout:
        return 'ERROR', {'reason': 'Request Timeout'}
    except Exception as e:
        return 'ERROR', {'reason': f'Network Error: {str(e)[:40]}'}

    # 1. Check Rate Limit / Captcha / Redirect to login
    if resp.status_code == 429:
        return 'RATE_LIMITED', {'reason': 'HTTP 429 Too Many Requests'}
    
    if 'accounts/login' in resp.url or 'challenge' in resp.url:
        return 'RATE_LIMITED', {'reason': 'Redirected to Login/Challenge (IP Flagged)'}

    # 2. Check 404
    if resp.status_code == 404:
        return 'DEAD', {'reason': '404 Not Found (Banned/Deleted)'}

    # 3. Extract Titles and OG Meta Tags
    text = resp.text
    titles = re.findall(r'<title>(.*?)</title>', text)
    title = html.unescape(titles[0]).strip() if titles else ""
    
    og_titles = re.findall(r'property="og:title" content="(.*?)"', text)
    og_title = html.unescape(og_titles[0]).strip() if og_titles else ""

    og_descs = re.findall(r'property="og:description" content="(.*?)"', text)
    og_desc = html.unescape(og_descs[0]).strip() if og_descs else ""

    # Check for Dead Indicators
    dead_phrases = [
        "sorry, this page isn't available",
        "the link you followed may be broken",
        "page not found"
    ]
    if any(phrase in text.lower() for phrase in dead_phrases):
        return 'DEAD', {'reason': 'Page Not Available (Deactivated/Suspended)'}

    # Check for Live Indicators
    user_handle = f"@{clean_user}"
    user_parentheses = f"({clean_user})"
    
    title_lower = title.lower()
    og_title_lower = og_title.lower()
    
    is_live = (
        user_handle in title_lower or 
        user_parentheses in title_lower or 
        user_handle in og_title_lower or 
        user_parentheses in og_title_lower
    )

    if is_live:
        name = ""
        if " • " in title:
            first_part = title.split(" • ")[0]
            name = re.sub(r'\(@[a-zA-Z0-9_\.]+\)', '', first_part).strip()
        elif " • " in og_title:
            first_part = og_title.split(" • ")[0]
            name = re.sub(r'\(@[a-zA-Z0-9_\.]+\)', '', first_part).strip()
            
        info = og_desc[:120] if og_desc else "Active Account"
        return 'LIVE', {'name': name, 'info': info}

    # If title is just generic "Instagram" with no user info and 200 OK -> Dead / Removed
    if title == "Instagram" and not og_title:
        return 'DEAD', {'reason': 'Account Removed or Not Found'}

    return 'DEAD', {'reason': 'Inactive / Not Accessible'}

def worker_thread(item_queue, proxies, proxy_lock, proxy_index_ref, delay):
    session = requests.Session()
    
    def get_proxy():
        if not proxies:
            return None
        with proxy_lock:
            p = proxies[proxy_index_ref[0] % len(proxies)]
            proxy_index_ref[0] += 1
            return p

    try:
        while not state.stop_requested.is_set():
            try:
                item = item_queue.get_nowait()
            except queue.Empty:
                break

            username, original = item
            try:
                p_dict = get_proxy()
                status, details = check_instagram_username(username, session=session, proxy=p_dict)
                
                if delay > 0:
                    time.sleep(delay)
                    
                with state.lock:
                    state.checked += 1
                    if status == 'LIVE':
                        state.live_list.append({
                            "username": username,
                            "name": details.get("name", ""),
                            "info": details.get("info", ""),
                            "original": original
                        })
                        state.add_log("LIVE", username, details.get("name", ""))
                    elif status == 'DEAD':
                        state.dead_list.append({
                            "username": username,
                            "original": original,
                            "reason": details.get("reason", "Dead")
                        })
                        state.add_log("DEAD", username, details.get("reason", ""))
                    elif status == 'RATE_LIMITED':
                        state.error_list.append({
                            "username": username,
                            "original": original,
                            "reason": details.get("reason", "Rate limited")
                        })
                        state.add_log("LIMITED", username, "Rate limited / Checkpoint")
                    else:
                        state.error_list.append({
                            "username": username,
                            "original": original,
                            "reason": details.get("reason", "Error")
                        })
                        state.add_log("ERROR", username, details.get("reason", ""))
            except Exception as e:
                with state.lock:
                    state.checked += 1
                    state.error_list.append({
                        "username": username,
                        "original": original,
                        "reason": f"Worker Exception: {str(e)[:40]}"
                    })
                    state.add_log("ERROR", username, str(e)[:40])
            finally:
                item_queue.task_done()
    finally:
        with state.lock:
            state.active_workers = max(0, state.active_workers - 1)
            if state.active_workers == 0:
                state.is_running = False
                state.end_time = time.time()

def start_queue_checker(items, proxies, delay, worker_count):
    state.start_time = time.time()
    
    item_queue = queue.Queue()
    for itm in items:
        item_queue.put(itm)
        
    proxy_lock = threading.Lock()
    proxy_index_ref = [0]
    
    # UNLIMITED THREADS: Scales dynamically
    thread_count = max(1, worker_count)
    if len(items) < thread_count:
        thread_count = len(items)
        
    state.active_workers = thread_count
    
    for _ in range(thread_count):
        t = threading.Thread(
            target=worker_thread,
            args=(item_queue, proxies, proxy_lock, proxy_index_ref, delay),
            daemon=True
        )
        t.start()

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class RequestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            file_path = os.path.join(STATIC_DIR, "index.html")
            self.serve_file(file_path, "text/html")
        elif path.startswith("/static/"):
            rel_path = path[len("/static/"):]
            file_path = os.path.join(STATIC_DIR, rel_path)
            content_type = "text/plain"
            if file_path.endswith(".css"):
                content_type = "text/css"
            elif file_path.endswith(".js"):
                content_type = "application/javascript"
            elif file_path.endswith(".svg"):
                content_type = "image/svg+xml"
            elif file_path.endswith(".png"):
                content_type = "image/png"
            self.serve_file(file_path, content_type)
        elif path == "/api/status":
            with state.lock:
                elapsed = 0
                if state.start_time:
                    end = state.end_time or time.time()
                    elapsed = round(end - state.start_time, 1)
                
                speed = 0
                if elapsed > 0 and state.checked > 0:
                    speed = round(state.checked / elapsed, 1)

                # Return recent 150 items to keep payload snappy even with 100k+ accounts
                data = {
                    "is_running": state.is_running,
                    "total": state.total,
                    "checked": state.checked,
                    "live_count": len(state.live_list),
                    "dead_count": len(state.dead_list),
                    "error_count": len(state.error_list),
                    "active_workers": state.active_workers,
                    "speed": speed,
                    "elapsed": elapsed,
                    "live_list_recent": state.live_list[-150:],
                    "dead_list_recent": state.dead_list[-150:],
                    "logs": state.logs[-40:]
                }
            self.send_json(data)
        elif path == "/api/export/live":
            with state.lock:
                content = "\n".join([x.get("original") or x.get("username") for x in state.live_list])
            self.send_text_download(content, "instagram_live_accounts.txt")
        elif path == "/api/export/dead":
            with state.lock:
                content = "\n".join([x.get("original") or x.get("username") for x in state.dead_list])
            self.send_text_download(content, "instagram_dead_accounts.txt")
        elif path == "/api/export/errors":
            with state.lock:
                content = "\n".join([f"{x.get('original') or x.get('username')} | {x.get('reason', 'Error')}" for x in state.error_list])
            self.send_text_download(content, "instagram_error_accounts.txt")
        else:
            self.send_error(404, "Not Found")

    def send_text_download(self, text, filename):
        body = text.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        try:
            req_data = json.loads(body.decode('utf-8')) if body else {}
        except Exception:
            req_data = {}

        if path == "/api/start":
            if state.is_running:
                self.send_json({"error": "Already running"}, status=400)
                return

            raw_accounts = req_data.get("accounts", "")
            lines = [line.strip() for line in raw_accounts.splitlines() if line.strip()]
            
            # Parse accounts efficiently
            parsed_items = []
            seen = set()
            for line in lines:
                u, orig = parse_account_line(line)
                if u and u.lower() not in seen:
                    seen.add(u.lower())
                    parsed_items.append((u, orig))

            if not parsed_items:
                self.send_json({"error": "No valid accounts provided"}, status=400)
                return

            # UNLIMITED THREADS: User can choose 10, 50, 100, 500, or any number!
            raw_threads = req_data.get("threads", 50)
            try:
                threads = max(1, int(raw_threads))
            except (ValueError, TypeError):
                threads = 50
                
            delay = max(0.0, float(req_data.get("delay", 0.05)))
            
            # Parse proxies
            raw_proxies = req_data.get("proxies", "")
            proxy_list = []
            for p_line in raw_proxies.splitlines():
                formatted = format_proxy(p_line)
                if formatted:
                    proxy_list.append(formatted)

            state.reset()
            state.total = len(parsed_items)
            state.is_running = True

            threading.Thread(
                target=start_queue_checker,
                args=(parsed_items, proxy_list, delay, threads),
                daemon=True
            ).start()

            self.send_json({"status": "started", "total": len(parsed_items), "threads": threads})

        elif path == "/api/stop":
            state.stop_requested.set()
            with state.lock:
                state.is_running = False
            self.send_json({"status": "stopped"})

        elif path == "/api/clear":
            state.reset()
            self.send_json({"status": "cleared"})

        else:
            self.send_error(404, "Not Found")

    def serve_file(self, file_path, content_type):
        if not os.path.exists(file_path):
            self.send_error(404, "File Not Found")
            return
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', f"{content_type}; charset=utf-8")
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Error reading file: {e}")

def run_server():
    port = PORT
    httpd = None
    for p in range(PORT, PORT + 20):
        try:
            server_address = ('0.0.0.0', p)
            httpd = ThreadedHTTPServer(server_address, RequestHandler)
            port = p
            break
        except OSError:
            continue
            
    if not httpd:
        print("[ERROR] Could not bind to any port from 5000 to 5020.")
        sys.exit(1)

    url = f"http://127.0.0.1:{port}"
    print(f"\n=======================================================")
    print(f"🚀 Instagram Live Checker (Unlimited Edition) started!")
    print(f"🌐 Local Access URL: {url}")
    print(f"⚡ Press Ctrl+C in this console to stop the server.")
    print(f"=======================================================\n")
    
    # Auto open browser only on local Windows desktop
    if "PORT" not in os.environ and sys.platform == "win32":
        try:
            threading.Timer(1.2, lambda: webbrowser.open(url)).start()
        except Exception:
            pass
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.shutdown()

if __name__ == '__main__':
    run_server()
