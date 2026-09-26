"""Command line interface; live writes are intentionally unavailable in this release."""
import argparse
from dataclasses import asdict
import json
import signal
from pathlib import Path
import sys
import threading
import time

from .config import load_settings
from .engine import PaperEngine, complete
from .store import Store, WriterLock, read_status


def emit(data):
    print(json.dumps(data,ensure_ascii=False,allow_nan=False),flush=True)


def run(settings, once=False):
    from .exchange import MarketClient
    shutdown=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):
        signal.signal(sig,lambda *_:shutdown.set())
    with WriterLock(settings.database):
        store=Store(settings.database)
        try:
            engine=PaperEngine(settings,MarketClient(),store)
            failures=0
            while not shutdown.is_set():
                try:
                    state=engine.cycle()
                    failures=0
                    emit({key:state.get(key) for key in ("mode","status","equity","trades","drawdown","last_cycle_ms","last_error")})
                except Exception as exc:
                    failures+=1
                    # Exception bodies can contain third-party payloads; emit only safe type names.
                    emit({"status":"DEGRADED","error":type(exc).__name__,"failures":failures})
                    with store.transaction():
                        state=store.load()
                        state["status"]="HALTED" if state["halted"] else "DEGRADED"
                        state["last_error"]=type(exc).__name__
                        if failures>=10:
                            state.update(halted=True,status="HALTED",halt_reason="REPEATED_CYCLE_FAILURE")
                        store.event(int(time.time()*1000),"CYCLE_FAILURE",error=type(exc).__name__)
                        store.save(state)
                    if once:
                        return 1
                if once:
                    return 0 if state["status"]=="RUNNING" else 2
                shutdown.wait(settings.poll_seconds)
            with store.transaction():
                state=store.load()
                if not state["halted"]:
                    state["status"]="STOPPED"
                store.event(int(time.time()*1000),"PROCESS_STOPPED")
                store.save(state)
        finally:
            store.close()
    return 0


def download(settings, days, output):
    from .exchange import MarketClient
    if not 3<=days<=1095:
        raise ValueError("history range must be 3..1095 days")
    client=MarketClient()
    now=int(time.time()*1000)
    start=now-days*86400000
    dataset={"schema":1,"source":"Bitget UTA v3", "downloaded_ms":now,"requested_start_ms":start,"symbols":{},"limitations":["Current fixed universe; not a survivorship-free universe", "Trade-price OHLC, no historical liquidation tiers"]}
    for symbol in settings.symbols:
        rows={}
        end=now
        for _ in range(days*24//100+20):
            page=client.candles(symbol,"1H",300,end_ms=end)
            if not page:
                break
            for c in page:
                if start<=c.ts and c.ts+3600000<=now:
                    rows[c.ts]=c
            earliest=min(c.ts for c in page)
            if earliest>=end:
                raise ValueError("history pagination did not advance")
            if earliest<=start:
                break
            end=earliest
            time.sleep(.15)
        bars=complete(list(rows.values()),now,3600000)
        if not bars or bars[0].ts>start+3600000:
            dataset["limitations"].append(symbol+": requested history not fully available")
        dataset["symbols"][symbol]=[asdict(c) for c in bars]
        emit({"event":"HISTORY_DOWNLOADED","symbol":symbol,"bars":len(bars)})
        # Save after every symbol, so interruption loses at most one in-progress symbol.
        path=Path(output)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(dataset,allow_nan=False),encoding="utf-8")
    return 0


def main(argv=None):
    parser=argparse.ArgumentParser(description="Bitget persistent paper trading and research")
    subs=parser.add_subparsers(dest="command",required=True)
    for name in ("run","status","health","halt","resume","dashboard","download","research","public-check"):
        item=subs.add_parser(name)
        item.add_argument("--config",default="config/paper.toml")
        if name=="run":
            item.add_argument("--once",action="store_true")
        if name=="resume":
            item.add_argument("--acknowledge",action="store_true")
        if name=="dashboard":
            item.add_argument("--port",type=int,default=8765)
        if name=="download":
            item.add_argument("--days",type=int,default=180)
            item.add_argument("--output",default="artifacts/history.json")
        if name=="research":
            item.add_argument("--input",default="artifacts/history.json")
            item.add_argument("--output",default="artifacts/research.json")
    args=parser.parse_args(argv)
    try:
        cfg=load_settings(args.config)
        if args.command=="run":
            return run(cfg,args.once)
        if args.command=="status":
            emit(read_status(cfg.database)); return 0
        if args.command=="health":
            state=read_status(cfg.database)
            age=time.time()*1000-state.get("last_cycle_ms",0)
            healthy=0<=age<=180000 and state.get("status")=="RUNNING"
            emit({"healthy":healthy,"state":state.get("status"),"age_seconds":round(age/1000,1)})
            return 0 if healthy else 1
        if args.command=="halt":
            path=Path(cfg.database).parent/"KILL_SWITCH"
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text("MANUAL_HALT\n",encoding="utf-8")
            emit({"requested":"HALT","effect":"next cycle; existing paper positions continue to be managed"})
            return 0
        if args.command=="resume":
            if not args.acknowledge:
                raise ValueError("manual recovery requires --acknowledge after incident review")
            with WriterLock(cfg.database):
                store=Store(cfg.database)
                try:
                    with store.transaction():
                        state=store.load()
                        if not state or state["positions"]:
                            raise ValueError("resume requires an existing flat ledger and stopped process")
                        if state.get("drawdown",0)>=cfg.max_drawdown:
                            raise ValueError("drawdown remains above limit; cannot reset risk history")
                        state.update(halted=False,halt_reason="",status="STOPPED")
                        store.save(state)
                        store.event(int(time.time()*1000),"MANUAL_RESUME")
                    (Path(cfg.database).parent/"KILL_SWITCH").unlink(missing_ok=True)
                finally:
                    store.close()
            emit({"status":"RESUME_READY"}); return 0
        if args.command=="dashboard":
            from .dashboard import serve
            serve(cfg.database,args.port); return 0
        if args.command=="download":
            return download(cfg,args.days,args.output)
        if args.command=="research":
            from .research import run_research
            from .models import Candle
            raw=json.loads(Path(args.input).read_text(encoding="utf-8"))
            dataset={s:[Candle(**c) for c in rows] for s,rows in raw["symbols"].items()}
            result=run_research(dataset,cfg)
            result["data_source"]={key:raw.get(key) for key in ("source","downloaded_ms","requested_start_ms","limitations")}
            Path(args.output).parent.mkdir(parents=True,exist_ok=True)
            Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
            emit({"report":args.output,"status":"RESEARCH_ONLY","live_eligible":False}); return 0
        if args.command=="public-check":
            from .exchange import MarketClient
            from .engine import quote_healthy
            client=MarketClient()
            instruments=client.instruments()
            checks=[]
            for s in cfg.symbols:
                quote=client.ticker(s)
                bars=complete(client.candles(s,"1H",cfg.history_limit),int(time.time()*1000),3600000)
                checks.append({"symbol":s,"instrument":s in instruments,"fresh":quote_healthy(quote,int(time.time()*1000),cfg),"closed_bars":len(bars)})
            emit({"mode":"public_read_only","checks":checks})
            return 0 if all(x["instrument"] and x["fresh"] and x["closed_bars"]>=cfg.ema_period+cfg.slope_bars for x in checks) else 1
    except (ValueError,RuntimeError) as exc:
        emit({"error":type(exc).__name__,"message":str(exc) if type(exc) is ValueError else "operation unavailable; inspect local configuration"})
        return 1
    except Exception as exc:
        emit({"error":type(exc).__name__,"message":"operation failed; credentials and upstream payload are not logged"})
        return 1
    return 0
