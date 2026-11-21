"""ETF flow snapshot fetcher (provider-style helper).

Data source:
- https://btcetfdata.com/etfs.v1.current.json

Returns normalized structure aligned with previous `latest-simple.json` format:
{
  timestamp,
  source,
  updated_date,
  btc_holdings,  # None if a fund's holdings cannot be established
  btc_price,
  trends,
  top_flows: [{ticker, flow_btc, flow_usd_million?}]
}
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from .http import get_json


class EtfFlowFetchError(RuntimeError):
    """Raised when ETF flow fetch fails."""


def _safe_float(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        value = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None

# 单日 |change| 超过前一日持仓的该比例即视为上游异常（真实单日赎回从未接近此量级）
MAX_DAILY_CHANGE_FRACTION = 0.5


def _flow_rejection_reason(holdings: float | None, flow_btc: float) -> str | None:
    """Return why a fund's daily change is untrustworthy, or None if it passes.

    btcetfdata 的 change = 当日 holdings - 前一日 holdings。上游抓取失败时
    holdings 会被写成 0，change 随之等于"全部持仓流出"（例：2026-11-19 BTCC
    holdings=0, change=-17,747 BTC）。
    """
    if holdings is None:
        return "holdings_missing"
    if holdings <= 0:
        return "holdings_non_positive"
    prior = holdings - flow_btc
    if prior <= 0:
        # 上游从 0 恢复的当天：holdings=真实值, change=+全部持仓，是假流入。
        # Current API 无首发标记。保留有效持仓，将无法确认的全额流入记入 rejected_flows。
        return "prior_holdings_non_positive"
    if abs(flow_btc) > MAX_DAILY_CHANGE_FRACTION * prior:
        return "change_exceeds_half_prior_holdings"
    return None


def _effective_holdings(holdings: float | None, flow_btc: float | None) -> tuple[float | None, str | None]:
    """Holdings to count in the total, plus a note when the reported value was replaced.

    上游 holdings=0 且 change<0 时，用 -change 还原前一日持仓
    （例：BTCC holdings=0, change=-17,747 → 17,747）。无法还原时，合计不可用。
    """
    if holdings is not None and holdings > 0:
        return holdings, None
    if holdings == 0 and flow_btc is not None and flow_btc < 0:
        return -flow_btc, "restored_prior_holdings"
    return None, "holdings_unusable"


def fetch_etf_flow_snapshot() -> dict[str, Any]:
    # 1. Fetch ETF data
    try:
        payload = get_json("https://btcetfdata.com/etfs.v1.current.json", timeout=15)
    except Exception as e:
        raise EtfFlowFetchError(f"Failed to fetch btcetfdata: {e}") from e

    # 2. Fetch BTC price to allow downstream USD calculations
    try:
        btc_price = _safe_float(get_json("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=10).get("price"))
    except Exception:
        btc_price = None

    data = payload.get("data", {})
    if not data:
        raise EtfFlowFetchError("Empty data returned from btcetfdata")

    # Sort out the dates to find the most recent 'updated_date' (dt) across all entries
    dates = [item["dt"] for item in data.values() if "dt" in item and item["dt"]]
    updated_date = max(dates) if dates else datetime.utcnow().strftime("%Y-%m-%d")

    # Calculate Total holdings（无效持仓用前一日值还原，替换记录在 holdings_adjustments）
    effective_holdings: list[float] = []
    fund_holdings: dict[str, float | None] = {}
    holdings_adjustments: list[dict[str, Any]] = []
    for ticker, item in data.items():
        reported = _safe_float(item.get("holdings"))
        effective, note = _effective_holdings(reported, _safe_float(item.get("change")))
        if effective is not None:
            effective_holdings.append(effective)
        fund_holdings[ticker.upper()] = reported
        if note is not None:
            holdings_adjustments.append({
                "ticker": ticker.upper(),
                "reported_holdings": reported,
                "used_holdings": effective,
                "dt": item.get("dt"),
                "reason": note,
            })
    btc_holdings = sum(effective_holdings) if len(effective_holdings) == len(data) else None

    top_flows: list[dict[str, Any]] = []
    rejected_flows: list[dict[str, Any]] = []
    for ticker, item in data.items():
        flow_btc = _safe_float(item.get("change"))
        if flow_btc is None:
            continue

        holdings = _safe_float(item.get("holdings"))
        reason = _flow_rejection_reason(holdings, flow_btc)
        if reason is not None:
            rejected_flows.append({
                "ticker": ticker.upper(),
                "flow_btc": flow_btc,
                "holdings": holdings,
                "dt": item.get("dt"),
                "reason": reason,
            })
            continue

        flow_usd_million = None
        if btc_price is not None:
            flow_usd_million = (flow_btc * btc_price) / 1_000_000.0

        top_flows.append({
            "ticker": ticker.upper(),
            "flow_btc": flow_btc,
            "flow_usd_million": flow_usd_million,
            # 各基金 holdings 快照的 as-of 日各不相同（同一时刻可能混杂 3 个日期），
            # 逐项透传 dt 供下游按真实归属日落库，勿用顶层 updated_date（=max(dt)）代替
            "dt": item.get("dt"),
        })

    # Sort top flows by absolute BTC flow, taking top 5 (consistent with old behavior)
    top_flows = sorted(top_flows, key=lambda x: abs(x.get("flow_btc") or 0), reverse=True)[:5]

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "kapy-provider:btcetfdata.com",
        "updated_date": updated_date,
        "btc_holdings": btc_holdings,
        # 逐基金上报持仓原值（未调整），供事后核查合计跳变
        "fund_holdings": fund_holdings,
        "holdings_adjustments": holdings_adjustments,
        "btc_price": btc_price,
        "trends": {},
        "top_flows": top_flows,
        # 被守卫剔除的条目（不进入 top_flows / 不落库），保留以便审计
        "rejected_flows": rejected_flows,
        "raw_providers": list(data.keys()),
    }
