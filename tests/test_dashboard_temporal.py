"""Unit tests for executive dashboard temporal / forecast helpers (no Streamlit runtime)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Load dashboard module without executing Streamlit app entrypoint.
_ROOT = Path(__file__).resolve().parents[1]
_DASH_PATH = _ROOT / "app" / "frontend" / "dashboard.py"
_spec = importlib.util.spec_from_file_location("exec_dashboard", _DASH_PATH)
assert _spec and _spec.loader
_dash = importlib.util.module_from_spec(_spec)
sys.modules["exec_dashboard"] = _dash
_spec.loader.exec_module(_dash)


def test_infer_trend_state_worsening_when_higher_is_bad() -> None:
    series = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]
    assert _dash.infer_trend_state(series, higher_is_bad=True) == "worsening"


def test_infer_trend_state_improving_when_higher_is_bad() -> None:
    series = [20.0, 19.0, 18.0, 17.0, 16.0, 15.0, 14.0]
    assert _dash.infer_trend_state(series, higher_is_bad=True) == "improving"


def test_infer_trend_state_volatile_zigzag() -> None:
    series = [10.0, 16.0, 9.0, 17.0, 8.0, 18.0, 10.0]
    assert _dash.infer_trend_state(series, higher_is_bad=True) == "volatile"


def test_render_kpi_sparkline_svg() -> None:
    svg = _dash.render_kpi_sparkline([1.0, 2.0, 1.5, 2.5, 2.0])
    assert "<svg" in svg and "polyline" in svg and "</svg>" in svg


def test_build_sparkline_altair_chart() -> None:
    chart = _dash.build_sparkline_altair_chart([1.0, 2.0, 3.0, 2.5])
    d = chart.to_dict()
    assert d["mark"]["type"] == "line"
    assert d["encoding"]["x"]["field"] == "i"


def test_build_forecast_summary_cap_and_uses_risk_volume() -> None:
    kpi_ctx = {
        "worsening_domains": ["deliveries"],
        "improving_domains": ["inventory"],
        "delta_rows": [],
        "values": {},
        "kpi_forecast": {
            "sla_breaches": {"state": "worsening", "caption": "worsening trend", "series": [], "sparkline_svg": ""},
            "critical_inventory": {"state": "improving", "caption": "improving trend", "series": [], "sparkline_svg": ""},
            "high_risk_suppliers": {"state": "stable", "caption": "stabilizing", "series": [], "sparkline_svg": ""},
            "critical_recommendations": {"state": "stable", "caption": "stabilizing", "series": [], "sparkline_svg": ""},
        },
    }
    lines = _dash.build_forecast_summary(
        kpi_ctx=kpi_ctx,
        risk_items=[{"severity": "medium", "label": f"r{i}"} for i in range(14)],
        ai_payload=None,
        critical_inventory=5,
        sla_breaches=10,
        high_risk_suppliers=3,
        critical_recommendations=1,
    )
    assert len(lines) <= 6
    assert any("Delivery pressure continues to worsen" in ln for ln in lines)
    assert any("Inventory exposure improved" in ln for ln in lines)


def test_compute_escalation_risk_cross_domain() -> None:
    kpi_ctx = {"worsening_domains": [], "improving_domains": [], "kpi_forecast": {}}
    alert = {
        "severity": "high",
        "category": "inventory",
        "title": "Stock and delivery conflict",
        "summary": "inventory backlog delays customer deliveries",
        "evidence": [],
    }
    assert _dash.compute_escalation_risk(alert, kpi_context=kpi_ctx) == "Cross-domain escalation risk"


def test_compute_escalation_risk_contained() -> None:
    kpi_ctx = {"worsening_domains": [], "improving_domains": ["inventory"], "kpi_forecast": {}}
    alert = {
        "severity": "low",
        "category": "inventory",
        "title": "Minor variance",
        "summary": "within tolerance",
        "evidence": [{"name": "x", "value": 1}],
    }
    assert _dash.compute_escalation_risk(alert, kpi_context=kpi_ctx) in ("Contained", "Stabilizing")


def test_kpi_mock_history_series_length_seven() -> None:
    s = _dash.kpi_mock_history_series("sla_breaches", 100.0)
    assert len(s) == 7 and abs(s[-1] - 100.0) < 1e-6
