import os
import json
import sqlite3
import random
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

# Premium GoldenPath AI UI - HTML Template
HTML_PAGE = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GoldenPath AI - Quant Engine Dashboard</title>
    <!-- Google Fonts -->
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
    <!-- TradingView Widget -->
    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
    <style>
        :root {
            --bg-color: #f8fafc; /* Light gray background */
            --panel-bg: #ffffff; /* White panels */
            --accent: #EA580C; /* GoldenPath Orange */
            --accent-glow: rgba(234, 88, 12, 0.2);
            --text-main: #0f172a; /* Dark text */
            --text-muted: #475569; /* Medium gray text */
            --green: #059669; /* Darker green for visibility */
            --red: #dc2626; /* Darker red */
            --glass-border: rgba(0, 0, 0, 0.1);
        }
        
        * { box-sizing: border-box; }
        
        body {
            margin: 0; padding: 0;
            background-color: var(--bg-color);
            background-image: 
                radial-gradient(circle at 15% 50%, rgba(234, 88, 12, 0.08), transparent 25%),
                radial-gradient(circle at 85% 30%, rgba(16, 185, 129, 0.05), transparent 25%);
            color: var(--text-main);
            font-family: 'Outfit', sans-serif;
            height: 100vh; display: flex; flex-direction: column; overflow: hidden;
        }

        /* Glassmorphism Navigation */
        .navbar {
            background: rgba(255, 255, 255, 0.9);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--glass-border);
            padding: 15px 20px; display: flex; justify-content: space-between; align-items: center;
            z-index: 10;
        }
        
        .brand {
            display: flex; align-items: center; gap: 12px;
        }
        
        .brand-icon {
            background: linear-gradient(135deg, var(--accent), #ff8a00);
            color: #fff; font-weight: 800; font-size: 14px;
            padding: 8px 12px; border-radius: 8px;
            box-shadow: 0 0 20px var(--accent-glow);
        }
        
        .brand-title {
            font-weight: 600; font-size: 18px; letter-spacing: 0.5px;
        }
        
        /* Navigation Tabs */
        .nav-tabs {
            display: flex; gap: 10px; overflow-x: auto; white-space: nowrap; padding-bottom: 5px; margin-top: 10px;
        }
        
        /* Hide scrollbar for tabs */
        .nav-tabs::-webkit-scrollbar { display: none; }
        .nav-tabs { -ms-overflow-style: none; scrollbar-width: none; }
        
        .nav-tab {
            background: #f1f5f9;
            border: 1px solid var(--glass-border);
            padding: 10px 16px; border-radius: 8px;
            color: var(--text-muted); font-size: 15px; font-weight: 500; cursor: pointer; transition: all 0.3s;
        }
        
        .nav-tab.active {
            background: rgba(234, 88, 12, 0.1);
            border-color: var(--accent);
            color: var(--accent); font-weight: 700; text-shadow: none;
        }

        /* Main Dashboard Container */
        .dashboard-container {
            flex: 1; padding: 20px; display: flex; flex-direction: column; overflow-y: auto; gap: 20px;
        }

        .panel {
            background: var(--panel-bg);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            padding: 20px;
            display: none; /* Hidden by default for tab system */
            flex-direction: column;
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.05);
            min-height: 500px;
        }
        
        .panel.active-panel {
            display: flex;
        }

        .panel-title {
            font-size: 16px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px;
            margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--glass-border); padding-bottom: 10px;
        }

        /* Status & Control Panel */
        .status-box {
            background: #f8fafc; border-radius: 12px; padding: 20px; margin-bottom: 20px;
            border: 1px solid var(--glass-border); text-align: center;
        }
        
        .status-indicator {
            display: inline-block; width: 12px; height: 12px; border-radius: 50%;
            margin-right: 10px; box-shadow: 0 0 12px currentColor;
        }
        
        .status-text { font-family: 'JetBrains Mono', monospace; font-size: 24px; font-weight: 800; }
        
        .running { color: var(--green); }
        .stopped { color: var(--red); }
        
        .metric {
            display: flex; justify-content: space-between; padding: 15px 5px; border-bottom: 1px solid var(--glass-border);
        }
        .metric:last-child { border-bottom: none; }
        .metric-label { color: var(--text-muted); font-size: 16px; }
        .metric-value { font-family: 'JetBrains Mono', monospace; font-size: 18px; font-weight: 700; }

        .kill-switch {
            margin-top: 30px; background: linear-gradient(135deg, #ef4444, #991b1b);
            color: white; border: none; padding: 20px; border-radius: 12px;
            font-size: 18px; font-weight: 800; text-transform: uppercase; cursor: pointer;
            box-shadow: 0 4px 20px rgba(239, 68, 68, 0.4); transition: transform 0.2s, box-shadow 0.2s;
            display: flex; justify-content: center; align-items: center; gap: 10px; width: 100%;
        }
        .kill-switch:hover { transform: translateY(-2px); box-shadow: 0 6px 25px rgba(239, 68, 68, 0.6); }

        /* Chart Panel */
        .chart-controls {
            padding: 10px 0;
            margin-bottom: 15px;
            display: flex; gap: 10px;
            overflow-x: auto;
        }

        .chart-controls button {
            background: #f1f5f9;
            border: 1px solid var(--glass-border);
            color: var(--text-muted);
            padding: 10px 18px;
            border-radius: 8px;
            cursor: pointer;
            font-family: 'Outfit', sans-serif;
            font-size: 15px; font-weight: 600;
            transition: all 0.2s;
        }
        
        .chart-controls button.active {
            background: rgba(234, 88, 12, 0.1);
            color: var(--accent);
            border-color: var(--accent);
        }

        .chart-container {
            flex: 1; border-radius: 12px; overflow: hidden; border: 1px solid var(--glass-border); min-height: 400px;
        }

        /* History Panel */
        .history-table { width: 100%; border-collapse: collapse; margin-top: 5px; }
        .history-table th { color: var(--text-muted); font-size: 13px; text-align: left; padding-bottom: 12px; border-bottom: 1px solid var(--glass-border); }
        .history-table td { padding: 12px 0; font-family: 'JetBrains Mono', monospace; font-size: 14px; border-bottom: 1px solid var(--glass-border); }
        .buy { color: var(--green); }
        .sell { color: var(--red); }
        
        .pos-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        .pos-table th { color: var(--text-muted); font-size: 13px; text-align: left; padding-bottom: 12px; border-bottom: 1px solid var(--glass-border); }
        .pos-table td { padding: 12px 0; font-family: 'JetBrains Mono', monospace; font-size: 14px; border-bottom: 1px solid var(--glass-border); }

        /* AI Insights Panel */
        .insight-card {
            background: rgba(234, 88, 12, 0.05); border: 1px solid rgba(234, 88, 12, 0.3);
            border-radius: 12px; padding: 25px; margin-bottom: 20px; 
            font-size: 24px; line-height: 1.8; color: var(--text-main); font-weight: 700;
        }

        /* Header wrapper for flex layout */
        .header-wrapper {
            background: rgba(255, 255, 255, 0.95);
            border-bottom: 1px solid var(--glass-border);
            padding-bottom: 10px;
        }
    </style>
</head>
<body>
    <div class="header-wrapper">
        <div class="navbar">
            <div class="brand">
                <div class="brand-icon">GP</div>
                <div class="brand-title">GoldenPath AI</div>
            </div>
        </div>
        <div class="nav-tabs" style="padding: 0 20px;">
            <div class="nav-tab active" data-target="panel-status">엔진 상태 & 자산</div>
            <div class="nav-tab" data-target="panel-chart">실시간 차트</div>
            <div class="nav-tab" data-target="panel-history">포지션 & 매매기록</div>
            <div class="nav-tab" data-target="panel-ai">AI 마켓 분석</div>
        </div>
    </div>

    <div class="dashboard-container">
        
        <!-- PANEL 1: Status & Balance -->
        <div id="panel-status" class="panel active-panel">
            <div class="panel-title">엔진 가동 상태 <span style="color:var(--green)" id="sys-status">LIVE</span></div>
            
            <div class="status-box">
                <div id="status-val" class="status-text running">
                    <span class="status-indicator running"></span>Connecting...
                </div>
            </div>
            
            <div style="flex:1;">
                <div class="metric"><span class="metric-label">현재 가용 잔고</span><span id="balance-val" class="metric-value" style="color:var(--green)">$0.00</span></div>
                <div class="metric"><span class="metric-label">총 자산 (Equity)</span><span id="equity-val" class="metric-value">$0.00</span></div>
                <div class="metric"><span class="metric-label">적용 알고리즘</span><span class="metric-value" style="color:var(--accent)">T3_MTF_5m (이중 잣대 추세돌파)</span></div>
                <div class="metric"><span class="metric-label">레버리지</span><span class="metric-value">최대 30x</span></div>
                <div class="metric"><span class="metric-label">엔진 연속 가동 시간</span><span id="uptime-val" class="metric-value">00:00:00</span></div>
            </div>
            
            <button class="kill-switch" onclick="stopBot()">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"></path><line x1="12" y1="2" x2="12" y2="12"></line></svg>
                긴급 킬 스위치 (강제 정지)
            </button>
        </div>

        <!-- PANEL 2: Chart -->
        <div id="panel-chart" class="panel" style="padding: 15px;">
            <div class="chart-controls">
                <button class="coin-btn active" data-symbol="BINANCE:BTCUSDT">BTC (비트코인)</button>
                <button class="coin-btn" data-symbol="BINANCE:ETHUSDT">ETH (이더리움)</button>
                <button class="coin-btn" data-symbol="BINANCE:SOLUSDT">SOL (솔라나)</button>
                <button class="coin-btn" data-symbol="BINANCE:XRPUSDT">XRP (리플)</button>
            </div>
            <div class="chart-container">
                <div id="tv_chart" style="height: 100%; width: 100%;"></div>
            </div>
        </div>

        <!-- PANEL 3: History & Positions -->
        <div id="panel-history" class="panel">
            <div class="panel-title">현재 보유 포지션 (Active)</div>
            <div style="overflow-x: auto; margin-bottom: 30px;">
                <table class="pos-table" style="min-width: 400px;">
                    <thead>
                        <tr>
                            <th>종목</th>
                            <th>포지션</th>
                            <th style="text-align:right">수량</th>
                            <th style="text-align:right">진입가</th>
                        </tr>
                    </thead>
                    <tbody id="positions-body">
                        <tr><td colspan="4" style="text-align:center; color:var(--text-muted); padding: 20px;">보유 중인 포지션이 없습니다.</td></tr>
                    </tbody>
                </table>
            </div>

            <div class="panel-title">엔진 실행 로그 (Event Log)</div>
            <div style="flex: 1; overflow-y: auto; overflow-x: auto;">
                <table class="history-table" style="min-width: 500px;">
                    <thead>
                        <tr>
                            <th>시간</th>
                            <th>이벤트</th>
                            <th>종목</th>
                            <th style="text-align:right">상세 내용</th>
                        </tr>
                    </thead>
                    <tbody id="history-body">
                        <tr><td colspan="4" style="text-align:center; color:var(--text-muted); padding: 20px;">시장을 스캔 중입니다...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- PANEL 4: AI Insights -->
        <div id="panel-ai" class="panel">
            <div class="panel-title">AI 마켓 딥러닝 분석</div>
            <div class="insight-card">
                <strong style="color:var(--accent); display:block; margin-bottom: 10px;">[시스템 상태 브리핑]</strong> 
                현재 4시간(4H) 봉 차트 기준으로 시장의 추세 모멘텀을 정밀 분석 중입니다. 
                <br><br>
                비트코인(BTC)을 포함한 주요 알트코인(ETH, SOL, XRP)의 변동성 지표가 알고리즘의 진입 허용 범위 내에 있습니다.
                <br><br>
                GoldenPath AI 퀀트 엔진은 켈리 공식(Kelly Criterion)에 기반한 리스크 관리 기법을 적용하여 <strong>안전하고 최적화된 매수/매도 타점</strong>을 실시간 24시간 스캔하고 있습니다. 조건이 충족되면 자동으로 주문이 실행됩니다.
            </div>
        </div>

    </div>

    <script>
        // Tab Switching Logic
        const tabs = document.querySelectorAll('.nav-tab');
        const panels = document.querySelectorAll('.panel');
        
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                // Remove active class from all tabs and panels
                tabs.forEach(t => t.classList.remove('active'));
                panels.forEach(p => p.classList.remove('active-panel'));
                
                // Add active class to clicked tab and corresponding panel
                tab.classList.add('active');
                const targetId = tab.getAttribute('data-target');
                document.getElementById(targetId).classList.add('active-panel');
            });
        });

        let tvWidget = null;
        
        function initChart(symbol) {
            if(tvWidget !== null) {
                document.getElementById('tv_chart').innerHTML = '';
            }
            tvWidget = new TradingView.widget({
                "autosize": true,
                "symbol": symbol,
                "interval": "240",
                "timezone": "Asia/Seoul",
                "theme": "light",
                "style": "1",
                "locale": "kr",
                "enable_publishing": false,
                "backgroundColor": "#ffffff",
                "gridColor": "rgba(0, 0, 0, 0.05)",
                "hide_top_toolbar": false,
                "hide_legend": false,
                "save_image": false,
                "container_id": "tv_chart",
                "studies": [
                    "Volume@tv-basicstudies",
                    "MACD@tv-basicstudies",
                    "RSI@tv-basicstudies"
                ]
            });
        }
        
        document.querySelectorAll('.coin-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.coin-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                initChart(e.target.dataset.symbol);
            });
        });

        // Init default chart
        initChart("BINANCE:BTCUSDT");

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                const statusEl = document.getElementById('status-val');
                const sysStatus = document.getElementById('sys-status');
                
                if (data.status === "STARTING" || data.status === "RUNNING") {
                    statusEl.className = "status-text running";
                    statusEl.innerHTML = '<span class="status-indicator running" style="background:var(--green)"></span>엔진 정상 가동 중';
                    sysStatus.innerText = data.mode ? data.mode.toUpperCase() : "LIVE";
                    sysStatus.style.color = "var(--green)";
                } else if (data.status === "HALTED") {
                    statusEl.className = "status-text stopped";
                    statusEl.innerHTML = '<span class="status-indicator stopped" style="background:var(--red)"></span>엔진 강제 정지됨';
                    sysStatus.innerText = "HALTED";
                    sysStatus.style.color = "var(--red)";
                } else {
                    statusEl.className = "status-text stopped";
                    statusEl.innerHTML = '<span class="status-indicator stopped" style="background:var(--text-muted)"></span>엔진 오프라인';
                    sysStatus.innerText = "OFFLINE";
                    sysStatus.style.color = "var(--text-muted)";
                }
                
                // Store started_ms globally for smooth 1-second ticking
                if (data.started_ms) {
                    window.botStartedMs = data.started_ms;
                }
                
                // Balances
                if (data.cash !== undefined) {
                    document.getElementById('balance-val').innerText = `$${parseFloat(data.cash).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                }
                if (data.equity !== undefined) {
                    document.getElementById('equity-val').innerText = `$${parseFloat(data.equity).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                }
                
                // Positions Update
                const posBody = document.getElementById('positions-body');
                if (data.positions && Object.keys(data.positions).length > 0) {
                    posBody.innerHTML = '';
                    for (const [symbol, pos] of Object.entries(data.positions)) {
                        let sideClass = pos.size > 0 ? 'buy' : 'sell';
                        let sideText = pos.size > 0 ? '롱(LONG)' : '숏(SHORT)';
                        posBody.innerHTML += `<tr>
                            <td style="font-weight:bold">${symbol.replace('USDT', '')}</td>
                            <td class="${sideClass}">${sideText}</td>
                            <td style="text-align:right">${Math.abs(pos.size)}</td>
                            <td style="text-align:right">$${parseFloat(pos.entry_price).toLocaleString()}</td>
                        </tr>`;
                    }
                } else {
                    posBody.innerHTML = `<tr><td colspan="4" style="text-align:center; color:var(--text-muted); padding: 20px;">보유 중인 포지션이 없습니다.</td></tr>`;
                }

                // History/Events Update
                const tbody = document.getElementById('history-body');
                if (data.events && data.events.length > 0) {
                    tbody.innerHTML = '';
                    data.events.forEach(row => {
                        let date = new Date(row.ts);
                        let timeStr = date.getHours().toString().padStart(2,'0') + ':' + 
                                      date.getMinutes().toString().padStart(2,'0') + ':' + 
                                      date.getSeconds().toString().padStart(2,'0');
                        
                        let detailStr = "";
                        if (row.kind === "ORDER_FILLED") detailStr = `체결가: $${row.detail.price}`;
                        else if (row.kind === "SIGNAL") detailStr = `신호 감지: ${row.detail.signal}`;
                        else if (row.kind === "ERROR") detailStr = `<span style="color:var(--red)">${row.detail.error || '오류 발생'}</span>`;
                        else detailStr = JSON.stringify(row.detail).substring(0, 30) + "...";
                        
                        tbody.innerHTML += `<tr>
                            <td>${timeStr}</td>
                            <td style="color:var(--accent)">${row.kind}</td>
                            <td style="font-weight:bold">${row.symbol ? row.symbol.replace('USDT','') : 'SYS'}</td>
                            <td style="text-align:right">${detailStr}</td>
                        </tr>`;
                    });
                }
            } catch (e) {
                console.error("Status fetch error", e);
            }
        }
        
        async function stopBot() {
            if(confirm("⚠ 경고: 정말로 킬 스위치를 작동하시겠습니까?\\n모든 신규 진입이 차단되며 봇이 강제 종료됩니다.")) {
                await fetch('/api/kill', {method: 'POST'});
                alert("킬 스위치 작동 완료. 시스템이 정지되었습니다.");
                fetchStatus();
            }
        }

        function updateUptimeUI() {
            if (window.botStartedMs) {
                let diff = Math.floor((Date.now() - window.botStartedMs) / 1000);
                if (diff < 0) diff = 0;
                let h = String(Math.floor(diff / 3600)).padStart(2, '0');
                let m = String(Math.floor((diff % 3600) / 60)).padStart(2, '0');
                let s = String(diff % 60).padStart(2, '0');
                document.getElementById('uptime-val').innerText = `${h}:${m}:${s}`;
            }
        }

        window.onload = () => {
            fetchStatus();
            setInterval(fetchStatus, 5000);
            setInterval(updateUptimeUI, 1000);
        };
    </script>
</body>
</html>
"""

class DashboardHandler(BaseHTTPRequestHandler):
    def _send_response(self, content: str, content_type="text/html", status=200):
        self.send_response(status)
        self.send_header('Content-type', content_type)
        self.end_headers()
        self.wfile.write(content.encode('utf-8'))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_response(HTML_PAGE)
        
        elif parsed.path == "/api/status":
            data = {"status": "OFFLINE"}
            if os.path.exists("data/KILL_SWITCH"):
                data["status"] = "HALTED"
            
            live_state_path = "data/live_state.json"
            db_path = "data/trader.sqlite3"
            
            # Check if live state JSON exists (Live trading)
            if os.path.exists(live_state_path):
                try:
                    with open(live_state_path, "r", encoding="utf-8") as f:
                        state = json.load(f)
                        data.update(state)
                        if data.get("status") == "OFFLINE" and "status" in state:
                            data["status"] = state["status"]
                except Exception as e:
                    data["error"] = f"JSON load error: {e}"

            # Fallback to Paper Trading SQLite DB if no JSON or missing fields
            elif os.path.exists(db_path):
                try:
                    # open read-only
                    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3)
                    cursor = conn.cursor()
                    
                    # 1. Load Portfolio State
                    row = cursor.execute("SELECT payload FROM portfolio WHERE id=1").fetchone()
                    if row:
                        state = json.loads(row[0])
                        data.update(state)
                        if data.get("status") == "STARTING" and data.get("last_cycle_ms", 0) > 0:
                            data["status"] = "RUNNING"
                        # Handle case where status doesn't match STARTING exactly
                        elif "status" in state and state["status"] not in ["HALTED", "STOPPED", "ERROR"] and data.get("status") == "OFFLINE":
                            data["status"] = "RUNNING"
                            
                    # 2. Load Recent Events
                    events = cursor.execute("SELECT ts, kind, symbol, payload FROM events ORDER BY id DESC LIMIT 25").fetchall()
                    data["events"] = [
                        {"ts": t, "kind": k, "symbol": s, "detail": json.loads(p)}
                        for t, k, s, p in events
                    ]
                    
                    conn.close()
                except Exception as e:
                    data["error"] = str(e)
            
            self._send_response(json.dumps(data), "application/json")
        else:
            self._send_response("Not Found", status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/kill":
            os.makedirs("data", exist_ok=True)
            with open("data/KILL_SWITCH", "w") as f:
                f.write("STOP")
            self._send_response(json.dumps({"success": True}), "application/json")
        else:
            self._send_response("Not Found", status=404)

if __name__ == "__main__":
    PORT = 8080
    server = HTTPServer(('0.0.0.0', PORT), DashboardHandler)
    print(f"GoldenPath Dashboard running at http://localhost:{PORT}")
    server.serve_forever()

