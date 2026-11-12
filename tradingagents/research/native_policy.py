"""Current specialist source partitions over qualified saved evidence."""
from tradingagents.research.native_valuation import VALUATION_SOURCES
from tradingagents.research.source_families import (
    BODY_SOURCES,
    FINANCIAL_DETAIL_SOURCES,
    FINANCIAL_SOURCES,
    OPERATING_SOURCES,
    PRICE_SOURCES,
)

ROLE_ORDER = ("operating_quality", "event_context", "market_context")

def _valuation_sources(record):
    if record.evidence_checks is not None:
        from tradingagents.research.minimum_evidence import SUPPLEMENTAL_VALUATION_SOURCES
        return VALUATION_SOURCES | SUPPLEMENTAL_VALUATION_SOURCES
    return VALUATION_SOURCES


def _operating_sources(record):
    if record.evidence_checks is not None:
        from tradingagents.dataflows.disclosure_documents_v2 import NUMERIC_SOURCE
        return FINANCIAL_SOURCES | FINANCIAL_DETAIL_SOURCES | OPERATING_SOURCES | {NUMERIC_SOURCE}
    return FINANCIAL_SOURCES | FINANCIAL_DETAIL_SOURCES | OPERATING_SOURCES


def fact_views(record, *, valuation=False):
    sources = {source.evidence_id: source for source in record.evidence}
    metric_sources = {key for metric in record.metrics if metric.availability == "available"
                      for key in metric.input_evidence_ids}
    views = {role: [] for role in ROLE_ORDER}
    for fact in record.claims:
        if fact.kind != "fact":
            continue
        if "native_dimension:company_introduction" in fact.limitations:
            continue
        if any(sources[key].availability != "available" or sources[key].content is None
               or sources[key].usable_as_of is None for key in fact.evidence_ids):
            continue
        names = [sources[key].source_name for key in fact.evidence_ids]
        evidence_ids = fact.evidence_ids
        # Web and capability supplements carry their requesting role; route by that, not by source name.
        if (any(name.startswith(('web.', 'derived.web_fields.')) for name in names)
                or any(key.startswith('capability.') for key in evidence_ids)):
            roles = [r for r in ROLE_ORDER if 'native_dimension:'+r in fact.limitations]
            if len(roles) == 1:
                views[roles[0]].append(fact)
            continue
        if valuation and any(name in _valuation_sources(record) for name in names) or any(name in _operating_sources(record) for name in names):
            views["operating_quality"].append(fact)
        elif any(name in BODY_SOURCES for name in names):
            role = "operating_quality" if "native_dimension:operating_quality" in fact.limitations else "event_context"
            views[role].append(fact)
        elif any(name == "cninfo.announcements" for name in names):
            views["event_context"].append(fact)
        elif (set(fact.evidence_ids) & metric_sources or
              any(name in PRICE_SOURCES for name in names)):
            views["market_context"].append(fact)
    return {role: tuple(items) for role, items in views.items()}


def global_coverage(record):
    """Collector coverage, not the model's impression of its isolated view."""
    coverage = {}
    for item in record.limitations:
        if item.startswith("global_coverage:"):
            _, capability, status = item.split(":", 2)
            coverage[capability] = {"status": status, "gaps": []}
    for item in record.limitations:
        if item.startswith("global_gap:"):
            _, capability, reason = item.split(":", 2)
            coverage.setdefault(capability, {"status": "unknown", "gaps": []})["gaps"].append(reason)
    return coverage
