"""Single-server face and maintenance dashboard. No GUI toolkit required."""
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from .core import BuddyCore

FACE = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Buddy</title><style>
*{box-sizing:border-box}body{margin:0;background:#121528;color:#f6f3ff;font-family:system-ui;min-height:100vh;display:grid;place-items:center}.face{width:min(90vw,600px);aspect-ratio:1.35;background:#222943;border-radius:28%;display:flex;align-items:center;justify-content:space-evenly;box-shadow:0 0 80px #6863d12c}.eye{width:25%;height:43%;background:#a8ecff;border-radius:48%;animation:blink 6s infinite;box-shadow:0 0 30px #9ae8ff77}@keyframes blink{0%,44%,48%,100%{transform:scaleY(1)}46%{transform:scaleY(.05)}}.label{position:fixed;bottom:15px;opacity:.5;font-size:13px}
</style></head><body><div class="face" aria-label="Buddy's face"><div class="eye"></div><div class="eye"></div></div><div class="label">Buddy • Day Zero 0.23.1</div></body></html>'''
DASH = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Buddy Dashboard</title><style>
body{background:#131728;color:#f4f3fc;font:16px system-ui;margin:0;padding:30px}main{max-width:620px;margin:auto}h1{margin-bottom:5px}p{color:#b7bdd3}.panel{background:#222941;border-radius:18px;padding:22px;margin:20px 0}label{display:block;margin:18px 0 7px}input{width:100%;padding:12px;border-radius:8px;border:1px solid #66708c;background:#101628;color:white;font:inherit}input[type=checkbox]{width:auto}button{background:#9586f9;color:#101022;border:0;padding:12px 18px;border-radius:10px;font:inherit;font-weight:700;cursor:pointer;margin:10px 8px 0 0}button.secondary{background:#505875;color:white}a{color:#b3dfff}#status{min-height:30px}#confirm{display:none;border:1px solid #9e92e9;border-radius:12px;padding:14px;margin-top:20px}
</style></head><body><main><h1>🤖 Buddy Dashboard</h1><p>Maintenance and configuration. The face remains separate.</p><p><a href="/face" target="_blank">Open Buddy's face ↗</a> · <a href="/chat">Talk to Buddy ↗</a></p><div class="panel"><h2>Settings</h2><label for="name">Name</label><input id="name" maxlength="40"><label for="volume">Volume (0–100)</label><input id="volume" type="number" min="0" max="100"><label for="rate">Speech rate (0.5–2.0)</label><input id="rate" type="number" min="0.5" max="2" step="0.1"><label><input id="voice" type="checkbox"> Voice enabled (configuration only)</label><button onclick="requestChange()">Review change</button><div id="confirm"><p id="question"></p><button onclick="resolve(true)">Confirm</button><button class="secondary" onclick="resolve(false)">Cancel</button></div><p id="status" role="status"></p></div><p>Day Zero: text conversation and fresh memory are connected. Audio and voice commands are not connected yet. These settings are saved for future modules.</p></main><script>
let original={},pending=null;const ids={name:'name',volume:'volume',speech_rate:'rate',voice_enabled:'voice'};
async function api(url,body){let r=await fetch(url,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});let j=await r.json();if(!r.ok)throw Error(j.error||'Request failed');return j}
async function load(){try{original=await api('/api/settings');for(let [key,id] of Object.entries(ids)){let el=document.getElementById(id);if(el.type==='checkbox')el.checked=original[key];else el.value=original[key]}}catch(e){status(e.message)}}
function status(s){document.getElementById('status').textContent=s}
async function requestChange(){let values={name:document.getElementById('name').value,volume:Number(document.getElementById('volume').value),speech_rate:Number(document.getElementById('rate').value),voice_enabled:document.getElementById('voice').checked};let changes=Object.keys(values).filter(k=>values[k]!==original[k]);if(!changes.length){status('Nothing to change.');return}if(changes.length>1){status('Change one setting at a time so each change can be confirmed.');return}let key=changes[0];try{let result=await api('/api/propose',{key,value:values[key]});pending=result.token;document.getElementById('question').textContent=`Change ${key.replaceAll('_',' ')} from ${original[key]} to ${values[key]}?`;document.getElementById('confirm').style.display='block';status('Waiting for confirmation.')}catch(e){status(e.message)}}
async function resolve(confirm){try{await api('/api/resolve',{token:pending,confirm});pending=null;document.getElementById('confirm').style.display='none';await load();status(confirm?'Setting saved.':'Change cancelled.')}catch(e){status(e.message)}}load();
</script></body></html>'''

CHAT = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Buddy — Day Zero</title><style>
*{box-sizing:border-box}body{margin:0;background:#111626;color:#f2f4ff;font:16px system-ui}main{max-width:820px;margin:0 auto;padding:20px;display:flex;flex-direction:column;height:100dvh}header{display:flex;justify-content:space-between;align-items:center;gap:12px}a{color:#b8d6ff}small{color:#a8b2ce}#log{flex:1;overflow:auto;margin:18px 0;padding:12px;background:#1c2338;border-radius:16px}article{margin:14px 0;padding:13px 16px;border-radius:16px;white-space:pre-wrap;overflow-wrap:anywhere;max-width:90%;line-height:1.5}article.user{background:#394a74;margin-left:auto}article.assistant{background:#2a304d;margin-right:auto}form{display:flex;gap:8px}textarea{flex:1;background:#242c43;border:1px solid #6e7b9b;border-radius:12px;color:white;padding:12px;font:inherit;resize:none;min-height:54px}button{background:#b2a0ff;border:0;border-radius:12px;padding:12px 18px;font-weight:700;cursor:pointer}button:disabled{opacity:.5}#status{min-height:22px;margin-top:7px;color:#c3c9d9;font-size:13px}
</style></head><body><main><header><div><h2 style="margin:0">🤖 <span id="name">Buddy</span></h2><small>Day Zero — a new beginning</small></div><nav><a href="/face" target="_blank">Face</a> · <a href="/dashboard">Dashboard</a></nav></header><div id="log" role="log" aria-live="polite"></div><form id="form"><textarea id="message" maxlength="4000" placeholder="Say hello to Buddy…" aria-label="Message"></textarea><button id="send" type="submit">Send</button></form><div id="status" role="status"></div></main><script>
const log=document.getElementById('log'),input=document.getElementById('message'),send=document.getElementById('send'),status=document.getElementById('status');
function add(role,content){const a=document.createElement('article');a.className=role;a.textContent=content;log.appendChild(a);log.scrollTop=log.scrollHeight}
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const j=await r.json();if(!r.ok)throw Error(j.error||'Request failed');return j}
async function init(){try{const [history,settings]=await Promise.all([api('/api/history'),api('/api/settings')]);document.getElementById('name').textContent=settings.name;history.messages.forEach(m=>add(m.role,m.content));if(!history.messages.length)add('assistant','…Hello?');}catch(e){status.textContent=e.message}};
document.getElementById('form').onsubmit=async e=>{e.preventDefault();const message=input.value.trim();if(!message)return;send.disabled=true;input.disabled=true;status.textContent='Buddy is thinking…';try{const r=await api('/api/chat',{message});add('user',message);add('assistant',r.reply);input.value='';status.textContent='';}catch(e){status.textContent=e.message}finally{send.disabled=false;input.disabled=false;input.focus()}};
input.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();document.getElementById('form').requestSubmit()}};init();
</script></body></html>'''


def make_handler(core, memory, brain, auth_token=None):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, data, content_type='application/json'):
            payload = data.encode('utf-8') if isinstance(data, str) else json.dumps(data).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self' 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(payload)

        def authorized(self):
            if auth_token is None:
                return True
            # Token supplied through HTTP Basic auth, password field; any username accepted.
            import base64
            header = self.headers.get('Authorization', '')
            try:
                if not header.startswith('Basic '):
                    return False
                value = base64.b64decode(header[6:], validate=True).decode('utf-8')
                return secrets.compare_digest(value.partition(':')[2], auth_token)
            except (ValueError, UnicodeDecodeError):
                return False

        def check_auth(self):
            if self.authorized():
                return True
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="Buddy Dashboard"')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return False

        def do_GET(self):
            if not self.check_auth(): return
            path = urlsplit(self.path).path
            if path in ('/', '/dashboard'):
                self.reply(200, DASH, 'text/html')
            elif path == '/chat':
                self.reply(200, CHAT, 'text/html')
            elif path == '/api/history':
                self.reply(200, {'messages': memory.recent(100), 'count': memory.count()})
            elif path == '/face':
                self.reply(200, FACE, 'text/html')
            elif path == '/api/settings':
                self.reply(200, core.snapshot())
            elif path == '/api/health':
                self.reply(200, {'status':'ok', 'version':'0.23.1-day-zero'})
            else:
                self.reply(404, {'error':'Not found'})

        def do_POST(self):
            if not self.check_auth(): return
            path = urlsplit(self.path).path
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 4096:
                    raise ValueError('Invalid request size')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('Expected an object')
                if path == '/api/chat':
                    message = data.get('message')
                    if not isinstance(message, str) or not 1 <= len(message.strip()) <= 4000:
                        raise ValueError('Message must be between 1 and 4000 characters')
                    # Serialize conversations so their history remains in order.
                    with core.lock:
                        answer = brain.reply(message)
                    self.reply(200, {'reply':answer})
                elif path == '/api/propose':
                    token = core.propose(data.get('key'), data.get('value'))
                    self.reply(200, {'token':token})
                elif path == '/api/resolve':
                    if not isinstance(data.get('confirm'), bool):
                        raise ValueError('Confirmation must be true or false')
                    self.reply(200, core.resolve(data.get('token'), data['confirm']))
                else:
                    self.reply(404, {'error':'Not found'})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.reply(400, {'error':str(exc)})
            except RuntimeError as exc:
                self.reply(503, {'error':str(exc)})

    return Handler


def run(core, memory, brain, host='127.0.0.1', port=8080, token=None):
    if host not in ('127.0.0.1', 'localhost', '::1') and not token:
        raise ValueError('Network access requires a dashboard password/token')
    server = ThreadingHTTPServer((host, port), make_handler(core, memory, brain, token))
    print(f'Buddy dashboard: http://{host}:{port}/dashboard', flush=True)
    print(f'Buddy face: http://{host}:{port}/face', flush=True)
    print(f'Buddy chat: http://{host}:{port}/chat', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
