"""Daily normalization must not hide conflicting upstream observations."""
import math

import pytest

from openbb_kapy.marketdata import onchain_indicators as provider


def test_identical_asopr_duplicates_are_one_daily_record(monkeypatch):
    row = {"d": "2026-09-09", "asopr": 1.0044, "unixTs": 1788912822}
    monkeypatch.setattr(provider, "get_json", lambda *a, **kw: [dict(row) for _ in range(100)])
    records = provider.fetch_bgeometrics_indicator("asopr", api_key="test-only")
    assert len(records) == 1
    assert records[0]["value"] == 1.0044
    assert records[0]["raw"]["item"] == row


@pytest.mark.parametrize("timestamps", [(1788912822, 1788912822), (1788912822, 1788916422)])
@pytest.mark.parametrize("values", [(1.0044, 1.0058), (1.0044, float("nan")), (1.0044, float("inf"))])
def test_conflicting_same_day_values_fail_without_guessing_final_observation(monkeypatch, timestamps, values):
    rows = [{"d": "2026-09-09", "asopr": value, "unixTs": timestamp}
            for timestamp, value in zip(timestamps, values)]
    monkeypatch.setattr(provider, "get_json", lambda *a, **kw: rows)
    with pytest.raises(provider.OnchainIndicatorFetchError, match="conflicting daily values at 2026-09-09"):
        provider.fetch_bgeometrics_indicator("asopr")


def test_same_value_with_different_observation_timestamps_does_not_change_daily_value(monkeypatch):
    rows = [{"d": "2026-09-09", "asopr": 1.0044, "unixTs": timestamp}
            for timestamp in (1788912822, 1788916422)]
    monkeypatch.setattr(provider, "get_json", lambda *a, **kw: rows)
    result = provider.fetch_bgeometrics_indicator("asopr")
    assert len(result) == 1 and result[0]["value"] == 1.0044


def test_repeated_historical_nan_remains_visible_for_downstream_validation(monkeypatch):
    rows = [{"d": "2026-06-03", "mvrvZscore": "NaN"}] * 2
    monkeypatch.setattr(provider, "get_json", lambda *a, **kw: rows)
    result = provider.fetch_bgeometrics_indicator("mvrv_zscore")
    assert len(result) == 1 and math.isnan(result[0]["value"])
