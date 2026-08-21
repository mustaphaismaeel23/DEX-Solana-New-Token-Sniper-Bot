import backend_api


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_get_sol_amount_for_usd_uses_configured_slippage(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return DummyResponse({"outAmount": str(1_000_000_000)})

    monkeypatch.setattr(backend_api.requests, "get", fake_get)
    backend_api.ENV["SLIPPAGE_BPS"] = "500"

    result = backend_api.get_sol_amount_for_usd(1)

    assert result == 1.0
    assert captured["params"]["slippageBps"] == 500
