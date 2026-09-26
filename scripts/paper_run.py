import logging
from src.bitget_bot.config import load_settings
from src.bitget_bot.engine import PaperEngine
from src.bitget_bot.store import Store
from src.bitget_bot.models import Candle

class MockFeed:
    def __init__(self, start_ts):
        self.now = start_ts
        self.events = []
    
    def price(self, symbol):
        return 50000.0

    def ticker(self, symbol):
        from src.bitget_bot.models import Ticker
        return Ticker(symbol, self.now, 50000.0)

    def history(self, symbol, interval_ms, limit):
        return [Candle(self.now - (i * interval_ms), 50000, 50000, 50000, 50000, 100) for i in range(limit, 0, -1)]

def main():
    logging.basicConfig(level=logging.INFO)
    settings = load_settings("config/paper.toml")
    feed = MockFeed(1000 * 3600 * 1000)
    store = Store(":memory:")
    
    # Initialize Engine
    engine = PaperEngine(settings, feed, store, clock=lambda: feed.now)
    
    import src.bitget_bot.strategy_v2 as v2
    from src.bitget_bot.models import Signal
    
    orig_eval = v2.Policy.evaluate
    def mock_eval(self, symbol, history, now, config):
        return Signal(symbol, 1, history[-1].ts, history[-1].close, history[-1].close - 100, self.name)
    
    v2.Policy.evaluate = mock_eval
    
    state = engine.cycle()
    print(f"Engine status after cycle 1: {state['status']}")
    print(f"Positions: {list(state['positions'].keys())}")
    
    if "BTCUSDT" in state["positions"]:
        print("Successfully opened position with V2 strategy!")
        
    v2.Policy.evaluate = orig_eval
    
if __name__ == '__main__':
    main()
