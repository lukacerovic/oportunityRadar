# Data Audit Report — Seismograph

*Generisano: 13. avgust 2026. Izvor: live Postgres `seismograph` baza.*

---

## 1. Inventar baze — šta smo scrapeovali

| Tabela | Broj redova | Šta predstavlja |
|---|---:|---|
| `raw_events` | 53,839 | Imutabilni događaji (repo snapshot, HN story, arXiv papir...) |
| `entities` | 49,236 | Trajni identiteti: 19,130 projekata, 20,886 osoba, 4,481 org, 4,174 papira |
| `entity_links` | 55,841 | Veza event → entitet |
| `momentum_states` | 1,208,757 | Dnevni momentum za svaki entitet |
| `comprehension_cards` | 12,363 | AI opisi entiteta |
| `entity_graph_edges` | 29,805 | Determinističke veze (built_by, cited, depends_on...) |
| `entity_semantic_edges` | 5,957 | LLM-razlučene veze (semantically_similar, conceptually_related) |
| `entity_community_research` | 8,502 | Community layer — GitHub/HN/HF istraživanje diskusija |
| `gate_decisions` | 2,650 | Ko je prošao significance gate (20 pass, 2,630 suppressed) |
| `impact_briefs` | 22 | Impact analize (svi draft) |
| `content_sanity_checks` | 3,339 | Kvalitet sadržaja (3,286 ok, 30 reject, 23 flagged) |
| `changes_daily` | 14,137 | Dnevni delta zapisi |

### Izvori podataka

| Izvor | Događaja | Tip signala | Vremenski opseg |
|---|---:|---|---|
| GitHub | 42,362 | participation (repo discovery + snapshots) | jan–avg 2026 |
| Hacker News | 4,599 | attention (stories) | feb–avg 2026 |
| arXiv | 3,683 | academic (papers) | jan–avg 2026 |
| Wikidata | 1,738 | identity (person→org veze) | enrichment batch |
| HuggingFace | 1,074 | usage (model snapshots) | jul–avg 2026 |
| OpenRouter | 42 | usage (token rankings) | jul 2026 |
| PyPI | 46 | usage (package metadata) | jul 2026 |

---

## 2. Šta je korisno — podaci koji imaju smisla

### ✅ Deterministički graf (29,805 ivica, 29,466 entiteta)

**Najvredniji deo baze.** Pokriva 17 tipova relacija:

| Tip veze | Broj | Šta govori |
|---|---:|---|
| `authored_by` | 19,295 | Ko je napisao koji kod/papir |
| `subsidiary_of` | 3,732 | Kompanijska struktura |
| `built_by` | 2,157 | Ko gradi koji projekat |
| `employed_by` | 1,264 | Gde ljudi rade |
| `educated_at` | 763 | Obrazovanje ključnih ljudi |
| `advised_by` | 648 | Mentorske veze |
| `produces` | 399 | Ko proizvodi koji proizvod |
| `founded` | 398 | Ko je osnovao šta |
| `cited` | 339 | Ko citira koji papir |
| `depends_on` | 83 | Zavisnosti između projekata |

Ovo je **upotrebljivo odmah** za analizu "ko stoji iza čega", "gde su ključni ljudi radili pre", "koji projekti zavise od kojih". Za grafički prikaz ekosistema i mapiranje uticaja — podaci su solidni.

### ✅ Community research (8,502 reda)

Izvor timestamp-ovanog teksta iz zajednice:
- GitHub diskusije/issues: 6,008
- Summaries: 1,261
- HN diskusije: 1,122
- HuggingFace: 111

Modeli: `deterministic` (7,240), `claude-haiku` (766), `ollama:qwen` (107). Ovo je gorivo za wave early-mention search — sistem može da traži ko je prvi pisao o nekom problemu pre nego što je trend detektovan.

### ✅ Semantičke veze (5,957 ivica, 4,790 entiteta)

| Confidence | Broj |
|---|---:|
| med | 4,706 |
| high | 746 |
| INFERRED | 276 |
| low | 222 |
| AMBIGUOUS | 7 |

Ove veze povezuju projekte koji rešavaju slične probleme ali se ne zovu isto i nemaju direktne dependency veze. Ključne su za wave detekciju — bez njih, clustering ne može da nađe konvergenciju.

### ✅ HN + arXiv signal

- **4,599 HN priča** (6 meseci) — attention signal, šta zajednica diskutuje
- **3,683 arXiv papira** — academic signal, šta se istražuje

### ✅ Comprehension kartice (12,363)

25% entiteta ima AI opis. Confidence distribucija je razumna: 73% low, 22% med, 5% high. Pokrivenost po kategorijama:

| Kategorija | Kartica | % kategorije |
|---|---:|---:|
| agent-framework | 2,400 | 45% |
| rag-framework | 1,339 | 49% |
| code-assistant | 487 | 50% |
| eval-tooling | 481 | 41% |
| model-efficiency | 362 | 39% |
| inference-runtime | 354 | 36% |

---

## 3. Šta NIJE korisno — problemi

### ❌ Momentum / track: nedovoljno podataka

Track je pokrenut samo **16 dana** u periodu od 32 dana (jul 11 → avg 5):

```
Jul: 11, 13, 14, 15, 16, 17, 18, 19, 20, 22, 24, 26*, 27, 28, 29
Avg: 5
```

Track dubina po repo-u:

| Track dana | Repo-a |
|---:|---:|
| 14-15 | 1,424 |
| 9-13 | 24 |
| 3-8 | 27 |
| 1-2 | 25 |

**1,475 repoa** ima 3+ dana track-a (minimum za velocity signal). Ali `--limit 1500` zamrzava set repoa — novootkriveni repo-ovi ne ulaze u track dok stari ne ispadnu. Svi top momentum entiteti imaju `score=1.000` — cold-start artifact, ne razlikuje signal od šuma.

### ❌ 47% entiteta su orphans (nema događaja)

| Event-ova | Entiteta | % |
|---:|---:|---:|
| 0 | 22,907 | 46.5% |
| 1 | 21,302 | 43.3% |
| 2-5 | 3,081 | 6.3% |
| 6+ | 1,888 | 3.8% |

Većina orphan-a su Wikidata `person` entiteti (16,272 od uncategorized 27,219). Postoje samo zato što su izvedeni iz graph edges-a, ali nemaju sopstvene event-ove.

### ❌ Entity spam inflira kategorije

Najbogatiji entiteti po broju event-ova su **hackathon projekti** od jednog vlasnika:

| Vlasnik | Projekata | Kategorija | Problem |
|---|---:|---|---|
| `hackindiaxyz` | 80 | agent-framework | Hackathon timovi, ne framework-i |
| `udotcash` | 114 | sdk-client | Crypto spam repos |
| `api-evangelist` | 96 | razne | Auto-generated API repos |
| `johnscheuer` | 58 | razne | Boilerplate repos |
| `alebrito124356` | 34 | razne | Bulk upload |
| `aidress-ai` | 43 | agent-framework | Veštački klon-ovi istog projekta |

Ovo inflira `agent-framework` (5,351 entiteta, najveća kategorija posle uncategorized) i zagađuje cohort-e za momentum scoring.

### ❌ Wave tabele ne postoje

Migracija `0013`/`0015` za wave tabele nije primenjena na bazu. `wave_clusters`, `wave_members`, `wave_observations`, `wave_outcomes` — **ne postoje**. Wave detekcija nikad nije pokrenuta protiv realnih podataka.

### ❌ Overclaiming na karticama

361 od 665 high-confidence kartica (54%) ima prazan `open_questions` i `evidence_breadth ≤ 1`. Ovo je mehanički detektabilno i identifikovano kao najviši prioritet u STATE.md od 28. jula — nepopravljeno.

### ❌ Maturity field je prazan na SVIM karticama

Svih 12,363 kartica ima `maturity = null`. Maturity ladder (idea_paper → ... → institutional_adoption) je centralni deo arhitekture ali se ne popunjava.

---

## 4. Zanimljivi entiteti i klasteri

### 4.1 Hub projekti — najpovezaniji u determinističkom grafu

Ovo su projekti oko kojih se vrti ceo ekosistem. Njihov graph neighborhood govori ko ih gradi, ko zavisi od njih, i koje papire citiraju.

| Projekat | Kategorija | Graph veza | Zanimljivo |
|---|---|---:|---|
| **LiteLLM** | llm-gateway | 20 | Gateway za 100+ LLM providera. Zavisi od njega: Mem0, Open WebUI, Chainlit. Ključna infrastrukturna tačka. |
| **LangChain** | agent-framework | 16 | Najpoznatiji agent framework. Gate-passed. Zavisnosti: OpenAI SDK, Anthropic SDK, Chroma. |
| **vLLM** | inference-runtime | 15 | High-throughput inference engine. Gate-passed. NVIDIA i Meta doprinose. |
| **Mem0** | memory-framework | 17 | Memorija za agenate. Zavisi od: Chroma, CrewAI, LangChain, LiteLLM, Sentence Transformers. **Hub zavisnosti** — 7 depends_on ivica. |
| **CrewAI** | agent-framework | 18 | Multi-agent orkestracija. Povezan sa Mem0, LiteLLM, i observability alatima. |
| **Guardrails AI** | guardrails | 14 | Validacija LLM output-a. Gate-passed. Deo "agent guardrail" trenda. |
| **browser-use** | agent-runtime | 13 | Browser automatizacija za agenate. Gate-passed. |
| **Aider** | code-assistant | 14 | AI pair programming u terminalu. Gate-passed. |
| **distilabel** | synthetic-data | 18 | Argilla-ov framework za sintetičke podatke. Gate-passed. |
| **Sentence Transformers** | embedding-model | 17 | Embedding modeli za RAG. Gate-passed. |

### 4.2 Mem0 — studija slučaja povezanosti

Mem0 je **najbolji primer hub entiteta** u bazi. Njegov deterministički graf:

```
Mem0
├── built_by: deshraj, sidmohanty11, taranjeet, kartik-mem0, ... (10 osoba)
├── depends_on:
│   ├── Chroma (vector-db)
│   ├── CrewAI (agent-framework)
│   ├── LangChain (agent-framework)
│   ├── LiteLLM (llm-gateway)
│   ├── OpenAI Python (sdk-client)
│   └── Sentence Transformers (embedding-model)
```

Ovo je kompletan stack za agent memoriju: embedding → vektor baza → LLM gateway → agent framework. Da imamo track podatke za sve ove zavisnosti, Mem0 bi bio idealan kandidat za wave/impact analizu — ako njegov stack raste, ceo klaster raste.

### 4.3 "Agent Guardrail" klaster — konvergencija koju sistem treba da detektuje

Ovo je klaster koji je dokumentovan u `AGENT_GUARDRAIL_WAVE.md` — nezavisni timovi koji grade alate za **kontrolu i verifikaciju AI agenata**:

| Projekat | Šta radi | Gate status |
|---|---|---|
| **Guardrails AI** | Validacija LLM output-a | ✅ Passed |
| **garak** (NVIDIA) | Vulnerability scanner za AI | ✅ Passed |
| **uipath/coder_eval** | Evaluiranje AI coding agenata | ✅ Passed |
| **hyperlogue/r3** | Code review za AI agenate | ✅ Passed |
| **termaxa/termaxa** | Shell command gate za agenate | ✅ Passed |
| **verbatimeter** | Deterministička tekst verifikacija | ✅ Passed |
| **video-db/open-record-replay** | Record/replay za agent akcije | ✅ Passed |

Ovo je **tačno tip konvergencije** koju Seismograph treba da detektuje kao wave: 7 nezavisnih timova, isti problem space, u kratkom vremenskom prozoru. Problem: wave tabele ne postoje, pa ovo nije formalno detektovano.

### 4.4 Semantički klasteri — gde su najgušće veze

**Unutar-kategorijske veze** (projekti u istoj kategoriji koji su semantički povezani):

| Kategorija | Veza | Unikatih projekata | Značenje |
|---|---:|---:|---|
| agent-framework | 1,307 | 941 | Ogroman prostor, mnogo varijacija |
| rag-framework | 1,005 | 750 | Drugi najgušći — RAG je zrelo polje |
| code-assistant | 248 | 185 | Aktivno polje sa mnogo klonova |
| eval-tooling | 185 | 134 | Evaluacija je vruća tema |
| inference-runtime | 131 | 87 | Manji ali gust klaster |

**Cross-category mostovi** (semantičke veze između različitih kategorija):

| Kategorija A | Kategorija B | Mostova | Značenje |
|---|---|---:|---|
| agent-framework | rag-framework | 68 | **Najjači most** — agenti koriste RAG kao memoriju |
| agent-framework | code-assistant | 37 | Coding agenti su podvrsta agent framework-a |
| agent-framework | workflow-orchestration | 31 | Agenti za orkestraciju radnih tokova |
| rag-framework | vector-db | 23 | RAG zavisi od vektorskih baza |
| agent-framework | memory-framework | 22 | Agenti sa persistentnom memorijom |
| agent-framework | eval-tooling | 16 | Evaluacija agenata (guardrail trend) |

Ovi mostovi su **najzanimljiviji signal u bazi**: govore nam koje kategorije se stapaju. Agent-framework + RAG + memory je **jedan ekosistem**, ne tri odvojena polja.

### 4.5 Mladi entiteti sa jakim semantičkim vezama

Entiteti stariji od <60 dana koji imaju neobično mnogo semantičkih veza — potencijalni trend indikatori:

| Projekat | Kategorija | Sem. veza | Šta je zanimljivo |
|---|---|---:|---|
| **hellothisworld/agent-skill-forge** | agent-framework | 79 | Skill marketplace za agenate — 79 semantičkih veza znači da ga LLM prepoznaje kao blizak desetinama drugih projekata |
| **slahnia/agentic-rag** | agent-framework | 54 | Spoj agent + RAG pristupa — tačno na najjačem cross-category mostu |
| **sovantica/engrava-mcp** | agent-framework | 39 | MCP (Model Context Protocol) implementacija — rastući standard |
| **maximskorohod/memohood-memobase** | agent-framework | 34 | Još jedan memory-framework — Mem0 klaster raste |
| **wanggang316/coloop** | workflow-orchestration | 41 | Workflow tool na crossroads-u agent + orchestration |

### 4.6 Najpovezaniji projekat u grafu: lucross-sensory-grounding-mcp

`luclinocruz/lucross-sensory-grounding-mcp` ima **75 determinističkih ivica** — najviše od bilo kog projekta. Citira 20+ arXiv papira (1706.03741 = Attention Is All You Need, 2303.11366 = GPT-4 Technical Report...) i ima `authored_by` veze. Ovo je MCP implementacija za sensory grounding agenata — povezuje foundational AI research sa praktičnom agent implementacijom.

---

## 5. Zaključak: da li podaci imaju smisla?

### Odgovor: Da, ali selektivno.

| Sloj | Korisno? | Ocena |
|---|---|---|
| **Deterministički graf** | ✅ Apsolutno | Najjači deo baze. Ko stoji iza čega, ko gradi šta, ko citira koga — upotrebljivo za analizu ekosistema odmah. |
| **Community research** | ✅ Da | 8,502 timestamp-ovanih zapisa iz zajednice. Gorivo za early-mention search. |
| **Comprehension kartice** | ⚠️ Delimično | 12,363 opisa je korisno za pregled, ali 361 overclaiming kartica + prazan maturity umanjuju pouzdanost. |
| **Semantičke veze** | ⚠️ Delimično | 5,957 veza povezuje 4,790 entiteta. Dovoljno za grube klastere, premalo za wave detekciju (treba 4 nezavisna entiteta povezana). |
| **HN + arXiv signali** | ✅ Da | 8,282 event-ova za attention + academic signal. |
| **Track / momentum** | ❌ Ne | 16 dana track-a u 32 dana, 1,475 repoa sa 3+ dana. Momentum score je besmislen (svi = 1.0). |
| **Wave detekcija** | ❌ Ne | Tabele ne postoje u bazi. Nikad nije pokrenuta. |
| **Gate** | ⚠️ Delimično | Propušta razumne entitete (LangChain, vLLM, Aider), ali score ne razlikuje kvalitet. |

### Šta je vredno a šta ne

**Vredno i odmah upotrebljivo:**
- Graf ekosistema — ko koga gradi, ko od koga zavisi, ko gde radi
- "Agent guardrail" klaster — 7 nezavisnih timova na istom problemu
- Cross-category mostovi — agent↔RAG↔memory je jedan ekosistem
- Community research tekst — šta zajednica diskutuje i kada

**Neupotrebljivo bez dodatnog rada:**
- Momentum ranking — track je previše redak
- Wave detekcija — tabele nisu ni migrirane
- Maturity ladder — maturity field je prazan svuda
- Brief quality — svi draft, niko nije review-ovao

### Tri najveća problema koja blokiraju cilj proizvoda

1. **Track frekvencija** — momentum je srce sistema, a 16 od 32 dana bez track-a znači da srce preskače. Bez dnevnog `daily.sh`, ništa ostalo ne radi.

2. **Wave infra ne postoji** — proizvodi se prodaje kao wave detector, ali wave tabele nisu u bazi. Kao da imaš automobil bez motora.

3. **Entity noise** — hackathon projekti, crypto spam i auto-generated repos čine ~5% baze ali infliraju kategorije (posebno `agent-framework` sa 5,351 entiteta, gde su mnogi hackathon timovi).

---

*Ovaj izveštaj je generisan automatski iz live baze. Brojevi se menjaju sa svakim `daily.sh` pokretanjem.*
