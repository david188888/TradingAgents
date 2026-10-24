"""Pure admission of saved web observations; summaries do not become facts."""

import hashlib
from datetime import date, datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from tradingagents.agents.schemas._research_record import (
    RecordClaimV1,
    SourceContentV1,
    SourceEvidenceV1,
)
from tradingagents.agents.schemas._search import AdmissionBatchV1, AdmittedObservationV1

SHANGHAI = ZoneInfo('Asia/Shanghai')


def _material_hits(batch, ticker):
    for hit in batch.hits:
        if hit.document is None:
            yield hit
            continue
        document = hit.document
        if document.security_id[:6] != ticker[:6]:
            continue
        header = f'公司代码：{document.security_id[:6]}\n{document.title}\n'
        for page in document.pages:
            text = header+page.text
            yield hit.model_copy(update={'url': hit.url.split('#')[0]+f'#page={page.page}',
                'content': text, 'truncated': page.truncated or len(text) > 4000})


def admit_search_batch(batch, *, ticker: str, cutoff: date) -> AdmissionBatchV1:
    cutoff = date.fromisoformat(cutoff) if isinstance(cutoff, str) else cutoff
    now = datetime.now(timezone.utc)
    observations, rejections = [], []
    for hit in _material_hits(batch, ticker):
        if not hit.content.strip():
            rejections.append('original_body_missing:' + hit.canonical_url)
            continue
        published = hit.published_at
        if published is None or published.astimezone(SHANGHAI).date() > cutoff:
            rejections.append('publication_unverified_or_after_cutoff:' + hit.canonical_url)
            continue
        host = urlsplit(hit.url).hostname or ''
        official = any(host == domain or host.endswith('.'+domain)
                       for domain in ('cninfo.com.cn', 'sse.com.cn', 'szse.cn', 'bse.cn', 'gov.cn'))
        immutable_report = official and urlsplit(hit.url).path.lower().endswith('.pdf')
        if cutoff < now.astimezone(SHANGHAI).date() and not immutable_report:
            rejections.append('historical_vintage_unverified:' + hit.canonical_url)
            continue
        linked = [r for r in batch.requests if r.provider == hit.provider]
        if batch.outcomes:
            ids = {o.task_id for o in batch.outcomes if any(h.url.split('#')[0] == hit.url.split('#')[0] or h.canonical_url == hit.canonical_url for h in o.hits)}
            linked = [r for r in linked if r.task_id in ids]
        scopes = {(r.role, r.capability) for r in linked}
        if not scopes:
            rejections.append('search_task_scope_missing:' + hit.canonical_url)
            continue
        text = hit.content[:4000]
        digest = hashlib.sha256(text.encode()).hexdigest()
        family = hit.family_id or hit.canonical_url
        family_id = 'web.' + hashlib.sha256(family.encode()).hexdigest()
        for role, capability in sorted(scopes):
            identity = hashlib.sha256((hit.url+hit.title+published.isoformat()+digest+role+capability).encode()).hexdigest()
            eid = 'web.' + identity
            try:
                source = SourceEvidenceV1(evidence_id=eid, source_name=f'web.{host}',
                    source_kind='official' if official else 'media', source_family_id=family_id,
                    availability='available', public_url=hit.url, published_at=published,
                    usable_as_of=published, captured_at=now,
                    content=SourceContentV1(kind='excerpt', text=text,
                        locator_label='PDF '+urlsplit(hit.url).fragment if hit.document else '网页原文起始片段',
                        content_sha256=digest, truncated=hit.truncated or len(hit.content) > 4000),
                    limitations=('source_reported_not_independently_verified', 'selected_web_excerpt',
                                 'native_dimension:'+role, 'web_capability:'+capability,
                                 *(('provider_date_estimate',) if hit.provider == 'tavily' else ()),
                                 *(('publication_day_precision',) if hit.published_precision == 'day' else ())))
                fact = RecordClaimV1(claim_id='fact.'+identity, kind='fact',
                    statement=f'来源《{hit.title[:120]}》载明：{text[:1000]}', evidence_ids=(eid,),
                    limitations=('source_reported_observation', 'native_dimension:'+role,
                                 'web_capability:'+capability))
                observations.append(AdmittedObservationV1(source=source, fact=fact, role=role, capability=capability))
            except ValidationError:
                rejections.append('source_contract_unqualified:' + hit.canonical_url)
    return AdmissionBatchV1(batch_id=batch.batch_id, observations=tuple(observations),
                             rejections=tuple(dict.fromkeys(rejections)))
