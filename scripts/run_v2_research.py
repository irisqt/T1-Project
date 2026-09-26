import json
from pathlib import Path
from src.bitget_bot.config import load_settings
from src.bitget_bot.models import Candle
from src.bitget_bot.strategy_v2 import NAMES, FeatureBook, candidate, Policy
import src.bitget_bot.research as res
from src.bitget_bot.research import _simulate

def patch_and_run():
    cfg = load_settings("config/paper.toml")
    raw = json.loads(Path("artifacts/history_180d_20260923.json").read_text(encoding="utf-8"))
    dataset = {s: [Candle(**c) for c in rows] for s, rows in raw["symbols"].items()}
    book = FeatureBook(dataset)
    
    results = []
    
    # We will temporarily mock res.evaluate and res.trailing_stop
    original_evaluate = res.evaluate
    original_trailing_stop = res.trailing_stop
    
    for name in NAMES:
        if name == "baseline_breakout24": continue
        print(f"Testing {name}...")
        
        cand_cfg = candidate(name, cfg)
        pol = Policy(name, book)
        
        # mock evaluate
        def patched_evaluate(symbol, history, now, config):
            return pol.evaluate(symbol, history, now, config)
            
        # mock trailing_stop
        # In _simulate, trailing_stop is called like: 
        # p["stop"] = trailing_stop(p["side"], p["stop"], history, config)
        # But Policy.trailing_stop requires (symbol, position, history, config)
        # However, _simulate doesn't provide symbol or position to trailing_stop easily.
        # Wait, let's look at _simulate's code in research.py:
        # for symbol, p in positions.items():
        #     history = streams[symbol][max(0, index-config.history_limit+1):index+1]
        #     p["stop"] = trailing_stop(p["side"], p["stop"], history, config)
        
        # We need a different approach. We can patch _simulate directly, or rewrite the trailing_stop call.
        pass

if __name__ == "__main__":
    patch_and_run()
