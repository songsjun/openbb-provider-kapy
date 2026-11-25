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


def test_total_restores_prior_holdings_when_reported_zero(monkeypatch):
    _patch_fetch(monkeypatch, {
        "BTCC": {"dt": "2026-11-19", "holdings": 0, "change": -17747.386542},
        "IBIT": {"dt": "2026-11-19", "holdings": 770251.8482, "change": -8714.6048},
    })
    snap = etf_flow.fetch_etf_flow_snapshot()

    assert abs(snap["btc_holdings"] - (770251.8482 + 17747.386542)) < 1e-6
    assert snap["fund_holdings"] == {"BTCC": 0.0, "IBIT": 770251.8482}
    assert snap["holdings_adjustments"] == [{
        "ticker": "BTCC",
        "reported_holdings": 0.0,
        "used_holdings": 17747.386542,
        "dt": "2026-11-19",
        "reason": "restored_prior_holdings",
    }]


def test_total_is_unavailable_when_holdings_unrecoverable(monkeypatch):
    _patch_fetch(monkeypatch, {
        "XYZ": {"dt": "2026-11-19", "change": -10},
        "ABC": {"dt": "2026-11-19", "holdings": 0, "change": 0},
        "DEF": {"dt": "2026-11-19", "holdings": -1, "change": -10},
        "IBIT": {"dt": "2026-11-19", "holdings": 100.0, "change": 1},
    })
    snap = etf_flow.fetch_etf_flow_snapshot()

    assert snap["btc_holdings"] is None
    assert [f["ticker"] for f in snap["top_flows"]] == ["IBIT"]
    assert {a["ticker"]: a["reason"] for a in snap["holdings_adjustments"]} == {
        "XYZ": "holdings_unusable",
        "ABC": "holdings_unusable",
        "DEF": "holdings_unusable",
    }
    assert all(a["used_holdings"] is None for a in snap["holdings_adjustments"])


def test_rejects_recovery_from_zero_as_fake_inflow(monkeypatch):
    # 上游从 holdings=0 恢复的当天：change=+全部持仓
    _patch_fetch(monkeypatch, {
        "BTCC": {"dt": "2026-11-20", "holdings": 17590, "change": 17590},
    })
    snap = etf_flow.fetch_etf_flow_snapshot()

    assert snap["top_flows"] == []
    assert snap["rejected_flows"][0]["reason"] == "prior_holdings_non_positive"
    # 持仓本身有效，照常计入合计
    assert snap["btc_holdings"] == 17590
    assert snap["holdings_adjustments"] == []


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
