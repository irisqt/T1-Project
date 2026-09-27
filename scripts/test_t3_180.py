import json
from pathlib import Path
from src.bitget_bot.config import load_settings
from src.bitget_bot.models import Candle
from src.bitget_bot.strategy_t3 import FeatureBook, candidate, Policy, NAMES
from scripts.t3_simulate import _simulate, INTERVAL_MS
from dataclasses import replace

def run_180d_test():
    cfg = load_settings("config/paper.toml")
    cfg = replace(cfg, candle_interval_ms=INTERVAL_MS)
    
    print("Loading 180d dataset...")
    raw = json.loads(Path("artifacts/history_t3_180d.json").read_text(encoding="utf-8"))
    dataset = {s: [Candle(**c) for c in rows] for s, rows in raw["symbols"].items()}
    book = FeatureBook(dataset)
    
    common_warmup = 3000
    count = len(next(iter(dataset.values())))
    
    name = "t3_trend4h_5m"
    print(f"Testing {name} on {count} candles (approx 180 days)...")
    cand_cfg = candidate(name, cfg)
    pol = Policy(name, book)
    
    result = _simulate(dataset, cand_cfg.settings, None, None, common_warmup, count, policy=pol)
    print(f"Net PnL: {result['net_pnl']:.2f}")
    print(f"Profit Factor: {result['profit_factor']}")
    print(f"Trade Count: {result['trade_count']}")
    print(f"Max Drawdown: {result['max_drawdown']:.4f}")
    print(f"Win Rate: {result['win_rate']}")

if __name__ == '__main__':
    run_180d_test()
