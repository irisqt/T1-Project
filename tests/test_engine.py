from dataclasses import replace
import pytest
from bitget_bot.config import Settings
from bitget_bot.models import Candle,Quote,Instrument,Funding
from bitget_bot.store import Store,WriterLock,read_status
from bitget_bot.engine import PaperEngine,complete,quote_healthy,HOUR,MINUTE


def bars(n=130):
    rows=[]
    for i in range(n):
        price=100+i*.15
        rows.append(Candle(i*HOUR,price,price+.12,price-.12,price+.08,100))
    last=rows[-1]
    rows[-1]=Candle(last.ts,last.open,last.open+1.2,last.low,last.open+1,100)
    return rows

class Feed:
    def __init__(self,now):
        self.now=now
        self.price=120.4
        self.hours=bars()
        self.minutes=[]
        self.events=[]
        self.bad=set()
    def instruments(self):
        return {s:Instrument(s,.001,.001,5,.01,30,.01) for s in ('BTCUSDT','ETHUSDT')}
    def ticker(self,s):
        if s in self.bad:
            raise TimeoutError()
        return Quote(s,self.price-.01,self.price+.01,self.price,self.price,self.price,self.now,self.now,0,0)
    def candles(self,s,interval='1H',limit=300,end_ms=None):
        return self.hours if interval=='1H' else self.minutes
    def funding_history(self,*args):
        return self.events

@pytest.fixture
def rig(tmp_path):
    cfg=replace(Settings(),symbols=('BTCUSDT',),database=str(tmp_path/'ledger.db'),heartbeat=str(tmp_path/'heartbeat.json'))
    now=130*HOUR+1000
    feed=Feed(now)
    store=Store(cfg.database)
    engine=PaperEngine(cfg,feed,store,clock=lambda:feed.now)
    yield cfg,feed,store,engine
    store.close()


def test_entry_fee_duplicate_and_restart(rig):
    cfg,feed,store,engine=rig
    state=engine.cycle()
    assert len(state['positions'])==1
    assert state['fees']>0 and state['cash']<cfg.initial_equity
    first=state['positions']['BTCUSDT'].copy()
    engine.cycle()
    restart=PaperEngine(cfg,feed,store,clock=lambda:feed.now)
    restart.cycle()
    assert restart.state['positions']['BTCUSDT']==first
    assert store.db.execute("SELECT count(*) FROM events WHERE kind='ENTRY'").fetchone()[0]==1


def test_candle_stop_gap_and_no_reentry(rig):
    cfg,feed,store,engine=rig
    engine.cycle()
    pos=engine.state['positions']['BTCUSDT']
    start=pos['replay_from_ms']
    price=pos['stop']-2
    feed.minutes=[Candle(start,price,price+.1,price-.2,price-.1,5)]
    feed.now=start+MINUTE+1000
    feed.price=pos['entry']+1
    state=engine.cycle()
    assert not state['positions'] and state['trades']==1
    event=store.db.execute("SELECT payload FROM events WHERE kind='EXIT'").fetchone()[0]
    import json
    exit=json.loads(event)
    assert exit['price']<price and exit['reason']=='STOP_CANDLE'
    assert state['realized_pnl']<0


def test_funding_deduplicated_after_restart(rig):
    cfg,feed,store,engine=rig
    engine.cycle()
    feed.now+=20000
    feed.events=[Funding(feed.now-1,.0001)]
    engine.cycle()
    cash=engine.state['cash']
    assert engine.state['funding']<0
    other=PaperEngine(cfg,feed,store,clock=lambda:feed.now)
    other.cycle()
    assert other.state['cash']==cash
    assert store.db.execute("SELECT count(*) FROM events WHERE kind='FUNDING'").fetchone()[0]==1


def test_stale_feed_no_entry_and_recovers_without_chasing(rig):
    cfg,feed,store,engine=rig
    feed.bad.add('BTCUSDT')
    state=engine.cycle()
    assert state['status']=='DEGRADED' and not state['positions']
    feed.bad.clear()
    feed.now+=3*MINUTE
    state=engine.cycle()
    assert state['status']=='RUNNING' and not state['positions']


def test_halt_persists_restart_and_protection_continues(rig):
    cfg,feed,store,engine=rig
    engine.cycle()
    from pathlib import Path
    (Path(cfg.database).parent/'KILL_SWITCH').write_text('HALT')
    engine.cycle()
    assert engine.state['halted']
    (Path(cfg.database).parent/'KILL_SWITCH').unlink()
    restart=PaperEngine(cfg,feed,store,clock=lambda:feed.now)
    feed.price=restart.state['positions']['BTCUSDT']['stop']-1
    restart.cycle()
    assert restart.state['halted'] and not restart.state['positions']


def test_transaction_rollback_reloads_memory(rig,monkeypatch):
    cfg,feed,store,engine=rig
    original=store.save
    monkeypatch.setattr(store,'save',lambda state:(_ for _ in ()).throw(OSError('disk')))
    with pytest.raises(OSError):
        engine.cycle()
    assert not engine.state['positions']
    assert not store.load()['positions']
    monkeypatch.setattr(store,'save',original)
    engine.cycle()
    assert len(engine.state['positions'])==1
    assert store.db.execute("SELECT count(*) FROM events WHERE kind='ENTRY'").fetchone()[0]==1


def test_changed_config_cannot_adopt_ledger(rig):
    cfg,feed,store,engine=rig
    with pytest.raises(ValueError,match='mismatch'):
        PaperEngine(replace(cfg,risk_per_trade=.002),feed,store)


def test_writer_lock_releases_on_exit(tmp_path):
    path=tmp_path/'ledger.db'
    with WriterLock(path):
        with pytest.raises(RuntimeError):
            with WriterLock(path):
                pass
    with WriterLock(path):
        pass


def test_store_rollback_and_readonly_status(rig):
    cfg,feed,store,engine=rig
    with pytest.raises(ValueError):
        with store.transaction():
            store.decide('BTCUSDT',1,'TEST')
            raise ValueError('failure')
    assert not store.decided('BTCUSDT',1)
    assert read_status(cfg.database)['mode']=='paper'


def test_completed_candle_quality():
    rows=bars(5)
    assert len(complete(rows,4*HOUR,HOUR))==4
    with pytest.raises(ValueError):
        complete([rows[0],rows[2]],5*HOUR,HOUR)
    with pytest.raises(ValueError):
        complete([rows[0],rows[0]],5*HOUR,HOUR)
    with pytest.raises(ValueError):
        complete([Candle(0,100,99,101,100)],HOUR,HOUR)


def test_quote_stale_and_clock_future():
    cfg=Settings()
    q=Quote('BTCUSDT',99,101,100,100,100,10000,10000)
    assert quote_healthy(q,10000,cfg)
    assert not quote_healthy(q,30000,cfg)
    assert not quote_healthy(replace(q,ts=20000),10000,cfg)
    assert not quote_healthy(replace(q,bid=float('nan')),10000,cfg)


def test_rolling_halt_survives_restart(rig):
    cfg,feed,store,engine=rig
    with store.transaction():
        state=store.load()
        state['cash']=9500
        store.save(state)
    engine.state=store.load()
    assert engine.cycle()['halted']
    assert PaperEngine(cfg,feed,store,clock=lambda:feed.now).cycle()['halted']


def test_config_rejects_unsafe_modes_and_limits():
    for bad in (replace(Settings(),mode='live'),replace(Settings(),mode='demo'),replace(Settings(),max_leverage=31),replace(Settings(),fee_bps=0),replace(Settings(),risk_per_trade=.5),replace(Settings(),poll_seconds=float('nan'))):
        with pytest.raises(ValueError):
            bad.validate()


@pytest.mark.parametrize("side", [1, -1])
def test_round_trip_cash_reconciles_fees_funding_and_realized_pnl(rig, monkeypatch, side):
    from bitget_bot.models import Signal
    cfg,feed,store,engine=rig
    monkeypatch.setattr('bitget_bot.engine.evaluate', lambda symbol,rows,now,cfg:
                        Signal(symbol,side,rows[-1].ts,120,120-side,"test"))
    engine.cycle()
    pos=engine.state['positions']['BTCUSDT'].copy()
    feed.now+=10000
    feed.events=[Funding(feed.now-1,.0001)]
    engine.cycle()
    funding=engine.state['funding']
    assert funding*side<0
    feed.now+=10000
    feed.price=pos['stop']-side
    state=engine.cycle()
    assert not state['positions']
    assert state['cash']==pytest.approx(cfg.initial_equity+state['realized_pnl'])
    assert state['equity']==state['cash']
    assert state['fees']>pos['entry_fee']
    assert state['funding']==funding
    import json
    closed=json.loads(store.db.execute("SELECT payload FROM events WHERE kind='EXIT'").fetchone()[0])
    gross=(closed['price']-pos['entry'])*side*pos['qty']
    assert state['realized_pnl']==pytest.approx(gross-state['fees']+funding)


@pytest.mark.parametrize("coverage", ['empty','missing_head','missing_tail','internal_gap'])
def test_unrecoverable_minute_coverage_halts_and_persists(rig, coverage):
    cfg,feed,store,engine=rig
    engine.cycle()
    pos=engine.state['positions']['BTCUSDT']
    first=pos['replay_from_ms']
    feed.now=first+3*MINUTE+1000
    rows=[Candle(first+i*MINUTE,feed.price,feed.price+.1,feed.price-.1,feed.price,1) for i in range(3)]
    feed.minutes={'empty':[], 'missing_head':rows[1:], 'missing_tail':rows[:-1],
                  'internal_gap':[rows[0],rows[2]]}[coverage]
    state=engine.cycle()
    assert state['halted'] and state['halt_reason']=='MINUTE_REPLAY_GAP'
    feed.minutes=rows
    restart=PaperEngine(cfg,feed,store,clock=lambda:feed.now)
    assert restart.cycle()['halted']


def test_degraded_history_keeps_latest_mark_and_enforces_time_exit(rig, monkeypatch):
    cfg,feed,store,engine=rig
    engine.cycle()
    opened=engine.state['positions']['BTCUSDT']['opened_ms']
    monkeypatch.setattr(feed,'candles',lambda *args,**kwargs:(_ for _ in ()).throw(TimeoutError()))
    feed.now+=10000
    feed.price+=1
    state=engine.cycle()
    mark=state['positions']['BTCUSDT']['last_mark']
    assert mark==feed.price and state['status']=='DEGRADED'
    feed.bad.add('BTCUSDT')
    state=engine.cycle()
    assert state['positions']['BTCUSDT']['last_mark']==mark
    feed.bad.clear()
    feed.now=opened+int(cfg.max_hold_hours*HOUR)
    state=engine.cycle()
    assert not state['positions'] and state['halted']
    assert state['halt_reason']=='DEGRADED_EXIT_ACCOUNTING'
    import json
    closed=json.loads(store.db.execute("SELECT payload FROM events WHERE kind='EXIT'").fetchone()[0])
    assert closed['reason']=='TIME_EXIT_DEGRADED'


def test_stale_quote_cannot_simulate_a_stop(rig, monkeypatch):
    cfg,feed,store,engine=rig
    engine.cycle()
    pos=engine.state['positions']['BTCUSDT'].copy()
    feed.now+=20000
    stale=Quote('BTCUSDT',pos['stop']-1,pos['stop']-.9,pos['stop']-1,
                pos['stop']-1,pos['stop']-1,feed.now-20000,feed.now-20000)
    monkeypatch.setattr(feed,'ticker',lambda symbol:stale)
    state=engine.cycle()
    assert state['status']=='DEGRADED' and state['positions']['BTCUSDT']==pos


def test_history_failure_does_not_starve_other_position_protection(tmp_path, monkeypatch):
    cfg=replace(Settings(),symbols=('BTCUSDT','ETHUSDT'),database=str(tmp_path/'ledger.db'),
                heartbeat=str(tmp_path/'heartbeat.json'))
    feed=Feed(130*HOUR+1000)
    store=Store(cfg.database)
    try:
        engine=PaperEngine(cfg,feed,store,clock=lambda:feed.now)
        engine.cycle()
        assert len(engine.state['positions'])==2
        feed.now+=10000
        feed.price=engine.state['positions']['ETHUSDT']['stop']-1
        original=feed.candles
        def candles(symbol,*args,**kwargs):
            if symbol=='BTCUSDT':
                raise TimeoutError()
            return original(symbol,*args,**kwargs)
        monkeypatch.setattr(feed,'candles',candles)
        state=engine.cycle()
        assert not state['positions'] and state['trades']==2
        assert state['halted']  # BTC's accounting uncertainty remains visible.
    finally:
        store.close()


def test_conflicting_funding_does_not_block_current_stop(rig):
    cfg,feed,store,engine=rig
    engine.cycle()
    feed.now+=10000
    feed.events=[Funding(feed.now-1,.0001),Funding(feed.now-1,.0002)]
    feed.price=engine.state['positions']['BTCUSDT']['stop']-1
    state=engine.cycle()
    assert not state['positions'] and state['halted'] and state['funding']==0


def test_request_crossing_minute_boundary_does_not_invent_gap(rig, monkeypatch):
    cfg,feed,store,engine=rig
    engine.cycle()
    first=engine.state['positions']['BTCUSDT']['replay_from_ms']
    feed.now=first+MINUTE-1
    original=feed.candles
    def candles(*args,**kwargs):
        answer=original(*args,**kwargs)
        feed.now+=2
        return answer
    monkeypatch.setattr(feed,'candles',candles)
    assert not engine.cycle()['halted']


def test_quote_symbol_mismatch_is_degraded(rig,monkeypatch):
    cfg,feed,store,engine=rig
    original=feed.ticker
    monkeypatch.setattr(feed,'ticker',lambda symbol:replace(original(symbol),symbol='ETHUSDT'))
    state=engine.cycle()
    assert not state['positions'] and state['status']=='DEGRADED'
