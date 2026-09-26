import pytest
from src.bitget_bot.models import Signal

@pytest.fixture(autouse=True)
def mock_policy_for_tests(monkeypatch):
    import src.bitget_bot.strategy_v2 as v2
    def mock_eval(self, symbol, history, now, config):
        if history and history[-1].close > history[0].close:
            return Signal(symbol, 1, history[-1].ts, history[-1].close, history[-1].close - 100, "mock")
        if history and history[-1].close < history[0].close:
            return Signal(symbol, -1, history[-1].ts, history[-1].close, history[-1].close + 100, "mock")
        return None
    def mock_trail(self, symbol, position, history, config):
        return position['stop']
    def mock_exit(self, symbol, position, history, config):
        return False
    monkeypatch.setattr(v2.Policy, 'evaluate', mock_eval)
    monkeypatch.setattr(v2.Policy, 'trailing_stop', mock_trail)
    monkeypatch.setattr(v2.Policy, 'exit_signal', mock_exit)
