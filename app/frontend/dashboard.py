"""Executive Streamlit dashboard — compressed ops-center layout over FastAPI (no backend changes)."""

from __future__ import annotations

import html
import math
import os
import sys
from datetime import datetime
from typing import Any, Literal, Sequence, TypedDict

import altair as alt
import httpx
import pandas as pd
import streamlit as st

# Allow `streamlit run app/frontend/dashboard.py` from repo root without PYTHONPATH hacks
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _api_base() -> str:
    return os.environ.get("SUPPLY_CHAIN_API_BASE", "http://localhost:8000").rstrip("/")
#return os.environ.get("SUPPLY_CHAIN_API_BASE", "http://127.0.0.1:8000").rstrip("/")


def _v1(path: str) -> str:
    base = _api_base()
    p = path if path.startswith("/") else f"/{path}"
    return f"{base}/api/v1{p}"


def _fetch_json(client: httpx.Client, path: str) -> tuple[Any | None, str | None]:
    url = _v1(path)
    try:
        r = client.get(url)
        r.raise_for_status()
        return r.json(), None
    except httpx.HTTPStatusError as e:
        return None, f"{url}: HTTP {e.response.status_code}"
    except httpx.RequestError as e:
        return None, f"{url}: {e}"


class DeltaResult(TypedDict):
    delta_pct: float | None
    direction: Literal["up", "down", "flat"]
    formatted: str


TrendState = Literal["improving", "stable", "worsening", "volatile"]


class KPIForecastSlice(TypedDict, total=False):
    state: TrendState
    caption: str
    series: list[float]
    sparkline_svg: str


def _is_non_numeric_scalar(x: Any) -> bool:
    if x is None:
        return True
    if isinstance(x, bool):
        return False
    try:
        f = float(x)
    except (TypeError, ValueError):
        return True
    return math.isnan(f) or math.isinf(f)


def compute_delta(current: Any, previous: Any) -> DeltaResult:
    """Relative change from previous to current; handles zeros, None, NaN, and negatives."""
    if _is_non_numeric_scalar(current) or _is_non_numeric_scalar(previous):
        return {"delta_pct": None, "direction": "flat", "formatted": "—"}
    cur = float(current)
    prev = float(previous)
    if prev == 0.0:
        if cur == 0.0:
            return {"delta_pct": 0.0, "direction": "flat", "formatted": "0%"}
        direction: Literal["up", "down", "flat"] = (
            "up" if cur > 0 else "down" if cur < 0 else "flat"
        )
        return {"delta_pct": None, "direction": direction, "formatted": "—"}
    raw_pct = (cur - prev) / abs(prev) * 100.0
    if raw_pct > 0.0:
        direction = "up"
    elif raw_pct < 0.0:
        direction = "down"
    else:
        direction = "flat"
    if direction == "flat":
        return {"delta_pct": 0.0, "direction": "flat", "formatted": "0%"}
    rounded = round(raw_pct)
    sign = "+" if rounded > 0 else ""
    return {"delta_pct": float(raw_pct), "direction": direction, "formatted": f"{sign}{rounded}%"}


# Mock prior-period anchors for executive trend row (replace with history API later).
_MOCK_KPI_PRIORS: dict[str, dict[str, Any]] = {
    "critical_inventory": {"previous": 95, "higher_is_bad": True},
    "sla_breaches": {"previous": 113, "higher_is_bad": True},
    "high_risk_suppliers": {"previous": 129, "higher_is_bad": True},
    "critical_recommendations": {"previous": 8, "higher_is_bad": True},
}

# Narrative domain keys align KPI rows to executive language in the banner and alert badges.
_KPI_NARR_BIND: list[tuple[str, str, str]] = [
    ("critical_inventory", "Critical inventory", "inventory"),
    ("sla_breaches", "SLA breaches", "deliveries"),
    ("high_risk_suppliers", "High-risk suppliers", "suppliers"),
    ("critical_recommendations", "Critical recommendations", "governance"),
]

# Seven-period shape multipliers (last = 1.0); scaled to live KPI for mock history.
_MOCK_KPI_SERIES_SHAPE: dict[str, list[float]] = {
    "critical_inventory": [1.12, 1.08, 1.05, 1.02, 0.99, 0.985, 1.0],
    "sla_breaches": [0.72, 0.78, 0.83, 0.87, 0.91, 0.96, 1.0],
    "high_risk_suppliers": [0.992, 0.994, 0.996, 0.998, 0.999, 0.9995, 1.0],
    "critical_recommendations": [1.25, 1.18, 1.12, 1.06, 1.02, 1.01, 1.0],
}

# Deterministic narrative streak (periods) when domain is worsening — rules-only mock until history API exists.
_MOCK_WORSEN_STREAK_PERIODS: dict[str, int] = {
    "deliveries": 3,
    "inventory": 0,
    "suppliers": 0,
    "governance": 0,
}


def kpi_mock_history_series(kpi_id: str, current: int | float | None) -> list[float]:
    """Seven mock periods ending at the live KPI (or prior anchor if current missing)."""
    shape = _MOCK_KPI_SERIES_SHAPE.get(
        kpi_id,
        [0.94, 0.95, 0.96, 0.97, 0.98, 0.99, 1.0],
    )
    if current is None or _is_non_numeric_scalar(current):
        base = _MOCK_KPI_PRIORS.get(kpi_id, {}).get("previous")
        if base is None or _is_non_numeric_scalar(base):
            return [1.0] * 7
        b = float(base)
        return [max(0.0, b * s) for s in shape]
    cur = float(current)
    anchor = cur / shape[-1] if shape[-1] else cur
    return [max(0.0, anchor * s) for s in shape]


def infer_trend_state(series: Sequence[float], *, higher_is_bad: bool) -> TrendState:
    """Rules-only trajectory: slope sign, magnitude vs noise, and step volatility (no ML)."""
    vals = [float(x) for x in series if not _is_non_numeric_scalar(x)]
    if len(vals) < 3:
        return "stable"
    first, last = vals[0], vals[-1]
    n = len(vals)
    slope = (last - first) / float(n - 1)
    steps = [vals[i + 1] - vals[i] for i in range(n - 1)]
    mean_abs_step = sum(abs(s) for s in steps) / float(len(steps)) if steps else 0.0
    if mean_abs_step < 1e-12:
        return "stable"
    step_var = sum((s - sum(steps) / len(steps)) ** 2 for s in steps) / float(len(steps))
    step_std = math.sqrt(max(0.0, step_var))
    cv = step_std / mean_abs_step
    slope_ratio = abs(slope) / mean_abs_step

    if cv >= 1.15 and slope_ratio < 0.55:
        return "volatile"
    # Flat net drift with high step churn — oscillatory / unstable regime (CV alone undercounts when |Δ| is large).
    if abs(slope) < mean_abs_step * 0.22 and step_std >= mean_abs_step * 0.82:
        return "volatile"

    eps = max(mean_abs_step * 0.12, 1e-9)
    if higher_is_bad:
        if slope > eps:
            return "worsening"
        if slope < -eps:
            return "improving"
    else:
        if slope < -eps:
            return "worsening"
        if slope > eps:
            return "improving"
    return "stable"


def trend_state_caption(state: TrendState) -> str:
    return {
        "improving": "improving trend",
        "stable": "stabilizing",
        "worsening": "worsening trend",
        "volatile": "elevated volatility",
    }[state]


def render_kpi_sparkline(values: Sequence[float], *, width: int = 52, height: int = 10) -> str:
    """Ultra-compact inline SVG sparkline for KPI cards (no axes, no interaction)."""
    seq = [float(x) for x in values if not _is_non_numeric_scalar(x)]
    if len(seq) < 2:
        return ""
    lo, hi = min(seq), max(seq)
    span = hi - lo
    pad = span * 0.08 if span > 1e-9 else 1.0
    y0, y1 = lo - pad, hi + pad
    y_rng = y1 - y0 if y1 > y0 else 1.0
    n = len(seq)
    pts: list[str] = []
    for i, v in enumerate(seq):
        x = (i / (n - 1)) * 100.0
        yn = (v - y0) / y_rng
        y = 4.0 + (1.0 - yn) * 16.0
        pts.append(f"{x:.2f},{y:.2f}")
    poly = " ".join(pts)
    return (
        f'<svg class="kpi-spark-svg" width="{width}" height="{height}" viewBox="0 0 100 20" '
        'preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        f'<polyline fill="none" stroke="#94a3b8" stroke-width="1.1" stroke-linecap="round" '
        f'stroke-linejoin="round" opacity="0.55" points="{poly}"/>'
        "</svg>"
    )


def build_sparkline_altair_chart(values: Sequence[float]) -> alt.Chart:
    """Minimal Altair line spec for the same series (tests / optional embedding); KPI cards use SVG."""
    seq = [float(x) for x in values if not _is_non_numeric_scalar(x)]
    if len(seq) < 2:
        seq = [0.0, 0.0]
    df = pd.DataFrame({"i": list(range(len(seq))), "v": seq})
    return (
        alt.Chart(df)
        .mark_line(stroke="#94a3b8", strokeWidth=1.25, interpolate="monotone")
        .encode(
            x=alt.X("i:Q", axis=None, scale=alt.Scale(zero=False), title=None),
            y=alt.Y("v:Q", axis=None, scale=alt.Scale(zero=False), title=None),
        )
        .properties(width=54, height=11, padding=0)
        .configure_view(strokeWidth=0)
    )


def compute_escalation_risk(alert: dict[str, Any], *, kpi_context: dict[str, Any]) -> str:
    """Muted escalation posture for alert chips — heuristics from severity, domain drift, counts, evidence."""
    worsening = frozenset(str(d) for d in (kpi_context.get("worsening_domains") or []))
    improving = frozenset(str(d) for d in (kpi_context.get("improving_domains") or []))
    kpi_forecast = kpi_context.get("kpi_forecast") or {}
    sev = _normalize_severity(str(alert.get("severity", "")))
    cat = str(alert.get("category", "")).strip().lower()
    cat_domain = {"inventory": "inventory", "delivery": "deliveries", "supplier": "suppliers", "operational": "governance"}.get(
        cat, ""
    )
    title = str(alert.get("title", "")).lower()
    summary = str(alert.get("summary", "")).lower()
    blob = f"{title} {summary}"
    cross = (
        ("inventory" in blob and "deliver" in blob)
        or ("supplier" in blob and ("inventory" in blob or "stock" in blob))
        or ("breach" in blob and "supplier" in blob)
    )
    evid = alert.get("evidence") or []
    n_evid = len(evid) if isinstance(evid, list) else 0
    breach_hits = 0
    if isinstance(evid, list):
        for ev in evid:
            if not isinstance(ev, dict):
                continue
            nm = str(ev.get("name", "")).lower()
            if "breach" in nm or "delay" in nm or "late" in nm:
                breach_hits += 1

    kpi_worsening = False
    if cat in ("inventory", "delivery", "supplier", "operational"):
        kid = {"inventory": "critical_inventory", "delivery": "sla_breaches", "supplier": "high_risk_suppliers", "operational": "critical_recommendations"}.get(cat)
        if kid and isinstance(kpi_forecast.get(kid), dict):
            kpi_worsening = str((kpi_forecast[kid] or {}).get("state")) == "worsening"

    raw_count = alert.get("count") or alert.get("entity_count")
    try:
        count_n = float(raw_count) if raw_count not in (None, "") else 0.0
    except (TypeError, ValueError):
        count_n = 0.0

    if cross and sev in ("critical", "high"):
        return "Cross-domain escalation risk"
    if cat_domain in worsening and sev == "critical" and (n_evid >= 4 or breach_hits >= 2 or count_n >= 12.0):
        return "Likely escalation"
    if cat_domain in worsening and sev == "high" and (n_evid >= 3 or breach_hits >= 1 or kpi_worsening):
        return "Likely escalation"
    if cat_domain in improving and sev in ("low", "medium") and n_evid <= 2 and not cross:
        return "Stabilizing"
    if sev == "low" and cat_domain not in worsening and count_n < 8.0:
        return "Contained"
    if sev in ("medium", "low") and not cross and cat_domain not in worsening:
        return "Contained"
    if kpi_worsening and sev in ("critical", "high"):
        return "Likely escalation"
    return "Contained"


def _ordinal_period(n: int) -> str:
    return {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth"}.get(n, f"{n}th")


def _phase2_priority_time_to_impact(ai_payload: dict[str, Any] | None) -> str | None:
    if not isinstance(ai_payload, dict):
        return None
    recs = [r for r in (ai_payload.get("recommendations") or []) if isinstance(r, dict)]
    if not recs:
        return None
    sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    recs_sorted = sorted(
        recs,
        key=lambda r: (
            sev_rank.get(_normalize_severity(str(r.get("severity", ""))), 9),
            str(r.get("id", "")),
        ),
    )
    for r in recs_sorted:
        raw = r.get("time_to_impact")
        if raw is None or str(raw).strip() == "":
            continue
        return str(raw).strip()
    return None


def _phase2_confidence_band_line(ai_payload: dict[str, Any] | None) -> str | None:
    if not isinstance(ai_payload, dict):
        return None
    levels: list[str] = []
    for r in ai_payload.get("recommendations") or []:
        if not isinstance(r, dict):
            continue
        c = str(r.get("confidence") or "").strip().lower()
        if c in ("high", "medium", "low"):
            levels.append(c)
    if not levels:
        return None
    rank = {"low": 0, "medium": 1, "high": 2}
    lo = min(levels, key=lambda x: rank[x])
    hi = max(levels, key=lambda x: rank[x])
    if lo == hi:
        band = lo.capitalize()
    else:
        band = f"{lo.capitalize()}–{hi.capitalize()}"
    return f"Cross-alert model confidence band: {band}."


def build_forecast_summary(
    *,
    kpi_ctx: dict[str, Any],
    risk_items: list[dict[str, Any]] | None,
    ai_payload: dict[str, Any] | None,
    critical_inventory: int | None,
    sla_breaches: int | None,
    high_risk_suppliers: int | None,
    critical_recommendations: int | None,
) -> list[str]:
    """Deterministic executive lines (max 6): trajectories, stabilizing domains, predicted pressure."""
    worsening: list[str] = list(kpi_ctx.get("worsening_domains") or [])
    improving: list[str] = list(kpi_ctx.get("improving_domains") or [])
    forecast: dict[str, Any] = kpi_ctx.get("kpi_forecast") or {}
    inv = int(critical_inventory or 0)
    sla = int(sla_breaches or 0)
    hrs = int(high_risk_suppliers or 0)
    cra = int(critical_recommendations or 0)

    def _state(kpi_id: str) -> TrendState:
        block = forecast.get(kpi_id)
        if isinstance(block, dict):
            raw = block.get("state", "stable")
            if raw in ("improving", "stable", "worsening", "volatile"):
                return raw  # type: ignore[return-value]
        return "stable"

    lines: list[str] = []

    sla_s, inv_s, sup_s, _gov_s = (
        _state("sla_breaches"),
        _state("critical_inventory"),
        _state("high_risk_suppliers"),
        _state("critical_recommendations"),
    )

    if "deliveries" in worsening or sla_s == "worsening" or (sla_s == "volatile" and sla > 0):
        streak = int(_MOCK_WORSEN_STREAK_PERIODS.get("deliveries", 0))
        if streak >= 2 and ("deliveries" in worsening or sla_s == "worsening"):
            ord_w = _ordinal_period(streak)
            lines.append(
                f"Delivery pressure continues to worsen with SLA breaches trending upward for the {ord_w} consecutive period."
            )
        else:
            lines.append(
                "Delivery pressure is building versus the recent baseline; SLA breach counts are tracking on the adverse side of the seven-period window."
            )
    elif sla > 0 and sla_s in ("stable", "volatile"):
        lines.append("Delivery lanes remain under SLA stress while short-horizon movement is not clearly directional.")

    if sup_s == "stable" and hrs > 0:
        lines.append("Supplier reliability remains elevated but stable.")
    elif sup_s == "improving":
        lines.append("Supplier risk cohorts are easing versus the trailing window.")

    if inv_s == "improving" or ("inventory" in improving and inv_s != "worsening"):
        lines.append("Inventory exposure improved materially, reducing near-term fulfillment risk.")
    elif inv_s == "volatile" and inv > 0:
        lines.append("Inventory signals are uneven period to period; exception handling should stay tight on critical SKUs.")

    stable_domains: list[str] = []
    for kpi_id, _label, domain in _KPI_NARR_BIND:
        stt = _state(kpi_id)
        if stt == "stable" and domain not in worsening and domain not in improving:
            stable_domains.append(domain)
    if stable_domains and len(lines) < 5:
        pretty = {"inventory": "inventory", "deliveries": "delivery", "suppliers": "supplier", "governance": "governance"}.get(
            stable_domains[0], stable_domains[0]
        )
        lines.append(f"{pretty.capitalize()} posture is steady versus the trailing window with no material drift signal.")

    volatile_kpis = [d for k, _l, d in _KPI_NARR_BIND if _state(k) == "volatile"]
    if volatile_kpis and len(lines) < 6:
        lines.append("One or more headline metrics show elevated short-horizon volatility; prioritize confirmation before broad actions.")

    if isinstance(risk_items, list) and len(risk_items) >= 12 and len(lines) < 6:
        lines.append(
            "Operational risk register volume is high; sequence containment to limit cross-owner contention."
        )

    ai_critical_n = 0
    if isinstance(ai_payload, dict):
        for _r in ai_payload.get("recommendations") or []:
            if isinstance(_r, dict) and _normalize_severity(str(_r.get("severity", ""))) == "critical":
                ai_critical_n += 1

    if ("deliveries" in worsening or sla_s == "worsening") and sla > 0:
        lines.append(
            "If current breach rates persist, delivery operations are likely to remain the primary escalation area over the next cycle."
        )
    elif "inventory" in worsening or inv_s == "worsening":
        lines.append(
            "If inventory drift continues, fulfillment risk is likely to concentrate on critical SKU coverage over the next cycle."
        )
    elif ai_critical_n >= 2 and not worsening:
        lines.append(
            "Predicted operational pressure is tilted toward exception volume while headline KPI drift remains comparatively contained."
        )
    elif not lines:
        lines.append(
            "Operational indicators are steady versus the trailing window; maintain cadence and watch tier-one lanes for early drift."
        )
    else:
        lines.append("Near-term operational pressure appears manageable if owners hold the current recovery tempo.")

    tti_ln = _phase2_priority_time_to_impact(ai_payload)
    if tti_ln:
        lines.insert(0, tti_ln)
    band_ln = _phase2_confidence_band_line(ai_payload)
    if band_ln:
        lines.append(band_ln)

    out: list[str] = []
    for ln in lines:
        s = str(ln).strip()
        if s and s not in out:
            out.append(s)
        if len(out) >= 6:
            break
    return out[:6]


def _format_metric_value(value: Any, *, max_decimals: int = 2) -> str:
    """Format numbers for display: integers without decimals, floats rounded to max_decimals."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if f == int(f):
        return f"{int(f):,}"
    rounded = round(f, max_decimals)
    s = f"{rounded:.{max_decimals}f}"
    if max_decimals > 0:
        s = s.rstrip("0").rstrip(".")
    return s


def _normalize_severity(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    if s in ("critical", "high", "medium", "low"):
        return s
    return "unknown"


# --- Root-cause intelligence & action orchestration (deterministic, no LLM) ---


class RootCauseDriver(TypedDict, total=False):
    """Single inferred operational driver (entities must come from supplied data only)."""

    driver_key: str
    headline: str
    strength: float
    entities: list[str]


class DominantEntityResult(TypedDict):
    """Concentration posture for executive chips and enrichment."""

    pattern: Literal["Concentrated risk", "Distributed risk", "Localized instability"]
    detail: str
    top_share: float
    top_entities: list[str]


class PrioritizedAction(TypedDict):
    """One ranked remediation line for the priority panel."""

    title: str
    owner: str
    impact: Literal["High", "Medium", "Low"]
    urgency: Literal["Immediate", "High", "Elevated", "Standard"]


class EnrichedAlertContext(TypedDict, total=False):
    """Subtle per-alert diagnosis for cards (no workflow semantics)."""

    driver: str
    concentration_badge: str
    owner: str
    target_window: str
    escalation_trigger: str


_ENRICH_DRIVER_MAP: dict[str, tuple[str, str]] = {
    "route_concentration": ("Carrier / route concentration", "Logistics"),
    "route_instability": ("Route instability", "Logistics"),
    "delivery_failure_concentration": ("Delivery failure concentration", "Logistics"),
    "supplier_reliability_degradation": ("Supplier reliability degradation", "Supplier Ops"),
    "inventory_allocation_imbalance": ("Inventory allocation imbalance", "Inventory Planning"),
    "delayed_replenishment": ("Delayed replenishment", "Inventory Planning"),
    "cross_domain_dependency_pressure": ("Cross-domain dependency pressure", "Ops leadership"),
}
_DELIVERY_DRIVER_KEYS = frozenset(_ENRICH_DRIVER_MAP) & frozenset(
    {"route_concentration", "route_instability", "delivery_failure_concentration"}
)


def _risk_row_weight(row: dict[str, Any]) -> float:
    sev = _normalize_severity(str(row.get("severity", "")))
    mult = {"critical": 1.35, "high": 1.15, "medium": 1.0, "low": 0.85, "unknown": 0.9}.get(sev, 0.9)
    raw_score = row.get("score")
    raw_count = row.get("count")
    try:
        s = float(raw_score) if raw_score not in (None, "") else 0.0
    except (TypeError, ValueError):
        s = 0.0
    try:
        c = float(raw_count) if raw_count not in (None, "") else 0.0
    except (TypeError, ValueError):
        c = 0.0
    base = s if s > 0 else c
    return max(0.0, base) * mult


def _parse_risk_entity(row: dict[str, Any]) -> tuple[str, str]:
    """Return (domain, entity_id) parsed from API risk labels — unknown shapes fall back to full label."""
    rt = str(row.get("risk_type", "")).strip().lower()
    label = str(row.get("label", "")).strip()
    if rt == "delivery" and label.startswith("SLA breaches on "):
        return ("route", label[len("SLA breaches on ") :].strip())
    if rt == "inventory" and label.startswith("Low stock for "):
        return ("product", label[len("Low stock for ") :].strip())
    if rt == "supplier" and label.startswith("Low reliability: "):
        return ("supplier", label[len("Low reliability: ") :].strip())
    return (rt or "risk", label)


def _entity_weight_map(risk_items: list[dict[str, Any]] | None) -> dict[str, float]:
    weights: dict[str, float] = {}
    for row in risk_items or []:
        if not isinstance(row, dict):
            continue
        dom, key = _parse_risk_entity(row)
        if not key:
            continue
        pk = f"{dom}:{key}"
        weights[pk] = weights.get(pk, 0.0) + _risk_row_weight(row)
    return weights


def concentration_score(entity_weights: dict[str, float]) -> float:
    """Normalized Herfindahl-style concentration in [0, 1]; higher means fewer entities dominate."""
    total = sum(entity_weights.values())
    if total <= 1e-12 or not entity_weights:
        return 0.0
    shares = [w / total for w in entity_weights.values()]
    n = len(shares)
    hhi = sum(s * s for s in shares)
    if n <= 1:
        return 1.0
    min_hhi = 1.0 / float(n)
    denom = 1.0 - min_hhi
    if denom <= 1e-12:
        return 0.0
    return max(0.0, min(1.0, (hhi - min_hhi) / denom))


def _top_k_share(entity_weights: dict[str, float], k: int = 3) -> tuple[float, list[str]]:
    total = sum(entity_weights.values())
    if total <= 1e-12:
        return 0.0, []
    ranked = sorted(entity_weights.items(), key=lambda x: x[1], reverse=True)
    topk = ranked[:k]
    share = sum(w for _, w in topk) / total
    keys = [key for key, _ in topk]
    return share, keys


def dominant_entity_detection(
    *,
    risk_items: list[dict[str, Any]] | None,
    kpi_ctx: dict[str, Any],
    failed_deliveries: int,
) -> DominantEntityResult:
    """Classify risk concentration for executive badges; uses only operational risk rows + KPI volatility."""
    weights = _entity_weight_map(risk_items)
    share3, top_keys = _top_k_share(weights, 3)
    forecast = kpi_ctx.get("kpi_forecast") or {}
    sla_block = forecast.get("sla_breaches") if isinstance(forecast.get("sla_breaches"), dict) else {}
    sla_state = str((sla_block or {}).get("state", "stable"))

    route_keys = [k.split(":", 1)[1] for k in top_keys if k.startswith("route:")]
    n_routes = sum(1 for k in weights if k.startswith("route:"))

    volatile_delivery = sla_state == "volatile" and int(failed_deliveries or 0) >= 0
    if (
        volatile_delivery
        and n_routes > 0
        and n_routes <= 6
        and share3 >= 0.38
        and any(k.startswith("route:") for k in top_keys[:2])
    ):
        rlist = ", ".join(route_keys[:3]) if route_keys else "key routes"
        return {
            "pattern": "Localized instability",
            "detail": f"Delivery KPI volatility aligns with concentrated breach exposure on {rlist}.",
            "top_share": round(share3, 2),
            "top_entities": route_keys[:5],
        }

    if share3 >= 0.56 and len(weights) >= 3:
        return {
            "pattern": "Concentrated risk",
            "detail": f"Top three entities account for {int(round(share3 * 100))}% of weighted operational exposure.",
            "top_share": round(share3, 2),
            "top_entities": [k.split(":", 1)[1] if ":" in k else k for k in top_keys],
        }

    if len(weights) >= 8 and share3 <= 0.42:
        return {
            "pattern": "Distributed risk",
            "detail": "Exposure is spread across many entities with no single dominant cluster in the risk register.",
            "top_share": round(share3, 2),
            "top_entities": [k.split(":", 1)[1] if ":" in k else k for k in top_keys],
        }

    if share3 >= 0.48:
        return {
            "pattern": "Concentrated risk",
            "detail": f"Top three entities account for {int(round(share3 * 100))}% of weighted operational exposure.",
            "top_share": round(share3, 2),
            "top_entities": [k.split(":", 1)[1] if ":" in k else k for k in top_keys],
        }
    return {
        "pattern": "Distributed risk",
        "detail": "No acute single-cluster dominance in the current risk register slice.",
        "top_share": round(share3, 2),
        "top_entities": [k.split(":", 1)[1] if ":" in k else k for k in top_keys],
    }


def _severity_mix(risk_items: list[dict[str, Any]] | None) -> dict[str, int]:
    mix: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0}
    for row in risk_items or []:
        if not isinstance(row, dict):
            continue
        k = _normalize_severity(str(row.get("severity", "")))
        mix[k] = mix.get(k, 0) + 1
    return mix


def _delivery_route_weights(risk_items: list[dict[str, Any]] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in risk_items or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("risk_type", "")).lower() != "delivery":
            continue
        _, key = _parse_risk_entity(row)
        if not key:
            continue
        out[key] = out.get(key, 0.0) + _risk_row_weight(row)
    return out


def _supplier_name_weights(risk_items: list[dict[str, Any]] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in risk_items or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("risk_type", "")).lower() != "supplier":
            continue
        _, key = _parse_risk_entity(row)
        if not key:
            continue
        out[key] = out.get(key, 0.0) + _risk_row_weight(row)
    return out


def infer_root_causes(
    *,
    risk_items: list[dict[str, Any]] | None,
    ai_alerts: list[dict[str, Any]] | None,
    kpi_ctx: dict[str, Any],
    critical_inventory: int | None,
    sla_breaches: int | None,
    high_risk_suppliers: int | None,
    critical_recommendations: int | None,
    delayed_delivery_summary: dict[str, Any] | None,
    supplier_overview: dict[str, Any] | None,
) -> list[RootCauseDriver]:
    """Deterministic multi-signal root-cause inference; entity strings are parsed from risk rows only."""
    risks = [r for r in (risk_items or []) if isinstance(r, dict)]
    alerts = [a for a in (ai_alerts or []) if isinstance(a, dict)]
    forecast = kpi_ctx.get("kpi_forecast") or {}
    worsening = frozenset(str(d) for d in (kpi_ctx.get("worsening_domains") or []))

    def _state(kpi_id: str) -> TrendState:
        block = forecast.get(kpi_id)
        if isinstance(block, dict):
            raw = block.get("state", "stable")
            if raw in ("improving", "stable", "worsening", "volatile"):
                return raw  # type: ignore[return-value]
        return "stable"

    sla_s = _state("sla_breaches")
    inv_s = _state("critical_inventory")
    sup_s = _state("high_risk_suppliers")

    inv_n = int(critical_inventory or 0)
    sla_n = int(sla_breaches or 0)
    hrs_n = int(high_risk_suppliers or 0)
    gov_n = int(critical_recommendations or 0)

    dd = delayed_delivery_summary or {}
    try:
        failed_d = int(dd.get("failed_deliveries") or 0)
    except (TypeError, ValueError):
        failed_d = 0
    try:
        breach_hours_proxy = float(sum(float(r.get("score") or 0) for r in risks if str(r.get("risk_type")) == "delivery"))
    except (TypeError, ValueError):
        breach_hours_proxy = 0.0

    so = supplier_overview or {}
    try:
        avg_rel = float(so.get("avg_reliability_score")) if so.get("avg_reliability_score") is not None else None
    except (TypeError, ValueError):
        avg_rel = None

    mix = _severity_mix(risks)
    route_w = _delivery_route_weights(risks)
    total_route_w = sum(route_w.values())
    top3_route_share, top_route_keys = _top_k_share(route_w, 3)
    sup_w = _supplier_name_weights(risks)
    total_sup_w = sum(sup_w.values())
    top3_sup_share, top_sup_keys = _top_k_share(sup_w, 3)

    risk_types = {str(r.get("risk_type", "")).lower() for r in risks}
    inv_rows = [r for r in risks if str(r.get("risk_type", "")).lower() == "inventory"]
    distinct_products = len({_parse_risk_entity(r)[1] for r in inv_rows})

    sev_high = mix.get("critical", 0) + mix.get("high", 0)
    cross_alert = 0
    for a in alerts:
        blob = f"{a.get('title','')} {a.get('summary','')}".lower()
        if ("inventory" in blob and "deliver" in blob) or ("supplier" in blob and ("inventory" in blob or "stock" in blob)):
            cross_alert += 1

    drivers: list[RootCauseDriver] = []

    if len(route_w) >= 2 and total_route_w > 0 and top3_route_share >= 0.5:
        ent = top_route_keys[:3]
        drivers.append(
            {
                "driver_key": "route_concentration",
                "headline": "Route / carrier concentration",
                "strength": float(top3_route_share) * (1.0 + 0.08 * mix.get("critical", 0)),
                "entities": ent,
            }
        )

    if sla_s == "volatile" or (sla_s == "worsening" and sla_n > 0):
        ent = top_route_keys[:4] if top_route_keys else []
        drivers.append(
            {
                "driver_key": "route_instability",
                "headline": "Route instability",
                "strength": 0.72 + (0.06 * len(ent)) + (0.04 if sla_s == "volatile" else 0.0),
                "entities": ent,
            }
        )

    if sup_w and (hrs_n > 0 or sup_s in ("worsening", "volatile") or (avg_rel is not None and avg_rel < 0.72)):
        ent = top_sup_keys[:4]
        drivers.append(
            {
                "driver_key": "supplier_reliability_degradation",
                "headline": "Supplier reliability degradation",
                "strength": float(total_sup_w) * 0.15 + float(hrs_n) * 0.12 + (0.2 if sup_s == "worsening" else 0.0),
                "entities": ent,
            }
        )

    if failed_d >= 2 or mix.get("critical", 0) >= 2 or (sla_n > 0 and failed_d >= 1):
        ent = top_route_keys[:3]
        drivers.append(
            {
                "driver_key": "delivery_failure_concentration",
                "headline": "Delivery failure pressure",
                "strength": float(failed_d) * 0.25 + float(sla_n) * 0.02 + float(breach_hours_proxy) * 0.01,
                "entities": ent,
            }
        )

    if distinct_products >= 4 and len(inv_rows) >= 4:
        prods = list({_parse_risk_entity(r)[1] for r in inv_rows})[:6]
        drivers.append(
            {
                "driver_key": "inventory_allocation_imbalance",
                "headline": "Inventory allocation imbalance",
                "strength": float(len(inv_rows)) * 0.11 + float(distinct_products) * 0.05,
                "entities": prods,
            }
        )

    if ("inventory" in worsening or inv_s == "worsening") and len(inv_rows) >= 2:
        inv_prods = sorted(
            ({_parse_risk_entity(r)[1] for r in inv_rows}),
            key=lambda p: sum(_risk_row_weight(r) for r in inv_rows if _parse_risk_entity(r)[1] == p),
            reverse=True,
        )[:4]
        drivers.append(
            {
                "driver_key": "delayed_replenishment",
                "headline": "Delayed replenishment",
                "strength": float(inv_n) * 0.04 + float(len(inv_rows)) * 0.14 + (0.25 if inv_s == "worsening" else 0.0),
                "entities": inv_prods,
            }
        )

    type_pressure = sum(1 for t in ("inventory", "delivery", "supplier") if t in risk_types)
    if (len(risk_types) >= 2 and sev_high >= 2) or cross_alert >= 1 or (type_pressure >= 2 and gov_n >= 1):
        drivers.append(
            {
                "driver_key": "cross_domain_dependency_pressure",
                "headline": "Cross-domain dependency pressure",
                "strength": float(cross_alert) * 0.4 + float(sev_high) * 0.08 + 0.15 * len(risk_types),
                "entities": [],
            }
        )

    # De-dupe by driver_key keeping max strength
    merged: dict[str, RootCauseDriver] = {}
    for d in drivers:
        key = str(d.get("driver_key", ""))
        if not key:
            continue
        cur = merged.get(key)
        if cur is None or float(d.get("strength", 0)) > float(cur.get("strength", 0)):
            merged[key] = d
    out = sorted(merged.values(), key=lambda x: float(x.get("strength", 0)), reverse=True)
    return out[:6]


def build_root_cause_summary(
    drivers: list[RootCauseDriver],
    *,
    top_supplier_share: float | None,
    top_route_share: float | None,
) -> list[str]:
    """Executive sentences grounded in inferred drivers and measured concentration shares."""
    lines: list[str] = []
    if not drivers:
        return lines

    for d in drivers[:3]:
        dk = str(d.get("driver_key", ""))
        ent = [str(e).strip() for e in (d.get("entities") or []) if str(e).strip()]
        if dk == "route_concentration" and len(ent) >= 2:
            shown = ent[:3]
            if len(shown) == 2:
                lines.append(
                    f"Primary delivery pressure is concentrated across {shown[0]} and {shown[1]}, representing repeated SLA breach patterns."
                )
            else:
                lines.append(
                    f"Primary delivery pressure is concentrated across {shown[0]}, {shown[1]}, and {shown[2]}, representing repeated SLA breach patterns."
                )
        elif dk == "supplier_reliability_degradation":
            lines.append(
                "Supplier reliability degradation appears correlated with elevated delivery failures and breach-hour accumulation."
            )
        elif dk == "delayed_replenishment" and ent:
            sku_txt = ", ".join(ent[:3])
            lines.append(f"Inventory exposure is increasingly linked to delayed replenishment for critical SKUs ({sku_txt}).")
        elif dk == "route_instability":
            if ent:
                lines.append(
                    f"Route-level instability is visible across {', '.join(ent[:3])}, consistent with uneven SLA performance."
                )
            else:
                lines.append(
                    "Route-level instability is consistent with uneven SLA performance in the delivery KPI window."
                )
        elif dk == "cross_domain_dependency_pressure":
            lines.append(
                "Multiple domains show simultaneous elevated severity, indicating cross-domain dependency pressure in the register."
            )

    if top_supplier_share is not None and top_supplier_share >= 0.55 and top_supplier_share < 0.99:
        lines.append(
            f"Top supplier entries in the risk register represent a high share (~{int(round(top_supplier_share * 100))}%) of supplier-weighted exposure."
        )
    if top_route_share is not None and top_route_share >= 0.55 and top_route_share < 0.99:
        lines.append(
            f"Route breach-hour mass is skewed: the top routes hold roughly {int(round(top_route_share * 100))}% of delivery-weighted exposure."
        )

    out: list[str] = []
    for ln in lines:
        s = str(ln).strip()
        if s and s not in out:
            out.append(s)
    return out[:4]


def prioritize_actions(
    *,
    root_causes: list[RootCauseDriver],
    dominant: DominantEntityResult,
    risk_items: list[dict[str, Any]] | None,
    kpi_ctx: dict[str, Any],
) -> list[PrioritizedAction]:
    """Rank up to five containment moves by leverage, cross-domain impact, urgency, containment, and blast-radius reduction."""
    route_w = _delivery_route_weights(risk_items)
    ranked_routes = sorted(route_w.items(), key=lambda x: x[1], reverse=True)
    top_routes = [k for k, _ in ranked_routes[:4]]
    sup_w = _supplier_name_weights(risk_items)
    ranked_sup = sorted(sup_w.items(), key=lambda x: x[1], reverse=True)
    top_sup = [k for k, _ in ranked_sup[:4]]

    keys = {str(d.get("driver_key", "")) for d in root_causes}
    forecast = kpi_ctx.get("kpi_forecast") or {}
    sla_fc = forecast.get("sla_breaches") if isinstance(forecast.get("sla_breaches"), dict) else {}
    sla_volatile = str((sla_fc or {}).get("state", "")) == "volatile"
    # Scoring axes (higher = stronger reason to act first): leverage, cross_domain, urgency_n, containment, blast_reduction
    cand: list[tuple[tuple[float, float, float, float, float, str], PrioritizedAction]] = []

    def _push(
        sort_key: tuple[float, float, float, float, float, str],
        row: PrioritizedAction,
    ) -> None:
        cand.append((sort_key, row))

    if "route_concentration" in keys or "route_instability" in keys or "delivery_failure_concentration" in keys:
        if len(top_routes) >= 2:
            rtxt = " / ".join(top_routes[:3])
            title = f"Stabilize {rtxt} delivery lanes"
        elif len(top_routes) == 1:
            title = f"Stabilize {top_routes[0]} delivery lane"
        else:
            title = "Stabilize tier-one delivery lanes with active SLA breaches"
        n_route = len(top_routes)
        blast = 22.0 + min(8.0, float(n_route) * 1.5)
        leverage = 30.0 if n_route else 18.0
        if sla_volatile:
            leverage += 2.0
        cross = 10.0 + (6.0 if "cross_domain_dependency_pressure" in keys else 0.0)
        urg_n = 40.0  # Immediate
        contain = 24.0 + min(6.0, float(sum(route_w.values())) * 0.02)
        _push(
            (leverage, cross, urg_n, contain, blast, title),
            {"title": title, "owner": "Logistics", "impact": "High", "urgency": "Immediate"},
        )

    if "supplier_reliability_degradation" in keys:
        if top_sup:
            st = ", ".join(top_sup[:3])
            title = f"Isolate and qualify unreliable supplier cohort ({st})"
        else:
            title = "Isolate unreliable supplier cohort flagged in the reliability register"
        leverage = 16.0 + min(10.0, float(len(top_sup)) * 2.5)
        cross = 14.0 + (5.0 if "delivery_failure_concentration" in keys else 0.0)
        urg_n = 28.0  # High
        contain = 18.0
        blast = 14.0 + min(8.0, float(sum(sup_w.values())) * 0.03)
        _push(
            (leverage, cross, urg_n, contain, blast, title),
            {"title": title, "owner": "Supplier Ops", "impact": "Medium", "urgency": "High"},
        )

    if "delayed_replenishment" in keys or "inventory_allocation_imbalance" in keys:
        title = "Re-sequence replenishment for critical SKU coverage gaps"
        leverage = 26.0
        cross = 18.0
        urg_n = 28.0
        contain = 22.0
        blast = 16.0
        _push(
            (leverage, cross, urg_n, contain, blast, title),
            {"title": title, "owner": "Inventory Planning", "impact": "High", "urgency": "High"},
        )

    if "cross_domain_dependency_pressure" in keys or dominant["pattern"] == "Localized instability":
        title = "Sequence cross-functional containment (logistics, supplier ops, inventory planning)"
        leverage = 24.0
        cross = 30.0
        urg_n = 40.0
        contain = 20.0
        blast = 20.0
        _push(
            (leverage, cross, urg_n, contain, blast, title),
            {"title": title, "owner": "Ops leadership", "impact": "High", "urgency": "Immediate"},
        )

    if not cand:
        title = "Hold steady-state monitoring; no acute driver ranked above threshold"
        _push(
            (1.0, 1.0, 4.0, 2.0, 1.0, title),
            {"title": title, "owner": "Ops leadership", "impact": "Low", "urgency": "Standard"},
        )

    # Dedupe by title keeping best sort tuple (lexicographic max)
    best: dict[str, tuple[tuple[float, float, float, float, float, str], PrioritizedAction]] = {}
    for sk, row in cand:
        t = str(row["title"])
        prev = best.get(t)
        if prev is None or sk > prev[0]:
            best[t] = (sk, row)

    ranked = sorted(best.values(), key=lambda x: x[0], reverse=True)
    out = [row for _, row in ranked[:5]]

    fed_title = "Maintain federated exception cadence; avoid over-rotating on a single lane"
    if len(out) < 2 and dominant["pattern"] == "Distributed risk" and not any(str(r.get("title")) == fed_title for r in out):
        out.append(
            {
                "title": fed_title,
                "owner": "Ops leadership",
                "impact": "Medium",
                "urgency": "Standard",
            }
        )

    return out[:5]


def build_action_panel(actions: list[PrioritizedAction]) -> str:
    """Compact HTML for the executive priority panel (read-only decision support)."""
    if not actions:
        return ""
    rows: list[str] = []
    for i, a in enumerate(actions, start=1):
        title = html.escape(str(a.get("title", "")))
        owner = html.escape(str(a.get("owner", "")))
        impact = html.escape(str(a.get("impact", "")))
        urg = html.escape(str(a.get("urgency", "")))
        rows.append(
            f'<div class="exec-pa-row">'
            f'<div class="exec-pa-idx">{i}</div>'
            f'<div class="exec-pa-body">'
            f'<div class="exec-pa-title">{title}</div>'
            f'<div class="exec-pa-meta">'
            f'<span class="exec-pa-chip exec-pa-chip--owner">{owner}</span>'
            f'<span class="exec-pa-chip exec-pa-chip--urg">{urg}</span>'
            f'<span class="exec-pa-impact">{impact} impact</span>'
            f"</div></div></div>"
        )
    return (
        '<div class="exec-pa" role="region" aria-label="Priority actions">'
        '<div class="exec-pa-head">Priority actions</div>'
        f'<div class="exec-pa-stack">{"".join(rows)}</div>'
        "</div>"
    )


def enrich_alert_context(
    alert: dict[str, Any],
    *,
    kpi_ctx: dict[str, Any],
    dominant: DominantEntityResult,
    root_causes: list[RootCauseDriver] | None = None,
) -> EnrichedAlertContext:
    """Map an alert to a probable driver, recommended owner, and concentration posture."""
    cat = str(alert.get("category", "")).strip().lower()
    forecast = kpi_ctx.get("kpi_forecast") or {}
    sla_block = forecast.get("sla_breaches") if isinstance(forecast.get("sla_breaches"), dict) else {}
    sla_state = str((sla_block or {}).get("state", "stable"))

    driver = "Operational variance"
    owner = "Ops leadership"
    if cat == "delivery":
        driver = "Route instability" if sla_state == "volatile" else "SLA breach concentration"
        owner = "Logistics"
    elif cat == "supplier":
        driver = "Supplier reliability degradation"
        owner = "Supplier Ops"
    elif cat == "inventory":
        driver = "Delayed replenishment"
        owner = "Inventory Planning"
    elif cat == "operational":
        driver = "Governance / exception load"
        owner = "Ops leadership"

    title = str(alert.get("title", "")).lower()
    summary = str(alert.get("summary", "")).lower()
    blob = f"{title} {summary}"
    if "route" in blob or "lane" in blob or "rt-" in blob:
        driver = "Route instability"
        owner = "Logistics"
    if "replenish" in blob or "sku" in blob or "stock" in blob:
        driver = "Delayed replenishment"
        owner = "Inventory Planning"

    for rc in root_causes or []:
        dk = str(rc.get("driver_key", "")).strip()
        if dk not in _ENRICH_DRIVER_MAP:
            continue
        if cat == "delivery" and dk in _DELIVERY_DRIVER_KEYS:
            driver, owner = _ENRICH_DRIVER_MAP[dk]
            break
        if cat == "supplier" and dk == "supplier_reliability_degradation":
            driver, owner = _ENRICH_DRIVER_MAP[dk]
            break
        if cat == "inventory" and dk in ("delayed_replenishment", "inventory_allocation_imbalance"):
            driver, owner = _ENRICH_DRIVER_MAP[dk]
            break
        if cat == "operational" and dk == "cross_domain_dependency_pressure":
            driver, owner = _ENRICH_DRIVER_MAP[dk]
            break

    api_owner = str(alert.get("owner") or "").strip()
    if api_owner:
        owner = api_owner
    target_window = str(alert.get("target_window") or "").strip()
    escalation_trigger = str(alert.get("escalation_trigger") or "").strip()

    conc = dominant["pattern"]

    return {
        "driver": driver,
        "concentration_badge": conc,
        "owner": owner,
        "target_window": target_window,
        "escalation_trigger": escalation_trigger,
    }


def _coerce_dominant_result(raw: Any) -> DominantEntityResult:
    if isinstance(raw, dict):
        pat = str(raw.get("pattern", "")).strip()
        if pat not in ("Concentrated risk", "Distributed risk", "Localized instability"):
            pat = "Distributed risk"
        te = raw.get("top_entities") or []
        if not isinstance(te, list):
            te = []
        clean_entities = [str(x) for x in te if str(x).strip()]
        return {
            "pattern": pat,  # type: ignore[typeddict-item]
            "detail": str(raw.get("detail", "") or ""),
            "top_share": float(raw.get("top_share") or 0.0),
            "top_entities": clean_entities,
        }
    return {"pattern": "Distributed risk", "detail": "", "top_share": 0.0, "top_entities": []}


def build_intel_bundle(
    *,
    risk_items: list[dict[str, Any]] | None,
    ai_payload: dict[str, Any] | None,
    kpi_ctx: dict[str, Any],
    critical_inventory: int | None,
    sla_breaches: int | None,
    high_risk_suppliers: int | None,
    critical_recommendations: int | None,
    delayed_delivery_summary: dict[str, Any] | None,
    supplier_overview: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assemble inference outputs for narrative, badges, alerts, and the action panel."""
    alerts = [r for r in ((ai_payload or {}).get("recommendations") or []) if isinstance(r, dict)]
    try:
        failed_d = int((delayed_delivery_summary or {}).get("failed_deliveries") or 0)
    except (TypeError, ValueError):
        failed_d = 0

    dominant = dominant_entity_detection(
        risk_items=risk_items,
        kpi_ctx=kpi_ctx,
        failed_deliveries=failed_d,
    )
    root_causes = infer_root_causes(
        risk_items=risk_items,
        ai_alerts=alerts,
        kpi_ctx=kpi_ctx,
        critical_inventory=critical_inventory,
        sla_breaches=sla_breaches,
        high_risk_suppliers=high_risk_suppliers,
        critical_recommendations=critical_recommendations,
        delayed_delivery_summary=delayed_delivery_summary,
        supplier_overview=supplier_overview,
    )
    sup_w = _supplier_name_weights(risk_items)
    route_w = _delivery_route_weights(risk_items)
    top_sup_share, _ = _top_k_share(sup_w, 3) if sup_w else (0.0, [])
    top_route_share, _ = _top_k_share(route_w, 3) if route_w else (0.0, [])
    root_summary = build_root_cause_summary(
        root_causes,
        top_supplier_share=top_sup_share if sup_w else None,
        top_route_share=top_route_share if route_w else None,
    )
    actions = prioritize_actions(
        root_causes=root_causes,
        dominant=dominant,
        risk_items=risk_items,
        kpi_ctx=kpi_ctx,
    )
    conc_idx = concentration_score(_entity_weight_map(risk_items))
    return {
        "dominant": dominant,
        "root_causes": root_causes,
        "root_summary": root_summary,
        "prioritized_actions": actions,
        "concentration_index": conc_idx,
        "top_supplier_share": top_sup_share,
        "top_route_share": top_route_share,
    }


def merge_executive_narrative_lines(
    *,
    forecast_lines: list[str],
    dominant: DominantEntityResult,
    root_summary: list[str],
    root_cause_keys: frozenset[str] | None = None,
) -> list[str]:
    """Blend forecast copy with concentration and driver guidance (bounded length)."""
    rkeys = root_cause_keys or frozenset()
    out: list[str] = []
    for ln in forecast_lines[:5]:
        s = str(ln).strip()
        if s and s not in out:
            out.append(s)

    pat = dominant["pattern"]
    det = str(dominant.get("detail", "")).strip()
    if pat == "Concentrated risk" and det:
        line = f"{pat}: {det}"
        if line not in out:
            out.append(line)
    elif pat == "Localized instability" and det:
        line = (
            "Delivery instability remains concentrated in a limited set of repeated breach routes, "
            "suggesting localized operational breakdown rather than network-wide degradation."
        )
        if line not in out:
            out.append(line)
    elif pat == "Distributed risk" and len(out) < 7:
        line = (
            "Distributed risk: register exposure is comparatively spread; "
            "prioritize sequencing over single-entity heroics."
        )
        if line not in out:
            out.append(line)

    for ln in root_summary[:2]:
        s = str(ln).strip()
        if s and s not in out:
            out.append(s)

    if (
        "supplier_reliability_degradation" in rkeys
        and (
            "delivery_failure_concentration" in rkeys
            or "route_instability" in rkeys
            or "route_concentration" in rkeys
        )
        and len(out) < 8
    ):
        corr = (
            "Supplier reliability pressure is increasingly correlated with delayed deliveries "
            "and breach accumulation."
        )
        if corr not in out:
            out.append(corr)

    coord = (
        "Cross-functional coordination between logistics, supplier operations, and inventory planning "
        "remains the highest-leverage containment path when delivery and supplier signals move together."
    )
    if len(out) < 8 and coord not in out and (pat in ("Concentrated risk", "Localized instability") or root_summary or rkeys):
        out.append(coord)

    final: list[str] = []
    for ln in out:
        if ln not in final:
            final.append(ln)
        if len(final) >= 8:
            break
    return final


def _severity_badge_markup(severity: str | None) -> str:
    raw = (severity or "").strip()
    key = _normalize_severity(raw)
    if key == "unknown" and raw:
        label = raw.strip() or "N/A"
    else:
        label = "N/A" if key == "unknown" else key.capitalize()
    safe_label = html.escape(label)
    return f'<span class="sev-badge sev-{key}">{safe_label}</span>'


def _format_evidence_value(val: Any) -> str:
    if val is None or val == "":
        return ""
    if isinstance(val, bool):
        return str(val)
    if isinstance(val, (int, float)):
        return _format_metric_value(val)
    if isinstance(val, str):
        stripped = val.strip()
        if not stripped:
            return val
        try:
            return _format_metric_value(float(stripped))
        except ValueError:
            return val
    return str(val)


def _enterprise_css() -> None:
    st.markdown(
        """
        <style>
          :root {
            --exec-bg: #c9d0de;
            --exec-surface: #e8ecf4;
            --exec-surface-elevated: #dfe6f0;
            --exec-border: #b8c2d4;
            --exec-border-strong: #94a3b8;
            --exec-text: #0a0f1a;
            --exec-muted: #334155;
            --exec-muted-soft: #64748b;
            --exec-label: #475569;
            --exec-accent: #0f172a;
            --exec-section-bar: #0f172a;
            --exec-section-bar-text: #f1f5f9;
            --exec-section-bar-soft: #334155;
            --exec-section-bar-soft-text: #e2e8f0;
            --exec-section-size: 0.8125rem;
            --exec-section-weight: 600;
            --kpi-alert: #b91c1c;
            --kpi-warn: #c2410c;
            --kpi-ok: #166534;
            --exec-section-gap: 0.7rem;
            --exec-section-gap-tight: 0.56rem;
          }
          html {
            font-size: 16px;
          }
          .stApp {
            background: var(--exec-bg);
            color: var(--exec-text);
            font-size: 0.9375rem !important;
            font-weight: 400;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
          }
          .stApp p,
          .stApp li,
          .stApp label {
            font-size: 0.9rem;
            font-weight: 400;
            line-height: 1.36;
          }
          div[data-testid="stMarkdownContainer"] > p:not([class]) {
            font-size: 0.9rem !important;
            font-weight: 400 !important;
            line-height: 1.36 !important;
          }
          /* Full-width main: remove Streamlit max-width; ~98% viewport feel */
          section.main,
          section[data-testid="stMain"] {
            padding-left: 0.15rem !important;
            padding-right: 0.15rem !important;
            margin-top: 0 !important;
          }
          section.main > div,
          section[data-testid="stMain"] > div {
            padding-top: 0.9rem !important;
            max-width: none !important;
            width: 100% !important;
            margin-top: 0 !important;
          }
          div[data-testid="stAppViewContainer"] > section[data-testid="stMain"] > div {
            max-width: none !important;
          }
          .main,
          section.main {
            margin-top: 0 !important;
          }
          .main .block-container,
          section.main > div > div > div.block-container,
          .block-container {
            padding-top: 1.05rem !important;
            padding-bottom: 0.25rem !important;
            padding-left: 0.25rem !important;
            padding-right: 0.25rem !important;
            max-width: none !important;
            width: min(100%, 98vw) !important;
            margin-top: 0 !important;
            margin-left: auto !important;
            margin-right: auto !important;
          }
          h1 {
            font-size: 1.34rem !important;
            font-weight: 700 !important;
            letter-spacing: -0.022em !important;
            margin-bottom: 0.06rem !important;
            margin-top: 0 !important;
            line-height: 1.12 !important;
            color: var(--exec-text) !important;
          }
          div[data-testid="stCaption"] {
            color: var(--exec-label) !important;
            font-size: 0.78rem !important;
            font-weight: 400 !important;
            margin-top: 0.02rem !important;
            line-height: 1.3 !important;
            letter-spacing: 0.01em;
          }
          .exec-section-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.5rem;
            margin: var(--exec-section-gap) 0 0.12rem 0;
            padding: 0.22rem 0.55rem;
            background: var(--exec-section-bar);
            border: 1px solid rgba(15, 23, 42, 0.2);
            border-radius: 6px;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.06);
          }
          .exec-section-head--soft {
            background: var(--exec-section-bar-soft);
            border-color: rgba(15, 23, 42, 0.14);
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
            margin: var(--exec-section-gap-tight) 0 0.12rem 0;
            padding: 0.18rem 0.5rem;
          }
          .exec-section-head--soft .exec-section-title {
            color: var(--exec-section-bar-soft-text);
            font-size: 0.78rem;
            font-weight: 600;
            letter-spacing: 0.03em;
          }
          .exec-section-head--soft .exec-section-meta {
            color: #cbd5e1;
            font-weight: 500;
            font-size: 0.74rem;
          }
          .exec-section-head--executive {
            margin: var(--exec-section-gap) 0 0.14rem 0;
            padding: 0.26rem 0.62rem;
            border-radius: 7px;
            border: 1px solid rgba(15, 23, 42, 0.24);
            box-shadow:
              inset 0 1px 0 rgba(255,255,255,0.07),
              0 1px 2px rgba(15, 23, 42, 0.12);
          }
          .exec-section-head--executive .exec-section-title {
            font-size: 0.84rem;
            font-weight: 700;
            letter-spacing: 0.015em;
          }
          .exec-section-head--first {
            margin-top: 0.12rem;
          }
          .exec-section-head.exec-section-head--tight-below {
            margin-bottom: 0.12rem;
          }
          .exec-section-title {
            margin: 0;
            padding: 0;
            font-size: var(--exec-section-size);
            font-weight: var(--exec-section-weight);
            letter-spacing: 0.02em;
            text-transform: none;
            color: var(--exec-section-bar-text);
            border: none;
            line-height: 1.22;
          }
          .exec-section-meta {
            margin: 0;
            font-size: 0.78rem;
            color: #cbd5e1;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
            font-weight: 600;
          }
          .exec-section-head--executive .exec-section-meta {
            color: #cbd5e1;
            font-weight: 500;
          }
          .exec-header-meta {
            color: var(--exec-label);
            font-size: 0.78rem;
            font-weight: 400;
            text-align: right;
            padding-top: 0.02rem;
            line-height: 1.3;
            margin: 0;
          }
          .exec-header-meta strong {
            color: var(--exec-text);
            font-size: 0.78rem;
            letter-spacing: 0.02em;
            text-transform: none;
            font-weight: 600;
          }
          .exec-ai-focal {
            margin: 0 0 0.06rem 0;
            padding: 0.22rem 0.34rem 0.22rem;
            background: rgba(241, 245, 249, 0.72);
            border: 1px solid rgba(71, 85, 105, 0.24);
            border-radius: 8px;
            box-shadow:
              0 1px 3px rgba(15, 23, 42, 0.07),
              inset 0 1px 0 rgba(255, 255, 255, 0.7);
          }
          .exec-ai-focal .rec-stack {
            gap: 0.2rem;
          }
          section[data-testid="stMain"] [data-testid="element-container"] {
            padding-left: 0.12rem !important;
            padding-right: 0.12rem !important;
          }
          section[data-testid="stSidebar"] {
            background: var(--exec-surface);
            border-right: 1px solid rgba(71, 85, 105, 0.35);
          }
          section[data-testid="stSidebar"] .block-container {
            padding-top: 0.55rem !important;
            padding-left: 0.7rem !important;
            padding-right: 0.7rem !important;
          }
          div[data-testid="stExpander"] {
            background: var(--exec-surface-elevated);
            border: 1px solid rgba(71, 85, 105, 0.2);
            border-radius: 7px;
            margin-bottom: 0.12rem;
            margin-top: 0;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
          }
          div[data-testid="stExpander"] summary {
            font-size: 0.78rem;
            font-weight: 600;
            color: var(--exec-label);
            padding: 0.06rem 0.26rem;
            min-height: unset;
            letter-spacing: 0.01em;
          }
          div[data-testid="stExpander"] summary span {
            font-size: 0.78rem !important;
            font-weight: 600 !important;
          }
          div[data-testid="stExpander"] [data-testid="stExpanderDetails"] {
            padding-top: 0.04rem;
            padding-bottom: 0.14rem;
            padding-left: 0.08rem;
            padding-right: 0.08rem;
          }
          div[data-testid="column"] {
            padding-top: 0.01rem;
            padding-bottom: 0.01rem;
          }
          div[data-testid="stHorizontalBlock"] > div {
            gap: 0.24rem;
          }
          .kpi-row {
            display: flex;
            flex-wrap: nowrap;
            gap: 0.2rem;
            width: 100%;
            margin-bottom: 0.04rem;
          }
          .kpi-card {
            position: relative;
            flex: 1 1 0;
            min-width: 0;
            background: var(--exec-surface-elevated);
            border: 1px solid rgba(71, 85, 105, 0.22);
            border-radius: 7px;
            padding: 0.14rem 0.34rem 0.12rem 0.36rem;
            box-shadow:
              0 1px 2px rgba(15, 23, 42, 0.055),
              0 0.5px 0 rgba(255, 255, 255, 0.55) inset;
            border-left: 3px solid var(--exec-accent);
          }
          .kpi-card--calm {
            border-left-color: #5b6b82;
          }
          .kpi-card--watch {
            border-left-color: var(--kpi-warn);
            box-shadow:
              0 1px 3px rgba(15, 23, 42, 0.07),
              0 0 0 1px rgba(194, 65, 12, 0.06) inset,
              0 0.5px 0 rgba(255, 255, 255, 0.5) inset;
          }
          .kpi-card--alert {
            border-left-color: var(--kpi-alert);
            box-shadow:
              0 1px 3px rgba(15, 23, 42, 0.08),
              0 0 0 1px rgba(185, 28, 28, 0.07) inset,
              0 0.5px 0 rgba(255, 255, 255, 0.45) inset;
          }
          .kpi-sev-pip {
            position: absolute;
            top: 0.24rem;
            right: 0.28rem;
            width: 7px;
            height: 7px;
            border-radius: 50%;
            box-shadow: 0 0 0 1px rgba(255,255,255,0.85);
          }
          .kpi-card--calm .kpi-sev-pip { background: #94a3b8; }
          .kpi-card--alert .kpi-sev-pip { background: var(--kpi-alert); }
          .kpi-card--watch .kpi-sev-pip { background: var(--kpi-warn); }
          .kpi-label {
            font-size: 0.72rem;
            font-weight: 500;
            letter-spacing: 0.02em;
            text-transform: none;
            color: var(--exec-label);
            line-height: 1.05;
            margin-bottom: 0.02rem;
            padding-right: 0.62rem;
            opacity: 0.9;
          }
          .kpi-value {
            font-size: 1.36rem;
            font-weight: 800;
            color: var(--exec-text);
            line-height: 1.0;
            font-variant-numeric: tabular-nums;
            letter-spacing: -0.03em;
          }
          .kpi-value--alert {
            color: #991b1b;
          }
          .kpi-value--watch {
            color: var(--kpi-warn);
          }
          .kpi-value-row {
            display: flex;
            flex-wrap: nowrap;
            align-items: baseline;
            gap: 0.22rem;
            min-width: 0;
            line-height: 1.0;
            margin-top: 0;
          }
          .kpi-value-row .kpi-value {
            flex: 0 1 auto;
            min-width: 0;
          }
          .kpi-trend {
            font-size: 0.72rem;
            font-weight: 600;
            font-variant-numeric: tabular-nums;
            letter-spacing: 0.01em;
            white-space: nowrap;
            flex: 0 0 auto;
          }
          .kpi-trend-arrow {
            margin-right: 0.12rem;
            font-size: 0.62rem;
            font-weight: 700;
          }
          .kpi-trend--bad {
            color: var(--kpi-alert);
          }
          .kpi-trend--good {
            color: var(--kpi-ok);
          }
          .kpi-trend--neutral {
            color: var(--exec-muted-soft);
          }
          .kpi-prior {
            font-size: 0.66rem;
            font-weight: 400;
            color: var(--exec-muted-soft);
            line-height: 1.1;
            margin-top: 0.02rem;
            letter-spacing: 0.008em;
          }
          .kpi-trend-note {
            font-size: 0.64rem;
            font-weight: 500;
            color: var(--exec-label);
            line-height: 1.08;
            margin-top: 0.01rem;
            opacity: 0.88;
          }
          .kpi-forecast-foot {
            display: flex;
            flex-direction: row;
            justify-content: space-between;
            align-items: flex-end;
            gap: 0.28rem;
            margin-top: 0.02rem;
            line-height: 0;
          }
          .kpi-trend-state {
            font-size: 0.605rem;
            font-weight: 500;
            color: #64748b;
            letter-spacing: 0.012em;
            line-height: 1.08;
            opacity: 0.85;
            flex: 1 1 auto;
            min-width: 0;
            padding-bottom: 0.02rem;
          }
          .kpi-spark-wrap {
            flex: 0 0 auto;
            overflow: visible;
            max-width: 100%;
          }
          .kpi-spark-svg {
            display: block;
            vertical-align: bottom;
          }
          .sev-badge {
            display: inline-block;
            padding: 0.06rem 0.32rem;
            border-radius: 4px;
            font-size: 0.68rem;
            font-weight: 700;
            letter-spacing: 0.02em;
            white-space: nowrap;
            border: 1px solid transparent;
            vertical-align: middle;
            line-height: 1.12;
            text-transform: none;
          }
          .sev-critical { background: #7f1d1d; color: #fef2f2; border-color: #991b1b; }
          .sev-high { background: #c2410c; color: #fff7ed; border-color: #ea580c; }
          .sev-medium { background: #a16207; color: #fefce8; border-color: #ca8a04; }
          .sev-low { background: #166534; color: #f0fdf4; border-color: #15803d; }
          .sev-unknown { background: #475569; color: #f8fafc; border-color: #64748b; }
          .rec-panel-wrap {
            margin: 0;
            padding: 0;
          }
          div[data-testid="stMarkdownContainer"]:has(.rec-panel-wrap) p {
            margin-block: 0 !important;
          }
          div[data-testid="stMarkdownContainer"]:has(.rec-panel-wrap) ul {
            margin-block: 0 !important;
          }
          div[data-testid="stMarkdownContainer"]:has(.rec-panel-wrap) .rec-details-body p {
            margin: 0 0 0.04rem 0 !important;
          }
          div[data-testid="stMarkdownContainer"]:has(.rec-panel-wrap) .rec-details-body ul {
            margin: 0.02rem 0 0.04rem 0.78rem !important;
          }
          .rec-stack {
            display: flex;
            flex-direction: column;
            gap: 0.22rem;
          }
          .rec-card {
            background: var(--exec-surface);
            border: 1px solid rgba(100, 116, 139, 0.26);
            border-radius: 7px;
            padding: 0.1rem 0.36rem 0.08rem 0.36rem;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
            margin-bottom: 0;
          }
          .rec-card--critical { border-left: 2px solid #991b1b; background: #f5ecec; }
          .rec-card--high { border-left: 2px solid #c2410c; background: #faf6f0; }
          .rec-card--medium { border-left: 2px solid #a16207; }
          .rec-card--low { border-left: 2px solid #166534; }
          .rec-alert-top {
            display: flex;
            flex-wrap: nowrap;
            align-items: flex-start;
            justify-content: space-between;
            gap: 0.3rem;
            width: 100%;
            margin-bottom: 0;
            min-height: 0;
          }
          .rec-alert-head {
            display: flex;
            flex: 1;
            min-width: 0;
            align-items: flex-start;
            gap: 0.3rem;
            flex-wrap: wrap;
          }
          .rec-conf {
            flex: 0 0 auto;
            font-size: 0.56rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            border-radius: 3px;
            padding: 0.02rem 0.2rem;
            line-height: 1.08;
            margin-top: 0.02rem;
          }
          .rec-conf--high {
            color: #14532d;
            background: #dcfce7;
            border: 1px solid rgba(22, 101, 52, 0.25);
          }
          .rec-conf--medium {
            color: #7c2d12;
            background: #ffedd5;
            border: 1px solid rgba(194, 65, 12, 0.22);
          }
          .rec-conf--low {
            color: #64748b;
            background: #f1f5f9;
            border: 1px solid rgba(148, 163, 184, 0.35);
          }
          .rec-tti {
            font-size: 0.68rem;
            color: #334155;
            margin: 0 0 0.03rem 0;
            line-height: 1.2;
            font-weight: 500;
          }
          .rec-sim-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.12rem;
            margin: 0.02rem 0 0.03rem 0;
          }
          .rec-sim-chip {
            font-size: 0.595rem;
            color: #475569;
            background: rgba(226, 232, 240, 0.55);
            border: 1px solid rgba(148, 163, 184, 0.35);
            border-radius: 3px;
            padding: 0.03rem 0.22rem;
            line-height: 1.15;
            max-width: 100%;
          }
          .rec-causal-chain {
            margin: 0.04rem 0 0.06rem 1rem;
            padding: 0;
            font-size: 0.68rem;
            color: #475569;
            line-height: 1.25;
          }
          .rec-title-inline {
            font-size: 0.93rem;
            font-weight: 600;
            color: var(--exec-text);
            line-height: 1.18;
            letter-spacing: -0.016em;
            margin: 0;
            flex: 1;
            min-width: 0;
            white-space: normal;
            overflow: visible;
            text-overflow: unset;
            opacity: 1;
          }
          .rec-summary {
            font-size: 0.78rem;
            font-weight: 400;
            color: var(--exec-muted);
            line-height: 1.3;
            margin: 0.03rem 0 0.04rem 0;
            white-space: normal;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            opacity: 0.93;
          }
          .rec-actions-inline {
            margin: 0.02rem 0 0.03rem 0;
            padding-left: 0.88rem;
            font-size: 0.675rem;
            font-weight: 400;
            line-height: 1.3;
            color: #64748b;
            list-style-position: outside;
            opacity: 0.82;
          }
          .rec-actions-inline li {
            margin: 0;
            padding: 0;
          }
          .rec-actions-inline li + li {
            margin-top: 0.02rem;
          }
          .rec-details {
            margin: 0.04rem 0 0 0;
            border: 1px solid rgba(148, 163, 184, 0.16);
            border-radius: 4px;
            background: rgba(248, 250, 252, 0.42);
          }
          .rec-details > summary {
            list-style: none;
            cursor: pointer;
            font-size: 0.6rem;
            font-weight: 400;
            color: #94a3b8;
            padding: 0.03rem 0.22rem;
            user-select: none;
            letter-spacing: 0.045em;
            text-transform: uppercase;
            line-height: 1.18;
            opacity: 0.72;
          }
          .rec-details > summary::-webkit-details-marker { display: none; }
          .rec-details > summary::after {
            content: " +";
            font-size: 0.6rem;
            font-weight: 500;
            opacity: 0.55;
          }
          .rec-details[open] > summary::after { content: " −"; }
          .rec-details[open] > summary {
            border-bottom: 1px solid rgba(148, 163, 184, 0.14);
            color: #8898a8;
            opacity: 0.78;
          }
          .rec-details-body {
            padding: 0.06rem 0.24rem 0.08rem 0.24rem;
            font-size: 0.675rem;
            font-weight: 400;
            line-height: 1.28;
            color: var(--exec-muted);
            opacity: 0.88;
          }
          .rec-details-body .rec-dl-label {
            font-weight: 500;
            font-size: 0.5625rem;
            color: #94a3b8;
            margin: 0.06rem 0 0.02rem 0;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            line-height: 1.08;
            opacity: 0.75;
          }
          .rec-details-body .rec-dl-label:first-child { margin-top: 0; }
          .rec-details-body .rec-dl-label--actions {
            margin-top: 0.1rem;
            padding-top: 0.06rem;
            border-top: 1px dashed rgba(148, 163, 184, 0.22);
          }
          .rec-details-body p {
            margin: 0 0 0.02rem 0;
            font-size: 0.675rem;
            font-weight: 400;
            line-height: 1.26;
            color: var(--exec-muted);
          }
          .rec-details-body ul { margin: 0.02rem 0 0.03rem 0.72rem; padding: 0; }
          .rec-details-body ul.rec-details-actions {
            margin-left: 0.65rem;
            margin-top: 0.02rem;
          }
          .rec-details-body li {
            margin-bottom: 0.01rem;
            font-size: 0.675rem;
            font-weight: 400;
            line-height: 1.24;
            color: var(--exec-muted);
            opacity: 0.9;
          }
          .rec-details-body li:last-child { margin-bottom: 0; }
          .rec-details-body .rec-signal {
            font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
            font-size: 0.605rem;
            font-weight: 400;
            color: #64748b;
            margin: 0.01rem 0;
            line-height: 1.24;
            letter-spacing: -0.01em;
            opacity: 0.78;
          }
          div[data-testid="stExpander"] div[data-testid="stMarkdownContainer"] p,
          div[data-testid="stExpander"] div[data-testid="stMarkdownContainer"] li {
            font-size: 0.84rem;
            font-weight: 400;
            line-height: 1.32;
            color: var(--exec-text);
            margin-bottom: 0.05rem;
          }
          .scenario-block {
            margin-top: 0.06rem;
            width: 100%;
          }
          .exec-narr {
            margin: 0.24rem 0 0.22rem 0;
            padding: 0.24rem 0.5rem 0.26rem 0.5rem;
            border-radius: 6px;
            border: 1px solid rgba(71, 85, 105, 0.22);
            background: #eef2f8;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
            overflow: hidden;
          }
          .exec-narr p {
            margin: 0 !important;
          }
          .exec-narr-lead {
            font-size: 0.84rem;
            font-weight: 600;
            letter-spacing: -0.012em;
            line-height: 1.26;
            color: var(--exec-text);
          }
          .exec-narr-deltas {
            margin-top: 0.08rem !important;
            font-size: 0.74rem;
            font-weight: 500;
            line-height: 1.24;
            color: var(--exec-muted);
            letter-spacing: -0.01em;
          }
          .exec-narr-forecast {
            margin-top: 0.06rem !important;
            font-size: 0.755rem;
            font-weight: 400;
            line-height: 1.24;
            color: var(--exec-muted);
            letter-spacing: -0.008em;
          }
          .exec-narr-forecast:first-of-type {
            margin-top: 0.03rem !important;
          }
          .exec-narr-inline {
            margin: 0.02rem 0 0 0 !important;
            font-size: 0.75rem;
            font-weight: 400;
            line-height: 1.28;
            color: var(--exec-muted);
          }
          .exec-narr-inline .exec-narr-k {
            font-weight: 600;
            color: var(--exec-muted);
            margin-right: 0.28rem;
          }
          .exec-command-wrap {
            margin: 0.22rem 0 0.18rem 0;
            padding: 0;
            border: none;
            background: transparent;
          }
          .exec-pa {
            margin-top: 0.18rem;
            padding: 0.2rem 0.42rem 0.2rem 0.42rem;
            border-radius: 6px;
            border: 1px solid rgba(71, 85, 105, 0.2);
            background: rgba(248, 250, 252, 0.65);
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.035);
          }
          .exec-pa-head {
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            color: #475569;
            margin: 0 0 0.1rem 0;
            line-height: 1.12;
          }
          .exec-pa-stack {
            display: flex;
            flex-direction: column;
            gap: 0.06rem;
          }
          .exec-pa-row {
            display: flex;
            flex-direction: row;
            align-items: stretch;
            gap: 0.28rem;
            padding: 0.06rem 0.06rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.18);
          }
          .exec-pa-row:last-child {
            border-bottom: none;
            padding-bottom: 0.02rem;
          }
          .exec-pa-idx {
            flex: 0 0 1rem;
            font-size: 0.7rem;
            font-weight: 500;
            color: #94a3b8;
            line-height: 1.25;
            padding-top: 0.04rem;
            font-variant-numeric: tabular-nums;
            opacity: 0.85;
          }
          .exec-pa-body {
            flex: 1;
            min-width: 0;
          }
          .exec-pa-title {
            font-size: 0.84rem;
            font-weight: 600;
            color: var(--exec-text);
            line-height: 1.24;
            letter-spacing: -0.014em;
          }
          .exec-pa-meta {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 0.16rem;
            margin-top: 0.03rem;
          }
          .exec-pa-chip {
            display: inline-block;
            font-size: 0.56rem;
            font-weight: 600;
            letter-spacing: 0.02em;
            border-radius: 3px;
            padding: 0.02rem 0.22rem;
            line-height: 1.1;
            border: 1px solid rgba(148, 163, 184, 0.4);
            white-space: nowrap;
            max-width: 100%;
            overflow: hidden;
            text-overflow: ellipsis;
          }
          .exec-pa-chip--owner {
            color: #334155;
            background: rgba(226, 232, 240, 0.75);
          }
          .exec-pa-chip--urg {
            color: #0f172a;
            background: rgba(203, 213, 225, 0.55);
          }
          .exec-pa-impact {
            font-size: 0.56rem;
            font-weight: 500;
            color: #64748b;
            letter-spacing: 0.02em;
          }
          .ops-intel-strip {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 0.22rem;
            margin: 0.03rem 0 0.08rem 0;
            font-size: 0.7rem;
            font-weight: 500;
            color: var(--exec-muted);
            line-height: 1.22;
          }
          .ops-intel-chip {
            display: inline-block;
            font-size: 0.6rem;
            font-weight: 600;
            letter-spacing: 0.02em;
            color: #334155;
            background: rgba(241, 245, 249, 0.95);
            border: 1px solid rgba(148, 163, 184, 0.42);
            border-radius: 3px;
            padding: 0.02rem 0.28rem;
            line-height: 1.1;
          }
          .ops-intel-meta {
            font-size: 0.66rem;
            font-weight: 400;
            color: #64748b;
            letter-spacing: 0.01em;
          }
          .rec-intel-micro {
            display: flex;
            flex-wrap: wrap;
            align-items: baseline;
            gap: 0.1rem 0.26rem;
            margin: 0.02rem 0 0.01rem 0;
            font-size: 0.615rem;
            font-weight: 500;
            color: #64748b;
            line-height: 1.22;
            max-width: 100%;
          }
          .rec-intel-micro .rec-intel-k {
            color: #94a3b8;
            font-weight: 600;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            font-size: 0.56rem;
          }
          .rec-intel-micro .rec-intel-v {
            color: #475569;
            font-weight: 500;
          }
          .rec-intel-sep {
            color: #cbd5e1;
            font-weight: 400;
            user-select: none;
          }
          .rec-priority-pill {
            flex: 0 0 auto;
            font-size: 0.555rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            color: #0f172a;
            background: #e2e8f0;
            border: 1px solid rgba(71, 85, 105, 0.28);
            border-radius: 3px;
            padding: 0.02rem 0.22rem;
            line-height: 1.08;
            margin-left: auto;
          }
          .rec-explain-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.16rem;
            margin: 0.02rem 0 0.02rem 0;
            align-items: center;
          }
          .rec-chip {
            display: inline-block;
            font-size: 0.555rem;
            font-weight: 500;
            letter-spacing: 0.02em;
            color: #475569;
            background: rgba(241, 245, 249, 0.9);
            border: 1px solid rgba(148, 163, 184, 0.45);
            border-radius: 3px;
            padding: 0.02rem 0.22rem;
            line-height: 1.1;
          }
          .rec-esc-chip {
            display: inline-block;
            font-size: 0.535rem;
            font-weight: 500;
            letter-spacing: 0.03em;
            text-transform: none;
            color: #64748b;
            background: rgba(226, 232, 240, 0.65);
            border: 1px solid rgba(148, 163, 184, 0.35);
            border-radius: 3px;
            padding: 0.02rem 0.24rem;
            line-height: 1.08;
            margin-left: 0.1rem;
            opacity: 0.92;
          }
          .rec-field-h {
            font-size: 0.5375rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.055em;
            color: #94a3b8;
            margin: 0.02rem 0 0.01rem 0;
            line-height: 1.06;
          }
          .rec-card > .rec-field-h:first-of-type {
            margin-top: 0;
          }
          .rec-impact {
            font-size: 0.78rem;
            font-weight: 400;
            color: var(--exec-muted);
            line-height: 1.28;
            margin: 0 0 0.02rem 0;
            white-space: normal;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            opacity: 0.93;
          }
          .rec-action-sep {
            margin: 0.04rem 0 0.02rem 0;
            border: none;
            border-top: 1px solid rgba(100, 116, 139, 0.22);
          }
          .rec-action-head {
            font-size: 0.5375rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: #475569;
            margin: 0 0 0.02rem 0;
            line-height: 1.06;
          }
          .rec-actions-main {
            margin: 0 !important;
            padding-left: 0.88rem !important;
            font-size: 0.71rem;
            font-weight: 600;
            line-height: 1.24;
            color: #334155;
            list-style-position: outside;
          }
          .rec-actions-main li {
            margin: 0 !important;
            padding: 0 !important;
          }
          .rec-actions-main li + li {
            margin-top: 0.03rem !important;
          }
          .scenario-shell {
            max-height: 280px;
            overflow: hidden;
            margin: 0;
            padding: 0.18rem 0.4rem 0.1rem 0.4rem;
            width: 100%;
            box-sizing: border-box;
            border: 1px solid rgba(71, 85, 105, 0.16);
            border-radius: 8px;
            background: rgba(232, 236, 244, 0.55);
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.5);
          }
          .scenario-shell [data-testid="stVegaLiteChart"],
          .scenario-shell [data-testid="stArrowVegaLiteChart"] {
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            margin-left: 0 !important;
            margin-right: 0 !important;
            width: 100% !important;
          }
          [data-testid="stVegaLiteChart"],
          [data-testid="stArrowVegaLiteChart"] {
            width: 100% !important;
          }
          [data-testid="stVegaLiteChart"] canvas,
          [data-testid="stArrowVegaLiteChart"] canvas {
            max-width: 100% !important;
          }
          hr {
            margin: 0.3rem 0 0.2rem 0 !important;
            border: none;
            border-top: 1px solid rgba(100, 116, 139, 0.28);
          }
          div[data-testid="stAlert"] {
            border-radius: 8px !important;
            border: 1px solid rgba(71, 85, 105, 0.18) !important;
            font-size: 0.84rem !important;
            font-weight: 400 !important;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04) !important;
          }
          div[data-testid="stAlert"] p {
            font-size: 0.84rem !important;
            font-weight: 400 !important;
            line-height: 1.34 !important;
          }
          .ops-risks-wrap {
            max-height: min(19vh, 178px);
            overflow: auto;
            border: 1px solid rgba(51, 65, 85, 0.18);
            border-radius: 6px;
            background: #e6ebf3;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.5), 0 1px 2px rgba(15, 23, 42, 0.04);
          }
          .ops-risks-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
            font-weight: 500;
            line-height: 1.18;
            color: var(--exec-text);
          }
          .ops-risks-table thead th {
            position: sticky;
            top: 0;
            z-index: 2;
            text-align: left;
            font-weight: 600;
            font-size: 0.7rem;
            letter-spacing: 0.02em;
            text-transform: none;
            color: #d8dee9;
            background: #2a3645;
            border-bottom: 1px solid rgba(15, 23, 42, 0.3);
            padding: 0.14rem 0.46rem;
            box-shadow: 0 1px 0 rgba(15, 23, 42, 0.1);
          }
          .ops-risks-table tbody td {
            padding: 0.09rem 0.46rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.32);
            vertical-align: middle;
          }
          .ops-risks-table tbody tr:last-child td { border-bottom: none; }
          .ops-risks-table tbody tr:nth-child(even) td {
            background: rgba(15, 23, 42, 0.035);
          }
          .ops-risks-table tbody tr:nth-child(odd) td {
            background: rgba(255, 255, 255, 0.25);
          }
          .ops-risks-table td.ops-num {
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
          }
          div[data-testid="stDataFrame"] {
            font-size: 0.84rem;
            font-weight: 500;
          }
          div[data-testid="stDataFrame"] [role="gridcell"],
          div[data-testid="stDataFrame"] [role="columnheader"] {
            padding: 2px 8px !important;
            line-height: 1.22 !important;
            font-size: 0.84rem !important;
            font-weight: 500 !important;
          }
          div[data-testid="stDataFrame"] [role="row"] {
            min-height: 20px !important;
          }
          div[data-testid="stDataFrame"] [role="columnheader"] {
            font-weight: 600 !important;
            color: var(--exec-text) !important;
            background: #dce3ed !important;
            border-bottom: 1px solid rgba(100, 116, 139, 0.35) !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _section_head(
    label: str,
    meta: str | None = None,
    *,
    first: bool = False,
    compact: bool = False,
    variant: str = "soft",
) -> None:
    """Section chrome. variant: soft (supporting), standard, executive (primary focal)."""
    safe_label = html.escape(label)
    first_cls = " exec-section-head--first" if first else ""
    tight_cls = " exec-section-head--tight-below" if compact else ""
    if variant == "executive":
        var_cls = " exec-section-head--executive"
    elif variant == "standard":
        var_cls = ""
    else:
        var_cls = " exec-section-head--soft"
    if meta:
        safe_meta = html.escape(meta)
        st.markdown(
            f'<div class="exec-section-head{var_cls}{first_cls}{tight_cls}">'
            f'<span class="exec-section-title">{safe_label}</span>'
            f'<span class="exec-section-meta">{safe_meta}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="exec-section-head{var_cls}{first_cls}{tight_cls}">'
            f'<span class="exec-section-title">{safe_label}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )


def _kpi_trend_markup(delta: DeltaResult, *, higher_is_bad: bool) -> str:
    """Compact arrow + percent with semantic coloring (higher_is_bad flips good/bad for directions)."""
    direction = delta["direction"]
    formatted = delta["formatted"]
    text_e = html.escape(formatted)
    if formatted == "—":
        return f'<span class="kpi-trend kpi-trend--neutral">{text_e}</span>'
    if direction == "flat":
        return (
            f'<span class="kpi-trend kpi-trend--neutral">'
            f'<span class="kpi-trend-arrow">·</span>{text_e}'
            f"</span>"
        )
    arrow = "▲" if direction == "up" else "▼"
    if higher_is_bad:
        sem = "kpi-trend--bad" if direction == "up" else "kpi-trend--good"
    else:
        sem = "kpi-trend--good" if direction == "up" else "kpi-trend--bad"
    return (
        f'<span class="kpi-trend {sem}">'
        f'<span class="kpi-trend-arrow">{arrow}</span>{text_e}'
        f"</span>"
    )


def _kpi_card_markup(
    *,
    label: str,
    current: int | float | None,
    previous: int | float | None,
    higher_is_bad: bool,
    trend_label: str | None = None,
    trend_state_label: str | None = None,
    sparkline_svg: str | None = None,
) -> str:
    """Border accent from current value; trend row from prior-period mock (see _MOCK_KPI_PRIORS)."""
    label_e = html.escape(label)
    if current is None:
        disp = "—"
        num_accent = None
    else:
        try:
            num_accent = int(current)
            disp = f"{num_accent:,}"
        except (TypeError, ValueError):
            num_accent = None
            disp = _format_metric_value(current)

    if num_accent is not None and num_accent > 0:
        card_cls = "kpi-card kpi-card--alert"
        val_cls = "kpi-value kpi-value--alert"
    elif num_accent is not None and num_accent == 0:
        card_cls = "kpi-card kpi-card--calm"
        val_cls = "kpi-value"
    else:
        card_cls = "kpi-card kpi-card--calm"
        val_cls = "kpi-value"

    delta = compute_delta(current, previous)
    trend_html = _kpi_trend_markup(delta, higher_is_bad=higher_is_bad)
    if previous is None or _is_non_numeric_scalar(previous):
        prior_disp = "—"
    else:
        try:
            pf = float(previous)
            pi = int(pf)
            prior_disp = f"{pi:,}" if pf == pi else _format_metric_value(previous)
        except (TypeError, ValueError):
            prior_disp = _format_metric_value(previous)
    prior_e = html.escape(prior_disp)

    note_html = ""
    if trend_label:
        note_html = f'<div class="kpi-trend-note">{html.escape(trend_label)}</div>'

    foot_html = ""
    if trend_state_label or sparkline_svg:
        left = (
            f'<span class="kpi-trend-state">{html.escape(trend_state_label or "")}</span>'
            if trend_state_label
            else '<span class="kpi-trend-state"></span>'
        )
        spark = f'<div class="kpi-spark-wrap">{sparkline_svg}</div>' if sparkline_svg else ""
        foot_html = f'<div class="kpi-forecast-foot">{left}{spark}</div>'

    val_e = html.escape(disp)
    return (
        f'<div class="{card_cls}">'
        f'<span class="kpi-sev-pip" aria-hidden="true"></span>'
        f'<div class="kpi-label">{label_e}</div>'
        f'<div class="kpi-value-row">'
        f'<div class="{val_cls}">{val_e}</div>'
        f"{trend_html}"
        f"</div>"
        f'<div class="kpi-prior">vs prior period: {prior_e}</div>'
        f"{note_html}"
        f"{foot_html}"
        f"</div>"
    )


def render_kpi_card(
    *,
    label: str,
    current: int | float | None,
    previous: int | float | None,
    higher_is_bad: bool,
    trend_label: str | None = None,
    trend_state_label: str | None = None,
    sparkline_svg: str | None = None,
) -> None:
    st.markdown(
        _kpi_card_markup(
            label=label,
            current=current,
            previous=previous,
            higher_is_bad=higher_is_bad,
            trend_label=trend_label,
            trend_state_label=trend_state_label,
            sparkline_svg=sparkline_svg,
        ),
        unsafe_allow_html=True,
    )


def _kpi_row(
    *,
    kpi_ctx: dict[str, Any],
    critical_inventory: int | None,
    sla_breaches: int | None,
    high_risk_suppliers: int | None,
    critical_recommendations: int | None,
) -> None:
    _section_head("Key metrics", first=True, variant="soft")
    c1, c2, c3, c4 = st.columns(4, gap="small")
    specs: list[tuple[Any, str, str, int | None]] = [
        (c1, "critical_inventory", "Critical inventory", critical_inventory),
        (c2, "sla_breaches", "SLA breaches", sla_breaches),
        (c3, "high_risk_suppliers", "High-risk suppliers", high_risk_suppliers),
        (c4, "critical_recommendations", "Critical recommendations", critical_recommendations),
    ]
    forecast = kpi_ctx.get("kpi_forecast") or {}
    for col, kpi_id, label, raw_val in specs:
        meta = _MOCK_KPI_PRIORS[kpi_id]
        prev = meta["previous"]
        higher_is_bad = bool(meta["higher_is_bad"])
        fc_raw = forecast.get(kpi_id)
        fc: dict[str, Any] = fc_raw if isinstance(fc_raw, dict) else {}
        cap = str(fc.get("caption") or "") if fc else ""
        spark = str(fc.get("sparkline_svg") or "") if fc else ""
        with col:
            render_kpi_card(
                label=label,
                current=raw_val,
                previous=prev,
                higher_is_bad=higher_is_bad,
                trend_state_label=cap or None,
                sparkline_svg=spark or None,
            )


def _operational_risks_table(
    items: list[dict[str, Any]] | None,
    *,
    intel_bundle: dict[str, Any] | None = None,
) -> None:
    _section_head("Operational risks", variant="soft")
    if intel_bundle:
        dom = intel_bundle.get("dominant") or {}
        pat = str(dom.get("pattern", "")).strip()
        conc = float(intel_bundle.get("concentration_index") or 0.0)
        if pat:
            chip = f'<span class="ops-intel-chip">{html.escape(pat)}</span>'
            meta = ""
            if conc > 0.02:
                meta = (
                    f'<span class="ops-intel-meta">Register concentration index {html.escape(f"{conc:.2f}")}</span>'
                )
            strip = f'<div class="ops-intel-strip" role="note">{chip}{meta}</div>'
            st.markdown(strip, unsafe_allow_html=True)
    if not items:
        st.caption("No operational risk rows returned.")
        return
    df = pd.DataFrame(items)
    display_cols = [c for c in ("risk_type", "label", "severity", "count", "score", "metric") if c in df.columns]
    out = df[display_cols].copy()
    if "score" in out.columns:
        out["score"] = out["score"].map(_format_metric_value)
    if "count" in out.columns:
        out["count"] = out["count"].map(_format_metric_value)

    header_labels = {
        "risk_type": "Risk type",
        "label": "Label",
        "severity": "Severity",
        "count": "Count",
        "score": "Score",
        "metric": "Metric",
    }
    num_cols = frozenset({"count", "score"})
    thead_cells = "".join(f"<th>{html.escape(header_labels.get(c, c))}</th>" for c in display_cols)
    body_rows: list[str] = []
    for _, row in out.iterrows():
        tds: list[str] = []
        for c in display_cols:
            raw = row[c]
            if c == "severity":
                tds.append(f"<td>{_severity_badge_markup(str(raw) if raw is not None else '')}</td>")
            else:
                cls = ' class="ops-num"' if c in num_cols else ""
                cell = "" if pd.isna(raw) else str(raw)
                tds.append(f"<td{cls}>{html.escape(cell)}</td>")
        body_rows.append("<tr>" + "".join(tds) + "</tr>")
    table_html = (
        '<div class="ops-risks-wrap">'
        '<table class="ops-risks-table">'
        f"<thead><tr>{thead_cells}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table></div>"
    )
    st.markdown(table_html, unsafe_allow_html=True)


def _build_kpi_exec_context(
    critical_inventory: int | None,
    sla_breaches: int | None,
    high_risk_suppliers: int | None,
    critical_recommendations: int | None,
) -> dict[str, Any]:
    """KPI deltas vs mock priors: worsening/improving domains and ranked delta magnitudes for narrative and badges."""
    worsening_domains: list[str] = []
    improving_domains: list[str] = []
    delta_rows: list[tuple[str, str, str, float, bool, bool]] = []
    # (domain, label, formatted_delta, abs_pct, is_worsening, is_improving)
    values = {
        "critical_inventory": critical_inventory,
        "sla_breaches": sla_breaches,
        "high_risk_suppliers": high_risk_suppliers,
        "critical_recommendations": critical_recommendations,
    }
    for kpi_id, label, domain in _KPI_NARR_BIND:
        meta = _MOCK_KPI_PRIORS.get(kpi_id) or {}
        prev = meta.get("previous")
        higher_is_bad = bool(meta.get("higher_is_bad", True))
        cur = values.get(kpi_id)
        d = compute_delta(cur, prev)
        dp = d["delta_pct"]
        direction = d["direction"]
        worsens = False
        improves = False
        if direction != "flat" and dp is not None and not math.isnan(dp):
            if higher_is_bad:
                worsens = direction == "up"
                improves = direction == "down"
            else:
                worsens = direction == "down"
                improves = direction == "up"
        if worsens and domain not in worsening_domains:
            worsening_domains.append(domain)
        if improves and domain not in improving_domains:
            improving_domains.append(domain)
        if dp is not None and not math.isnan(dp):
            delta_rows.append((domain, label, d["formatted"], abs(float(dp)), worsens, improves))
    delta_rows.sort(key=lambda x: x[3], reverse=True)
    kpi_forecast: dict[str, KPIForecastSlice] = {}
    for kpi_id, _label, _domain in _KPI_NARR_BIND:
        meta = _MOCK_KPI_PRIORS.get(kpi_id) or {}
        higher_is_bad = bool(meta.get("higher_is_bad", True))
        cur = values.get(kpi_id)
        series = kpi_mock_history_series(kpi_id, cur)
        state = infer_trend_state(series, higher_is_bad=higher_is_bad)
        kpi_forecast[kpi_id] = {
            "state": state,
            "caption": trend_state_caption(state),
            "series": series,
            "sparkline_svg": render_kpi_sparkline(series),
        }
    return {
        "worsening_domains": worsening_domains,
        "improving_domains": improving_domains,
        "delta_rows": delta_rows,
        "values": values,
        "kpi_forecast": kpi_forecast,
    }


def compute_alert_priority(alert: dict[str, Any]) -> float:
    """Weighted heuristic priority for ranking AI alerts (higher = more urgent)."""
    sev = _normalize_severity(str(alert.get("severity", "")))
    base = {"critical": 100.0, "high": 72.0, "medium": 38.0, "low": 14.0, "unknown": 9.0}.get(sev, 9.0)
    cat = str(alert.get("category", "")).strip().lower()
    cat_w = {"inventory": 14.0, "delivery": 13.0, "supplier": 12.0, "operational": 9.0}.get(cat, 7.0)
    score = base + cat_w
    evid = alert.get("evidence") or []
    if isinstance(evid, list):
        score += min(16.0, float(len(evid)) * 2.75)
        for ev in evid:
            if not isinstance(ev, dict):
                continue
            name = str(ev.get("name", "")).lower()
            if any(k in name for k in ("breach", "delay", "critical", "fail", "risk")):
                score += 4.5
                break
    actions = alert.get("actions") or []
    if isinstance(actions, list) and len(actions) >= 3:
        score += 3.0
    raw_score = alert.get("score")
    try:
        if raw_score is not None and raw_score != "":
            score += min(12.0, max(0.0, float(raw_score)))
    except (TypeError, ValueError):
        pass
    raw_count = alert.get("count") or alert.get("entity_count")
    try:
        if raw_count is not None and raw_count != "":
            score += min(10.0, float(raw_count) * 0.35)
    except (TypeError, ValueError):
        pass
    return score


def compute_alert_badges(
    alert: dict[str, Any],
    *,
    worsening_domains: frozenset[str],
) -> list[str]:
    """Rule-based explainability chips; order is stable and compact."""
    badges: list[str] = []
    cat = str(alert.get("category", "")).strip().lower()
    sev = _normalize_severity(str(alert.get("severity", "")))
    title = str(alert.get("title", "")).lower()
    summary = str(alert.get("summary", "")).lower()
    rid = str(alert.get("id", "")).lower()
    blob = f"{title} {summary} {rid}"
    actions_txt = " ".join(_recommendation_actions_list(alert)).lower()

    cat_domain = {"inventory": "inventory", "delivery": "deliveries", "supplier": "suppliers", "operational": "governance"}.get(
        cat, ""
    )
    if cat_domain in worsening_domains and sev in ("critical", "high"):
        badges.append("Worsening")
    if cat == "operational" or ("inventory" in blob and "deliver" in blob) or (
        "supplier" in blob and ("inventory" in blob or "stock" in blob)
    ):
        badges.append("Cross-domain")
    if (
        "replenish" in actions_txt
        or "recovery" in actions_txt
        or "critical" in rid
        or (cat == "inventory" and sev == "critical")
    ):
        badges.append("Recovery candidate")
    if cat == "supplier" or "supplier" in title:
        badges.append("Supplier-driven")
    if cat == "inventory" or "sku" in blob or "stock" in blob:
        badges.append("Inventory pressure")
    # De-dupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for b in badges:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out[:5]


def _executive_narrative_html(
    *,
    kpi_ctx: dict[str, Any],
    risk_items: list[dict[str, Any]] | None,
    ai_payload: dict[str, Any] | None,
    critical_inventory: int | None,
    sla_breaches: int | None,
    high_risk_suppliers: int | None,
    critical_recommendations: int | None,
    intel_bundle: dict[str, Any] | None = None,
) -> str:
    """Forecast-oriented executive narrative plus optional intelligence overlay and priority panel."""
    base_lines = build_forecast_summary(
        kpi_ctx=kpi_ctx,
        risk_items=risk_items,
        ai_payload=ai_payload,
        critical_inventory=critical_inventory,
        sla_breaches=sla_breaches,
        high_risk_suppliers=high_risk_suppliers,
        critical_recommendations=critical_recommendations,
    )
    if intel_bundle:
        dom = _coerce_dominant_result(intel_bundle.get("dominant"))
        lines = merge_executive_narrative_lines(
            forecast_lines=base_lines,
            dominant=dom,
            root_summary=list(intel_bundle.get("root_summary") or []),
            root_cause_keys=frozenset(
                str(d.get("driver_key", "")).strip()
                for d in (intel_bundle.get("root_causes") or [])
                if isinstance(d, dict) and str(d.get("driver_key", "")).strip()
            ),
        )
    else:
        lines = base_lines
    if not lines:
        lines = ["Operational indicators are steady versus the trailing window; maintain exception cadence."]
    lead = lines[0]
    rest = lines[1:]
    body_rest = "".join(f'<p class="exec-narr-forecast">{html.escape(s)}</p>' for s in rest)
    narr = (
        '<div class="exec-narr" role="region" aria-label="Executive narrative">'
        f'<p class="exec-narr-lead">{html.escape(lead)}</p>'
        f"{body_rest}"
        "</div>"
    )
    pa = ""
    if intel_bundle:
        acts = intel_bundle.get("prioritized_actions") or []
        if isinstance(acts, list) and acts:
            pa = build_action_panel([a for a in acts if isinstance(a, dict)][:5])
    return f'<div class="exec-command-wrap">{narr}{pa}</div>'


def _executive_narrative_banner(
    *,
    kpi_ctx: dict[str, Any],
    critical_inventory: int | None,
    sla_breaches: int | None,
    high_risk_suppliers: int | None,
    critical_recommendations: int | None,
    risk_items: list[dict[str, Any]] | None,
    ai_payload: dict[str, Any] | None,
    intel_bundle: dict[str, Any] | None = None,
) -> None:
    html_block = _executive_narrative_html(
        kpi_ctx=kpi_ctx,
        risk_items=risk_items,
        ai_payload=ai_payload,
        critical_inventory=critical_inventory,
        sla_breaches=sla_breaches,
        high_risk_suppliers=high_risk_suppliers,
        critical_recommendations=critical_recommendations,
        intel_bundle=intel_bundle,
    )
    st.markdown(html_block, unsafe_allow_html=True)


def _recommendation_actions_list(r: dict[str, Any]) -> list[str]:
    raw = r.get("actions") or []
    out: list[str] = []
    if isinstance(raw, list):
        for a in raw:
            if a is None:
                continue
            s = str(a).strip()
            if s:
                out.append(s)
    return out


def _recommendation_evidence_body_html(r: dict[str, Any], actions_full: list[str]) -> str:
    """Rationale, signals/evidence, and actions beyond the 2–3 shown on the card."""
    parts: list[str] = []
    rationale = r.get("rationale")
    evidence = r.get("evidence") or []
    if rationale:
        parts.append('<div class="rec-dl-label">Rationale</div>')
        parts.append(f"<p>{html.escape(str(rationale))}</p>")
    ex = r.get("explainability")
    if isinstance(ex, dict):
        dom = str(ex.get("dominant_trigger_source") or "").strip()
        if dom:
            parts.append('<div class="rec-dl-label">Dominant trigger</div>')
            parts.append(f'<p class="rec-signal">{html.escape(dom)}</p>')
        chain = ex.get("causal_chain") or []
        if isinstance(chain, list) and chain:
            parts.append('<div class="rec-dl-label">Causal chain</div>')
            parts.append('<ol class="rec-causal-chain">')
            for step in chain:
                if str(step).strip():
                    parts.append(f"<li>{html.escape(str(step))}</li>")
            parts.append("</ol>")
        wcontrib = ex.get("weighted_contributors") or []
        if isinstance(wcontrib, list) and wcontrib:
            parts.append('<div class="rec-dl-label">Weighted contributors</div>')
            for row in wcontrib:
                if not isinstance(row, dict):
                    continue
                nm = str(row.get("name", ""))
                wt = row.get("weight")
                try:
                    pct = int(round(float(wt) * 100)) if wt is not None else None
                except (TypeError, ValueError):
                    pct = None
                if pct is not None:
                    parts.append(
                        f'<p class="rec-signal">{html.escape(nm)} — {pct}% of modeled driver weight</p>'
                    )
                else:
                    parts.append(f'<p class="rec-signal">{html.escape(nm)}</p>')
        kinf = ex.get("kpi_influences") or []
        if isinstance(kinf, list) and kinf:
            parts.append('<div class="rec-dl-label">KPI influence</div>')
            for row in kinf:
                if not isinstance(row, dict):
                    continue
                kid = str(row.get("kpi_id", ""))
                ip = row.get("influence_pct")
                try:
                    ipf = float(ip) if ip is not None else None
                except (TypeError, ValueError):
                    ipf = None
                if ipf is not None:
                    parts.append(
                        f'<p class="rec-signal">{html.escape(kid)} — {ipf:g}% of signal mix</p>'
                    )
    if evidence:
        parts.append('<div class="rec-dl-label">Signals / evidence</div>')
        for ev in evidence:
            if not isinstance(ev, dict):
                continue
            name = ev.get("name", "")
            val = ev.get("value")
            cmp_ = ev.get("comparison")
            bits = [str(name)]
            if val is not None and val != "":
                formatted = _format_evidence_value(val)
                if formatted:
                    bits.append(formatted)
            line = " — ".join(bits)
            if cmp_:
                line = f"{line} ({cmp_})"
            parts.append(f'<p class="rec-signal">{html.escape(line)}</p>')
    extra_actions = actions_full[2:]
    if extra_actions:
        parts.append('<div class="rec-dl-label rec-dl-label--actions">Additional actions</div>')
        parts.append('<ul class="rec-details-actions">')
        for a in extra_actions:
            parts.append(f"<li>{html.escape(str(a))}</li>")
        parts.append("</ul>")
    if not parts:
        parts.append('<p class="rec-signal">No supporting evidence recorded.</p>')
    return '<div class="rec-details-body">' + "".join(parts) + "</div>"


def _ai_recommendations_panel(
    payload: dict[str, Any] | None,
    *,
    kpi_context: dict[str, Any] | None = None,
    intel_bundle: dict[str, Any] | None = None,
) -> None:
    meta = None
    if payload:
        meta = f"v{payload.get('engine_version', '?')} · {payload.get('generated_at', '')}"
    _section_head("AI alerts", meta, compact=True, variant="executive")
    if not payload:
        st.caption("Alerts unavailable.")
        return
    recs = payload.get("recommendations") or []
    if not recs:
        st.info("No alerts returned for the current dataset.")
        return
    kpi_context = kpi_context or {}
    worsening_domains = frozenset(str(d) for d in (kpi_context.get("worsening_domains") or []))
    dominant = _coerce_dominant_result((intel_bundle or {}).get("dominant"))
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    recs_sorted = sorted(
        [r for r in recs if isinstance(r, dict)],
        key=lambda r: (
            -compute_alert_priority(r),
            severity_order.get(_normalize_severity(str(r.get("severity", ""))), 9),
            str(r.get("title", "")),
        ),
    )
    if not recs_sorted:
        st.info("No alerts returned for the current dataset.")
        return
    n_total = len(recs_sorted)
    default_visible = 5
    if n_total > default_visible:
        show_all = bool(st.session_state.get("dash_show_all_recs", False))
    else:
        show_all = False
    limit = n_total if show_all else min(default_visible, n_total)

    blocks: list[str] = ['<div class="rec-panel-wrap"><div class="exec-ai-focal"><div class="rec-stack">']
    for idx, r in enumerate(recs_sorted[:limit]):
        sev_key = _normalize_severity(str(r.get("severity", "")))
        title = str(r.get("title", "Alert"))
        summary_raw = r.get("summary") or ""
        summary = str(summary_raw).strip() or "—"
        actions_list = _recommendation_actions_list(r)
        card_mod = f" rec-card--{sev_key}" if sev_key in ("critical", "high", "medium", "low") else ""
        title_e = html.escape(title)
        summary_e = html.escape(summary)
        details_inner = _recommendation_evidence_body_html(r, actions_list)
        badges = compute_alert_badges(r, worsening_domains=worsening_domains)
        esc_lbl = compute_escalation_risk(r, kpi_context=kpi_context)
        ctx = enrich_alert_context(
            r,
            kpi_ctx=kpi_context,
            dominant=dominant,
            root_causes=[x for x in ((intel_bundle or {}).get("root_causes") or []) if isinstance(x, dict)],
        )
        cb = str(ctx.get("concentration_badge", "") or "")
        if cb == "Concentrated risk":
            rp_short = "Concentrated"
        elif cb == "Localized instability":
            rp_short = "Localized"
        else:
            rp_short = "Distributed"
        tw = str(ctx.get("target_window") or "").strip()
        esc_api = str(ctx.get("escalation_trigger") or "").strip()
        tw_seg = ""
        if tw:
            tw_seg = (
                '<span class="rec-intel-sep">·</span>'
                '<span class="rec-intel-k">Target</span>'
                f'<span class="rec-intel-v">{html.escape(tw)}</span>'
            )
        esc_seg = ""
        if esc_api:
            esc_seg = (
                '<span class="rec-intel-sep">·</span>'
                '<span class="rec-intel-k">Escalate</span>'
                f'<span class="rec-intel-v">{html.escape(esc_api)}</span>'
            )
        intel_micro = (
            '<div class="rec-intel-micro" aria-label="Alert diagnosis">'
            '<span class="rec-intel-k">Driver</span>'
            f'<span class="rec-intel-v">{html.escape(str(ctx.get("driver", "")))}</span>'
            '<span class="rec-intel-sep">·</span>'
            '<span class="rec-intel-k">Owner</span>'
            f'<span class="rec-intel-v">{html.escape(str(ctx.get("owner", "")))}</span>'
            '<span class="rec-intel-sep">·</span>'
            '<span class="rec-intel-k">Risk pattern</span>'
            f'<span class="rec-intel-v">{html.escape(rp_short)}</span>'
            f"{tw_seg}{esc_seg}"
            "</div>"
        )
        chips_inner = "".join(f'<span class="rec-chip">{html.escape(b)}</span>' for b in badges)
        esc_html = f'<span class="rec-esc-chip">{html.escape(esc_lbl)}</span>'
        chips_html = ""
        if badges or esc_lbl:
            chips_html = f'<div class="rec-explain-row">{chips_inner}{esc_html}</div>'
        actions_block = ""
        if actions_list:
            lis = "".join(f"<li>{html.escape(a)}</li>" for a in actions_list[:2])
            actions_block = (
                '<hr class="rec-action-sep" />'
                '<div class="rec-action-head">Recommended action</div>'
                f'<ul class="rec-actions-main">{lis}</ul>'
            )
        pri_html = ""
        if idx == 0:
            pri_html = '<span class="rec-priority-pill">Top priority</span>'
        open_attr = " open" if idx == 0 else ""
        conf_raw = str(r.get("confidence") or "").strip().lower()
        conf_html = ""
        if conf_raw in ("high", "medium", "low"):
            conf_html = f'<span class="rec-conf rec-conf--{conf_raw}">{conf_raw.capitalize()} confidence</span>'
        tti_html = ""
        raw_tti = r.get("time_to_impact")
        if raw_tti is not None and str(raw_tti).strip():
            tti_html = f'<p class="rec-tti">{html.escape(str(raw_tti).strip())}</p>'
        sims = r.get("simulation_insights") or []
        sim_html = ""
        if isinstance(sims, list) and sims:
            shown = [str(s).strip() for s in sims[:2] if str(s).strip()]
            if shown:
                inner = "".join(f'<span class="rec-sim-chip">{html.escape(s)}</span>' for s in shown)
                sim_html = f'<div class="rec-sim-row" aria-label="What-if simulations">{inner}</div>'
        blocks.append(
            f'<div class="rec-card{card_mod}">'
            f'<div class="rec-field-h">Issue</div>'
            f'<div class="rec-alert-top">'
            f'<div class="rec-alert-head">'
            f"{_severity_badge_markup(r.get('severity'))}"
            f"{conf_html}"
            f'<p class="rec-title-inline">{title_e}</p>'
            f"</div>"
            f"{pri_html}"
            f"</div>"
            f'<div class="rec-field-h">Impact</div>'
            f'<p class="rec-impact">{summary_e}</p>'
            f"{tti_html}"
            f"{sim_html}"
            f"{intel_micro}"
            f"{chips_html}"
            f"{actions_block}"
            f'<details class="rec-details"{open_attr}>'
            f"<summary>Evidence</summary>"
            f"{details_inner}"
            f"</details>"
            f"</div>"
        )
    blocks.append("</div></div></div>")
    st.markdown("".join(blocks), unsafe_allow_html=True)
    if n_total > default_visible:
        st.checkbox(
            f"Show all alerts ({n_total})",
            key="dash_show_all_recs",
        )
        if not bool(st.session_state.get("dash_show_all_recs", False)):
            st.caption(f"Showing {min(default_visible, n_total)} of {n_total}, ranked by priority score.")


def _scenario_distribution_chart(dist: dict[str, Any] | None) -> None:
    _section_head("Scenario mix (preview)", variant="soft")
    if not dist or not dist.get("items"):
        st.caption("No scenario distribution returned.")
        return
    rows = []
    for b in dist["items"]:
        rows.append(
            {
                "Scenario": b.get("scenario_tag") or "(untagged)",
                "Inventory": int(b.get("inventory_items") or 0),
                "Deliveries": int(b.get("delivery_metrics") or 0),
                "Suppliers": int(b.get("suppliers") or 0),
            }
        )
    df = pd.DataFrame(rows)
    df["Total"] = df["Inventory"] + df["Deliveries"] + df["Suppliers"]
    df = df.sort_values("Total", ascending=False)
    plot_df = df.melt(
        id_vars=["Scenario"],
        value_vars=["Inventory", "Deliveries", "Suppliers"],
        var_name="Domain",
        value_name="Records",
    )
    chart_h = 240
    domain_order = ["Inventory", "Deliveries", "Suppliers"]
    color_scale = alt.Scale(
        domain=domain_order,
        range=["#0f172a", "#0e7490", "#0f766e"],
    )
    chart = (
        alt.Chart(plot_df)
        .mark_bar(cornerRadiusEnd=2, size=9)
        .encode(
            y=alt.Y(
                "Scenario:N",
                sort=list(df["Scenario"]),
                title=None,
                axis=alt.Axis(
                    labelLimit=300,
                    labelPadding=10,
                    labelFlush=False,
                    tickSize=0,
                    tickWidth=0,
                    offset=2,
                ),
                scale=alt.Scale(paddingInner=0.18),
            ),
            x=alt.X(
                "Records:Q",
                title=None,
                axis=alt.Axis(
                    tickMinStep=1,
                    ticks=False,
                    domain=False,
                    labelPadding=6,
                    tickSize=0,
                    tickWidth=0,
                    gridDash=[2, 3],
                ),
            ),
            color=alt.Color(
                "Domain:N",
                scale=color_scale,
                legend=alt.Legend(
                    orient="top",
                    direction="horizontal",
                    title=None,
                    labelFontSize=10,
                    labelFontWeight=500,
                    labelColor="#64748b",
                    symbolSize=52,
                    symbolStrokeWidth=0,
                    padding=3,
                    rowPadding=1,
                    columnPadding=10,
                    titlePadding=0,
                    offset=2,
                ),
            ),
            yOffset=alt.YOffset("Domain:N"),
            tooltip=[
                alt.Tooltip("Scenario:N", title="Scenario"),
                alt.Tooltip("Domain:N", title="Domain"),
                alt.Tooltip("Records:Q", title="Records"),
            ],
        )
        .properties(
            height=chart_h,
            padding={"left": 10, "right": 12, "top": 4, "bottom": 2},
        )
        .configure_view(
            strokeWidth=0,
            fill="#f4f7fb",
        )
        .configure_axis(
            labelColor="#64748b",
            labelFontSize=10,
            labelFontWeight=400,
            labelPadding=5,
            titleColor="#94a3b8",
            tickColor="transparent",
            tickSize=0,
            domainWidth=0.5,
        )
        .configure_axisX(
            grid=True,
            gridColor="#e2e8f0",
            gridOpacity=0.38,
            domain=False,
        )
        .configure_axisY(
            grid=False,
            domainColor="#cbd5e1",
            domainWidth=0.5,
            labelPadding=8,
        )
        .configure_legend(
            orient="top",
            direction="horizontal",
            labelFontSize=10,
            labelFontWeight=500,
            labelColor="#64748b",
            symbolSize=52,
            symbolStrokeWidth=0,
            padding=3,
            rowPadding=1,
            columnPadding=10,
        )
    )
    st.markdown('<div class="scenario-block scenario-shell">', unsafe_allow_html=True)
    st.altair_chart(chart, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)
    with st.expander("Record-level breakdown", expanded=False):
        show = df.drop(columns=["Total"], errors="ignore")
        st.dataframe(show, use_container_width=True, hide_index=True, height=min(140, 24 + 16 * len(show)))


def main() -> None:
    st.set_page_config(
        page_title="Supply Chain AI — Executive",
        page_icon="",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _enterprise_css()

    with st.sidebar:
        st.header("Connection")
        api_override = st.text_input("API base URL", value=_api_base(), help="FastAPI root, e.g. http://127.0.0.1:8000")
        if api_override.strip():
            os.environ["SUPPLY_CHAIN_API_BASE"] = api_override.strip().rstrip("/")
        st.caption("Set SUPPLY_CHAIN_API_BASE in the environment to default this value.")

    errors: list[str] = []
    timeout = float(os.environ.get("SUPPLY_CHAIN_API_TIMEOUT", "30"))

    with httpx.Client(timeout=timeout) as client:
        inv, e = _fetch_json(client, "/analytics/inventory-risk-summary")
        if e:
            errors.append(e)

        deliv, e = _fetch_json(client, "/analytics/delayed-delivery-summary")
        if e:
            errors.append(e)

        sup, e = _fetch_json(client, "/analytics/supplier-reliability-overview")
        if e:
            errors.append(e)

        risks_payload, e = _fetch_json(client, "/analytics/top-operational-risks?limit=20")
        if e:
            errors.append(e)

        scenarios, e = _fetch_json(client, "/analytics/scenario-tag-distribution")
        if e:
            errors.append(e)

        ai, e = _fetch_json(client, "/ai/recommendations?operational_risk_limit=15")
        if e:
            errors.append(e)

    last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    head_left, head_right = st.columns((3.2, 0.8), gap="small")
    with head_left:
        st.title("Supply chain command center")
        st.caption("KPIs · operational risk · AI alerts · scenario mix — executive view.")
    with head_right:
        st.markdown(
            f'<p class="exec-header-meta"><strong>Last updated</strong><br/>{html.escape(last_updated)}</p>',
            unsafe_allow_html=True,
        )

    if errors:
        for msg in errors:
            st.error(msg)

    critical_inv = int(inv["critical_items"]) if isinstance(inv, dict) and "critical_items" in inv else None
    sla = int(deliv["sla_breaches"]) if isinstance(deliv, dict) and "sla_breaches" in deliv else None
    high_risk = int(sup["high_risk_suppliers"]) if isinstance(sup, dict) and "high_risk_suppliers" in sup else None

    crit_recs: int | None = None
    if isinstance(ai, dict):
        recs = ai.get("recommendations") or []
        crit_recs = sum(1 for r in recs if isinstance(r, dict) and r.get("severity") == "critical")

    risk_items = risks_payload.get("items") if isinstance(risks_payload, dict) else None
    risk_list = risk_items if isinstance(risk_items, list) else None

    kpi_ctx = _build_kpi_exec_context(
        critical_inventory=critical_inv,
        sla_breaches=sla,
        high_risk_suppliers=high_risk,
        critical_recommendations=crit_recs,
    )

    intel_bundle = build_intel_bundle(
        risk_items=risk_list,
        ai_payload=ai if isinstance(ai, dict) else None,
        kpi_ctx=kpi_ctx,
        critical_inventory=critical_inv,
        sla_breaches=sla,
        high_risk_suppliers=high_risk,
        critical_recommendations=crit_recs,
        delayed_delivery_summary=deliv if isinstance(deliv, dict) else None,
        supplier_overview=sup if isinstance(sup, dict) else None,
    )

    _kpi_row(
        kpi_ctx=kpi_ctx,
        critical_inventory=critical_inv,
        sla_breaches=sla,
        high_risk_suppliers=high_risk,
        critical_recommendations=crit_recs,
    )

    _executive_narrative_banner(
        kpi_ctx=kpi_ctx,
        critical_inventory=critical_inv,
        sla_breaches=sla,
        high_risk_suppliers=high_risk,
        critical_recommendations=crit_recs,
        risk_items=risk_list,
        ai_payload=ai if isinstance(ai, dict) else None,
        intel_bundle=intel_bundle,
    )

    _operational_risks_table(risk_list, intel_bundle=intel_bundle)

    _ai_recommendations_panel(
        ai if isinstance(ai, dict) else None,
        kpi_context=kpi_ctx,
        intel_bundle=intel_bundle,
    )

    _scenario_distribution_chart(scenarios if isinstance(scenarios, dict) else None)


if __name__ == "__main__":
    main()
