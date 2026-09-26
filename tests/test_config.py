from dataclasses import replace
import pytest
from bitget_bot.config import Settings, load_settings


@pytest.mark.parametrize("key,value", [
    ('fee_bps','6'), ('min_leverage',5.5), ('max_leverage',30.0), ('history_limit',300.5),
    ('cooldown_bars',False), ('stale_quote_ms',0), ('pause_hours',0),
    ('slippage_bps',10000), ('fee_bps',float('inf')), ('ema_period',True),
    ('max_atr_fraction',0), ('high_vol_atr_fraction',.05), ('symbols',('BTCUSDT',17)),
    ('symbols','BTCUSDT'), ('database',''), ('heartbeat',None),
])
def test_invalid_configuration_rejected_cleanly(key,value):
    with pytest.raises(ValueError):
        replace(Settings(),**{key:value}).validate()


@pytest.mark.parametrize("suffix", ['', '.lock', '-wal', '-shm'])
def test_heartbeat_cannot_overwrite_ledger_files(tmp_path,suffix):
    database=tmp_path/'ledger.db'
    with pytest.raises(ValueError,match='heartbeat'):
        replace(Settings(),database=str(database),heartbeat=str(database)+suffix).validate()


def test_fingerprint_allows_moving_paths_but_not_strategy_change():
    base=Settings()
    assert base.fingerprint==replace(base,database='other.db',heartbeat='other.json',poll_seconds=30).fingerprint
    assert base.fingerprint!=replace(base,fee_bps=7).fingerprint


def test_loader_rejects_unknown_fields_and_wrong_types(tmp_path):
    path=tmp_path/'config.toml'
    path.write_text('unknown_setting = 1',encoding='utf-8')
    with pytest.raises(ValueError,match='unknown config'):
        load_settings(path)
    path.write_text('history_limit = 300.5',encoding='utf-8')
    with pytest.raises(ValueError,match='history_limit'):
        load_settings(path)
