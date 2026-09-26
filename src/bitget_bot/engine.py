"""Persistent, causal public-price paper engine. No exchange write access."""
import json
import math
from pathlib import Path
import time

from .risk import size_position
from .strategy_v2 import FeatureBook, Policy

HOUR = 3600000
MINUTE = 60000


class CandleGapError(ValueError):
    """A completed historical price path cannot be reconstructed."""

def complete(candles, now_ms, interval_ms):
    ordered = sorted(candles, key=lambda c:c.ts)
    if len({c.ts for c in ordered}) != len(ordered):
        raise ValueError("duplicate candles")
    selected = []
    for c in ordered:
        values=(c.open,c.high,c.low,c.close,c.volume)
        if not all(math.isfinite(v) for v in values) or min(values[:4])<=0 or c.volume<0 or c.low>min(c.open,c.close) or c.high<max(c.open,c.close) or c.low>c.high or c.ts % interval_ms:
            raise ValueError("invalid candle")
        if c.ts+interval_ms<=now_ms:
            selected.append(c)
    if any(b.ts-a.ts!=interval_ms for a,b in zip(selected,selected[1:])):
        raise CandleGapError("candle gap")
    return selected


def quote_healthy(q, now_ms, settings):
    values=(q.bid,q.ask,q.last,q.mark,q.index,q.funding_rate)
    if not all(math.isfinite(v) for v in values) or min(values[:5])<=0 or q.ask<q.bid:
        return False
    if not 0<=now_ms-q.received_ts<=settings.stale_quote_ms:
        return False
    return -settings.clock_skew_ms<=now_ms-q.ts<=settings.stale_quote_ms


def equity(state, quotes):
    total=state["cash"]
    for symbol,p in state["positions"].items():
        price=quotes[symbol].mark if symbol in quotes else p.get("last_mark",p["entry"])
        total+=(price-p["entry"])*p["side"]*p["qty"]
    return total


def atomic_json(path, data):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding="utf-8")
    tmp.replace(path)


class PaperEngine:
    def __init__(self, settings, client, store, clock=None):
        settings.validate()
        if settings.mode!="paper":
            raise ValueError("PaperEngine cannot send exchange orders")
        self.cfg=settings
        self.client=client
        self.store=store
        self.clock=clock or (lambda:int(time.time()*1000))
        self.state=store.initialize(settings)
        self.instruments={}

    def _halt(self, reason, now):
        if not self.state["halted"]:
            self.store.event(now,"HALTED",reason=reason)
        self.state.update(halted=True,halt_reason=reason,status="HALTED")

    def _close(self, symbol, price, ts, reason):
        p=self.state["positions"][symbol]
        fill=price*(1-p["side"]*self.cfg.slippage_bps/10000)
        fee=abs(fill*p["qty"])*self.cfg.fee_bps/10000
        gross=(fill-p["entry"])*p["side"]*p["qty"]
        net=gross-fee-p["entry_fee"]+p["funding"]
        self.state["cash"]+=gross-fee
        self.state["fees"]+=fee
        self.state["realized_pnl"]+=net
        self.state["trades"]+=1
        self.state["cooldown"][symbol]=ts+self.cfg.cooldown_bars*HOUR
        del self.state["positions"][symbol]
        self.store.event(ts,"EXIT",symbol,reason=reason,price=fill,qty=p["qty"],net_pnl=net,fee=fee,leverage=p["leverage"])

    def _fund(self,symbol,p,events,until,reference_price):
        for event in sorted(events,key=lambda e:e.ts):
            if p["last_funding_ms"]<event.ts<=until and event.ts>p["opened_ms"]:
                if not math.isfinite(event.rate) or abs(event.rate)>.1:
                    raise ValueError("invalid funding event")
                amount=-p["side"]*p["qty"]*reference_price*event.rate
                p["funding"]+=amount
                self.state["cash"]+=amount
                self.state["funding"]+=amount
                p["last_funding_ms"]=event.ts
                self.store.event(event.ts,"FUNDING",symbol,amount=amount,rate=event.rate,price_model="trade_price_proxy")

    def _manage(self,symbol,q,hours,minutes,events,now,replay_until,policy):
        p=self.state["positions"][symbol]
        p["last_mark"]=q.mark
        unseen=[c for c in minutes if c.ts>=p["replay_from_ms"] and c.ts+MINUTE>p["last_checked_ms"]]
        expected=max(p["replay_from_ms"],p["last_checked_ms"])
        # An empty or stale response can hide a stop just as a missing first bar can.
        # Compare to the time captured before the request, so a slow fetch crossing
        # a minute boundary does not invent a missing candle.
        if expected<replay_until and (not unseen or unseen[0].ts>expected
                or unseen[-1].ts+MINUTE<replay_until):
            self._halt("MINUTE_REPLAY_GAP",now)
            self.store.event(now,"UNCERTAIN_PAPER_PATH",symbol)
        for c in unseen:
            self._fund(symbol,p,events,c.ts,c.open)
            hit=c.low<=p["stop"] if p["side"]==1 else c.high>=p["stop"]
            if hit:
                base=min(c.open,p["stop"]) if p["side"]==1 else max(c.open,p["stop"])
                self._close(symbol,base,c.ts+MINUTE,"STOP_CANDLE")
                return
            if c.ts+MINUTE-p["opened_ms"]>=self.cfg.max_hold_hours*HOUR:
                self._fund(symbol,p,events,c.ts+MINUTE,c.close)
                self._close(symbol,c.close,c.ts+MINUTE,"TIME_EXIT")
                return
            p["last_checked_ms"]=c.ts+MINUTE
            eligible=[h for h in hours if h.ts+HOUR<=c.ts+MINUTE]
            if eligible and eligible[-1].ts>p["last_trail_bar"]:
                p["stop"]=policy.trailing_stop(symbol,p,eligible,self.cfg)
                p["last_trail_bar"]=eligible[-1].ts
                if policy.exit_signal(symbol,p,eligible,self.cfg):
                    self._fund(symbol,p,events,c.ts+MINUTE,c.close)
                    self._close(symbol,c.close,c.ts+MINUTE,"STRATEGY_EXIT")
                    return
        self._fund(symbol,p,events,now,q.mark)
        hit=q.last<=p["stop"] if p["side"]==1 else q.last>=p["stop"]
        if hit or now-p["opened_ms"]>=self.cfg.max_hold_hours*HOUR:
            self._close(symbol,q.bid if p["side"]==1 else q.ask,now,"STOP_QUOTE" if hit else "TIME_EXIT")
        else:
            # Persisted risk is conservative: initial stop risk, never assume trailing profit frees cash risk.
            p["last_mark"]=q.mark

    def cycle(self):
        now=self.clock()
        errors={}
        quotes={}
        histories={}
        minutes={}
        funding={}
        replay_until={}
        replay_gaps=set()
        if not self.instruments:
            try:
                self.instruments=self.client.instruments()
            except Exception as exc:
                errors["instruments"]=type(exc).__name__
        # Fetch each symbol independently; one broken feed cannot starve protection of the others.
        for symbol in self.cfg.symbols:
            try:
                check_now=self.clock()
                bars=complete(self.client.candles(symbol,"1H",self.cfg.history_limit),check_now,HOUR)
                if not bars or check_now-(bars[-1].ts+HOUR)>HOUR+self.cfg.max_signal_age_ms:
                    raise ValueError("stale candles")
                histories[symbol]=bars
                if symbol in self.state["positions"]:
                    p=self.state["positions"][symbol]
                    replay_until[symbol]=check_now//MINUTE*MINUTE
                    try:
                        minutes[symbol]=complete(self.client.candles(symbol,"1m",1000),check_now,MINUTE)
                    except CandleGapError:
                        replay_gaps.add(symbol)
                        raise
                    events=self.client.funding_history(symbol,p["last_funding_ms"]+1,check_now)
                    rates={}
                    for event in events:
                        if (type(event.ts) is not int or event.ts<0 or not math.isfinite(event.rate)
                                or abs(event.rate)>.1 or (event.ts in rates and rates[event.ts]!=event.rate)):
                            raise ValueError("invalid or conflicting funding event")
                        rates[event.ts]=event.rate
                    funding[symbol]=events
            except Exception as exc:
                errors[symbol]=type(exc).__name__
        # Fetch quotes after potentially slow history calls. History failure must
        # not prevent current-stop management for any symbol.
        for symbol in self.cfg.symbols:
            try:
                q=self.client.ticker(symbol)
                if q.symbol!=symbol:
                    raise ValueError("ticker symbol mismatch")
                quotes[symbol]=q
            except Exception as exc:
                errors[symbol]=type(exc).__name__
        now=self.clock()
        # A quote fetched at the beginning of a slow cycle must pass freshness again.
        fresh={s:q for s,q in quotes.items() if quote_healthy(q,now,self.cfg)}
        for s in quotes.keys()-fresh.keys():
            errors[s]="CycleQuoteExpired"
        quotes=fresh
        try:
            book = FeatureBook(histories)
            policy = Policy(self.cfg.strategy, book)
            with self.store.transaction():
                # Reload committed state so a failed prior cycle never leaves uncommitted in-memory fills.
                self.state=self.store.load()
                if Path(self.cfg.database).parent.joinpath("KILL_SWITCH").exists():
                    self._halt("KILL_SWITCH",now)
                for symbol in replay_gaps:
                    self._halt("MINUTE_REPLAY_GAP",now)
                    self.store.event(now,"UNCERTAIN_PAPER_PATH",symbol)
                for symbol in list(self.state["positions"]):
                    if symbol not in self.cfg.symbols:
                        self._halt("UNKNOWN_LOCAL_POSITION",now)
                    elif symbol in quotes:
                        if symbol in errors:
                            # Current stop check still applies despite missing history/funding.
                            p=self.state["positions"][symbol]
                            q=quotes[symbol]
                            p["last_mark"]=q.mark
                            hit=q.last<=p["stop"] if p["side"]==1 else q.last>=p["stop"]
                            if hit or now-p["opened_ms"]>=self.cfg.max_hold_hours*HOUR:
                                # Missing history/funding means this fill cannot be a
                                # complete research observation; persist the uncertainty.
                                self._halt("DEGRADED_EXIT_ACCOUNTING",now)
                                self.store.event(now,"UNCERTAIN_PAPER_PATH",symbol)
                                self._close(symbol,q.bid if p["side"]==1 else q.ask,now,
                                            "STOP_DEGRADED" if hit else "TIME_EXIT_DEGRADED")
                        else:
                            self._manage(symbol,quotes[symbol],histories[symbol],minutes[symbol],funding[symbol],now,replay_until[symbol],policy)
                current=equity(self.state,quotes)
                self.state["peak"]=max(current,self.state["peak"])
                dd=1-current/self.state["peak"]
                baseline=self.store.baseline(now,self.cfg.initial_equity)
                loss=1-current/baseline if baseline>0 else 1
                if dd>=self.cfg.max_drawdown or loss>=self.cfg.rolling_halt_loss or current<=0:
                    self._halt("DRAWDOWN_OR_ROLLING_LOSS",now)
                elif loss>=self.cfg.rolling_pause_loss and self.state["pause_until"]<=now:
                    self.state["pause_until"]=now+int(self.cfg.pause_hours*HOUR)
                    self.store.event(now,"PAUSED_RISK",loss=loss)
                self.state["status"]="HALTED" if self.state["halted"] else "DEGRADED" if errors else "PAUSED_RISK" if now<self.state["pause_until"] else "RUNNING"
                for symbol,bars in histories.items():
                    self.store.cache_candles(symbol,HOUR,bars)
                    bar=bars[-1]
                    if self.store.decided(symbol,bar.ts):
                        continue
                    reason=self.state["status"]
                    if self.state["status"]=="RUNNING" and symbol in quotes:
                        current=equity(self.state,quotes)
                        reason=self._entry(symbol,bars,quotes[symbol],current,dd,now,policy)
                    self.store.decide(symbol,bar.ts,reason)
                    self.store.event(now,"DECISION",symbol,bar_ts=bar.ts,reason=reason)
                self.state["equity"]=equity(self.state,quotes)
                self.state["last_cycle_ms"]=now
                self.state["last_error"]=",".join(s+":"+r for s,r in errors.items())
                self.state["drawdown"]=max(0,1-self.state["equity"]/self.state["peak"])
                self.state["rolling_loss"]=loss
                self.store.record_equity(now,self.state["equity"])
                self.store.prune(now)
                self.store.save(self.state)
        except BaseException:
            self.state=self.store.load()
            raise
        atomic_json(self.cfg.heartbeat,{"timestamp":now/1000,"state":self.state["status"],"mode":"paper","equity":self.state["equity"]})
        return self.state

    def _entry(self,symbol,bars,q,current,dd,now,policy):
        if symbol in self.state["positions"]:
            return "POSITION_EXISTS"
        if now<self.state["cooldown"].get(symbol,0):
            return "COOLDOWN"
        if now-(bars[-1].ts+HOUR)>self.cfg.max_signal_age_ms:
            return "MISSED_SIGNAL_WINDOW"
        mid=(q.bid+q.ask)/2
        if (q.ask-q.bid)/mid*10000>self.cfg.max_spread_bps:
            return "SPREAD"
        if abs(q.mark-q.index)/q.index*10000>self.cfg.max_basis_bps:
            return "BASIS"
        if abs(q.funding_rate)>self.cfg.max_funding_rate:
            return "FUNDING_EXTREME"
        signal=policy.evaluate(symbol,bars,now,self.cfg)
        if signal is None:
            return "NO_SIGNAL"
        instrument=self.instruments.get(symbol)
        if not instrument or instrument.status.lower() not in {"online","normal","listed"}:
            return "INSTRUMENT_UNAVAILABLE"
        entry=(q.ask if signal.side==1 else q.bid)*(1+signal.side*self.cfg.slippage_bps/10000)
        distance=abs(signal.entry-signal.stop)
        stop=entry-signal.side*distance
        from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
        tick=Decimal(str(instrument.price_tick))
        # Round protective stop away from entry, then size from actual rounded distance.
        stop=float((Decimal(str(stop))/tick).to_integral_value(rounding=ROUND_FLOOR if signal.side==1 else ROUND_CEILING)*tick)
        positions=list(self.state["positions"].values())
        sized=size_position(current,entry,stop,instrument,self.cfg,
            open_risk=sum(p["risk_cash"] for p in positions),used_margin=sum(p["margin"] for p in positions),
            gross_notional=sum(abs(p["qty"]*p["last_mark"]) for p in positions),drawdown=dd)
        if sized is None:
            return "RISK_LIMIT"
        fee=entry*sized.qty*self.cfg.fee_bps/10000
        self.state["cash"]-=fee
        self.state["fees"]+=fee
        self.state["positions"][symbol]=dict(side=signal.side,qty=sized.qty,entry=entry,stop=stop,initial_stop=stop,
            leverage=sized.leverage,margin=sized.margin,risk_cash=sized.risk_cash,opened_ms=now,
            last_mark=q.mark,last_checked_ms=now//MINUTE*MINUTE+MINUTE,
            replay_from_ms=now//MINUTE*MINUTE+MINUTE,last_funding_ms=now,
            last_trail_bar=bars[-1].ts,entry_fee=fee,funding=0.0)
        self.store.event(now,"ENTRY",symbol,price=entry,stop=stop,qty=sized.qty,leverage=sized.leverage,
                         risk_cash=sized.risk_cash,fee=fee,partial_first_minute="not_reconstructed")
        return "ENTERED"
