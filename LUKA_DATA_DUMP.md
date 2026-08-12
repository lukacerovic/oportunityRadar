# Data dump za Luku — enrichment nalazi + company-backed repo analiza

*2026-08-12. Sirovi podaci iz dve teme: (1) guardrails/ai-security wave iz
`ENRICHMENT_REPORT.md` §4, i (2) analiza 12 kompanijski-backovanih repoa
(kandidati za dealroom.co poređenje). Sve kartice su iz Haiku batch prolaza
(`model = claude-agent-batch:haiku`), izvučene direktno iz `comprehension_cards`
tabele na dev bazi.*

---

## Deo 1 — Enrichment prolaz, brojke

| | pre | posle |
|---|---:|---:|
| comprehension_cards | 1.713 | **12.093** |
| entity_semantic_edges | 283 | **5.758** |
| pokrivenost entiteta karticom | 3,4% | **21,2%** |

Kvalitet (mehanički test na `confidence: high` + prazan `open_questions`):

| model | kartica | `confidence: high` | ima `open_questions` |
|---|---:|---:|---:|
| claude-agent-batch:haiku | 10.380 | **1,8%** | **99,9%** |
| ollama:qwen2.5:7b | 40 | 90,0% | 92,5% |
| ollama:qwen2.5:3b | 1.625 | 23,3% | 58,9% |

Pun detalj u `ENRICHMENT_REPORT.md`, sekcije 1–7.

---

## Deo 2 — guardrails + ai-security klaster (60 entiteta)

Hairball (§5c iz izveštaja) je jednu temu mehanički presekao na dva klastera.
Zajedno: 60 entiteta, skoro svi mlađi od 45 dana. Nastavak `AGENT_GUARDRAIL_WAVE.md`
(28.07.2026, tada 5 entiteta).

### Šest slojeva gde se agent presreće

**1. Presretanje tool-call-a pre izvršenja**
- `othy19904-eng/agent-action-guard` — proverava akciju protiv policy pravila pre izvršenja
- `srinu16it/llm-tool-host` — validira semantiku tool poziva protiv deklarisane šeme
- `amurlaniakea/agent-shield-runtime` — pet senzora (scope, shield, wallet-guard, goal)
- `dicklesworthstone/destructive_command_guard` — blokira destruktivne shell/git operacije
- `yvoolab/claude-code-safety-hooks` — Claude Code `PreToolUse` hook
- `pamiray-m/wace-light` — kontrolisano komandno okruženje, PII redakcija, audit trail

**2. Kernel/mrežni sloj**
- `itsventie/ebpf-llm-firewall` — eBPF firewall za LLM API saobraćaj
- `jyswee/a2a-trustgate` — compliance firewall za agent-to-agent
- `pk0559505-cloud/securerag` — RBAC na RAG pozivima

**3. Supply chain agentovih komponenti (nov ugao, post-MCP)**
- `eltociear/mcp-audit` — skenira MCP servere/tool opise za prompt-injection markere, exfil, download-and-execute
- `amurlaniakea/skill-auditor` — statička analiza skill YAML/JSON
- `2607.11086` (akademski rad) — empirijska studija MCP sigurnosti u produkciji

**4. Red-team / testiranje odbrane**
- `shimiyahya/prompt-injection-redteam`, `krishna89287/prompt-injection-detector`, `jleonceo/guardianes-verificados-ia`
- sidra: `garak` (NVIDIA, 8.704 zvezdice), `PyRIT` (Microsoft), `PurpleLlama` (Meta) — sva tri ušla u klaster preko novih repoa

**5. Prevođenje mekih instrukcija u tvrda pravila**
- `singh38600-svg/hardline` — NL ograničenja → izvršna guard pravila
- `adekka-canada/actionspecs` — standardizovan handshake za agent-operacije
- `theo-ai-lab/farthing` — deterministički policy engine + Temporal exactly-once

**6. Grounding / verifikacija tvrdnji**
- `erikolson/grounding-harness` — briše netragabilne tvrdnje pre outputa
- `flyingfredcurry/faithful-cite`

### Kontaminacija (~4 od 60, u skladu sa §5d izveštaja)
- `jvbotelho/skewrun` — Kerberos clock skew, nema veze sa AI
- `xmahdi1/wisp` — enkriptovani messaging, nema veze
- `elementmerc/senbonzakura` — **skida** guardrails, suprotan predznak
- `giosh-me/venture-validator` — pogrešna kategorizacija

### Bez dokazane adopcije (`evidence_breadth = 1` = jedan izvor, nula potvrde)
`ebpf-llm-firewall`, `mcp-audit`, `llm-tool-host`, `actionspecs`, `grounding-harness`,
`ricardocabral/ajq` (3 zvezdice), `hardline` (1 zvezdica) — svi repoi stari
nekoliko nedelja. Signal je *konvergencija namere*, ne dokazana tehnologija.

---

## Deo 3 — 12 kompanijski-backovanih repoa (dealroom.co kandidati)

Filtrirano iz `who_is_behind` polja Haiku kartica — isključeni big-tech
(OpenAI, Microsoft, NVIDIA, Hugging Face, Apache, Neo4j) i akademske grupe.
Ovo su startapi/kompanije koje bi realno imale profil na dealroom.co.

### Zvezdice (najnovija vrednost, `entity_metrics_daily`)

| repo | stars | kompanija | kategorija |
|---|---:|---|---|
| Dify | 151.459 | LangGenius | app-builder |
| Flowise | 55.194 | FlowiseAI | app-builder |
| Langfuse | 32.581 | Langfuse | observability |
| promptfoo | 23.970 | promptfoo | eval-tooling |
| Opik | 21.125 | Comet ML | observability |
| Portkey Gateway | 12.650 | Portkey AI | llm-gateway |
| Axolotl | 12.314 | axolotl-ai-cloud | fine-tuning |
| OpenLLMetry | 7.356 | Traceloop | observability |
| Helicone | 6.036 | Helicone | observability |
| PromptTools | 3.046 | HegelAI | prompt-tooling |
| Curator | 1.709 | bespokelabsai | synthetic-data |
| LangKit | 994 | WhyLabs | guardrails |

### Semantički graf — ivice između njih (`entity_semantic_edges`)

```
Dify         <-> Flowise        semantically_similar_to  0.85
Langfuse     <-> OpenLLMetry    semantically_similar_to  0.80
Opik         <-> Langfuse       semantically_similar_to  0.80
Flowise      <-> Dify           semantically_similar_to  0.80
Langfuse     <-> Opik           semantically_similar_to  0.75
Helicone     <-> Langfuse       semantically_similar_to  0.75
```

Observability grupa (Langfuse, Opik, OpenLLMetry, Helicone) je najgušća — 4 od 5
direktno povezana, Langfuse je hub čvor. Dify↔Flowise je najjača pojedinačna
ivica u ovom podskupu, ali oba su već ogromna (150k/55k) — nisu rani signal.

### Pune kartice (Haiku batch)

**Axolotl** — fine-tuning, `axolotl-ai-cloud`, confidence: med
> Simplifies fine-tuning of large models with built-in support for LoRA, QLoRA, and distributed training.
> community_note: Community actively using but encountering VRAM management and memory crash challenges.
> open_questions: VRAM management solutions; training stability improvements

**Curator** — synthetic-data, `bespokelabsai`, confidence: low
> Curates and synthesizes training data to improve model quality.
> community_note: Community discussion about Curator is minimal.
> open_questions: Community adoption; practical effectiveness of curation methods

**Dify** — app-builder, `LangGenius`, confidence: med
> No-code/low-code platform for building LLM applications with visual workflow editor.
> community_note: Praise for interface overshadowed by critical upgrade issues.
> open_questions: Critical upgrade issues; credibility concerns about recent changes

**Flowise** — app-builder, `FlowiseAI`, confidence: med
> Provides visual workflow builder for LLM applications with support for RAG, memory, and tool integration.
> community_note: Critical bugs blocking core workflows reported.
> open_questions: Critical bugs blocking workflows; feature completeness

**Helicone** — observability, `Helicone`, confidence: med
> LLM observability platform for monitoring API usage, costs, and performance. **Currently in maintenance mode.**
> community_note: Users report strong satisfaction but project entered maintenance mode, prompting replacements.
> open_questions: Impact of maintenance mode on user retention; user replacement trajectories

**Langfuse** — observability, `Langfuse`, confidence: high
> Provides production observability for LLM applications with tracing, metrics, and debugging capabilities.
> community_note: The community recognizes Langfuse as one of the better LLM observability solutions with multiple users reporting successful adoption.
> open_questions: Feature comparison with Helicone, OpenLLMetry, Opik on specific dimensions

**LangKit** — guardrails, `WhyLabs`, confidence: low
> Monitors LLM application outputs for hallucinations, prompt injection, and compliance issues.
> community_note: Discussion centers on adding Azure OpenAI support and improving hallucination detection.
> open_questions: Azure OpenAI support status; accuracy of hallucination detection methodology

**LLM Guard** — guardrails, `ProtectAI`, confidence: med
> Provides input/output filtering and validation for LLM applications to prevent harmful content and prompt injection.
> community_note: Installation failures dominate discussion with xformers and torch build issues on macOS.
> open_questions: Installation challenges on different platforms; performance impact on inference

**OpenLLMetry** — observability, `Traceloop`, confidence: med
> Standardizes LLM observability signals through OpenTelemetry conventions and semantic attributes.
> community_note: Community views OpenLLMetry as a valuable standardization effort for LLM observability via OpenTelemetry.
> open_questions: Adoption rate among LLM platforms; practical ecosystem support breadth

**Opik** — observability, `Comet ML`, confidence: med
> Combines evaluation and observability capabilities for LLM applications with multi-model support.
> community_note: Discussion focuses on Opik's capabilities as an LLM evaluation and observability framework with multi-model support.
> open_questions: Market positioning relative to Langfuse and other observability platforms

**Portkey Gateway** — llm-gateway, `Portkey AI`, confidence: high
> Routes LLM requests across providers with load balancing, failover, and cost optimization.
> community_note: Enthusiastic launch reception; proven scale at launch.
> claimed_advantage: TypeScript-based gateway with production scale (3B tokens/day at launch).
> open_questions: Adoption by production applications

**promptfoo** — eval-tooling, `promptfoo`, confidence: med
> Provides testing infrastructure for prompt evaluation with support for multiple models and metrics.
> community_note: The small sample reflects tension between skepticism and pragmatism.
> open_questions: Specific differentiation from OpenAI Evals and LightEval; production adoption rates

**PromptTools** — prompt-tooling, `HegelAI`, confidence: med
> Provides testing infrastructure for prompt optimization with support for multiple LLM and embedding providers.
> community_note: Community appreciates multi-LLM and Vector DB support.
> open_questions: Market position relative to other prompt tools

**Rebuff** — ai-security, `ProtectAI`, confidence: low
> Detects and prevents prompt injection attacks on LLM applications.
> community_note: GitHub technical support threads provided; no Hacker News comments.
> open_questions: Effectiveness against advanced prompt injection techniques; false positive rates

---

## Deo 4 — čitanje, kratko

- **Observability je najgušći, najbolje dokumentovan sub-klaster** — 4 kompanije direktno povezane u grafu, sve sa realnim GitHub metrikama (6k–32k zvezdica). Zanimljiv detalj koji nije bio istaknut ranije: **Helicone kartica eksplicitno kaže "Currently in maintenance mode" + community_note beleži da korisnici traže zamenu** — to je signal za odliv ka Langfuse/Opik, ne za guardrails temu nego za observability wave specifično.
- **Dify/Flowise su već arrived** (150k/55k zvezdica) — dobri kao anchor za validaciju grafa, loši kao "next revolution" primer.
- **guardrails+ai-security (60 entiteta) je jači signal za "sledeću revoluciju"** od company-backed liste — mlađi, manje poznat, oblik konvergencije je jasniji (šest slojeva istog problema, nezavisno pronađenih).
- Sirovi izvor za sve iznad: `psql` upiti na `comprehension_cards`, `entity_semantic_edges`, `entity_metrics_daily` (dev baza, snapshot 12.08.2026).
