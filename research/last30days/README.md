# Primeri — last30days

Tri brifa pokrenuta 2026-08-19 kao demonstracija alata (uputstvo:
`../../LAST30DAYS_RUNBOOK.md`). Sekvencijalno, po Pravilu 1.

| brif | tema | trajanje |
|---|---|---:|
| `ai-agent-guardrails-...-raw.md` | guardrails / prompt injection / MCP security | 185s |
| `llm-gateway-...-raw.md` | LLM gateway / routing / failover | 146s |
| `ai-agent-long-term-memory-...-raw.md` | agent memory / persistent context | 168s |

## Graf

`graphify-out/graph.html` — otvori u browseru, ne treba server.
**192 čvora, 385 grana, 12 zajednica.** Tri brifa su spojena preko deljenih
`platform_*` čvorova (Reddit, HN, GitHub, TikTok, YouTube, Digg, Instagram,
arXiv, Techmeme), pa graf nije tri odvojena ostrva nego jedna mreža.

Šta je u grafu:
- **entiteti** (`concept`) — proizvodi, repoi, firme, standardi
- **tvrdnje** (`rationale`) — šta svaki evidence klaster tvrdi
- **platforme i zajednice** (`document`) — odakle tvrdnja dolazi

Rebuild: `graphify export html` iz ovog foldera.

## Napomena o pokrivenosti

Bluesky je u ovom runu vraćao HTTP 401 (inline komentar u `.env` je ušao u
vrednost lozinke — popravljeno posle, vidi runbook §"Dve zamke"). Instagram je
proradio istog dana. Reddit je kao i uvek stao na ~12 stavki po upitu.
