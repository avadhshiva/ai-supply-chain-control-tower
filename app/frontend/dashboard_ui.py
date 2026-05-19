"""Reusable Streamlit / HTML helpers for the executive dashboard."""

from __future__ import annotations

import html
from typing import Any

import streamlit as st

from app.frontend.dashboard_filters import (
    PRIORITY_DRILL_ENTITIES,
    _text_blob,
    parse_route_from_label,
    parse_supplier_from_label,
)

_SEVERITY_ORDER = ("critical", "high", "medium", "low")


def normalize_severity_key(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    if key in _SEVERITY_ORDER:
        return key
    return "unknown"


def severity_chip_markup(severity: str | None) -> str:
    raw = (severity or "").strip()
    key = normalize_severity_key(raw)
    if key == "unknown" and raw:
        label = raw.strip() or "N/A"
    else:
        label = "N/A" if key == "unknown" else key.capitalize()
    safe_label = html.escape(label)
    return f'<span class="sev-badge sev-{key}">{safe_label}</span>'


def executive_section_head_html(
    label: str,
    meta: str | None = None,
    *,
    first: bool = False,
    compact: bool = False,
    variant: str = "soft",
) -> str:
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
        return (
            f'<div class="exec-section-head{var_cls}{first_cls}{tight_cls}">'
            f'<span class="exec-section-title">{safe_label}</span>'
            f'<span class="exec-section-meta">{safe_meta}</span>'
            f"</div>"
        )
    return (
        f'<div class="exec-section-head{var_cls}{first_cls}{tight_cls}">'
        f'<span class="exec-section-title">{safe_label}</span>'
        f"</div>"
    )


def render_executive_section_head(
    label: str,
    meta: str | None = None,
    *,
    first: bool = False,
    compact: bool = False,
    variant: str = "soft",
) -> None:
    st.markdown(
        executive_section_head_html(label, meta, first=first, compact=compact, variant=variant),
        unsafe_allow_html=True,
    )


def metric_card_html(
    *,
    label: str,
    value: str,
    subline: str | None = None,
    accent: str = "calm",
) -> str:
    cls = "dash-metric-card dash-metric-card--alert" if accent == "alert" else "dash-metric-card"
    sub = f'<div class="dash-metric-sub">{html.escape(subline)}</div>' if subline else ""
    return (
        f'<div class="{cls}">'
        f'<div class="dash-metric-label">{html.escape(label)}</div>'
        f'<div class="dash-metric-value">{html.escape(value)}</div>'
        f"{sub}"
        f"</div>"
    )


def render_metric_card(
    *,
    label: str,
    value: str,
    subline: str | None = None,
    accent: str = "calm",
) -> None:
    st.markdown(metric_card_html(label=label, value=value, subline=subline, accent=accent), unsafe_allow_html=True)


def alert_block_html(
    *,
    title: str,
    summary: str,
    severity: str | None,
    chips: list[str] | None = None,
) -> str:
    chips_html = "".join(
        f'<span class="rec-chip">{html.escape(c)}</span>' for c in (chips or [])
    )
    return (
        f'<div class="dash-alert-block">'
        f"{severity_chip_markup(severity)}"
        f'<div class="dash-alert-title">{html.escape(title)}</div>'
        f'<div class="dash-alert-summary">{html.escape(summary)}</div>'
        f'<div class="dash-alert-chips">{chips_html}</div>'
        f"</div>"
    )


def filters_active_banner_html(active: bool, summary: str) -> str:
    if not active:
        return ""
    return (
        '<div class="dash-filter-banner" role="status">'
        f'<span class="dash-filter-banner-label">Filters active</span>'
        f'<span class="dash-filter-banner-detail">{html.escape(summary)}</span>'
        "</div>"
    )


def render_filters_active_banner(active: bool, summary: str) -> None:
    block = filters_active_banner_html(active, summary)
    if block:
        st.markdown(block, unsafe_allow_html=True)


def inject_dashboard_ux_css() -> None:
    st.markdown(
        """
        <style>
          .dash-filter-banner {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin: 0.35rem 0 0.5rem 0;
            padding: 0.35rem 0.55rem;
            background: #e0e7ff;
            border: 1px solid #a5b4fc;
            border-radius: 6px;
            font-size: 0.78rem;
          }
          .dash-filter-banner-label { font-weight: 600; color: #312e81; }
          .dash-filter-banner-detail { color: #4338ca; }
          .dash-metric-card {
            background: #eef2f8;
            border: 1px solid var(--exec-border, #b8c2d4);
            border-radius: 8px;
            padding: 0.45rem 0.55rem;
            min-height: 4.2rem;
          }
          .dash-metric-card--alert { border-left: 3px solid #b91c1c; }
          .dash-metric-label {
            font-size: 0.72rem;
            color: var(--exec-label, #475569);
            text-transform: uppercase;
            letter-spacing: 0.04em;
          }
          .dash-metric-value {
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--exec-text, #0a0f1a);
            line-height: 1.15;
          }
          .dash-metric-sub { font-size: 0.72rem; color: var(--exec-muted-soft, #64748b); }
          .dash-drill-bar { margin: 0.25rem 0 0.45rem 0; }
          .dash-drill-bar .stButton > button {
            font-size: 0.74rem !important;
            padding: 0.2rem 0.35rem !important;
            min-height: 1.65rem !important;
            border-radius: 6px !important;
          }
          .dash-trend-shell {
            background: #f4f7fb;
            border: 1px solid var(--exec-border, #b8c2d4);
            border-radius: 8px;
            padding: 0.15rem 0.25rem 0.05rem 0.25rem;
            margin-bottom: 0.35rem;
          }
          .dash-graph-shell {
            background: #f4f7fb;
            border: 1px solid var(--exec-border, #b8c2d4);
            border-radius: 8px;
            padding: 0.25rem;
            margin-top: 0.15rem;
          }
          .dash-alert-block {
            border: 1px solid var(--exec-border, #b8c2d4);
            border-radius: 8px;
            padding: 0.45rem 0.55rem;
            margin-bottom: 0.35rem;
            background: #eef2f8;
          }
          .dash-alert-title { font-weight: 600; font-size: 0.86rem; margin-top: 0.2rem; }
          .dash-alert-summary { font-size: 0.8rem; color: var(--exec-muted, #334155); margin-top: 0.15rem; }
          .dash-dep-panel-lite { font-size: 0.8rem; color: var(--exec-muted, #334155); }
          div[data-testid="stSidebar"] .stSelectbox label { font-size: 0.78rem !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def build_entity_drilldown_context(
    entity: str,
    *,
    risk_items: list[dict[str, Any]] | None,
    ai_payload: dict[str, Any] | None,
    dependency: dict[str, Any] | None,
    intel_bundle: dict[str, Any] | None,
) -> dict[str, Any]:
    needle = entity.strip().lower()
    alerts = [
        r
        for r in (ai_payload or {}).get("recommendations") or []
        if isinstance(r, dict) and needle in _text_blob(r.get("title"), r.get("summary"))
    ]
    risks = [
        r
        for r in (risk_items or [])
        if isinstance(r, dict) and needle in _text_blob(r.get("label"), r.get("risk_type"))
    ]
    chains: list[dict[str, Any]] = []
    is_route = needle.startswith("rt-")
    for chain in (dependency or {}).get("dependency_chains") or []:
        if not isinstance(chain, dict):
            continue
        labels = chain.get("path_labels") or []
        label_blob = _text_blob(*(labels if isinstance(labels, list) else []))
        if needle in label_blob or needle in _text_blob(chain.get("chain_id")):
            chains.append(chain)
        elif is_route and "delivery" in label_blob:
            chains.append(chain)
        elif needle in ("delivery network", "inventory network", "supplier network"):
            if needle.split()[0] in label_blob:
                chains.append(chain)

    metrics: list[tuple[str, str]] = []
    for row in risks:
        label = str(row.get("label", ""))
        metrics.append(("Risk", label))
        metrics.append(("Severity", str(row.get("severity", ""))))
        metrics.append(("Score", str(row.get("score", ""))))
        route = parse_route_from_label(label)
        if route:
            metrics.append(("Route", route))
        sup = parse_supplier_from_label(label)
        if sup:
            metrics.append(("Supplier", sup))

    actions: list[str] = []
    for action in (intel_bundle or {}).get("prioritized_actions") or []:
        if not isinstance(action, dict):
            continue
        title = str(action.get("title", ""))
        if needle in title.lower() or any(needle in str(r.get("label", "")).lower() for r in risks):
            actions.append(title)
    if not actions and entity in PRIORITY_DRILL_ENTITIES:
        actions.append(f"Coordinate cross-functional review for {entity}.")

    return {
        "entity": entity,
        "alerts": alerts,
        "risks": risks,
        "chains": chains,
        "metrics": metrics,
        "actions": actions[:6],
    }


def render_entity_drilldown_panel(ctx: dict[str, Any]) -> None:
    entity = str(ctx.get("entity", "Focus"))
    with st.expander(f"Details — {entity}", expanded=True):
        tab_alerts, tab_chains, tab_metrics, tab_actions = st.tabs(
            ["Related alerts", "Dependency chains", "Operational metrics", "Recommended actions"]
        )
        with tab_alerts:
            alerts = ctx.get("alerts") or []
            if not alerts:
                st.caption("No linked alerts for this focus.")
            for alert in alerts[:8]:
                if isinstance(alert, dict):
                    st.markdown(
                        alert_block_html(
                            title=str(alert.get("title", "Alert")),
                            summary=str(alert.get("summary") or "—"),
                            severity=str(alert.get("severity", "")),
                        ),
                        unsafe_allow_html=True,
                    )
        with tab_chains:
            chains = ctx.get("chains") or []
            if not chains:
                st.caption("No dependency chains linked to this focus.")
            for chain in chains[:6]:
                if isinstance(chain, dict):
                    labels = chain.get("path_labels") or []
                    path = " → ".join(str(x) for x in labels if x)
                    pressure = float(chain.get("chain_pressure") or 0.0)
                    st.markdown(
                        f'<p class="dash-dep-panel-lite"><strong>{html.escape(path)}</strong> '
                        f"· pressure {pressure:.2f}</p>",
                        unsafe_allow_html=True,
                    )
        with tab_metrics:
            metrics = ctx.get("metrics") or []
            if not metrics:
                st.caption("No operational metrics for this focus.")
            else:
                st.dataframe(
                    {"Metric": [m[0] for m in metrics], "Value": [m[1] for m in metrics]},
                    use_container_width=True,
                    hide_index=True,
                    height=min(220, 40 + 28 * len(metrics)),
                )
        with tab_actions:
            actions = ctx.get("actions") or []
            if not actions:
                st.caption("No prioritized actions mapped to this focus.")
            else:
                for act in actions:
                    st.markdown(f"- {html.escape(str(act))}", unsafe_allow_html=True)


def render_drilldown_selector(targets: list[str], *, session_key: str = "dash_drill_entity") -> str | None:
    if not targets:
        return None
    st.markdown('<div class="dash-drill-bar">', unsafe_allow_html=True)
    st.caption("Quick focus — select an entity for drilldown")
    cols = st.columns(min(len(targets), 5))
    selected = st.session_state.get(session_key)
    for idx, target in enumerate(targets):
        with cols[idx % len(cols)]:
            if st.button(target, key=f"dash_drill_{target}", use_container_width=True):
                st.session_state[session_key] = target
                selected = target
    if st.button("Clear focus", key="dash_drill_clear"):
        st.session_state.pop(session_key, None)
        selected = None
    st.markdown("</div>", unsafe_allow_html=True)
    return str(selected) if selected else None
