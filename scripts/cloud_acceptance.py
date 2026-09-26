"""On the dedicated paper VM, verify restart, SQLite backup and local UI."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import time
import urllib.request

DATA = Path('/var/lib/bitget/data')
BOT = 'bitget-bot.service'

def command(*args):
    return subprocess.check_output(args, text=True, timeout=60).strip()

def ledger(path=DATA / 'trader.sqlite3'):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        state=json.loads(db.execute('SELECT payload FROM portfolio WHERE id=1').fetchone()[0])
        assert state['mode']=='paper'
        state['_decisions']=db.execute('SELECT count(*) FROM decisions').fetchone()[0]
        return state

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--restart',action='store_true')
    args=parser.parse_args()
    before=ledger()
    before_pid=command('systemctl','show',BOT,'--property=MainPID','--value')
    if args.restart:
        subprocess.run(['systemctl','restart',BOT],check=True,timeout=60)
    ready=False
    for _ in range(15):
        check=subprocess.run(['python3','/opt/bitget/current/infra/gcp/runtime_ops.py','verify'],capture_output=True,text=True,timeout=20)
        if check.returncode==0:
            ready=True
            break
        time.sleep(4)
    assert ready, 'Readiness did not pass'
    after=ledger()
    after_pid=command('systemctl','show',BOT,'--property=MainPID','--value')
    assert after['started_ms']==before['started_ms'], 'Ledger initialization changed'
    assert after['fingerprint']==before['fingerprint'], 'Configuration identity changed'
    assert after['_decisions']>=before['_decisions'], 'Lost decisions'
    assert after['trades']>=before['trades'], 'Lost completed trades'
    if args.restart:
        assert before_pid!=after_pid, 'Worker process did not change'
    subprocess.run(['systemctl','start','bitget-backup.service'],check=True,timeout=240)
    backups=sorted(Path('/var/lib/bitget/backups').glob('trader-*.sqlite3'),key=lambda p:p.stat().st_mtime)
    assert backups, 'No backup generated'
    backup_state=ledger(backups[-1])
    assert backup_state['started_ms']==after['started_ms']
    with urllib.request.urlopen('http://127.0.0.1:8765/status',timeout=10) as response:
        ui=json.load(response)
    assert ui['mode']=='paper' and ui['started_ms']==after['started_ms']
    units={name:command('systemctl','is-active',name) for name in (BOT,'bitget-dashboard.service','bitget-health.timer','bitget-backup.timer')}
    enabled={name:command('systemctl','is-enabled',name) for name in units}
    result={'verified_at_ms':int(time.time()*1000),'mode':'paper','state':after['status'],
        'restart_test':args.restart,'before_pid':before_pid,'after_pid':after_pid,
        'started_ms':after['started_ms'],'last_cycle_ms':after['last_cycle_ms'],
        'ledger_integrity':'ok','backup_integrity':'ok','backup_file':backups[-1].name,
        'ledger_preserved':True,'dashboard_http':200,'services':units,'enabled':enabled,
        'trades':after['trades'],'positions':len(after['positions']),
        'data_mount':command('findmnt','-n','-o','SOURCE,FSTYPE,TARGET','/var/lib/bitget')}
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':
    main()
