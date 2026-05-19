"""Cross-section dashboard filters — pure logic (no Streamlit runtime required)."""

from __future__ import annotations

import re
from typing import Any, TypedDict

_SEVERITY_ORDER = ("critical", "high", "medium", "low")
_ROUTE_RE = re.compile(r"\bRT-\d+\b", re.IGNORECASE)

# Executive quick-focus entities (matched case-insensitively in labels / chain text).
PRIORITY_DRILL_ENTITIES: tuple[str, ...] = (
    "RT-001",
    "RT-012",
    "Brown Inc",
    "delivery network",
    "inventory network",
)

_RISK_TYPE_TO_DOMAIN: dict[str, str] = {
    "delivery": "deliveries",
    "inventory": "inventory",
    "supplier": "suppliers",
    "governance": "governance",
}

_ALERT_CATEGORY_TO_DOMAIN: dict[str, str] = {
    "delivery": "deliveries",
    "inventory": "inventory",
    "supplier": "suppliers",
    "operational": "governance",
}


class DashboardFilterState(TypedDict):
    severity: str
    domain: str
    supplier: str
    route: str
    scenario_type: str


def default_filter_state() -> DashboardFilterState:
    return {
        "severity": "All",
        "domain": "All",
        "supplier": "All",
        "route": "All",
        "scenario_type": "All",
    }


def normalize_severity(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    if key in _SEVERITY_ORDER:
        return key
    return "unknown"


def _risk_domain(row: dict[str, Any]) -> str:
    rt = str(row.get("risk_type", "")).strip().lower()
    return _RISK_TYPE_TO_DOMAIN.get(rt, rt or "unknown")


def parse_route_from_label(label: str) -> str | None:
    m = _ROUTE_RE.search(label or "")
    return m.group(0).upper() if m else None


def parse_supplier_from_label(label: str) -> str | None:
    text = (label or "").strip()
    if text.startswith("Low reliability: "):
        return text[len("Low reliability: ") :].strip()
    return None


def _text_blob(*parts: Any) -> str:
    return " ".join(str(p) for p in parts if p is not None).lower()


def _severity_sort_key(value: str) -> int:
    try:
        return _SEVERITY_ORDER.index(value)
    except ValueError:
        return len(_SEVERITY_ORDER)


def extract_filter_options(
    *,
    risk_items: list[dict[str, Any]] | None,
    ai_payload: dict[str, Any] | None,
    scenarios: dict[str, Any] | None,
) -> dict[str, list[str]]:
    """Build sidebar option lists from live payloads."""
    severities: set[str] = set()
    domains: set[str] = set()
    suppliers: set[str] = set()
    routes: set[str] = set()
    scenario_tags: set[str] = set()

    for row in risk_items or []:
        if not isinstance(row, dict):
            continue
        sev = normalize_severity(str(row.get("severity", "")))
        if sev != "unknown":
            severities.add(sev)
        domains.add(_risk_domain(row))
        label = str(row.get("label", ""))
        route = parse_route_from_label(label)
        if route:
            routes.add(route)
        sup = parse_supplier_from_label(label)
        if sup:
            suppliers.add(sup)

    for rec in (ai_payload or {}).get("recommendations") or []:
        if not isinstance(rec, dict):
            continue
        sev = normalize_severity(str(rec.get("severity", "")))
        if sev != "unknown":
            severities.add(sev)
        cat = str(rec.get("category", "")).strip().lower()
        domains.add(_ALERT_CATEGORY_TO_DOMAIN.get(cat, cat or "unknown"))
        blob = _text_blob(rec.get("title"), rec.get("summary"))
        for m in _ROUTE_RE.findall(blob):
            routes.add(m.upper())
        if "brown inc" in blob:
            suppliers.add("Brown Inc")

    for item in (scenarios or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("scenario_tag") or "(untagged)").strip()
        if tag:
            scenario_tags.add(tag)

    return {
        "severities": ["All", *sorted(severities, key=_severity_sort_key)],
        "domains": ["All", *sorted(domains)],
        "suppliers": ["All", *sorted(suppliers, key=str.lower)],
        "routes": ["All", *sorted(routes)],
        "scenario_types": ["All", *sorted(scenario_tags, key=str.lower)],
    }


def filters_are_active(filters: DashboardFilterState) -> bool:
    return any(str(v).strip() not in ("", "All") for v in filters.values())


def risk_matches_filters(row: dict[str, Any], filters: DashboardFilterState) -> bool:
    sev_f = filters.get("severity", "All")
    if sev_f != "All" and normalize_severity(str(row.get("severity", ""))) != sev_f:
        return False
    dom_f = filters.get("domain", "All")
    if dom_f != "All" and _risk_domain(row) != dom_f:
        return False
    route_f = filters.get("route", "All")
    if route_f != "All":
        label_route = parse_route_from_label(str(row.get("label", "")))
        if label_route != route_f and route_f.lower() not in _text_blob(row.get("label")):
            return False
    sup_f = filters.get("supplier", "All")
    if sup_f != "All":
        sup_name = parse_supplier_from_label(str(row.get("label", "")))
        if sup_name != sup_f and sup_f.lower() not in _text_blob(row.get("label")):
            return False
    return True


def alert_matches_filters(alert: dict[str, Any], filters: DashboardFilterState) -> bool:
    sev_f = filters.get("severity", "All")
    if sev_f != "All" and normalize_severity(str(alert.get("severity", ""))) != sev_f:
        return False
    dom_f = filters.get("domain", "All")
    if dom_f != "All":
        cat = str(alert.get("category", "")).strip().lower()
        dom = _ALERT_CATEGORY_TO_DOMAIN.get(cat, cat)
        if dom != dom_f:
            return False
    blob = _text_blob(alert.get("title"), alert.get("summary"))
    route_f = filters.get("route", "All")
    if route_f != "All" and route_f.lower() not in blob:
        return False
    sup_f = filters.get("supplier", "All")
    if sup_f != "All" and sup_f.lower() not in blob:
        return False
    return True


def scenario_item_matches_filters(item: dict[str, Any], filters: DashboardFilterState) -> bool:
    tag_f = filters.get("scenario_type", "All")
    if tag_f == "All":
        return True
    tag = str(item.get("scenario_tag") or "(untagged)").strip()
    return tag == tag_f


def dependency_payload_matches_filters(
    payload: dict[str, Any] | None,
    filters: DashboardFilterState,
) -> bool:
    """When entity/route/supplier filters are set, keep dependency panel if any chain mentions them."""
    if payload is None:
        return True
    if not filters_are_active(filters):
        return True
    active_entity_filters = [
        filters.get("route", "All"),
        filters.get("supplier", "All"),
        filters.get("domain", "All"),
    ]
    if all(x == "All" for x in active_entity_filters) and filters.get("severity", "All") == "All":
        return True

    blob_parts: list[str] = []
    norm = payload
    for ent in norm.get("top_fragile_entities") or []:
        if isinstance(ent, dict):
            blob_parts.extend([ent.get("label"), ent.get("entity_id"), ent.get("domain")])
    for chain in norm.get("dependency_chains") or []:
        if isinstance(chain, dict):
            labels = chain.get("path_labels") or []
            if isinstance(labels, list):
                blob_parts.extend(labels)
    for stmt in norm.get("cascading_risk_statements") or []:
        if isinstance(stmt, dict):
            blob_parts.append(stmt.get("statement"))
            blob_parts.append(stmt.get("source_domain"))
    blob = _text_blob(*blob_parts)

    route_f = filters.get("route", "All")
    if route_f != "All" and route_f.lower() not in blob:
        return False
    sup_f = filters.get("supplier", "All")
    if sup_f != "All" and sup_f.lower() not in blob:
        return False
    dom_f = filters.get("domain", "All")
    if dom_f != "All":
        dom_aliases = {
            "deliveries": ("delivery", "deliveries"),
            "inventory": ("inventory",),
            "suppliers": ("supplier", "suppliers"),
            "governance": ("governance", "operational"),
        }
        needles = dom_aliases.get(dom_f, (dom_f,))
        if not any(n in blob for n in needles):
            return False
    return True


def filter_risk_items(
    items: list[dict[str, Any]] | None,
    filters: DashboardFilterState,
) -> list[dict[str, Any]]:
    return [r for r in (items or []) if isinstance(r, dict) and risk_matches_filters(r, filters)]


def filter_ai_payload(
    payload: dict[str, Any] | None,
    filters: DashboardFilterState,
) -> dict[str, Any] | None:
    if payload is None:
        return None
    recs = payload.get("recommendations") or []
    filtered = [r for r in recs if isinstance(r, dict) and alert_matches_filters(r, filters)]
    out = dict(payload)
    out["recommendations"] = filtered
    return out


def filter_scenario_distribution(
    dist: dict[str, Any] | None,
    filters: DashboardFilterState,
) -> dict[str, Any] | None:
    if dist is None:
        return None
    items = dist.get("items") or []
    filtered = [i for i in items if isinstance(i, dict) and scenario_item_matches_filters(i, filters)]
    out = dict(dist)
    out["items"] = filtered
    return out


def entity_in_data(entity: str, *, risks: list[dict[str, Any]], alerts: list[dict[str, Any]], dependency: dict[str, Any] | None) -> bool:
    needle = entity.strip().lower()
    if not needle:
        return False
    for row in risks:
        if needle in _text_blob(row.get("label"), row.get("risk_type")):
            return True
    for alert in alerts:
        if needle in _text_blob(alert.get("title"), alert.get("summary"), alert.get("category")):
            return True
    if dependency:
        for chain in dependency.get("dependency_chains") or []:
            if not isinstance(chain, dict):
                continue
            labels = chain.get("path_labels") or []
            if isinstance(labels, list) and any(needle in str(x).lower() for x in labels):
                return True
        for ent in dependency.get("top_fragile_entities") or []:
            if isinstance(ent, dict) and needle in _text_blob(ent.get("label"), ent.get("entity_id")):
                return True
    return False


def discover_drill_targets(
    *,
    risk_items: list[dict[str, Any]] | None,
    ai_payload: dict[str, Any] | None,
    dependency: dict[str, Any] | None,
    max_targets: int = 8,
) -> list[str]:
    alerts = [r for r in (ai_payload or {}).get("recommendations") or [] if isinstance(r, dict)]
    risks = [r for r in (risk_items or []) if isinstance(r, dict)]
    ordered: list[str] = []
    seen: set[str] = set()
    for preset in PRIORITY_DRILL_ENTITIES:
        if entity_in_data(preset, risks=risks, alerts=alerts, dependency=dependency):
            key = preset.lower()
            if key not in seen:
                seen.add(key)
                ordered.append(preset)
    for row in risks:
        route = parse_route_from_label(str(row.get("label", "")))
        if route and route.lower() not in seen:
            seen.add(route.lower())
            ordered.append(route)
    for row in risks:
        sup = parse_supplier_from_label(str(row.get("label", "")))
        if sup and sup.lower() not in seen:
            seen.add(sup.lower())
            ordered.append(sup)
    return ordered[:max_targets]
