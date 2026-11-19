"""Exact lexical retrieval restricted to saved specialist source passages."""
import re


def _terms(text):
    words = set(re.findall(r"[a-zA-Z_]{2,}|\d{4}", text.lower()))
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        words.update(run[i:i + 2] for i in range(len(run) - 1))
    return words


def related_fact_refs(cards, query, *, excluded, limit=4):
    """Rank saved evidence cards by shared query terms, with stable ties."""
    terms = _terms(query)
    candidates = [(len(terms & _terms(card.text)), card.ref)
                  for card in cards if card.ref not in excluded]
    return [ref for score, ref in sorted(candidates, key=lambda item: (-item[0], item[1]))[:limit]
            if score]


def retrieve_evidence(context, query, *, limit=8, coalesce=False):
    """Rank exact saved passages; optionally send each selected source span only once."""
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
    selected = sorted(result, key=lambda item: (-item["score"], item["evidence_id"], item["start"]))[:limit]
    if not coalesce:
        return selected

    # Do not change ranking or selection: merge only overlap in the selected set,
    # so sources retain exactly the same covered characters (including boundaries).
    groups = []
    for rank, passage in sorted(enumerate(selected), key=lambda entry: (entry[1]["evidence_id"], entry[1]["start"])):
        if groups:
            best_rank, previous = groups[-1]
            if previous["evidence_id"] == passage["evidence_id"] and passage["start"] < previous["end"]:
                if passage["end"] > previous["end"]:
                    previous["text"] += passage["text"][previous["end"] - passage["start"]:]
                    previous["end"] = passage["end"]
                previous["score"] = max(previous["score"], passage["score"])
                groups[-1] = (min(best_rank, rank), previous)
                continue
        groups.append((rank, dict(passage)))
    return [passage for _, passage in sorted(groups, key=lambda entry: entry[0])]

