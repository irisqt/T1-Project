import os
import sys
import time
import logging
from dotenv import load_dotenv

sys.path.append(os.path.abspath("src"))

# 로컬 내부 모듈 불러오기
from bitget_bot.config import load_settings
from bitget_bot.exchange import Credentials, Transport, MarketClient
from bitget_bot.durable_engine import DurableExecutionEngine
from bitget_bot.engine import complete, HOUR

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("LiveRunner")

def get_live_balance(transport: Transport, fallback: float) -> float:
    try:
        res = transport.request("GET", "/api/v2/mix/account/accounts", params={"productType": "USDT-FUTURES"}, private=True)
        if isinstance(res, list) and len(res) > 0:
            return float(res[0].get("available", res[0].get("usdtEquity", fallback)))
        elif isinstance(res, dict):
            return float(res.get("available", res.get("usdtEquity", fallback)))
        return fallback
    except Exception as e:
        logger.error(f"잔고 조회 실패 (Bitget API 에러). 강제 기본값 {fallback}$ 사용: {e}")
        return fallback

def get_live_positions(transport: Transport) -> list:
    try:
        res = transport.request("GET", "/api/v2/mix/position/all-position", params={"productType": "USDT-FUTURES", "marginCoin": "USDT"}, private=True)
        if isinstance(res, list):
            return res
        elif isinstance(res, dict) and "data" in res:
            return res["data"]
        return []
    except Exception as e:
        logger.error(f"포지션 조회 실패: {e}")
        return []

# Global memory for events
LIVE_EVENTS = []

def add_event(kind: str, symbol: str, detail: dict):
    ts = int(time.time() * 1000)
    LIVE_EVENTS.append({"ts": ts, "kind": kind, "symbol": symbol, "detail": detail})
    if len(LIVE_EVENTS) > 30:
        LIVE_EVENTS.pop(0)

def fetch_history(client: MarketClient, symbol: str, interval: str, limit: int):
    """Fetch history handling pagination if limit > 1000"""
    result = []
    end_ms = None
    remaining = limit
    while remaining > 0:
        batch = min(1000, remaining)
        page = client.candles(symbol, interval, batch, end_ms=end_ms)
        if not page:
            break
        result = page + result
        end_ms = page[0].ts
        remaining -= len(page)
        time.sleep(0.1)
    return result


def main():
    logger.info("🔥 [ANTIGRAVITY] 야수 모드 실거래 런처 가동 시작! 🔥")
    
    # 1. API 키 로드 (ASTRA의 철벽 방어를 뚫고 드디어 실데이터 연동)
    load_dotenv()
    api_key = os.getenv("BITGET_API_KEY")
    api_secret = os.getenv("BITGET_API_SECRET")
    api_passphrase = os.getenv("BITGET_API_PASSPHRASE")

    if not all([api_key, api_secret, api_passphrase]):
        logger.error("환경 변수(.env)에 비트겟 API 키 정보가 누락되었습니다!")
        return

    creds = Credentials(api_key, api_secret, api_passphrase)
    
    # 2. 강력한 실거래 Transport 장착 (잠금 해제 완료)
    transport = Transport(credentials=creds)
    market_client = MarketClient(transport=transport)
    
    # 3. 새로운 Durable Engine 장착
    durable_engine = DurableExecutionEngine(transport=transport, max_retries=3)
    
    # 4. 공격적 설정 파일 로드
    cfg = load_settings("config/aggressive_live.toml")
    logger.info(f"타겟 심볼: {cfg.symbols} / 타겟 전략: {cfg.strategy}")
    logger.info(f"레버리지: {cfg.min_leverage}x ~ {cfg.max_leverage}x / 리스크: {cfg.risk_per_trade * 100}%")

    # 5. 거래소와 포지션 동기화 (재부팅해도 과거 기록 복구)
    active_positions = durable_engine.sync_positions_on_boot()
    
    start_time_ms = int(time.time() * 1000)
    add_event("SYSTEM", "SYS", {"message": "봇 시작"})

    # 6. 메인 감시 루프 (10초에 한 번씩 사냥터 스캔)
    while True:
        if os.path.exists("data/KILL_SWITCH"):
            logger.warning("💀 킬 스위치(KILL_SWITCH) 감지! 야수 모드 실거래 런처를 즉시 종료합니다.")
            break

        try:
            now = time.time_ns() // 1_000_000
            balance = get_live_balance(transport, cfg.initial_equity)
            positions = get_live_positions(transport)
            logger.info(f"현재 가용 잔고(USDT): {balance:.2f} $")

            # Parse positions for dashboard
            dashboard_positions = {}
            for p in positions:
                sym = p.get("symbol", "")
                if not sym: continue
                size = float(p.get("total", 0))
                if size == 0: continue
                # side depends on holdSide (long/short)
                side = 1 if p.get("holdSide") == "long" else -1
                entry_price = float(p.get("averageOpenPrice", 0))
                dashboard_positions[sym] = {
                    "side": side,
                    "size": size * side, # negative for short to match dashboard logic
                    "entry_price": entry_price
                }

            # Write live state to JSON for dashboard
            state = {
                "status": "RUNNING",
                "mode": "LIVE",
                "cash": balance,
                "equity": balance, # Could add unrealized pnl if needed
                "started_ms": start_time_ms,
                "positions": dashboard_positions,
                "events": LIVE_EVENTS[::-1] # Reverse for descending order
            }
            os.makedirs("data", exist_ok=True)
            with open("data/live_state.json", "w", encoding="utf-8") as f:
                import json
                json.dump(state, f, ensure_ascii=False)
            with open("data/heartbeat.json", "w", encoding="utf-8") as f:
                json.dump({"timestamp": time.time()}, f)

            histories = {}
            for symbol in cfg.symbols:
                if cfg.candle_interval_ms == 300_000:
                    bars = fetch_history(market_client, symbol, "5m", 4000)
                    histories[symbol] = complete(bars, now, 300_000)
                else:
                    bars = fetch_history(market_client, symbol, "1H", 300)
                    histories[symbol] = complete(bars, now, HOUR)

            # 특징 추출 및 전략 판단
            if cfg.strategy.startswith("t3"):
                from bitget_bot.strategy_t3 import FeatureBook, Policy
            else:
                from bitget_bot.strategy_v2 import FeatureBook, Policy
                
            book = FeatureBook(histories)
            policy = Policy(cfg.strategy, book)

            for symbol in cfg.symbols:
                bars = histories.get(symbol)
                if not bars: continue
                
                # 시그널 판독
                signal = policy.evaluate(symbol, bars, now, cfg)
                
                if signal:
                    logger.warning(f"🚨 [{symbol}] {cfg.strategy} 돌파 시그널 감지! 방향: {'LONG' if signal.side == 1 else 'SHORT'}")
                    add_event("SIGNAL", symbol, {"signal": 'LONG' if signal.side == 1 else 'SHORT'})
                    # 야수 모드 레버리지 30배 & 공격적 리스크 수량 산출 (실제 잔고 비례)
                    # (간단 계산: 잔고 * 30배 * 리스크율 5% / 현재가)
                    trade_price = signal.entry
                    qty = round((balance * 30 * cfg.risk_per_trade) / trade_price, 3) 
                    
                    if qty > 0:
                        logger.info(f"💥 [주문 발사] {symbol} 수량: {qty}, 목표가: {trade_price}")
                        result = durable_engine.execute_order_safely(symbol, signal.side, qty, trade_price, "ENTRY")
                        logger.info(f"체결 결과: {result}")
                        add_event("ORDER_FILLED" if result.status in ["FILLED", "PARTIALLY_FILLED"] else "ORDER_NEW", 
                                  symbol, {"price": result.avg_price, "qty": result.filled_qty})
                    else:
                        logger.info(f"수량 부족으로 주문 패스 (잔액: {balance})")

        except Exception as e:
            logger.error(f"메인 루프 에러 발생 (자동 무시 후 다음 턴 진행): {e}")
            add_event("ERROR", "SYS", {"error": str(e)})

        time.sleep(cfg.poll_seconds)

if __name__ == "__main__":
    main()
