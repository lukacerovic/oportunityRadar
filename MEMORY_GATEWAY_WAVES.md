# Dva nova talasa: agent memory i LLM gateway — veći od guardrails-a

*2026-08-12. Produbljena analiza posle `NEXT_REVOLUTIONS.md`. Fokus: šestorka
malih "accelerating" repoa rođenih u istoj januarskoj nedelji, i dva mnogo veća
klastera otkrivena proverom 1-hop suседa oko `Mem0` i `LiteLLM` u
`entity_semantic_edges`. Svi citati funkcija su iz Haiku kartica
(`model = claude-agent-batch:haiku`), sve ivice iz semantičkog grafa
(dev baza, snapshot 12.08.2026).*

---

## TL;DR

| klaster | broj entiteta | anchor | poznat od ranije? |
|---|---:|---|---|
| `guardrails` + `ai-security` | 60 | Guardrails AI, garak, PyRIT | da — `NEXT_REVOLUTIONS.md` |
| **`agent-memory` (oko Mem0)** | **24** | Mem0 | **ne — nov nalaz** |
| **`llm-gateway` (oko LiteLLM)** | **20** | LiteLLM | **ne — nov nalaz** |
| januarski mini-talas (6 repoa, ista nedelja) | 6 | — | delimično |

Memory i gateway klasteri nisu bili vidljivi u prošlom prolazu jer smo gledali
samo *nove/mlade* klastere (§4 enrichment izveštaja). Mem0 i LiteLLM su već
etablirani (60k+ zvezdica), pa su njihovi sateliti bili van fokusa — ali sama
gustina suседstva (24 i 20 nezavisnih pokušaja) je istog reda veličine kao
guardrails talas, samo organizovana oko starijeg anchora umesto oko praznog
prostora.

---

## Deo 1 — Januarski mini-talas: šest repoa, ista nedelja

Pet od šest malih "accelerating" repoa iz prošlog nalaza je rođeno u **10 dana**,
sredinom januara 2026 (GitHub `created_at`, ne datum ulaska u našu bazu):

```
13.01  borghei/claude-skills
14.01  pierpaolo28/awesome-fde-roadmap
19.01  nicobailon/pi-mcp-adapter
20.01  rynfar/meridian
21.01  analysedecircuit/oxideterm
23.01  hacklyc/myagents
```

`iannuttall/seo` (10.07) je odvojen slučaj, mnogo mlađi — van ovog obrasca.

| repo | šta radi | najbliži sused u grafu |
|---|---|---|
| `borghei/claude-skills` | skill/agent biblioteka za Claude Code, Cursor, Codex, Gemini, Copilot | `composiohq/awesome-codex-skills` (0.75) |
| `pierpaolo28/awesome-fde-roadmap` | roadmap lista za "Forward Deployment Engineer" | `avinash201199/free-ai-agents-resources` (0.65) |
| `nicobailon/pi-mcp-adapter` | token-efikasan MCP adapter za Pi coding agenta | `burkan2/hsum` (0.8) |
| `rynfar/meridian` | proxy koji omogućava Claude Max u third-party alatima | **`LiteLLM` (0.76)** — vidi Deo 3 |
| `analysedecircuit/oxideterm` | AI-native terminal, Rust/Tauri, MCP podrška | `inotgreen/openladonx` (0.69) |
| `hacklyc/myagents` | desktop radni prostor za agente | `wing900/manimcat` (0.65) |

Nije potvrđeno da je ovo koordinisano — verovatnije je da je nešto zajedničko
(release nekog SDK-a, viralan post) okinulo talas nezavisnih graditelja u istoj
nedelji. `hacklyc/myagents` je jedini kom je momentum label "accelerating"
netačan — zvezdice su mu pale 841→802 u istom periodu.

---

## Deo 2 — Talas oko Mem0: 24 nezavisna pokušaja "agent memory"

Mem0 (62.601 zvezdica, `mem0ai`) je anchor. Svih 24 suседa su manji, nezavisni
pokušaji da se reši isti problem: **kako agent pamti preko sesija**.

| repo | relacija | skor | šta radi |
|---|---|---:|---|
| `mienetic/mnema` | semantically_similar_to | 0.80 | Apstrahuje memory storage preko Chroma/Qdrant/sqlite-vec, value-ranked retrieval |
| `fqih/lethe` | semantically_similar_to | 0.80 | Čuva memorije sa importance score u SQLite, decay skorova kroz vreme |
| `dancenitra/mnemo` | semantically_similar_to | 0.80 | In-memory storage za agent facts, importance scoring, auditable |
| `lamentis-operating-systems/naome-memory` | semantically_similar_to | 0.80 | Deterministička memory consolidation, episodic retention za agent kernele |
| `mugenjoka1234/llm-wiki` | semantically_similar_to | 0.76 | Čuva odluke, neslaganja, trust-graded znanje u persistent wiki-jima |
| `brianschroeder/simple-agent-memory` | semantically_similar_to | 0.75 | Repository-scoped memory za Claude Code |
| `keep-it-inmind/keep-it-inmind.github.io` | semantically_similar_to | 0.75 | Benchmark metodologija za agent memory sisteme |
| `bryanslongbl-sys/aurum-recall` | semantically_similar_to | 0.73 | Memory storage sa vizuelnim context routing-om (ContextQR) |
| `sashamitrovich/milepost` | semantically_similar_to | 0.72 | Agent memory u Markdown formatu, integracija sa Claude Code skill-om |
| `mohsinsheikhani/governed-agent-memory` | semantically_similar_to | 0.70 | GDPR-compliant erasure, write-time poisoning detection |
| `trustmaster/emos` | semantically_similar_to | 0.70 | Second-brain arhitektura template sa MCP integracijom |
| `agricidaniel/fablesecondbrain` | semantically_similar_to | 0.70 | Searchable knowledge base za agent operacije |
| `mavaali/daftari` | semantically_similar_to | 0.70 | Agent memorije sa eksplicitnim contradiction tracking-om |
| `runsagents/memory-ledger` | semantically_similar_to | 0.70 | Memorije sa metapodacima: source, timestamp, authorization level, expiry |
| `hebbrix/hebbrix-mcp` | conceptually_related_to | 0.70 | MCP server za Claude Desktop/Cline/Cursor/Continue, store+retrieve |
| `qzsos/researchmemorykit` | semantically_similar_to | 0.70 | Structured memory sa access controls i audit trails za research agente |
| `fuckbigtech-ai/homestead-memory` | conceptually_related_to | 0.70 | Markdown memory sa kriptografskim dokazom da sadržaj nije menjan |
| `nmdra/notebrain-cli` | conceptually_related_to | 0.70 | Embeduje Obsidian beleške lokalno, semantic search API za agente |
| `lesliewo/lamar` | semantically_similar_to | 0.65 | Retrieval kao contextual bandit optimizacioni problem |
| `ali-ulu/levh` | semantically_similar_to | 0.65 | Self-curating memory za AI coding alate |
| `fahaddubush/obsidian-agentic-second-brain` | semantically_similar_to | 0.65 | Obsidian setup sa memory governance, agent-facing interfejsima |
| `memoraxlabs/memorax` | semantically_similar_to | 0.65 | "Memory layer for long-horizon intelligence" |
| `sumanth0401/lara` | semantically_similar_to | 0.60 | Konverzacioni AI sa perzistentnom memorijom, personality switching |
| `hiteshyadav2616/feng-chatbot` | conceptually_related_to | 0.60 | Omotava Groq Llama 3.3 preko LangChain-a, čuva istoriju konverzacije |

**Insight**: bar 6 od 24 (`daftari`, `governed-agent-memory`, `memory-ledger`,
`hebbrix-mcp`, `researchmemorykit`, `naome-memory`) eksplicitno rešava
*upravljanje* memorijom (audit, governance, expiry, contradiction tracking),
ne samo skladištenje. To je isti obrazac kao guardrails talas — prvi talas
gradi osnovnu sposobnost (Mem0), drugi talas gradi kontrolu nad njom.

---

## Deo 3 — Talas oko LiteLLM: 20 nezavisnih LLM gateway/proxy pokušaja

LiteLLM (55.641 zvezdica, `berriai`) je anchor. Svi ovi rade neku varijaciju
"jedan interfejs preko više LLM provajdera":

| repo | relacija | skor | šta radi |
|---|---|---:|---|
| `bharat3645/mcp-gateway-lite` | semantically_similar_to | 0.80 | Presreće MCP zahteve: audit logging, tool access control |
| **`rynfar/meridian`** | semantically_similar_to | 0.76 | Proxy za Claude Max u third-party alatima — vidi napomenu ispod |
| `nossulenko/heimdal` | semantically_similar_to | 0.75 | Rutira po ceni/latenciji, kešira odgovore |
| `rishika1099/llm-gateway` | semantically_similar_to | 0.75 | Unifikuje zahteve preko heterogenih backend-ova, API-key auth, keš |
| `moeaisaka/openclaw-model-policy-router` | semantically_similar_to | 0.72 | Policy-based routing, fail-closed semantika |
| `alebrito124356/llm-gateway` | conceptually_related_to | 0.70 | Rutira preko NVIDIA NIM/Ollama/OpenAI, semantic caching |
| `lucheeseng827/recall` | conceptually_related_to | 0.70 | Presreće LLM API saobraćaj, semantic-similarity keš, single-binary |
| `intelharvestproject-del/omnicode` | conceptually_related_to | 0.70 | Proxy sa context optimizacijom, token reduction, protocol translation |
| `diogox451/archon-llm-gateway` | conceptually_related_to | 0.70 | Apstrahuje provider-specific detalje iza unified ugovora |
| `sceuz/llm-inference-gateway` | semantically_similar_to | 0.70 | Agregira provider pozive, auto-failover, throttling, keš |
| `gencikodraer47/aiwts-lowcost-ai` | semantically_similar_to | 0.70 | Proxy sa unified interfejsom i cost aggregation |
| `laurent-durand/vox` | semantically_similar_to | 0.70 | Go CLI, apstrakcija preko provajdera, streaming |
| `glama-ai/lightport` | semantically_similar_to | 0.70 | Routing proxy koji drži Portkey-jev feature set (open alternativa) |
| `nguyenbatam/switchboard` | semantically_similar_to | 0.70 | Routing preko provajdera, streaming, tool calling, RAG pipeline podrška |
| `haichen1985/opti-moa` | conceptually_related_to | 0.65 | Rutira po karakteristikama upita, conditional logika |
| `shkyyy18/kimi-adapter` | conceptually_related_to | 0.60 | Rutira Claude Code zahteve ka Kimi API preko lokalnog proxy-ja |
| `syedahmad0786/mcp-business-server` | conceptually_related_to | 0.60 | Izlaže business bazu kao MCP alate |
| `mindpool-labs/bowline` | conceptually_related_to | 0.60 | Lokalni reverse proxy, policy enforcement, tamper-evident audit |
| `ashwinhegde19/openharness` | semantically_similar_to | 0.50 | Rutira coding agent sesije ka provajderima, in-session switching |
| `proxyhatcom/langchain-proxyhat` | semantically_similar_to | 0.50 | Proširuje LangChain sa ProxyHatLoader-om |

**Insight (bitno)**: `rynfar/meridian` — isti repo iz januarskog mini-talasa
(Deo 1) — pojavljuje se ovde direktno povezan sa LiteLLM-om. Graf ga je
ispravno prepoznao kao *manju, rizičniju varijantu iste kategorije*: obojica
rutiraju/proksiraju LLM saobraćaj, ali meridian specifično zaobilazi
Anthropic-ove ToS granice (Claude Max pretplata u nepodržanim alatima), dok
LiteLLM legitimno multi-provider routuje. Isti tehnički oblik, suprotan
legalni status — vredi ga označiti kao rizik, ne kao priliku.

Takođe zanimljivo: `glama-ai/lightport` eksplicitno tvrdi da drži "Portkey's
feature set" — što znači da je jedna od kompanija iz `LUKA_DATA_DUMP.md`
(Portkey AI) već dovoljno etablirana da postane referentna tačka za open-source
klonove, isto kao LiteLLM.

---

## Deo 4 — Šta ovo znači zajedno

1. **Guardrails (60) + agent-memory (24) + llm-gateway (20) = 104 nezavisna
   pokušaja** u tri teme, sve unutar iste šire kategorije (agent infrastruktura
   posle MCP-a). Ovo nije tri odvojena talasa — to je jedan veći obrazac:
   ekosistem agenata je dovoljno sazreo da svaka njegova slabost (kontrola,
   pamćenje, routing) sad ima desetine nezavisnih pokušaja rešenja u istoj
   sedmici do dva meseca.

2. **Memory i gateway klasteri nisu bili vidljivi u prošlom prolazu** jer smo
   filtrirali samo mlade/rastuće entitete oko *praznog* prostora. Mem0 i
   LiteLLM su stari i veliki, pa je njihovo susedstvo bilo van radara —
   pouka: wave detekcija ne treba da isključuje klastere oko etabliranih
   anchora, oni mogu biti isto toliko aktivni.

3. **Kvalitet podataka**: većina od ovih ~44 novih entiteta nema
   `entity_metrics_daily` zapis (zvezdice), što znači da su ili prerano
   uhvaćeni pre prvog metrike-prolaza, ili je kolektor promašio. Pre nego što
   se ovo prezentuje kao "104 dokazana entiteta", treba pustiti metrike
   collector da ih pokrije — trenutno imamo samo semantičku ivicu i Haiku
   karticu, ne i realan trakcioni dokaz.

4. **Preporuka**: dodati `agent-memory` i `llm-gateway` kao formalne kandidate
   u wave detektor, uz postojeći `guardrails`+`ai-security`. Sve tri dele
   istu strukturu (jedan stariji anchor + desetine nezavisnih malih pokušaja)
   pa ih ista mašinerija (26/26 testirana, §7.4 enrichment izveštaja) treba
   da obradi bez izmena.

---

*Povezano: `NEXT_REVOLUTIONS.md` (guardrails/ai-security talas, 60 entiteta),
`LUKA_DATA_DUMP.md` (company-backed repoi), `ENRICHMENT_REPORT.md` (izvorni
Haiku prolaz, 10.650 kartica).*
