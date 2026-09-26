import json
from pathlib import Path

def generate_v2_simulate():
    code = Path('src/bitget_bot/research.py').read_text(encoding='utf-8')
    code = code.replace('from .strategy import _valid, evaluate, trailing_stop', 'from .strategy import _valid')
    code = code.replace('def _simulate(dataset, config, instruments, funding, start_index, end_index):', 'def _simulate(dataset, config, instruments, funding, start_index, end_index, policy=None):')
    code = code.replace('p["stop"] = trailing_stop(p["side"], p["stop"], history, config)', 'p["stop"] = policy.trailing_stop(symbol, p, history, config)')
    code = code.replace('decision = evaluate(symbol, history, stamp+HOUR_MS, config)', 'decision = policy.evaluate(symbol, history, stamp+HOUR_MS, config)')
    
    # Insert exit_signal logic
    exit_logic = """for symbol, p in list(positions.items()):
            if policy.exit_signal(symbol, p, streams[symbol][max(0, index-config.history_limit+1):index+1], config):
                exit_position(symbol, closes[symbol], stamp+HOUR_MS, "strategy_exit")
        if not permanent_halt and stamp+HOUR_MS >= pause_until and index+1 < end:"""
    code = code.replace('if not permanent_halt and stamp+HOUR_MS >= pause_until and index+1 < end:', exit_logic)

    header = '''
from src.bitget_bot.strategy_v2 import FeatureBook, candidate, Policy, NAMES
import src.bitget_bot.models as models
import src.bitget_bot.risk as risk
Instrument = models.Instrument
size_position = risk.size_position
'''

    code = header + code

    # also patch run_research to use strategy_v2
    run_res_patch = """
def run_v2_research():
    import json
    from src.bitget_bot.config import load_settings
    from src.bitget_bot.models import Candle
    
    cfg = load_settings("config/paper.toml")
    raw = json.loads(Path("artifacts/history_180d_20260923.json").read_text(encoding="utf-8"))
    dataset = {s: [Candle(**c) for c in rows] for s, rows in raw["symbols"].items()}
    book = FeatureBook(dataset)
    
    common_warmup = 100
    count = len(next(iter(dataset.values())))
    split = common_warmup + int((count-common_warmup)*.8)
    folds = [(common_warmup+(split-common_warmup)*i//3,
              common_warmup+(split-common_warmup)*(i+1)//3) for i in range(3)]
              
    results = []
    for name in NAMES:
        if name == "baseline_breakout24": continue
        print(f"Testing {name}...")
        cand_cfg = candidate(name, cfg)
        pol = Policy(name, book)
        
        # Test on cost_multiple = 1 only for speed
        for number, (left, right) in enumerate(folds, 1):
            result = _simulate(dataset, cand_cfg, None, None, left, right, policy=pol)
            results.append({
                "candidate": name,
                "fold": number,
                "net_pnl": result["net_pnl"],
                "profit_factor": result["profit_factor"],
                "trade_count": result["trade_count"],
                "max_drawdown": result["max_drawdown"]
            })
            print(f"  Fold {number}: {result['net_pnl']:.2f} PnL, {result['trade_count']} trades, PF {result['profit_factor']}")

if __name__ == '__main__':
    run_v2_research()
"""
    code += run_res_patch
    Path('scripts/v2_simulate.py').write_text(code, encoding='utf-8')

generate_v2_simulate()
