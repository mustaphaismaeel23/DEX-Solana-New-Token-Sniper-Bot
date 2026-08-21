import os
import time

os.environ.setdefault("RPC_URL", "http://localhost")
os.environ.setdefault("HELIUS_API_KEY", "test")
os.environ.setdefault("WALLET_PRIVATE_KEY", "test")

from buyer import _event_age_seconds
from pump_scanner import _timestamp_seconds


def test_event_age_accepts_millisecond_timestamps():
    timestamp = time.time() * 1000
    assert _event_age_seconds(timestamp) < 2
    assert _timestamp_seconds(timestamp) == timestamp / 1000


def test_invalid_event_timestamp_fails_closed_as_stale():
    assert _event_age_seconds("invalid") == float("inf")
