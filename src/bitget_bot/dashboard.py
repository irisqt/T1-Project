"""Loopback-only, read-only operations dashboard; no account secrets or controls."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess

CONTROL_ACTIONS = frozenset({"start", "stop", "restart", "verify"})
CONTROL_COMMAND = "/usr/local/sbin/bitget-dashboard-control"

def run_control(action):
    if action not in CONTROL_ACTIONS:
        raise ValueError("Unknown control action")
    try:
        result = subprocess.run(["sudo", "-n", CONTROL_COMMAND, action], text=True, capture_output=True, timeout=35, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {"ok": False, "message": "서버 제어 도구에 연결하지 못했습니다."}
    messages = {"start": "봇 시작 요청을 완료했습니다. 잠시 후 상태를 새로고침하세요.", "stop": "봇 중지 요청을 완료했습니다.", "restart": "봇 재시작 요청을 완료했습니다. 새 heartbeat까지 잠시 기다리세요.", "verify": "정상 상태 확인을 통과했습니다."}
    return {"ok": result.returncode == 0, "message": messages[action] if result.returncode == 0 else "서버가 요청을 완료하지 못했습니다. 운영 로그를 확인하세요."}
from .store import read_status

PAGE = r"""<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bitget · 운영 현황</title>
<style>body{margin:0;background:#101720;color:#dae5ef;font:16px system-ui,sans-serif}main{max-width:1120px;margin:48px auto;padding:0 24px}h1{font-size:30px;margin:12px 0}small{color:#9badbe}.pill{border:1px solid #3d5265;border-radius:20px;padding:6px 12px;color:#65dcc3;font-size:12px}header{display:flex;justify-content:space-between;align-items:center}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:28px 0}.card,section{background:#18232f;border:1px solid #2d3d4c;border-radius:12px;padding:20px}.value{font-size:28px;margin-top:12px}section{margin:18px 0}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:12px 8px;border-bottom:1px solid #2d3d4c;font-size:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}#notice{color:#ffd28c;margin-top:12px}a{color:#65dcc3}.controls{display:flex;gap:10px;flex-wrap:wrap}.controls button{border:1px solid #3d5265;border-radius:8px;background:#233748;color:#dae5ef;padding:10px 14px;font-weight:650;cursor:pointer}.controls button.warn{background:#542e32;border-color:#9b5960}.controls button:disabled{opacity:.55;cursor:wait}@media(max-width:700px){.grid{grid-template-columns:repeat(2,1fr)}main{margin:20px auto}section{overflow:auto}}</style>
<main><header><div><small>BITGET AUTO COIN TRADING</small><h1>자동매매 운영 현황</h1></div><span class="pill">PAPER · 실제 시세 / 모의 자금</span></header>
<small>조회 전용 · 5초마다 갱신 · 거래소 주문은 전송되지 않습니다.</small><div id="notice"></div>
<div class="grid"><div class="card"><small>상태</small><div class="value" id="status">—</div></div><div class="card"><small>모의 자산 · USDT</small><div class="value" id="equity">—</div></div><div class="card"><small>고점 대비 낙폭</small><div class="value" id="dd">—</div></div><div class="card"><small>완료 거래</small><div class="value" id="trades">—</div></div></div>
<section><h3>운영 제어</h3><div class="controls"><button onclick="refresh()">상태 새로고침</button><button onclick="control('verify')">정상 상태 확인</button><button onclick="control('start')">봇 시작</button><button onclick="control('restart')">봇 재시작</button><button class="warn" onclick="control('stop')">봇 중지</button></div><div id="control-result">명령은 SSH 터널 안에서만 서버에 전달됩니다.</div></section><section><h3>현재 포지션</h3><table><thead><tr><th>종목</th><th>방향</th><th>수량</th><th>진입</th><th>손절</th><th>레버리지</th></tr></thead><tbody id="positions"></tbody></table></section>
<section><h3>최근 기록</h3><pre id="events"></pre></section><small id="updated"></small></main>
<script>const el=id=>document.getElementById(id);const n=(x,d=2)=>Number(x||0).toLocaleString('en-US',{maximumFractionDigits:d});async function refresh(){try{const r=await fetch('/status',{cache:'no-store'});if(!r.ok)throw Error();const s=await r.json();el('status').textContent=s.status;el('equity').textContent=n(s.equity);el('dd').textContent=n((s.drawdown||0)*100)+'%';el('trades').textContent=s.trades||0;const age=Date.now()-(s.last_cycle_ms||0);el('notice').textContent=age>180000?'최근 heartbeat가 없습니다. 서비스 상태를 확인하세요.':s.halted?'중단 사유: '+s.halt_reason:s.last_error||'';el('positions').replaceChildren();for(const [symbol,p]of Object.entries(s.positions||{})){const tr=document.createElement('tr');for(const v of[symbol,p.side===1?'LONG':'SHORT',n(p.qty,8),n(p.entry,6),n(p.stop,6),p.leverage+'×']){const td=document.createElement('td');td.textContent=v;tr.appendChild(td)}el('positions').appendChild(tr)}el('events').textContent=(s.events||[]).map(e=>new Date(e.ts).toLocaleString()+' | '+e.kind+' | '+e.symbol+' | '+JSON.stringify(e.detail)).join('\n');el('updated').textContent='마지막 처리: '+new Date(s.last_cycle_ms||0).toLocaleString()}catch{el('notice').textContent='원장 조회 실패 · 서비스와 데이터 경로를 확인하세요.'}}refresh();setInterval(refresh,5000);async function control(action){if(action==='stop'&&!confirm('모의매매 봇을 중지할까요?'))return;const buttons=[...document.querySelectorAll('.controls button')];buttons.forEach(b=>b.disabled=true);el('control-result').textContent='명령을 전송하고 있습니다…';try{const r=await fetch('/control/'+action,{method:'POST',headers:{'Content-Type':'application/json'}});const data=await r.json();el('control-result').textContent=data.message||'요청을 처리하지 못했습니다.';setTimeout(refresh,1000)}catch{el('control-result').textContent='제어 요청 실패 · SSH 터널과 서버 권한을 확인하세요.'}finally{buttons.forEach(b=>b.disabled=false)}}</script></html>"""


def serve(database,port=8765):
    if not 1024<=port<=65535:
        raise ValueError("dashboard port must be 1024..65535")
    allowed_hosts={f"127.0.0.1:{port}",f"localhost:{port}"}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Host") not in allowed_hosts:
                self.send_error(403); return
            try:
                if self.path=="/":
                    body=PAGE.encode(); content="text/html; charset=utf-8"
                elif self.path=="/status":
                    body=json.dumps(read_status(database),allow_nan=False).encode(); content="application/json"
                else:
                    self.send_error(404); return
                self.send_response(200)
                self.send_header("Content-Type",content)
                self.send_header("Cache-Control","no-store")
                self.send_header("X-Content-Type-Options","nosniff")
                self.send_header("Content-Security-Policy","default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
                self.send_header("Content-Length",str(len(body)))
                self.end_headers(); self.wfile.write(body)
            except Exception:
                self.send_error(503,"Ledger unavailable")
        def do_POST(self):
            action=self.path.removeprefix("/control/")
            origins={f"http://{host}" for host in allowed_hosts}
            if self.headers.get("Host") not in allowed_hosts or self.headers.get("Origin") not in origins:
                self.send_error(403); return
            if not self.path.startswith("/control/") or action not in CONTROL_ACTIONS:
                self.send_error(404); return
            body=json.dumps(run_control(action),allow_nan=False).encode()
            self.send_response(200)
            self.send_header("Content-Type","application/json")
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers(); self.wfile.write(body)

        def log_message(self,*args):
            return
    print(f"Read-only paper dashboard: http://127.0.0.1:{port}",flush=True)
    ThreadingHTTPServer(("127.0.0.1",port),Handler).serve_forever()
