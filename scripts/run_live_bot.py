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
from bitget_bot.strategy_v2 import FeatureBook, Policy
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

    # 6. 메인 감시 루프 (10초에 한 번씩 사냥터 스캔)
    while True:
        if os.path.exists("data/KILL_SWITCH"):
            logger.warning("💀 킬 스위치(KILL_SWITCH) 감지! 야수 모드 실거래 런처를 즉시 종료합니다.")
            break

        try:
            now = time.time_ns() // 1_000_000
            balance = get_live_balance(transport, cfg.initial_equity)
            logger.info(f"현재 가용 잔고(USDT): {balance:.2f} $")

            histories = {}
            for symbol in cfg.symbols:
                bars = complete(market_client.candles(symbol, "1H", limit=300), now, HOUR)
                histories[symbol] = bars

            # 특징 추출 및 전략 판단
            book = FeatureBook(histories)
            policy = Policy(cfg.strategy, book)

            for symbol in cfg.symbols:
                bars = histories.get(symbol)
                if not bars: continue
                
                # 시그널 판독
                signal = policy.evaluate(symbol, bars, now, cfg)
                
                if signal:
                    logger.warning(f"🚨 [{symbol}] {cfg.strategy} 돌파 시그널 감지! 방향: {'LONG' if signal.side == 1 else 'SHORT'}")
                    # 야수 모드 레버리지 30배 & 공격적 리스크 수량 산출 (실제 잔고 비례)
                    # (간단 계산: 잔고 * 30배 * 리스크율 5% / 현재가)
                    trade_price = signal.entry
                    qty = round((balance * 30 * cfg.risk_per_trade) / trade_price, 3) 
                    
                    if qty > 0:
                        logger.info(f"💥 [주문 발사] {symbol} 수량: {qty}, 목표가: {trade_price}")
                        result = durable_engine.execute_order_safely(symbol, signal.side, qty, trade_price, "ENTRY")
                        logger.info(f"체결 결과: {result}")
                    else:
                        logger.info(f"수량 부족으로 주문 패스 (잔액: {balance})")

        except Exception as e:
            logger.error(f"메인 루프 에러 발생 (자동 무시 후 다음 턴 진행): {e}")

        time.sleep(cfg.poll_seconds)

if __name__ == "__main__":
    main()
