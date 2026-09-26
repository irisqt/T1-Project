import sqlite3
import pytest
from bitget_bot.store import Store


def test_commit_failure_rolls_back_and_allows_next_transaction(tmp_path):
    store=Store(tmp_path/'ledger.db')
    real=store.db
    class FailCommitOnce:
        def __init__(self):
            self.failed=False
        def __getattr__(self,key):
            return getattr(real,key)
        def commit(self):
            if not self.failed:
                self.failed=True
                raise sqlite3.OperationalError('simulated commit failure')
            real.commit()
    store.db=FailCommitOnce()
    try:
        with pytest.raises(sqlite3.OperationalError):
            with store.transaction():
                store.decide('BTCUSDT',1,'failed')
        assert not store.decided('BTCUSDT',1)
        assert not real.in_transaction
        with store.transaction():
            store.decide('BTCUSDT',2,'committed')
        assert store.decided('BTCUSDT',2)
    finally:
        store.close()
