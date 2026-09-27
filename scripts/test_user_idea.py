import json
from pathlib import Path
from decimal import Decimal, ROUND_FLOOR
from src.bitget_bot.config import load_settings
from src.bitget_bot.models import Candle, Sizing
from src.bitget_bot.strategy_t3 import FeatureBook, candidate, Policy, NAMES
import src.bitget_bot.risk as risk
import scripts.t3_simulate as sim

# --- User's Custom Logic Override ---
def custom_size_position(equity, entry, stop, instrument, config, open_risk=0, used_margin=0, gross_notional=0, drawdown=0):
    distance = abs(entry - stop)
    if distance <= 0: return None
    
    # Calculate ATR fraction to determine volatility
    # Since config.atr_multiplier was passed, we reverse engineer current_atr
    # Actually, we can just use the config's high_vol_atr_fraction to decide
    # In the override evaluate(), we pass the dynamic stop.
    # To keep it simple, we just determine leverage based on volatility here.
    # But wait, stop is already set. Let's just determine leverage based on distance.
    # If distance is > 1.5% of price, consider it high vol.
    is_high_vol = (distance / entry) > 0.015
    
    leverage = 10 if is_high_vol else 30
    
    # ALL-IN MARGIN: Use 95% of available equity
    available_margin = equity * 0.95
    notional = available_margin * leverage
    
    step = Decimal(str(instrument.qty_step))
    raw_qty = Decimal(str(notional / entry))
    qty = float((raw_qty / step).to_integral_value(rounding=ROUND_FLOOR) * step)
    
    if qty <= 0: return None
    
    actual_notional = qty * entry
    margin = actual_notional / leverage
    risk_cash = qty * distance
    
    # We ignore the fixed risk budget entirely!
    return Sizing(qty, leverage, actual_notional, margin, risk_cash)

# Monkey-patch risk sizing
sim.size_position = custom_size_position

class UserPolicy(Policy):
    def evaluate(self, symbol, history, stamp, config):
        # Call original evaluate
        decision = super().evaluate(symbol, history, stamp, config)
        if decision is None:
            return None
            
        bar = history[-1]
        frames = self.book.at(symbol, history)
        action = frames["action"]
        if not action:
            return None
        current_atr = action["atr"]
        
        # Determine volatility state
        is_high_vol = (current_atr / bar.close) > 0.0075 # Roughly 0.75% ATR per 5m is huge
        
        # User Idea: 1.5 multiplier if high vol, 2.5 if normal
        multiplier = 1.5 if is_high_vol else 2.5
        
        # Recalculate initial stop
        from dataclasses import replace
        distance = multiplier * current_atr
        if decision.side == 1:
            new_stop = decision.entry - distance
        else:
            new_stop = decision.entry + distance
            
        return replace(decision, stop=new_stop)

def run_user_test():
    cfg = load_settings("config/paper.toml")
    cfg = sim.replace(cfg, candle_interval_ms=sim.INTERVAL_MS)
    
    print("Loading 30d dataset...")
    raw = json.loads(Path("artifacts/history_t3_5m.json").read_text(encoding="utf-8"))
    dataset = {s: [Candle(**c) for c in rows] for s, rows in raw["symbols"].items()}
    book = FeatureBook(dataset)
    
    count = len(next(iter(dataset.values())))
    name = "t3_trend4h_5m"
    cand_cfg = candidate(name, cfg)
    
    # Use UserPolicy
    pol = UserPolicy(name, book)
    
    print(f"Running user's ALL-IN logic on {count} candles...")
    result = sim._simulate(dataset, cand_cfg.settings, None, None, 3000, count, policy=pol)
    
    print(f"--- USER IDEA TEST RESULTS ---")
    print(f"Net PnL: ${result['net_pnl']:.2f} (from initial ${result['initial_equity']})")
    print(f"Profit Factor: {result['profit_factor']}")
    print(f"Trade Count: {result['trade_count']}")
    print(f"Max Drawdown: {result['max_drawdown']*100:.2f}%")
    print(f"Halt Reason: {result['halt']}")

if __name__ == '__main__':
    run_user_test()
