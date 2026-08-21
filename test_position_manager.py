import os

os.environ.setdefault("RPC_URL", "http://localhost")
os.environ.setdefault("HELIUS_API_KEY", "test")
os.environ.setdefault("WALLET_PRIVATE_KEY", "test")

from position_manager import evaluate_profit_take


def test_staged_profit_targets_sell_guide_amounts():
    initial = 1000

    amount, stage, reason = evaluate_profit_take(1.0, 2.0, initial, 1000, 0)
    assert (amount, stage, reason) == (500, 1, "profit target 2x")

    amount, stage, reason = evaluate_profit_take(1.0, 5.0, initial, 500, 1)
    assert (amount, stage, reason) == (250, 2, "profit target 5x")

    amount, stage, reason = evaluate_profit_take(1.0, 10.0, initial, 250, 2)
    assert (amount, stage, reason) == (200, 3, "profit target 10x")


def test_staged_profit_targets_do_not_repeat_completed_stage():
    amount, stage, reason = evaluate_profit_take(1.0, 2.5, 1000, 500, 1)

    assert amount == 0
    assert stage == 1
    assert reason == ""
