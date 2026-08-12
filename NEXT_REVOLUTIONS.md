# Sledeće revolucije — čitanje `ENRICHMENT_REPORT.md`

*2026-08-12. Analiza klastera iz §4 enrichment izveštaja, sa detaljima izvučenim
direktno iz baze (opisi entiteta, kategorije, metrike) jer sam izveštaj nabraja
imena bez objašnjenja šta svaki projekat radi.*

---

## Glavni nalaz: ovo je jedna revolucija, ne više njih

`guardrails` (29 članova) i `ai-security` (31 član) iz §4 nisu dve teme —
to je **jedna tema koju je hairball (§5c) mehanički presekao na dva klastera**.
Zajedno: ~60 entiteta, skoro svi mlađi od 45 dana.

Postoji i drugi, slabiji klaster: `structured-output` (43 člana, 42 mlada).

## Teza u jednoj rečenici

Prompt prestaje da bude mesto gde se kontroliše ponašanje agenta. Šezdesetak
nezavisnih ljudi je u istih mesec i po dana nezavisno zaključilo isto:
**instrukcija agentu nije garancija — garancija je deterministički enforcement
izvan modela** (u hooku, u proxy-ju, u kernelu, u policy engine-u).

Ovo je direktan nastavak `AGENT_GUARDRAIL_WAVE.md` od 28.07.2026 — tada 5
entiteta oko iste ideje, sad 60.

---

## Šest slojeva gde se agent presreće

Kad se pročita šta svaki projekat stvarno radi, klaster se raspada na šest
različitih mesta u lancu izvršenja. Ne kopiraju jedni druge — napadaju isti
problem sa različitih visina.

### 1. Presretanje tool-call-a pre izvršenja (najgušće naseljeno)

| projekat | šta radi |
|---|---|
| `othy19904-eng/agent-action-guard` | proverava predloženu akciju protiv policy pravila pre izvršenja, deterministički |
| `srinu16it/llm-tool-host` | presreće tool pozive, validira semantiku protiv deklarisane šeme, blokira neslaganja |
| `amurlaniakea/agent-shield-runtime` | omotava runtime, provlači svaki poziv kroz pet senzora (scope, shield, wallet-guard, goal) |
| `dicklesworthstone/destructive_command_guard` | blokira destruktivne shell/git operacije |
| `yvoolab/claude-code-safety-hooks` | isto, kroz Claude Code `PreToolUse` hook |
| `pamiray-m/wace-light` | kontrolisano komandno okruženje sa PII redakcijom i audit trailom |

### 2. Kernel/mrežni sloj — presretanje ispod aplikacije

| projekat | šta radi |
|---|---|
| `itsventie/ebpf-llm-firewall` | eBPF firewall koji hvata LLM API saobraćaj u kernelu, protiv injectiona i exfiltracije |
| `jyswee/a2a-trustgate` | compliance firewall za agent-to-agent akcije |
| `pk0559505-cloud/securerag` | RBAC na RAG pozivima |

### 3. Supply chain agentovih komponenti (nov ugao, nije postojao pre MCP-a)

| projekat | šta radi |
|---|---|
| `eltociear/mcp-audit` | skenira MCP servere i opise alata za prompt-injection markere, exfil kredencijala, download-and-execute |
| `amurlaniakea/skill-auditor` | statička analiza skill YAML/JSON fajlova |
| `2607.11086` (akademski rad) | empirijska studija sigurnosti MCP servera u produkciji |

### 4. Red-team / testiranje odbrane

| projekat | šta radi |
|---|---|
| `shimiyahya/prompt-injection-redteam` | generiše deterministički pass/fail test matriks |
| `krishna89287/prompt-injection-detector` | analizira tekst za prompt-injection obrasce, vraća risk score |
| `jleonceo/guardianes-verificados-ia` | testira guardrails izazivajući namerne otkaze |
| `garak` (NVIDIA), `PyRIT` (Microsoft), `PurpleLlama` (Meta) | etablirana sidra klastera — svi su ušli u klaster **preko** novih repoa, ne obratno |

### 5. Prevođenje mekih instrukcija u tvrda pravila (konceptualno najzanimljivije)

| projekat | šta radi |
|---|---|
| `singh38600-svg/hardline` | parsira ograničenja pisana prirodnim jezikom u izvršna guard pravila |
| `adekka-canada/actionspecs` | standardizovan handshake za agent-inicirane operacije (policy + audit + ljudsko odobrenje) |
| `theo-ai-lab/farthing` | deterministički policy engine računa iznos refunda, čovek odobrava, Temporal garantuje exactly-once |

### 6. Grounding / verifikacija tvrdnji

| projekat | šta radi |
|---|---|
| `erikolson/grounding-harness` | vadi citate iz outputa, validira protiv izvora, briše netragabilne tvrdnje pre nego što izađu |
| `flyingfredcurry/faithful-cite` | isto, iz `structured-output` klastera |

---

## Drugi klaster: `structured-output` (43 člana, slabiji)

Nema jedinstvenu tezu kao guardrails/ai-security. Kvalitetni primeri:

- `ricardocabral/ajq` — semantički jq nad JSON/NDJSON streamovima (LLM upiti umesto sintaksičkih putanja); aktivan razvoj (tikceti TP-071 do TP-078: windowed batching, concurrency, streaming)
- `cognizenorg/compatcanary` — conformance testovi: da li OpenAI-kompatibilni API-ji stvarno rade streaming i tool-calling

Ali `olehdatsyk/ocr-reader` je obična OCR biblioteka bez veze sa temom —
naracija ovde je slabija: "svi grade infrastrukturu za pouzdan output", ne
oštra teza kao guardrails klaster.

---

## Šta ovo NIJE — pre nego što se poveruje

### Nema dokazane adopcije

| projekat | gh_stars | evidence_breadth |
|---|---:|---:|
| `garak` (sidro) | 8.704 | 2 |
| `ricardocabral/ajq` | 3 | 1 |
| `singh38600-svg/hardline` | 1 | 1 |
| `ebpf-llm-firewall`, `mcp-audit`, `llm-tool-host`, `actionspecs`, `grounding-harness` | *nema podataka* | 1 |

`evidence_breadth = 1` znači jedan izvor, nula nezavisne potvrde. Ovo su repoi
stari nekoliko nedelja bez ikakve adopcije. Sistem radi ono za šta je
napravljen — hvata konvergenciju pre nego što bilo ko primeti — ali
"revolucija" ovde znači **konvergencija namere**, ne dokazana tehnologija.
Većina ovih repoa verovatno neće postojati do kraja godine. Signal je oblik
u kom se slažu, ne pojedinačni projekat.

### Merljiva kontaminacija klastera (~4 od 60, u skladu sa §5d)

| projekat | problem |
|---|---|
| `jvbotelho/skewrun` | popravlja Kerberos clock skew u Windows domenima — nema veze sa AI |
| `xmahdi1/wisp` | enkriptovani messaging — nema veze sa temom |
| `elementmerc/senbonzakura` | **skida** guardrails sa modela — suprotan predznak, isti vektor |
| `giosh-me/venture-validator` | `function: "business-brainstorming"` — čista greška kategorizacije |

Prag na semantičke ivice (≥0,7) iz §7.2 verovatno rešava većinu ovoga.

### Provera vlasnika je obavezna

`amurlaniakea` se pojavljuje dva puta u klasteru (`agent-shield-runtime`,
`skill-auditor`) — mora proći kroz proveru shared-GitHub-owner iz §5d pre
nego što se broji kao dva nezavisna signala.

---

## Preporuka

1. Spoji `guardrails` + `ai-security` u jedan kandidat-klaster (60 entiteta) — hairball ih je veštački razdvojio.
2. Ručno izbaci 4 kontaminanta identifikovana gore.
3. Pusti spojeni, očišćeni klaster kroz wave detektor kao prvi test na stvarnim podacima (mašinerija je testirana 26/26 po §7.4).
4. Ne prezentuj ovo kao "60 dokazanih projekata" — prezentuj kao "60 nezavisnih pokušaja u istom razmaku od 45 dana", što je i jače i tačnije.
