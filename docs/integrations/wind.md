# Wind integration scope

Status: Current

V9 company-research collection does not dispatch Wind during prefetch: Wind never joins the minimum
evidence package and no query is issued on its own. A specialist may still request the `wind_enrich`
capability card on an explicit gap; the gateway then uses the local Wind CLI (`wind_enabled` plus a
resolvable CLI) for that bounded request only, and the card is hidden when either is missing. Existing
source adapters do not imply admission to the maintained workflow. See
[A-share source capabilities](../operations/a-share-data-capabilities.md) and the
[current architecture](../../ARCHITECTURE.md). Retired classic graph and preset instructions no longer
apply.
