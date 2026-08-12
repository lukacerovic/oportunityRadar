# Šta smo videli kad smo kartirali 10.380 entiteta

*2026-08-12. Sve brojke su merene na dev bazi u trenutku pisanja, ne procenjene.
Prolaz je bio na 85% (350/411 batch-eva) kad je izveštaj napisan — ostatak je i dalje tekao.*

---

## 1. Šta je urađeno

Pustili smo Haiku agente preko backlog-a entiteta koji su ili **mladi** (prvi put viđeni u
poslednjih 30 dana) ili imaju **realan rast** (momentum stanje ≠ `dormant`, bilo koje starosti).
Svaki agent je za svojih 30 entiteta čitao pravi evidence pack, čitao community sloj, pisao karticu,
i tražio veze ka već kartiranim entitetima iste kategorije.

| | pre | posle |
|---|---:|---:|
| comprehension_cards | 1.713 | **12.093** |
| entity_semantic_edges | 283 | **5.758** |
| pokrivenost entiteta karticom | 3,4% | **21,2%** |

Semantički sloj je narastao **20×**. To je bio glavni blocker za wave detekciju — sa 283 ivice na
48.947 entiteta "slično" praktično nije postojalo.

## 2. Kvalitet — Haiku je ispao konzervativniji od svega pre njega

`STATE.md` je označio 671 qwen-kartica kao rizik: model je pisao `confidence: high` sa praznim
`open_questions`, prepričavajući vendorove tvrdnje kao činjenice. Isti mehanički test na novom setu:

| model | kartica | `confidence: high` | ima `open_questions` | bogato `function` polje |
|---|---:|---:|---:|---:|
| **claude-agent-batch:haiku** | 10.380 | **1,8%** | **99,9%** | 100% |
| ollama:qwen2.5:7b | 40 | 90,0% | 92,5% | 97,5% |
| ollama:qwen2.5:3b | 1.625 | 23,3% | 58,9% | 93,9% |
| ollama:llama3.2 | 47 | 87,2% | 14,9% | 63,8% |

**1,8% naspram 23,3%.** Od 10.380 kartica samo 187 tvrdi visoku pouzdanost. Ostalih 10.193 eksplicitno
piše šta dokazi *ne* utvrđuju.

Najčešće priznate rupe, agregirano preko svih kartica:

```
55  maintenance status          49  performance overhead
53  production readiness        47  production deployment examples
50  community adoption          41  feature completeness / performance at scale
```

Ovo je tačno ono što sistem treba da radi — ne "ovaj repo je odličan", nego "ovo tvrdi, ovo nije dokazano".

## 3. Community sloj je promenio ono što kartica kaže

**2.324 kartice (22%) nose `community_note`** — sintezu onoga što ljudi stvarno govore, odvojeno od
onoga što projekat tvrdi o sebi. Razlika je vidljiva golim okom:

> **Ollama** — *"Strong praise for ease of use and API design; significant frustration that Vulkan PR
> pending 6+ months."*

> **Text Generation Inference** — *"Community discussion focused on licensing changes (now Apache 2.0);
> ARM64 not supported due to compiled inference stack."*

> **MLX** — *"Positive reception for PyTorch-like API and unified memory architecture; C++20 language
> features block some builds."*

> **Kubeflow** — *"Active installation/deployment failures with kfctl tooling in v0.7.1."*

Nijedan README ne piše "Vulkan PR stoji 6 meseci" ni "kfctl puca". To se vidi samo iz diskusije,
i to je jedini sloj koji razlikuje *tvrđenu* od *stvarne* upotrebljivosti.

## 4. Glavni nalaz — klasteri koji izgledaju tačno kao teza proizvoda

Semantički graf ima **190 komponenti**; jedna je hairball od 3.468 čvorova (o tome u §5), ali
**36 komponenti ima 5–60 članova** i one su koherentne. Presudno: **31 klaster sadrži ≥3 entiteta
mlađa od 45 dana**, a nekoliko ih meša potpuno nove repoe sa etabliranim sidrima u istom prostoru.

**`structured-output` — 43 člana, 42 mlađa od 45 dana**

Sidra: `Outlines`, `Guidance`. Novi ulazi: `ricardocabral/ajq` (jq-like stream procesor za semantičko
izvlačenje), `cognizenorg/compatcanary` (testira da li OpenAI-kompatibilni API-ji stvarno rade
streaming i tool-calling), `flyingfredcurry/faithful-cite`, `olehdatsyk/ocr-reader`.

**`ai-security` — 31 član, svi mlađi od 45 dana, nula etabliranih**

Sidra po imenu poznata: `garak` (NVIDIA), `PyRIT` (Microsoft), `PurpleLlama` (Meta) — ali **svi su
ušli u klaster preko novih repoa**, ne obratno. Novi: `itsventie/ebpf-llm-firewall` (eBPF firewall
protiv prompt injectiona), `eltociear/mcp-audit`, `xmahdi1/wisp`, `jvbotelho/skewrun`, plus dva
akademska rada (`VulnGym`, `Bridging the Epistemic Gap`).

**`guardrails` — 29 članova, svih 29 mlađih od 45 dana**

`Guardrails AI` i `nvidia-nemo/guardrails` kao sidra, a oko njih: `singh38600-svg/hardline`
(pretvara meke instrukcije agentu u tvrda runtime pravila), `dicklesworthstone/destructive_command_guard`,
`yvoolab/claude-code-safety-hooks`, `othy19904-eng/agent-action-guard`,
`shimiyahya/prompt-injection-redteam`.

Ovo je direktan nastavak nalaza iz `AGENT_GUARDRAIL_WAVE.md` od 2026-07-28 — tada je bilo 5 gate-passed
entiteta oko iste ideje. Sada ih je **29 u jednom klasteru plus 31 u `ai-security`**, uglavnom
nezavisnih i skoro svi noviji od 45 dana. Isti oblik, red veličine više dokaza.

**Kategorije se prelivaju, i to konzistentno**

Veze koje spajaju dve različite kategorije nisu šum — imaju jasan smer:

```
61  agent-framework → rag-framework        26  agent-framework → workflow-orchestration
40  agent-framework → code-assistant       25  rag-framework   → vector-db
15  model-foundation → multimodal-model    11  memory-framework → agent-framework
```

`agent-framework` je čvorište kroz koje sve prolazi. To nije bila pretpostavka — to je ispalo iz
podataka.

## 5. Problemi koje smo našli, iskreno

Prolaz je otkrio četiri stvari koje treba popraviti pre nego što se ovome veruje bez ograde.

**(a) 17% kartiranog nije softver.** Moj filter je pustio Wikidata entitete kroz:

| tip | kartica |
|---|---:|
| project | 7.856 |
| **org** | **995** |
| paper | 717 |
| **person** | **439** |
| **work** | **303** |
| model / product | 70 |

Rezultat: `Elon Musk`, `Sam Altman`, `Ilya Sutskever`, `Fidelity Investments` imaju comprehension
kartice sa `maturity_stage`. Model je bio pošten koliko je mogao — svi su `confidence: low` sa
`who_is_behind: "not established by evidence"` — ali kartica za osobu nema smisla. **Filter mora da
uslovi `entity_type IN ('project','model','paper','product')`.**

**(b) `institutional_adoption` je naduvan.** 964 softverska entiteta su ocenjena iznad `distribution`,
iako `ARCHITECTURE.md` eksplicitno kaže da v1 staje na `distribution` dok jobs i pricing kolektori ne
postoje. Model nema dokaz za tu rung — nagađa je. Ovo je isti tip greške kao qwen overclaiming, samo
u drugom polju.

**(c) Hairball.** 3.468 od 4.342 čvora su u jednoj komponenti. `conceptually_related_to`
(prosečan skor 0,62) je prelabav i spaja sve sa svime. `semantically_similar_to` (0,65) je bolji.
**Za wave detekciju treba prag** — verovatno samo ivice ≥0,7, ili samo `semantically_similar_to`.

**(d) 9% klastera nije prava konvergencija.** Tri od 33 klastera padaju na proveri nezavisnosti:

```
6 od 6 clanova → 'aidress-ai'      (dva puta, dva odvojena klastera)
5 od 18 clanova → 'udotcash'       (nostr-, telegram-, twitch-, whatsapp-, reddit-ucashpay)
```

Jedan čovek koji objavi pet varijanti istog projekta izgleda identično kao pet nezavisnih ljudi koji
rešavaju isti problem — **osim ako se proveri vlasnik**. Wave detektor već ima ovu proveru
(`shared GitHub owner`) i ona radi; ovaj nalaz je potvrda da je bila neophodna, ne opciona.

## 6. Šta je sad otključano

Pre ovog prolaza wave detekcija je bila teoretski funkcionalna ali praktično prazna — 283 ivice ne
mogu da naprave klaster. Sada:

- **36 kandidat-klastera** veličine 5–60, od kojih **31 ima ≥3 mlada člana**
- Nakon uklanjanja tri kontaminirana: **~28 klastera vredna prolaska kroz wave detektor**
- `guardrails` + `ai-security` (60 entiteta ukupno) su najjači kandidat — nastavak već dokumentovanog
  trenda sa 12× više materijala

## 7. Redosled popravki, po ceni

1. **Filtriraj `entity_type`** pri sledećem prolazu — jedan `WHERE`, briše 1.737 besmislenih kartica.
2. **Prag na semantičke ivice** pre wave detekcije — jedan broj u upitu, razbija hairball.
3. **Ograniči `maturity_stage` na `distribution`** dok jobs/pricing ne postoje — validator u kontraktu.
4. **Pusti wave detektor preko 28 čistih klastera** — sve mašinerije već postoje i testirane su (26/26).
5. Kad prolaz završi 100%, ponovo finalizuj (`finalize_comprehend_batch.py` je idempotentan).

---

*Skripta za finalizaciju: `scratchpad/finalize_comprehend_batch.py`. Sve kartice nose
`model='claude-agent-batch:haiku'` pa se ceo set može izolovati, revidirati ili obrisati jednim upitom.*
