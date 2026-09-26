import time
import uuid
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

@dataclass
class OrderResult:
    client_oid: str
    status: str
    filled_qty: float
    avg_price: float
    error: Optional[str] = None

class DurableExecutionEngine:
    """
    거래소 API 장애, 핑 지연, 강제 종료 상황에서도 
    '이중 주문'과 '누락'을 막는 실전형 주문 체결 엔진입니다.
    """
    def __init__(self, transport, max_retries=3):
        self.transport = transport
        self.max_retries = max_retries

    def generate_client_oid(self, symbol: str, intent: str) -> str:
        """
        주문의 고유 영수증 번호 생성 (Idempotency Key).
        """
        unique_id = uuid.uuid4().hex[:8]
        return f"{symbol}-{intent}-{unique_id}"

    def get_order_status(self, symbol: str, client_oid: str) -> Optional[Dict[str, Any]]:
        """
        비트겟 서버에 clientOid를 기반으로 해당 주문이 살았는지 죽었는지 조회.
        """
        try:
            # /api/v3/trade/history-orders or unfulfilled-orders
            # Bitget UTA v3: GET /api/v3/mix/order/detail
            response = self.transport.request(
                "GET", "/api/v3/trade/order-info", 
                params={"symbol": symbol, "clientOid": client_oid},
                private=True
            )
            # Response is typically a list, find our order
            if isinstance(response, list) and len(response) > 0:
                return response[0]
            elif isinstance(response, dict):
                return response
            return None
        except Exception as e:
            logger.error(f"주문 상태 조회 실패: {e}")
            return None

    def execute_order_safely(self, symbol: str, side: int, qty: float, price: float, intent: str) -> OrderResult:
        """
        주문 실행 및 자동 에러 복구 로직 (Durable Intent의 핵심)
        """
        client_oid = self.generate_client_oid(symbol, intent)
        
        # Bitget UTA V3 Place Order Payload
        payload = {
            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "marginMode": "isolated",
            "marginCoin": "USDT",
            "tradeSide": "buy" if side == 1 else "sell",
            "orderType": "limit",
            "price": str(price),
            "size": str(qty),
            "clientOid": client_oid
        }

        for attempt in range(self.max_retries):
            try:
                # 1. 거래소로 주문 쏘기 (POST)
                logger.info(f"[{attempt+1}/{self.max_retries}] 실주문 발송 시도: {client_oid}")
                response = self.transport.request("POST", "/api/v3/trade/place-order", payload=payload, private=True)
                
                # 2. 체결 대기 및 확인 (Reconciliation)
                time.sleep(0.5) # 잠시 대기
                status = self.get_order_status(symbol, client_oid)
                
                if status and status.get("state") in ("filled", "partially_filled"):
                    return OrderResult(
                        client_oid, 
                        status.get("state").upper(), 
                        float(status.get("baseVolume", qty)), 
                        float(status.get("priceAvg", price))
                    )
                
                # 만약 아직 new(미체결) 상태라면 로컬에서 모니터링 큐로 넘겨야 함.
                return OrderResult(client_oid, "NEW", 0, price)

            except Exception as e:
                logger.warning(f"네트워크/응답 에러 발생: {e}. 주문 상태 확인 돌입.")
                # 응답을 못 받았을 뿐, 비트겟 서버에는 체결이 되었을 수 있음!
                status = self.get_order_status(symbol, client_oid)
                if status and status.get("state") in ("filled", "partially_filled"):
                    logger.info("조회 결과 이미 정상 체결됨을 확인!")
                    return OrderResult(
                        client_oid, 
                        status.get("state").upper(), 
                        float(status.get("baseVolume", qty)), 
                        float(status.get("priceAvg", price))
                    )
                
                time.sleep(1) # 잠시 대기 후 재시도
        
        return OrderResult(client_oid, "FAILED", 0, 0, "MAX_RETRIES_EXCEEDED")

    def sync_positions_on_boot(self):
        """
        재부팅 시 거래소의 실제 포지션을 가져와 로컬 DB와 맞추는 동기화(Reconciliation).
        """
        logger.info("재부팅 동기화 시작: 비트겟 거래소 내 실제 포지션 내역을 가져옵니다.")
        try:
            positions = self.transport.request("GET", "/api/v2/mix/position/all-position", params={"productType": "USDT-FUTURES", "marginCoin": "USDT"}, private=True)
            logger.info(f"거래소 동기화 완료. 확보된 포지션 수: {len(positions) if isinstance(positions, list) else 0}")
            return positions
        except Exception as e:
            logger.error(f"포지션 동기화 실패. 봇 기동을 중단합니다: {e}")
            raise
