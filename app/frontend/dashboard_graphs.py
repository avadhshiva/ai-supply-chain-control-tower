"""Trend and dependency graph builders for the executive dashboard."""

from __future__ import annotations

from typing import Any, Sequence, TypedDict

import altair as alt
import pandas as pd

_SEVERITY_COLORS = {
    "critical": "#b91c1c",
    "high": "#c2410c",
    "medium": "#ca8a04",
    "low": "#166534",
    "unknown": "#64748b",
}

_DOMAIN_NODE_COLORS = {
    "supplier": "#0f766e",
    "suppliers": "#0f766e",
    "inventory": "#0f172a",
    "delivery": "#0e7490",
    "deliveries": "#0e7490",
    "route": "#0369a1",
    "product": "#475569",
    "governance": "#6b21a8",
}


class GraphNode(TypedDict, total=False):
    id: str
    label: str
    domain: str
    severity: str
    size: float


class GraphEdge(TypedDict, total=False):
    source: str
    target: str
    label: str
    severity: str


def period_labels(n: int) -> list[str]:
    if n <= 0:
        return []
    return [f"P{i + 1}" for i in range(n)]


def series_to_trend_frame(
    series: Sequence[float],
    *,
    metric: str,
) -> pd.DataFrame:
    labels = period_labels(len(series))
    return pd.DataFrame({"period": labels, "value": [float(x) for x in series], "metric": metric})


def build_altair_trend_chart(
    series: Sequence[float],
    *,
    title: str,
    color: str = "#0f172a",
) -> alt.Chart:
    df = series_to_trend_frame(series, metric=title)
    return (
        alt.Chart(df)
        .mark_area(line={"color": color, "strokeWidth": 2}, color=alt.Gradient(
            gradient="linear",
            stops=[
                alt.GradientStop(color=color, offset=0, opacity=0.28),
                alt.GradientStop(color=color, offset=1, opacity=0.02),
            ],
            x1=1,
            x2=1,
            y1=1,
            y2=0,
        ))
        .encode(
            x=alt.X("period:N", title=None, axis=alt.Axis(labelAngle=0, tickSize=0)),
            y=alt.Y("value:Q", title=None, axis=alt.Axis(grid=True, gridOpacity=0.25)),
            tooltip=[
                alt.Tooltip("period:N", title="Period"),
                alt.Tooltip("value:Q", title=title, format=".1f"),
            ],
        )
        .properties(height=160, title=title)
        .configure_view(strokeWidth=0, fill="#f4f7fb")
        .configure_title(fontSize=11, fontWeight=600, color="#334155", anchor="start")
    )


def build_plotly_trend_figure(
    series: Sequence[float],
    *,
    title: str,
    color: str = "#0f172a",
) -> Any | None:
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None
    labels = period_labels(len(series))
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=labels,
            y=[float(x) for x in series],
            mode="lines+markers",
            name=title,
            line={"color": color, "width": 2},
            marker={"size": 5},
            fill="tozeroy",
            fillcolor="rgba(15, 23, 42, 0.08)",
            hovertemplate="%{x}<br>" + title + ": %{y:.1f}<extra></extra>",
        )
    )
    fig.update_layout(
        title={"text": title, "x": 0, "font": {"size": 12, "color": "#334155"}},
        margin={"l": 8, "r": 8, "t": 36, "b": 8},
        height=170,
        paper_bgcolor="#f4f7fb",
        plot_bgcolor="#f4f7fb",
        xaxis={"showgrid": False, "title": ""},
        yaxis={"gridcolor": "#e2e8f0", "title": ""},
        showlegend=False,
    )
    return fig


def _node_id(domain: str, label: str) -> str:
    return f"{domain}:{label}".lower().replace(" ", "_")


def build_dependency_graph_from_payload(
    payload: dict[str, Any] | None,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Supplier → inventory → delivery chain graph from dependency-analysis payload."""
    if not payload:
        return [], []

    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    def _ensure_node(domain: str, label: str, *, severity: str = "medium", size: float = 14.0) -> str:
        nid = _node_id(domain, label)
        if nid not in nodes:
            nodes[nid] = {
                "id": nid,
                "label": label,
                "domain": domain,
                "severity": severity,
                "size": size,
            }
        return nid

    for ent in payload.get("top_fragile_entities") or []:
        if not isinstance(ent, dict):
            continue
        label = str(ent.get("label") or ent.get("entity_id") or "").strip()
        domain = str(ent.get("domain") or "entity").strip().lower()
        sev = str(ent.get("severity") or "medium").strip().lower()
        if label:
            score = float(ent.get("fragility_score") or 0.5)
            _ensure_node(domain, label, severity=sev, size=12.0 + score * 10.0)

    for chain in payload.get("dependency_chains") or []:
        if not isinstance(chain, dict):
            continue
        labels = chain.get("path_labels") or []
        if not isinstance(labels, list) or len(labels) < 2:
            continue
        pressure = float(chain.get("chain_pressure") or 0.0)
        sev = "critical" if pressure >= 0.7 else "high" if pressure >= 0.45 else "medium"
        path_domains = chain.get("path") or []
        prev_id: str | None = None
        for idx, lbl in enumerate(labels):
            lbl_s = str(lbl).strip()
            if not lbl_s:
                continue
            dom = "network"
            if isinstance(path_domains, list) and idx < len(path_domains):
                dom = str(path_domains[idx]).replace("domain:", "").strip().lower() or dom
            elif "supplier" in lbl_s.lower():
                dom = "supplier"
            elif "inventory" in lbl_s.lower():
                dom = "inventory"
            elif "delivery" in lbl_s.lower():
                dom = "delivery"
            nid = _ensure_node(dom, lbl_s, severity=sev, size=14.0 + pressure * 6.0)
            if prev_id:
                edges.append(
                    {
                        "source": prev_id,
                        "target": nid,
                        "label": "depends on",
                        "severity": sev,
                    }
                )
            prev_id = nid

    # Canonical cross-domain backbone when chains are sparse.
    if len(nodes) < 3:
        s = _ensure_node("supplier", "Supplier network", severity="medium", size=16.0)
        i = _ensure_node("inventory", "Inventory network", severity="medium", size=16.0)
        d = _ensure_node("delivery", "Delivery network", severity="medium", size=16.0)
        edges.extend(
            [
                {"source": s, "target": i, "label": "feeds", "severity": "medium"},
                {"source": i, "target": d, "label": "fulfills", "severity": "medium"},
            ]
        )

    return list(nodes.values()), edges


def build_plotly_dependency_graph(
    nodes: list[GraphNode],
    edges: list[GraphEdge],
) -> Any | None:
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None
    if not nodes:
        return None

    # Simple layered layout: supplier left, inventory center, delivery right.
    layer_x = {
        "supplier": 0.0,
        "suppliers": 0.0,
        "inventory": 0.5,
        "product": 0.5,
        "delivery": 1.0,
        "deliveries": 1.0,
        "route": 1.0,
        "network": 0.5,
        "entity": 0.5,
    }
    node_index = {n["id"]: i for i, n in enumerate(nodes)}
    xs, ys, texts, sizes, colors = [], [], [], [], []
    for i, node in enumerate(nodes):
        dom = str(node.get("domain", "entity")).lower()
        xs.append(layer_x.get(dom, 0.5))
        ys.append(1.0 - (i % 5) * 0.18)
        texts.append(f"{node.get('label', '')}<br>{dom}")
        sizes.append(float(node.get("size") or 14.0))
        sev = str(node.get("severity") or "medium").lower()
        colors.append(_SEVERITY_COLORS.get(sev, _SEVERITY_COLORS["unknown"]))

    edge_x, edge_y = [], []
    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src not in node_index or tgt not in node_index:
            continue
        x0, y0 = xs[node_index[src]], ys[node_index[src]]
        x1, y1 = xs[node_index[tgt]], ys[node_index[tgt]]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    edge_trace = go.Scatter(
        x=edge_x,
        y=edge_y,
        mode="lines",
        line={"width": 1.5, "color": "#94a3b8"},
        hoverinfo="none",
        showlegend=False,
    )
    node_trace = go.Scatter(
        x=xs,
        y=ys,
        mode="markers+text",
        text=[n.get("label", "") for n in nodes],
        textposition="top center",
        marker={
            "size": sizes,
            "color": colors,
            "line": {"width": 1, "color": "#0f172a"},
        },
        hovertext=texts,
        hoverinfo="text",
        showlegend=False,
    )
    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        height=280,
        paper_bgcolor="#f4f7fb",
        plot_bgcolor="#f4f7fb",
        xaxis={"visible": False, "range": [-0.15, 1.15]},
        yaxis={"visible": False, "range": [-0.05, 1.05]},
        showlegend=False,
    )
    return fig


def operational_pressure_series(
    *,
    sla_breaches: int | None,
    critical_inventory: int | None,
    high_risk_suppliers: int | None,
    critical_recommendations: int | None,
) -> list[float]:
    """Composite pressure index (seven periods) from KPI anchors."""
    parts = [
        float(sla_breaches or 0),
        float(critical_inventory or 0),
        float(high_risk_suppliers or 0),
        float(critical_recommendations or 0),
    ]
    total = sum(parts) or 1.0
    shape = [0.88, 0.9, 0.93, 0.96, 0.98, 0.99, 1.0]
    return [total * s for s in shape]
