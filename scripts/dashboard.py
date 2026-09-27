import os
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

HTML_PAGE = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>GoldenPath AI - Quant Engine</title>
    <!-- Google Fonts -->
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
    <style>
        :root {
            --bg: #090a0f;
            --bg-card: rgba(16, 18, 27, 0.6);
            --bg-card-hover: rgba(25, 28, 41, 0.8);
            --border: rgba(255, 255, 255, 0.08);
            --border-highlight: rgba(255, 255, 255, 0.15);
            --text-main: #ffffff;
            --text-muted: #8b94a7;
            --accent: #ff8a00; 
            --accent-glow: rgba(255, 138, 0, 0.25);
            --green: #00e676;
            --green-glow: rgba(0, 230, 118, 0.3);
            --red: #ff3b69;
            --red-glow: rgba(255, 59, 105, 0.3);
            --cyan: #00e5ff;
        }
        
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        
        body {
            margin: 0; padding: 0;
            background-color: var(--bg);
            background-image: 
                radial-gradient(circle at 15% 0%, rgba(255, 138, 0, 0.08), transparent 40%),
                radial-gradient(circle at 85% 100%, rgba(0, 229, 255, 0.05), transparent 40%);
            color: var(--text-main);
            font-family: 'Outfit', -apple-system, sans-serif;
            height: 100vh; display: flex; flex-direction: column; overflow: hidden;
        }

        /* Animations */
        @keyframes pulseGlow {
            0% { box-shadow: 0 0 10px var(--green-glow); }
            50% { box-shadow: 0 0 25px var(--green-glow); }
            100% { box-shadow: 0 0 10px var(--green-glow); }
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Top Bar */
        .top-navbar {
            padding: 15px 25px;
            display: flex; justify-content: space-between; align-items: center;
            background: rgba(9, 10, 15, 0.8);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid var(--border);
            z-index: 20;
        }
        
        .brand { display: flex; align-items: center; gap: 12px; }
        .brand-icon {
            background: linear-gradient(135deg, #ff8a00, #ff2a00);
            color: #fff; font-weight: 800; font-size: 16px;
            padding: 8px 12px; border-radius: 10px;
            box-shadow: 0 0 20px var(--accent-glow);
            letter-spacing: 1px;
        }
        .brand-title { font-weight: 700; font-size: 20px; letter-spacing: 0.5px; }

        /* Navigation */
        .nav-container {
            padding: 15px 25px 0 25px;
        }
        .nav-tabs {
            display: flex; gap: 12px;
            overflow-x: auto; scrollbar-width: none;
        }
        .nav-tabs::-webkit-scrollbar { display: none; }
        
        .nav-tab {
            background: var(--bg-card);
            border: 1px solid var(--border);
            padding: 12px 20px; border-radius: 12px;
            color: var(--text-muted); font-size: 15px; font-weight: 600;
            cursor: pointer; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            white-space: nowrap;
        }
        .nav-tab:hover { border-color: var(--border-highlight); color: var(--text-main); }
        .nav-tab.active {
            background: rgba(255, 138, 0, 0.1);
            border-color: var(--accent);
            color: var(--accent);
            box-shadow: 0 0 20px var(--accent-glow);
        }

        /* Main Area */
        .dashboard-container {
            flex: 1; padding: 25px; display: flex; flex-direction: column; 
            overflow-y: auto; overflow-x: hidden; scroll-behavior: smooth;
        }

        .panel {
            display: none; flex-direction: column; gap: 20px;
            animation: fadeIn 0.4s ease-out forwards;
        }
        .panel.active-panel { display: flex; }

        /* Cards */
        .card {
            background: var(--bg-card);
            backdrop-filter: blur(10px);
            border: 1px solid var(--border);
            border-radius: 20px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            transition: transform 0.3s, border-color 0.3s;
        }
        .card:hover { border-color: var(--border-highlight); }
        
        .card-header {
            font-size: 14px; font-weight: 700; color: var(--text-muted);
            text-transform: uppercase; letter-spacing: 1.5px;
            margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;
        }

        /* Status Widget */
        .status-hero {
            display: flex; align-items: center; justify-content: center; flex-direction: column;
            padding: 30px 20px; text-align: center;
            background: linear-gradient(180deg, rgba(16, 18, 27, 0) 0%, rgba(16, 18, 27, 0.8) 100%);
            border-radius: 16px; border: 1px solid var(--border);
            position: relative; overflow: hidden;
        }
        .status-hero::before {
            content: ''; position: absolute; top: -50%; left: -50%; width: 200%; height: 200%;
            background: radial-gradient(circle, var(--green-glow) 0%, transparent 50%);
            opacity: 0.1; pointer-events: none;
        }
        
        .status-badge {
            display: inline-flex; align-items: center; gap: 10px;
            background: rgba(0, 230, 118, 0.1); border: 1px solid var(--green);
            color: var(--green); padding: 8px 16px; border-radius: 30px;
            font-weight: 800; font-size: 14px; letter-spacing: 1px;
            box-shadow: 0 0 15px var(--green-glow);
        }
        .status-dot {
            width: 10px; height: 10px; background: var(--green); border-radius: 50%;
            animation: pulseGlow 2s infinite;
        }
        
        .status-badge.stopped {
            background: rgba(255, 59, 105, 0.1); border-color: var(--red); color: var(--red);
            box-shadow: 0 0 15px var(--red-glow);
        }
        .status-badge.stopped .status-dot {
            background: var(--red); animation: none; box-shadow: 0 0 10px var(--red);
        }

        /* Metrics Grid */
        .metrics-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;
        }
        .metric-box {
            background: rgba(0,0,0,0.2); border: 1px solid var(--border);
            padding: 20px; border-radius: 16px;
        }
        .metric-label { font-size: 13px; color: var(--text-muted); margin-bottom: 8px; font-weight: 600; text-transform: uppercase; }
        .metric-value { font-family: 'JetBrains Mono', monospace; font-size: 28px; font-weight: 800; color: var(--text-main); }
        .metric-value.highlight { color: var(--cyan); text-shadow: 0 0 15px rgba(0, 229, 255, 0.3); }
        .metric-value.green { color: var(--green); text-shadow: 0 0 15px var(--green-glow); }

        /* Kill Switch */
        .kill-switch {
            width: 100%; background: linear-gradient(135deg, #ff3b69, #b9002d);
            color: white; border: none; padding: 20px; border-radius: 16px;
            font-size: 18px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px;
            cursor: pointer; box-shadow: 0 10px 30px var(--red-glow);
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            display: flex; justify-content: center; align-items: center; gap: 12px;
            margin-top: 10px;
        }
        .kill-switch:active { transform: scale(0.98); }

        /* Chart Controls */
        .coin-selectors {
            display: flex; gap: 10px; margin-bottom: 20px; overflow-x: auto; scrollbar-width: none;
        }
        .coin-selectors::-webkit-scrollbar { display: none; }
        .coin-btn {
            background: rgba(0,0,0,0.3); border: 1px solid var(--border);
            color: var(--text-muted); padding: 10px 20px; border-radius: 12px;
            font-weight: 600; font-size: 14px; cursor: pointer; transition: 0.3s;
            white-space: nowrap;
        }
        .coin-btn.active {
            background: rgba(0, 229, 255, 0.1); border-color: var(--cyan);
            color: var(--cyan); box-shadow: 0 0 15px rgba(0, 229, 255, 0.2);
        }

        .chart-wrapper {
            height: 500px; border-radius: 16px; overflow: hidden;
            border: 1px solid var(--border);
        }

        /* Tables */
        .data-table-container {
            overflow-x: auto; border-radius: 12px; border: 1px solid var(--border);
            background: rgba(0,0,0,0.2);
        }
        .data-table { width: 100%; border-collapse: collapse; min-width: 600px; }
        .data-table th {
            background: rgba(255,255,255,0.03); color: var(--text-muted);
            font-size: 12px; font-weight: 600; text-transform: uppercase;
            letter-spacing: 1px; padding: 15px; text-align: left; border-bottom: 1px solid var(--border);
        }
        .data-table td {
            padding: 15px; font-family: 'JetBrains Mono', monospace; font-size: 14px;
            border-bottom: 1px solid rgba(255,255,255,0.03);
        }
        .data-table tr:last-child td { border-bottom: none; }
        .data-table tr:hover { background: rgba(255,255,255,0.02); }
        
        .badge {
            padding: 6px 10px; border-radius: 6px; font-size: 12px; font-weight: 700;
        }
        .badge-long { background: rgba(0, 230, 118, 0.15); color: var(--green); border: 1px solid rgba(0, 230, 118, 0.3); }
        .badge-short { background: rgba(255, 59, 105, 0.15); color: var(--red); border: 1px solid rgba(255, 59, 105, 0.3); }

        /* AI Insight */
        .ai-brain {
            background: linear-gradient(145deg, rgba(16, 18, 27, 0.8), rgba(9, 10, 15, 0.9));
            border: 1px solid rgba(255, 138, 0, 0.3);
            border-radius: 20px; padding: 30px;
            position: relative; overflow: hidden;
        }
        .ai-brain::after {
            content: ''; position: absolute; top: 0; right: 0; width: 150px; height: 150px;
            background: radial-gradient(circle, var(--accent-glow) 0%, transparent 70%);
        }
        .ai-brain p { font-size: 16px; line-height: 1.8; color: #d1d5db; margin: 15px 0; }
        .ai-brain strong { color: var(--accent); font-weight: 700; }

        /* Mobile Adjustments */
        @media (max-width: 768px) {
            .nav-container { padding: 0; }
            .nav-tabs {
                position: fixed; bottom: 0; left: 0; right: 0; z-index: 100;
                background: rgba(9, 10, 15, 0.95); backdrop-filter: blur(20px);
                border-top: 1px solid var(--border); border-radius: 20px 20px 0 0;
                padding: 15px 10px; padding-bottom: max(15px, env(safe-area-inset-bottom));
                justify-content: space-around; gap: 5px;
            }
            .nav-tab {
                flex: 1; text-align: center; padding: 10px 5px; font-size: 13px;
                border: none; background: transparent; border-radius: 10px;
            }
            .nav-tab.active { background: rgba(255,255,255,0.05); box-shadow: none; border-bottom: 2px solid var(--accent); border-radius: 0; }
            .dashboard-container { padding: 15px; padding-bottom: 100px; }
            .metrics-grid { grid-template-columns: 1fr 1fr; }
            .metric-value { font-size: 20px; }
            .chart-wrapper { height: 400px; }
        }
    </style>
</head>
<body>
    <div class="top-navbar">
        <div class="brand">
            <div class="brand-icon">GP</div>
            <div class="brand-title">GoldenPath AI</div>
        </div>
        <div style="font-family:'JetBrains Mono',monospace; font-size: 14px; color:var(--text-muted); font-weight:700;">
            v3.0.0-T3
        </div>
    </div>
    
    <div class="nav-container">
        <div class="nav-tabs">
            <div class="nav-tab active" data-target="panel-status">대시보드</div>
            <div class="nav-tab" data-target="panel-chart">실시간 마켓</div>
            <div class="nav-tab" data-target="panel-history">포지션/내역</div>
            <div class="nav-tab" data-target="panel-ai">AI 분석</div>
        </div>
    </div>

    <div class="dashboard-container">
        
        <!-- PANEL 1: Status & Balance -->
        <div id="panel-status" class="panel active-panel">
            <div class="card status-hero">
                <div id="status-badge" class="status-badge">
                    <div class="status-dot"></div><span id="sys-status">엔진 스캔 중...</span>
                </div>
                <div style="margin-top:20px; font-size: 14px; color:var(--text-muted); font-weight:600; letter-spacing:1px">엔진 가동 시간</div>
                <div id="uptime-val" style="font-family:'JetBrains Mono',monospace; font-size: 46px; font-weight:800; margin-top:5px; text-shadow: 0 0 20px rgba(255,255,255,0.2);">00:00:00</div>
            </div>

            <div class="metrics-grid">
                <div class="metric-box">
                    <div class="metric-label">현재 가용 잔고</div>
                    <div id="balance-val" class="metric-value green">$0.00</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">총 자산 (Equity)</div>
                    <div id="equity-val" class="metric-value">$0.00</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">적용 알고리즘</div>
                    <div class="metric-value highlight" style="font-size: 18px; font-family:'Outfit'">T3_MTF_5m</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">최대 레버리지</div>
                    <div class="metric-value" style="font-size: 22px">30x</div>
                </div>
            </div>
            
            <button class="kill-switch" onclick="stopBot()">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"></path><line x1="12" y1="2" x2="12" y2="12"></line></svg>
                긴급 킬 스위치 (강제 셧다운)
            </button>
        </div>

        <!-- PANEL 2: Chart -->
        <div id="panel-chart" class="panel">
            <div class="card" style="padding: 20px;">
                <div class="coin-selectors">
                    <button class="coin-btn active" data-symbol="BINANCE:BTCUSDT">BTC/USDT</button>
                    <button class="coin-btn" data-symbol="BINANCE:ETHUSDT">ETH/USDT</button>
                    <button class="coin-btn" data-symbol="BINANCE:SOLUSDT">SOL/USDT</button>
                    <button class="coin-btn" data-symbol="BINANCE:XRPUSDT">XRP/USDT</button>
                </div>
                <div class="chart-wrapper">
                    <div id="tv_chart" style="height: 100%; width: 100%;"></div>
                </div>
            </div>
        </div>

        <!-- PANEL 3: History & Positions -->
        <div id="panel-history" class="panel">
            <div class="card" style="padding: 0; overflow: hidden;">
                <div class="card-header" style="padding: 25px 25px 10px 25px; margin:0;">🚀 Active Positions</div>
                <div class="data-table-container" style="border:none; border-radius:0;">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Symbol</th>
                                <th>Side</th>
                                <th style="text-align:right">Size</th>
                                <th style="text-align:right">Entry Price</th>
                            </tr>
                        </thead>
                        <tbody id="positions-body">
                            <tr><td colspan="4" style="text-align:center; color:var(--text-muted); padding: 30px;">포지션 대기 중...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <div class="card" style="padding: 0; overflow: hidden;">
                <div class="card-header" style="padding: 25px 25px 10px 25px; margin:0;">📋 System Event Log</div>
                <div class="data-table-container" style="border:none; border-radius:0;">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>Event</th>
                                <th>Symbol</th>
                                <th style="text-align:right">Detail</th>
                            </tr>
                        </thead>
                        <tbody id="history-body">
                            <tr><td colspan="4" style="text-align:center; color:var(--text-muted); padding: 30px;">로그 수집 중...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        
        <!-- PANEL 4: AI Insights -->
        <div id="panel-ai" class="panel">
            <div class="ai-brain">
                <div class="card-header" style="color:var(--accent);">GoldenPath Deep-Q Core</div>
                <p>현재 <strong>4시간(4H) 멀티타임프레임(MTF)</strong> 스캔을 통해 거시적 추세를 판별하고, <strong>5분(5m) 프랙탈 돌파</strong> 조건에 부합하는 타점을 실시간으로 추적 중입니다.</p>
                <p>시장 변동성(ATR)을 기반으로 진입 시나리오가 갱신되며, 공격적 <strong>켈리 배팅(최대 30x)</strong>과 엄격한 <strong>고정 비율 손절망(5% Risk)</strong>을 동시에 유지하여 생존력을 극대화하고 있습니다.</p>
                <div style="margin-top: 30px; display:inline-block; padding:10px 20px; background:rgba(0,229,255,0.1); border:1px solid var(--cyan); border-radius:10px; color:var(--cyan); font-weight:700; font-size:14px; letter-spacing:1px;">
                    STATUS: T3_MTF_5m ACTIVE 🟢
                </div>
            </div>
        </div>

    </div>

    <script>
        // Tab System
        const tabs = document.querySelectorAll('.nav-tab');
        const panels = document.querySelectorAll('.panel');
        
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                tabs.forEach(t => t.classList.remove('active'));
                panels.forEach(p => p.classList.remove('active-panel'));
                
                tab.classList.add('active');
                document.getElementById(tab.getAttribute('data-target')).classList.add('active-panel');
            });
        });

        // TradingView
        let tvWidget = null;
        function initChart(symbol) {
            if(tvWidget !== null) document.getElementById('tv_chart').innerHTML = '';
            tvWidget = new TradingView.widget({
                "autosize": true,
                "symbol": symbol,
                "interval": "240",
                "timezone": "Asia/Seoul",
                "theme": "dark", // Changed to dark theme!
                "style": "1",
                "locale": "kr",
                "enable_publishing": false,
                "backgroundColor": "#090a0f",
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
        }
        
        document.querySelectorAll('.coin-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.coin-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                initChart(e.target.dataset.symbol);
            });
        });
        initChart("BINANCE:BTCUSDT");

        // API Fetch
        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                const badge = document.getElementById('status-badge');
                const sysStatus = document.getElementById('sys-status');
                
                if (data.status === "STARTING" || data.status === "RUNNING") {
                    badge.className = "status-badge";
                    sysStatus.innerText = "엔진 정상 가동 중 (LIVE)";
                } else if (data.status === "HALTED") {
                    badge.className = "status-badge stopped";
                    sysStatus.innerText = "킬 스위치 작동 (HALTED)";
                } else {
                    badge.className = "status-badge stopped";
                    badge.style.background = "rgba(139, 148, 167, 0.1)";
                    badge.style.borderColor = "#8b94a7";
                    badge.style.color = "#8b94a7";
                    badge.style.boxShadow = "none";
                    sysStatus.innerText = "엔진 오프라인";
                }
                
                if (data.started_ms) window.botStartedMs = data.started_ms;
                
                if (data.cash !== undefined) {
                    document.getElementById('balance-val').innerText = `$${parseFloat(data.cash).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                }
                if (data.equity !== undefined) {
                    document.getElementById('equity-val').innerText = `$${parseFloat(data.equity).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                }
                
                // Positions
                const posBody = document.getElementById('positions-body');
                if (data.positions && Object.keys(data.positions).length > 0) {
                    posBody.innerHTML = '';
                    for (const [symbol, pos] of Object.entries(data.positions)) {
                        let sideClass = pos.size > 0 ? 'badge-long' : 'badge-short';
                        let sideText = pos.size > 0 ? 'LONG' : 'SHORT';
                        posBody.innerHTML += `<tr>
                            <td style="font-weight:bold; color:var(--text-main);">${symbol.replace('USDT', '')}</td>
                            <td><span class="badge ${sideClass}">${sideText}</span></td>
                            <td style="text-align:right; color:var(--text-main);">${Math.abs(pos.size)}</td>
                            <td style="text-align:right; color:var(--text-main);">$${parseFloat(pos.entry_price).toLocaleString()}</td>
                        </tr>`;
                    }
                } else {
                    posBody.innerHTML = `<tr><td colspan="4" style="text-align:center; color:var(--text-muted); padding: 30px;">현재 진입한 포지션이 없습니다.</td></tr>`;
                }

                // History
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
                        else detailStr = JSON.stringify(row.detail).substring(0, 40) + "...";
                        
                        let badgeCol = "";
                        if (row.kind.includes("ORDER")) badgeCol = `color:var(--green)`;
                        else if (row.kind.includes("ERROR")) badgeCol = `color:var(--red)`;
                        else badgeCol = `color:var(--cyan)`;
                        
                        tbody.innerHTML += `<tr>
                            <td style="color:var(--text-muted)">${timeStr}</td>
                            <td style="font-weight:700; ${badgeCol}">${row.kind}</td>
                            <td style="color:var(--text-main)">${row.symbol ? row.symbol.replace('USDT','') : 'SYS'}</td>
                            <td style="text-align:right; color:var(--text-main);">${detailStr}</td>
                        </tr>`;
                    });
                }
            } catch (e) {
                console.error(e);
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
            setInterval(fetchStatus, 3000);
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
            
            if os.path.exists(live_state_path):
                try:
                    with open(live_state_path, "r", encoding="utf-8") as f:
                        state = json.load(f)
                        data.update(state)
                        if data.get("status") == "OFFLINE" and "status" in state:
                            data["status"] = state["status"]
                except Exception as e:
                    data["error"] = f"JSON load error: {e}"

            elif os.path.exists(db_path):
                try:
                    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3)
                    cursor = conn.cursor()
                    
                    row = cursor.execute("SELECT payload FROM portfolio WHERE id=1").fetchone()
                    if row:
                        state = json.loads(row[0])
                        data.update(state)
                        if data.get("status") == "STARTING" and data.get("last_cycle_ms", 0) > 0:
                            data["status"] = "RUNNING"
                        elif "status" in state and state["status"] not in ["HALTED", "STOPPED", "ERROR"] and data.get("status") == "OFFLINE":
                            data["status"] = "RUNNING"
                            
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
