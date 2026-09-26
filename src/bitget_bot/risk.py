"""Pure cash-risk sizing. Leverage is a margin setting, not a risk multiplier."""
from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
import math
from .models import Sizing


def size_position(equity, entry, stop, instrument, config, open_risk=0,
                  used_margin=0, gross_notional=0, drawdown=0):
    """Floor size to contract steps and enforce a single correlated-risk cluster.

    Dynamic leverage is the greatest integer satisfying a conservative proxy:
    1/leverage > maintenance + 2*stop_distance + transaction_costs + reserve.
    This is NOT an exchange liquidation-price calculation. Actual margin tiers,
    mark/last divergence, and fill stress remain live-promotion requirements.
    Invalid/missing metadata and a safe maximum below 5 refuse entry.
    """
    numeric = (equity, entry, stop, open_risk, used_margin, gross_notional, drawdown,
               instrument.qty_step, instrument.min_qty, instrument.min_notional,
               instrument.price_tick, instrument.maintenance_margin,
               config.risk_per_trade, config.portfolio_risk, config.fee_bps,
               config.slippage_bps, config.atr_multiplier, config.liquidation_buffer,
               config.max_margin_fraction, config.max_gross_exposure)
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool)
               and math.isfinite(x) for x in numeric):
        return None
    if (min(equity, entry, stop, instrument.qty_step, instrument.min_qty,
            instrument.min_notional, instrument.price_tick) <= 0
            or min(open_risk, used_margin, gross_notional, drawdown) < 0
            or not 0 < instrument.maintenance_margin < 1
            or not isinstance(instrument.status, str)
            or instrument.status.lower() not in {"online", "normal"}
            or drawdown >= config.max_drawdown):
        return None
    if (not isinstance(instrument.max_leverage, int) or isinstance(instrument.max_leverage, bool)
            or not 5 <= config.min_leverage <= config.max_leverage <= 30):
        return None
    if (min(config.risk_per_trade, config.portfolio_risk, config.atr_multiplier,
            config.liquidation_buffer, config.max_margin_fraction, config.max_gross_exposure) <= 0
            or min(config.fee_bps, config.slippage_bps) < 0):
        return None
    distance = abs(entry-stop)
    if distance <= 0:
        return None
    # Add one adverse tick so independent execution rounding cannot increase
    # the planned loss beyond the size budget.
    distance_with_tick = distance + instrument.price_tick
    stop_fraction = distance_with_tick / entry
    inferred_atr_fraction = distance / entry / config.atr_multiplier
    if inferred_atr_fraction > config.max_atr_fraction:
        return None
    cost_fraction = 2*(config.fee_bps + config.slippage_bps)/10_000
    denominator = (instrument.maintenance_margin
                   + config.liquidation_buffer*stop_fraction + cost_fraction + .005)
    safe_max = min(config.max_leverage, instrument.max_leverage,
                   math.floor(math.nextafter(1/denominator, 0)))
    if safe_max < config.min_leverage:
        return None
    leverage = safe_max
    scale = 1.0
    if inferred_atr_fraction >= config.high_vol_atr_fraction:
        scale *= .5
    if drawdown >= config.reduce_risk_drawdown:
        scale *= .5
    risk_budget = min(equity*config.risk_per_trade*scale,
                      equity*config.portfolio_risk-open_risk)
    available_margin = equity*config.max_margin_fraction-used_margin
    available_gross = equity*config.max_gross_exposure-gross_notional
    if min(risk_budget, available_margin, available_gross) <= 0:
        return None
    unit_risk = distance_with_tick + entry*cost_fraction
    # Reserve entry/exit charges in the margin cap as well.
    raw = min(risk_budget/unit_risk,
              available_margin/(entry/leverage + entry*cost_fraction),
              available_gross/entry)
    step = Decimal(str(instrument.qty_step))
    qty = float((Decimal(str(raw))/step).to_integral_value(rounding=ROUND_FLOOR)*step)
    notional = qty*entry
    if qty <= 0 or qty < instrument.min_qty-1e-12 or notional < instrument.min_notional-1e-9:
        return None
    margin = notional/leverage
    risk_cash = qty*unit_risk
    if (risk_cash > risk_budget + 1e-8
            or margin + notional*cost_fraction > available_margin + 1e-8
            or notional > available_gross + 1e-8):
        return None
    return Sizing(qty, leverage, notional, margin, risk_cash)
