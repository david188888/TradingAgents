"""Exact lexical retrieval restricted to saved specialist source passages."""
import re


def _terms(text):
    words = set(re.findall(r"[a-zA-Z_]{2,}|\d{4}", text.lower()))
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        words.update(run[i:i + 2] for i in range(len(run) - 1))
    return words


def retrieve_evidence(context, query, *, limit=8):
    """Lexically rank exact saved passages inside this stage's fact sources."""
    record = context.get("record", {})
    facts = context.get("facts", record.get("claims", []))
    allowed = {eid for fact in facts if fact.get("kind", "fact") == "fact"
               for eid in fact.get("evidence_ids", [])}
    sources = context.get("sources", record.get("evidence", []))
    terms = _terms(query)
    result = []
    for source in sources:
        if source.get("evidence_id") not in allowed or source.get("availability", "available") != "available":
            continue
        content = source.get("content") or {}
        text = content.get("text", "")
        # Whole bounded windows, with offsets into the saved payload, not a summary.
        for start in range(0, len(text), 1000):
            passage = text[start:start + 1200]
            score = len(terms & _terms(passage))
            if score:
                result.append({"evidence_id": source["evidence_id"], "source_name": source.get("source_name"),
                    "start": start, "end": start + len(passage), "text": passage, "score": score})
    return sorted(result, key=lambda item: (-item["score"], item["evidence_id"], item["start"]))[:limit]

