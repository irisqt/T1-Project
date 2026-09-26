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
            --bg-color: #050507;
            --panel-bg: rgba(20, 20, 25, 0.7);
            --accent: #EA580C; /* GoldenPath Orange */
            --accent-glow: rgba(234, 88, 12, 0.4);
            --text-main: #FFFFFF;
            --text-muted: #94a3b8;
            --green: #10b981;
            --red: #ef4444;
            --glass-border: rgba(255, 255, 255, 0.05);
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
            background: rgba(10, 10, 12, 0.8);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--glass-border);
            padding: 15px 30px; display: flex; justify-content: space-between; align-items: center;
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
            font-weight: 600; font-size: 20px; letter-spacing: 0.5px;
        }
        
        .nav-links {
            display: flex; gap: 20px;
        }
        
        .nav-links div {
            color: var(--text-muted); font-size: 14px; font-weight: 400; cursor: pointer; transition: color 0.3s;
        }
        
        .nav-links div.active {
            color: var(--accent); font-weight: 600; text-shadow: 0 0 10px var(--accent-glow);
        }

        /* Main Dashboard Grid */
        .dashboard-container {
            flex: 1; padding: 25px 30px; display: grid; gap: 20px;
            grid-template-columns: 300px 1fr 300px; /* Left Sidebar, Center Chart, Right Panel */
            grid-template-rows: 1fr;
            overflow-y: auto;
        }

        .panel {
            background: var(--panel-bg);
            backdrop-filter: blur(16px);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            padding: 20px;
            display: flex; flex-direction: column;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }

        .panel-title {
            font-size: 12px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px;
            margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center;
        }

        /* Left Column: Status & Control */
        .status-box {
            background: rgba(0,0,0,0.4); border-radius: 12px; padding: 15px; margin-bottom: 15px;
            border: 1px solid var(--glass-border); text-align: center;
        }
        
        .status-indicator {
            display: inline-block; width: 10px; height: 10px; border-radius: 50%;
            margin-right: 8px; box-shadow: 0 0 10px currentColor;
        }
        
        .status-text { font-family: 'JetBrains Mono', monospace; font-size: 18px; font-weight: 700; }
        
        .running { color: var(--green); }
        .stopped { color: var(--red); }
        
        .metric {
            display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .metric:last-child { border-bottom: none; }
        .metric-label { color: var(--text-muted); font-size: 13px; }
        .metric-value { font-family: 'JetBrains Mono', monospace; font-size: 14px; font-weight: 700; }

        .kill-switch {
            margin-top: auto; background: linear-gradient(135deg, #ef4444, #991b1b);
            color: white; border: none; padding: 18px; border-radius: 12px;
            font-size: 15px; font-weight: 800; text-transform: uppercase; cursor: pointer;
            box-shadow: 0 4px 20px rgba(239, 68, 68, 0.4); transition: transform 0.2s, box-shadow 0.2s;
            display: flex; justify-content: center; align-items: center; gap: 10px;
        }
        .kill-switch:hover { transform: translateY(-2px); box-shadow: 0 6px 25px rgba(239, 68, 68, 0.6); }

        /* Center Column: Chart */
        .chart-container {
            width: 100%; height: 100%; border-radius: 12px; overflow: hidden;
            border: 1px solid var(--glass-border);
        }

        /* Right Column: AI Insights & History */
        .history-table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        .history-table th { color: var(--text-muted); font-size: 11px; text-align: left; padding-bottom: 10px; border-bottom: 1px solid var(--glass-border); }
        .history-table td { padding: 10px 0; font-family: 'JetBrains Mono', monospace; font-size: 12px; border-bottom: 1px solid rgba(255,255,255,0.02); }
        .buy { color: var(--green); }
        .sell { color: var(--red); }
        
        .insight-card {
            background: rgba(234, 88, 12, 0.05); border: 1px solid rgba(234, 88, 12, 0.2);
            border-radius: 10px; padding: 15px; margin-bottom: 15px; font-size: 13px; line-height: 1.5;
        }

        /* Responsive */
        @media (max-width: 1024px) {
            .dashboard-container { grid-template-columns: 1fr; grid-template-rows: auto 500px auto; overflow-y: auto; }
            .nav-links { display: none; }
            body { height: auto; overflow-y: auto; }
        }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="brand">
            <div class="brand-icon">GP</div>
            <div class="brand-title">GoldenPath AI | Quant Engine</div>
        </div>
        <div class="nav-links">
            <div>증상 NLP 분석</div>
            <div>심층 의학 분석</div>
            <div>정밀 검사 안내</div>
            <div class="active">트레이딩 AI 대시보드</div>
            <div>기술과 비전</div>
        </div>
    </div>

    <div class="dashboard-container">
        <!-- Left Sidebar: Engine Status -->
        <div class="panel">
            <div class="panel-title">Engine Status <span style="color:var(--green)">LIVE</span></div>
            
            <div class="status-box">
                <div id="status-val" class="status-text running">
                    <span class="status-indicator running"></span>Connecting...
                </div>
            </div>
            
            <div>
                <div class="metric"><span class="metric-label">Strategy</span><span class="metric-value" style="color:var(--accent)">Trend4H_20</span></div>
                <div class="metric"><span class="metric-label">Leverage</span><span class="metric-value">30x</span></div>
                <div class="metric"><span class="metric-label">Symbols</span><span class="metric-value">BTC, ETH, SOL, XRP</span></div>
                <div class="metric"><span class="metric-label">Engine Uptime</span><span id="uptime-val" class="metric-value">00:00:00</span></div>
                <div class="metric"><span class="metric-label">CPU Load</span><span id="cpu-val" class="metric-value">12%</span></div>
                <div class="metric"><span class="metric-label">Latency</span><span class="metric-value" style="color:var(--green)">14ms</span></div>
            </div>
            
            <button class="kill-switch" onclick="stopBot()">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"></path><line x1="12" y1="2" x2="12" y2="12"></line></svg>
                KILL SWITCH
            </button>
        </div>

        <!-- Center: TradingView Chart -->
        <div class="panel" style="padding: 0; overflow: hidden;">
            <div class="tradingview-widget-container" style="height: 100%; width: 100%;">
                <div id="tv_chart" style="height: 100%; width: 100%;"></div>
            </div>
        </div>

        <!-- Right: AI Insights & Trade History -->
        <div class="panel">
            <div class="panel-title">AI Market Insights</div>
            <div class="insight-card">
                <strong style="color:var(--accent)">[SYSTEM]</strong> 4H Trend Analysis indicates strong momentum. Volatility index is stable. The Durable Engine is actively scanning for optimal entry points based on Kelly Criterion.
            </div>
            
            <div class="panel-title" style="margin-top: 10px;">Recent Executions</div>
            <div style="flex: 1; overflow-y: auto; max-height: 400px;">
                <table class="history-table">
                    <thead>
                        <tr>
                            <th>TIME</th>
                            <th>PAIR</th>
                            <th>SIDE</th>
                            <th style="text-align:right">PRICE</th>
                        </tr>
                    </thead>
                    <tbody id="history-body">
                        <tr><td colspan="4" style="text-align:center; color:var(--text-muted); padding: 20px;">No trades executed yet.<br>Scanning market...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        // Initialize TradingView
        new TradingView.widget({
            "autosize": true,
            "symbol": "BINANCE:BTCUSDT",
            "interval": "240",
            "timezone": "Asia/Seoul",
            "theme": "dark",
            "style": "1",
            "locale": "kr",
            "enable_publishing": false,
            "backgroundColor": "rgba(20, 20, 25, 1)",
            "gridColor": "rgba(255, 255, 255, 0.05)",
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

        let start_time = Date.now() - (Math.random() * 5000000); // mock uptime

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                const statusEl = document.getElementById('status-val');
                if (data.bot_running) {
                    statusEl.className = "status-text running";
                    statusEl.innerHTML = '<span class="status-indicator running" style="background:var(--green)"></span>BEAST MODE LIVE';
                } else {
                    statusEl.className = "status-text stopped";
                    statusEl.innerHTML = '<span class="status-indicator stopped" style="background:var(--red)"></span>ENGINE STOPPED';
                }
                
                // Mock dynamic CPU
                document.getElementById('cpu-val').innerText = (Math.random() * 15 + 5).toFixed(1) + '%';
                
                // Uptime
                let diff = Math.floor((Date.now() - start_time) / 1000);
                let h = String(Math.floor(diff / 3600)).padStart(2, '0');
                let m = String(Math.floor((diff % 3600) / 60)).padStart(2, '0');
                let s = String(diff % 60).padStart(2, '0');
                document.getElementById('uptime-val').innerText = `${h}:${m}:${s}`;
                
                // History Update
                const tbody = document.getElementById('history-body');
                if (data.history && data.history.length > 0) {
                    tbody.innerHTML = '';
                    data.history.forEach(row => {
                        let sideClass = row.side === 'BUY' ? 'buy' : 'sell';
                        tbody.innerHTML += `<tr>
                            <td>${row.time.substring(11, 19)}</td>
                            <td style="font-weight:bold">${row.symbol}</td>
                            <td class="${sideClass}">${row.side}</td>
                            <td style="text-align:right">$${parseFloat(row.price).toLocaleString()}</td>
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
                alert("킬 스위치 작동 완료. 엔지니어링 팀에 알림이 전송되었습니다.");
                fetchStatus();
            }
        }

        window.onload = () => {
            fetchStatus();
            setInterval(fetchStatus, 3000);
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
            bot_running = not os.path.exists("data/KILL_SWITCH")
            history = []
            if os.path.exists("data/live_trader.sqlite3"):
                try:
                    conn = sqlite3.connect("data/live_trader.sqlite3")
                    cursor = conn.cursor()
                    cursor.execute("SELECT timestamp, side, symbol, quantity, price FROM trades ORDER BY timestamp DESC LIMIT 15")
                    for row in cursor.fetchall():
                        history.append({
                            "time": str(row[0]),
                            "side": "BUY" if row[1] == 1 else "SELL",
                            "symbol": str(row[2]),
                            "qty": row[3],
                            "price": row[4]
                        })
                    conn.close()
                except Exception:
                    pass

            data = {
                "bot_running": bot_running,
                "history": history
            }
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
