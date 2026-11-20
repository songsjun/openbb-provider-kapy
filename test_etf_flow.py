"""Tests for the btcetfdata ETF flow snapshot guard."""

from __future__ import annotations

from openbb_kapy.marketdata import etf_flow


def _patch_fetch(monkeypatch, data: dict) -> None:
    def fake_get_json(url, timeout=None):
        if "btcetfdata" in url:
            return {"data": data}
        return {"price": "60000"}

    monkeypatch.setattr(etf_flow, "get_json", fake_get_json)


def test_rejects_zero_holdings_glitch(monkeypatch):
    # 2026-11-19 真实案例：BTCC holdings=0, change=-全部持仓
    _patch_fetch(monkeypatch, {
        "BTCC": {"dt": "2026-11-19", "holdings": 0, "change": -17747.386542},
        "IBIT": {"dt": "2026-11-19", "holdings": 770251.8482, "change": -8714.6048},
    })
    snap = etf_flow.fetch_etf_flow_snapshot()

    assert [f["ticker"] for f in snap["top_flows"]] == ["IBIT"]
    assert snap["rejected_flows"] == [{
        "ticker": "BTCC",
        "flow_btc": -17747.386542,
        "holdings": 0.0,
        "dt": "2026-11-19",
        "reason": "holdings_non_positive",
    }]


def test_rejects_change_larger_than_half_prior_holdings(monkeypatch):
    # 前值 1000，当日 -600（> 50%）
    _patch_fetch(monkeypatch, {
        "XYZ": {"dt": "2026-11-19", "holdings": 400, "change": -600},
    })
    snap = etf_flow.fetch_etf_flow_snapshot()

    assert snap["top_flows"] == []
    assert snap["rejected_flows"][0]["reason"] == "change_exceeds_half_prior_holdings"


def test_rejects_missing_holdings(monkeypatch):
    _patch_fetch(monkeypatch, {
        "XYZ": {"dt": "2026-11-19", "change": -10},
    })
    snap = etf_flow.fetch_etf_flow_snapshot()

    assert snap["top_flows"] == []
    assert snap["rejected_flows"][0]["reason"] == "holdings_missing"


def test_keeps_normal_flows_and_zero_change(monkeypatch):
    _patch_fetch(monkeypatch, {
        "FBTC": {"dt": "2026-11-19", "holdings": 171135.53, "change": -739.03},
        "BITB": {"dt": "2026-11-19", "holdings": 36112.29, "change": 0},
        "ARKB": {"dt": "2026-11-20", "holdings": 27356, "change": -504},
    })
    snap = etf_flow.fetch_etf_flow_snapshot()

    assert {f["ticker"] for f in snap["top_flows"]} == {"FBTC", "BITB", "ARKB"}
    assert snap["rejected_flows"] == []
    fbtc = next(f for f in snap["top_flows"] if f["ticker"] == "FBTC")
    assert abs(fbtc["flow_usd_million"] - (-739.03 * 60000 / 1e6)) < 1e-9
