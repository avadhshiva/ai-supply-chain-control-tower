"""Deterministic forecasting and what-if simulations (no ML, no external APIs)."""

from __future__ import annotations

import math
from typing import Literal, Sequence

ConfidenceLevel = Literal["high", "medium", "low"]

# Policy mirrors decision_engine / analytics heuristics (fixed constants).
_DEL_BREACH_RATIO_HIGH = 0.12
_INV_LOW_STOCK_RATIO_HIGH = 0.08


def infer_metric_trend_state(series: Sequence[float], *, higher_is_bad: bool) -> str:
    """Rules-only trajectory label aligned with dashboard `infer_trend_state` (duplicated to avoid Streamlit deps)."""
    vals = [float(x) for x in series if not (math.isnan(float(x)) or math.isinf(float(x)))]
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


def _series_cv(values: Sequence[float]) -> float:
    vals = [float(x) for x in values if not (math.isnan(float(x)) or math.isinf(float(x)))]
    if len(vals) < 2:
        return 0.0
    mean = sum(vals) / len(vals)
    if abs(mean) < 1e-12:
        step_mean = sum(abs(vals[i + 1] - vals[i]) for i in range(len(vals) - 1)) / (len(vals) - 1)
        return 0.0 if step_mean < 1e-12 else 1.0
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    std = math.sqrt(max(0.0, var))
    return std / abs(mean) if abs(mean) > 1e-12 else 0.0


def _coerce_series(metric_series: Sequence[float] | None, *, terminal: float, shape: Sequence[float]) -> list[float]:
    """Build a 7-point terminal-anchored series; deterministic when history is absent."""
    t = float(terminal)
    if metric_series is not None and len(metric_series) >= 3:
        out = [float(x) for x in metric_series]
        if not out:
            return [t * s for s in shape]
        return out
    return [max(0.0, t * float(s)) for s in shape]


def project_threshold_crossing(
    *,
    current_value: float,
    threshold: float,
    metric_series: Sequence[float] | None = None,
    higher_is_bad: bool = True,
    period_label: str = "day",
    max_horizon: int = 90,
    series_shape: Sequence[float] | None = None,
    risk_descriptor: str = "SLA risk",
    drift_descriptor: str = "breach acceleration",
) -> dict[str, float | int | str | bool | None]:
    """
    Rolling-endpoint slope projection: extrapolate linear trend from the supplied (or shaped) series.

    Returns keys: days_to_cross, slope_per_period, summary, already_breached, threshold, current_value.
    """
    shape = series_shape or (0.88, 0.90, 0.92, 0.94, 0.96, 0.98, 1.0)
    vals = _coerce_series(metric_series, terminal=current_value, shape=shape)
    n = len(vals)
    if n < 2:
        return {
            "days_to_cross": None,
            "slope_per_period": 0.0,
            "summary": "Insufficient series density to project threshold crossing.",
            "already_breached": False,
            "threshold": float(threshold),
            "current_value": float(current_value),
        }

    slope = (vals[-1] - vals[0]) / float(n - 1)
    last = float(vals[-1])
    thr = float(threshold)
    cur = float(current_value)

    def _cross_message(days: int | None, *, adverse_slope: bool) -> str:
        if days is None:
            if adverse_slope:
                return (
                    f"Current trajectory does not intersect the escalation threshold within {max_horizon} "
                    f"{period_label}s under the modeled linear slope."
                )
            return (
                f"At current slope, the metric is not projected to reach the escalation threshold within "
                f"{max_horizon} {period_label}s."
            )
        if days <= 0:
            return "Already at or above the modeled escalation threshold on the latest observation."
        approx = "~" if days >= 2 else ""
        return (
            f"At current {drift_descriptor}, {risk_descriptor} exceeds escalation threshold in {approx}{days} "
            f"{period_label}{'s' if days != 1 else ''}."
        )

    if higher_is_bad:
        already = last >= thr - 1e-9
        if already:
            return {
                "days_to_cross": 0,
                "slope_per_period": slope,
                "summary": _cross_message(0, adverse_slope=True),
                "already_breached": True,
                "threshold": thr,
                "current_value": cur,
            }
        if slope <= 1e-12:
            return {
                "days_to_cross": None,
                "slope_per_period": slope,
                "summary": _cross_message(None, adverse_slope=False),
                "already_breached": False,
                "threshold": thr,
                "current_value": cur,
            }
        raw_days = math.ceil((thr - last) / slope)
        if raw_days > max_horizon:
            return {
                "days_to_cross": None,
                "slope_per_period": slope,
                "summary": _cross_message(None, adverse_slope=True),
                "already_breached": False,
                "threshold": thr,
                "current_value": cur,
            }
        d = max(1, int(raw_days))
        return {
            "days_to_cross": d,
            "slope_per_period": slope,
            "summary": _cross_message(d, adverse_slope=True),
            "already_breached": False,
            "threshold": thr,
            "current_value": cur,
        }

    # lower is bad (e.g. reliability)
    already = last <= thr + 1e-9
    if already:
        return {
            "days_to_cross": 0,
            "slope_per_period": slope,
            "summary": "Already at or below the modeled escalation threshold on the latest observation.",
            "already_breached": True,
            "threshold": thr,
            "current_value": cur,
        }
    if slope >= -1e-12:
        return {
            "days_to_cross": None,
            "slope_per_period": slope,
            "summary": _cross_message(None, adverse_slope=False),
            "already_breached": False,
            "threshold": thr,
            "current_value": cur,
        }
    raw_days = math.ceil((last - thr) / abs(slope))
    if raw_days > max_horizon:
        return {
            "days_to_cross": None,
            "slope_per_period": slope,
            "summary": _cross_message(None, adverse_slope=True),
            "already_breached": False,
            "threshold": thr,
            "current_value": cur,
        }
    d = max(1, int(raw_days))
    return {
        "days_to_cross": d,
        "slope_per_period": slope,
        "summary": f"At current slope, the metric is projected to cross the escalation threshold in ~{d} {period_label}s.",
        "already_breached": False,
        "threshold": thr,
        "current_value": cur,
    }


def _breach_exposure_ratio(breach_ratio: float, delay_ratio: float) -> float:
    return min(1.0, max(0.0, 0.62 * breach_ratio + 0.38 * delay_ratio))


def simulate_delay_reduction(
    *,
    total_deliveries: int,
    delayed_deliveries: int,
    sla_breaches: int,
    delay_reduction_pct: float,
) -> dict[str, float | int | str]:
    """Deterministic counterfactual: scale delays and partially couple SLA breaches to delays."""
    td = max(0, int(total_deliveries))
    if td <= 0:
        return {
            "baseline_exposure": 0.0,
            "simulated_exposure": 0.0,
            "exposure_delta_pct": 0.0,
            "breach_ratio_before": 0.0,
            "breach_ratio_after": 0.0,
            "delay_ratio_before": 0.0,
            "delay_ratio_after": 0.0,
            "summary": "No delivery volume; simulation neutral.",
        }

    r = min(0.95, max(0.0, float(delay_reduction_pct)))
    breach_coupling = 0.78 + 0.12 * (1.0 - r)

    delay_before = max(0, int(delayed_deliveries))
    breach_before = max(0, int(sla_breaches))
    delay_after = int(round(delay_before * (1.0 - r)))
    breach_after = int(round(breach_before * (1.0 - r * breach_coupling)))
    delay_after = max(0, min(delay_after, td))
    breach_after = max(0, min(breach_after, td))

    dr_b = delay_before / float(td)
    br_b = breach_before / float(td)
    dr_a = delay_after / float(td)
    br_a = breach_after / float(td)

    exp_b = _breach_exposure_ratio(br_b, dr_b)
    exp_a = _breach_exposure_ratio(br_a, dr_a)
    if exp_b < 1e-9:
        delta_pct = 0.0 if exp_a < 1e-9 else -100.0
    else:
        delta_pct = round((exp_b - exp_a) / exp_b * 100.0, 1)

    return {
        "baseline_exposure": round(exp_b, 4),
        "simulated_exposure": round(exp_a, 4),
        "exposure_delta_pct": float(delta_pct),
        "breach_ratio_before": round(br_b, 4),
        "breach_ratio_after": round(br_a, 4),
        "delay_ratio_before": round(dr_b, 4),
        "delay_ratio_after": round(dr_a, 4),
        "summary": (
            f"Reducing delivery delays by {int(round(r * 100))}% lowers projected breach exposure by "
            f"{abs(delta_pct):.0f}% versus the baseline mix."
        ),
    }


def simulate_supplier_recovery(
    *,
    high_risk_suppliers: int,
    total_suppliers: int,
    avg_reliability_score: float | None,
    reliability_improvement: float,
) -> dict[str, float | str]:
    """Counterfactual: absolute reliability gain trims modeled supplier-side exposure."""
    ts = max(0, int(total_suppliers))
    hr = max(0, int(high_risk_suppliers))
    if ts <= 0:
        return {
            "baseline_exposure": 0.0,
            "simulated_exposure": 0.0,
            "exposure_delta_pct": 0.0,
            "summary": "No supplier cohort; simulation neutral.",
        }

    gain = min(0.25, max(0.0, float(reliability_improvement)))
    high_ratio = hr / float(ts)
    rel = float(avg_reliability_score) if avg_reliability_score is not None else max(0.0, 1.0 - high_ratio)
    rel = min(1.0, max(0.0, rel))

    baseline = min(1.0, max(0.0, 0.55 * high_ratio + 0.45 * (1.0 - rel)))
    new_rel = min(1.0, rel + gain)
    new_high_ratio = max(0.0, high_ratio * (1.0 - 1.35 * gain))
    simulated = min(1.0, max(0.0, 0.55 * new_high_ratio + 0.45 * (1.0 - new_rel)))

    if baseline < 1e-9:
        delta_pct = 0.0 if simulated < 1e-9 else -100.0
    else:
        delta_pct = round((baseline - simulated) / baseline * 100.0, 1)

    return {
        "baseline_exposure": round(baseline, 4),
        "simulated_exposure": round(simulated, 4),
        "exposure_delta_pct": float(delta_pct),
        "summary": (
            f"Improving portfolio reliability by {gain * 100:.0f} pts lowers modeled supplier breach pressure by "
            f"{abs(delta_pct):.0f}%."
        ),
    }


def simulate_inventory_replenishment(
    *,
    low_stock_items: int,
    total_items: int,
    avg_stock_coverage_days: float | None,
    replenishment_acceleration_pct: float,
) -> dict[str, float | str]:
    """Counterfactual: faster replenishment cycle compresses low-stock exposure proxy."""
    ti = max(0, int(total_items))
    ls = max(0, int(low_stock_items))
    if ti <= 0:
        return {
            "baseline_exposure": 0.0,
            "simulated_exposure": 0.0,
            "exposure_delta_pct": 0.0,
            "summary": "No inventory cohort; simulation neutral.",
        }

    accel = min(0.6, max(0.0, float(replenishment_acceleration_pct)))
    low_ratio = ls / float(ti)
    cover = float(avg_stock_coverage_days) if avg_stock_coverage_days is not None else max(3.0, 14.0 * (1.0 - low_ratio))
    cover = max(0.5, cover)

    baseline = min(1.0, max(0.0, 0.65 * low_ratio + 0.35 * max(0.0, 1.0 - min(1.0, cover / 21.0))))
    new_low_ratio = max(0.0, low_ratio * (1.0 - 0.62 * accel))
    new_cover = cover * (1.0 + 0.45 * accel)
    simulated = min(1.0, max(0.0, 0.65 * new_low_ratio + 0.35 * max(0.0, 1.0 - min(1.0, new_cover / 21.0))))

    if baseline < 1e-9:
        delta_pct = 0.0 if simulated < 1e-9 else -100.0
    else:
        delta_pct = round((baseline - simulated) / baseline * 100.0, 1)

    return {
        "baseline_exposure": round(baseline, 4),
        "simulated_exposure": round(simulated, 4),
        "exposure_delta_pct": float(delta_pct),
        "summary": (
            f"Accelerating replenishment cadence by {int(round(accel * 100))}% reduces projected stockout pressure by "
            f"{abs(delta_pct):.0f}% versus baseline coverage assumptions."
        ),
    }


def compute_confidence_score(
    *,
    evidence_count: int,
    metric_series: Sequence[float] | None,
    cross_domain_agreement: bool,
    volatility_state: str,
) -> tuple[ConfidenceLevel, float]:
    """
    Map structural signals to High / Medium / Low confidence and a 0-1 score.

    volatility_state: improving | stable | worsening | volatile (same vocabulary as dashboard trend states).
    """
    vol = str(volatility_state or "stable").strip().lower()
    ec = max(0, int(evidence_count))
    series = [float(x) for x in (metric_series or []) if not (math.isnan(float(x)) or math.isinf(float(x)))]
    cv = _series_cv(series) if len(series) >= 3 else 0.18

    density = min(1.0, ec / 7.0)
    consistency = max(0.0, min(1.0, 1.0 - min(1.2, cv) / 1.2))
    cross = 1.0 if cross_domain_agreement else 0.0
    vol_pen = 0.35 if vol == "volatile" else 0.18 if vol == "worsening" else 0.08 if vol == "stable" else 0.12

    raw = 0.34 * density + 0.30 * consistency + 0.22 * cross + 0.14 * (1.0 - vol_pen)
    raw = max(0.0, min(1.0, raw))

    if raw >= 0.72:
        return "high", round(raw, 3)
    if raw >= 0.48:
        return "medium", round(raw, 3)
    return "low", round(raw, 3)


def inventory_threshold_for_low_stock_ratio(total_items: int, low_stock_items: int) -> float:
    """Escalation threshold on low-stock ratio consistent with inventory policy band."""
    _ = low_stock_items
    return _INV_LOW_STOCK_RATIO_HIGH if total_items > 0 else 1.0


def delivery_breach_escalation_threshold() -> float:
    return _DEL_BREACH_RATIO_HIGH
