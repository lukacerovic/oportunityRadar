# Šta se dešava u projektu — pregled za Luku

*Pisano 2026-08-19. Sve brojke su merene na dev bazi i na ovoj mašini, nijedna
nije procenjena. Gde nešto nije dokazano, tako i piše.*

## Ukratko

Prošli smo kroz tri faze: (1) obogatili smo bazu sa 10.650 novih kartica i 20×
većim semantičkim slojem, (2) iz tog sloja izvukli tri klastera koji liče na
prave talase, i (3) otkrili da sistem meri samo **jednu stranu tržišta** — pa
smo dodali spoljni alat da izmerimo drugu. Ta treća stvar je najvažnija i o njoj
je najveći deo ovog dokumenta.

---

## 1. Odakle je krenulo — enrichment prolaz

Pustili smo Haiku agente preko backloga entiteta koji su mladi ili imaju realan
rast. Rezultat (detaljno u `ENRICHMENT_REPORT.md`):

| | pre | posle |
|---|---:|---:|
| comprehension_cards | 1.713 | **12.093** |
| entity_semantic_edges | 283 | **5.758** |
| pokrivenost karticom | 3,4% | **21,2%** |

Bitno: Haiku je ispao **konzervativniji** od svih modela pre njega. Samo 1,8%
kartica tvrdi `confidence: high` (qwen2.5:3b je tvrdio 23,3%), a 99,9% kartica
eksplicitno piše šta dokazi *ne* utvrđuju. To je tačno ono što želimo — ne "ovaj
repo je odličan", nego "ovo tvrdi, ovo nije dokazano".

## 2. Šta smo našli — tri talasa umesto jednog

Semantički sloj je konačno bio dovoljno gust da se vide klasteri. Našli smo tri:

| klaster | entiteta | anchor | kako smo ga našli |
|---|---:|---|---|
| guardrails + ai-security | 60 | Guardrails AI, garak, PyRIT | wave logika (mladi klaster u praznom prostoru) |
| **agent-memory** | 24 | Mem0 | 1-hop susedstvo oko starog anchora |
| **llm-gateway** | 20 | LiteLLM | isto |

Prvi je nastavak nalaza iz `AGENT_GUARDRAIL_WAVE.md` od 28.07 — tada 5 entiteta,
sada 60. Teza: **instrukcija agentu nije garancija; garancija je deterministički
enforcement izvan modela** (hook, proxy, kernel, policy engine). Detaljno u
`NEXT_REVOLUTIONS.md`.

Druga dva su **nov nalaz** i otkrivaju slepu tačku: wave detektor traži mlade
klastere u *praznom* prostoru, pa klastere koji se formiraju **oko etabliranog
sidra** uopšte ne vidi. Mem0 i LiteLLM su stari i veliki, njihovi sateliti su
bili van filtera. Detaljno u `MEMORY_GATEWAY_WAVES.md`.

Postoje dakle dva oblika konvergencije:
- **oko praznine** — niko ne rešava problem, pojavi se 30 ljudi odjednom
- **oko sidra** — neko je rešio 80%, pojavi se 20 ljudi koji krpe ostalih 20%

Drugi oblik je komercijalno zanimljiviji jer potražnja već postoji i dokazana je.

## 3. Glavni problem: merimo ponudu, ne potražnju

Ovo je najvrednija stvar iz cele sesije i nije ni graf ni klaster.

Seismograph čita GitHub, HN, arXiv, HuggingFace. Sve su to kanali **graditelja**.
Sistem odgovara na pitanje "koliko ljudi gradi X". Nikad ne odgovara na "koliko
ljudi *traži* X".

Kad smo doveli drugi izvor podataka, ispalo je da se te dve ose ne poklapaju:

| talas | ponuda (naša baza) | potražnja (zajednica) | faza |
|---|---|---|---|
| gateway | 20 repoa oko LiteLLM | isto pitanje na 4 subreddita, "svaki tim krpi svoj nginx config" | artikulisan bol |
| observability | 5 zrelih firmi, 32k zvezdica | tri "Ask HN: kako se ovo uopšte radi?" u dve nedelje | zreli alati, nezrela praksa |
| memory | 24 repoa oko Mem0 | diskusija postoji, ali na TikToku/YouTubeu, ne na HN-u | druga populacija |

Sva tri u grafu izgledaju identično. Ali jedan ima kupce koji viču, jedan ima
zbunjene praktičare, a jedan ima publiku koju uopšte ne gledamo. **To je razlika
između prilike i mode**, i sistem je trenutno ne vidi.

## 4. Alat koji smo dodali — `last30days`

Instalirali smo eksterni skill koji vadi diskusiju iz poslednjih 30 dana sa
Reddit / HN / GitHub / TikTok / YouTube / Digg / arXiv / Techmeme / Jobs.

**Ovo NIJE kolektor i ne sme da uđe u `daily.sh`.** Video i društveni sadržaj
nema pouzdan `occurred_at` ni stabilan identitet — razbio bi invarijante 1 i 2.
Koristi se **ručno, za validaciju** onoga što baza već tvrdi.

Kompletno uputstvo, ograničenja po izvoru i podešavanje: `LAST30DAYS_RUNBOOK.md`.

Trenutno radi 9 izvora + Bluesky i Groq tek dodati. Najveće ograničenje je
Reddit — puca na HTTP 422/429 posle 8–12 stavki, svaki put.

## 5. Šta je alat našao a baza nema

Tri konkretne stvari koje sistem ne bi otkrio sam:

1. **Langfuse je kupljen od strane ClickHouse.** Piše doslovno u njihovom oglasu
   za posao: *"We are now part of ClickHouse."* U našoj bazi Langfuse je i dalje
   zaveden kao nezavisna firma i anchor observability klastera. Struktura oglasa
   to potvrđuje — zapošljavaju Product Marketing i DevRel, dakle go-to-market
   faza, ne inženjerska ekspanzija.

2. **Tencent DB Agent Memory** — Tencent je 09.08. otvorio kod lokalnog memory
   sistema za agente. Ulazak velikog igrača = konsolidacioni signal za taj
   klaster. Kod nas ga nema uopšte.

3. **arize, orqai, humanloop, fiddler** — četiri eval/governance firme koje neko
   na r/AI_Governance nabraja tražeći platformu sa pravim governance-om
   (verzionisanje, odobrenja, audit trail). Od tih pet imena samo je **WhyLabs**
   u našoj bazi.

Plus jedna nezavisna potvrda naše teze, rečima praktičara a ne našom analizom —
naslov posta na r/LLMDevs: *"LLM guardrails written as prompt rules don't hold up
in production"*, i najbolji komentar: *"a prompt rule saying 'verify before you
report done' fails exactly when verification is hardest"*.

## 6. Greška koju smo napravili i ispravili

Vredi zapisati jer je poučna.

Prvi put smo pustili tri upita **paralelno**. Reddit je odgovorio sa HTTP 429 i
dva od tri upita su vratila **nula** Reddit stavki. Na osnovu tog osakaćenog
uzorka zaključili smo da memory talas "ima gomilu koda a skoro nikakvu diskusiju".

Kad smo instalirali ostale izvore i pustili isti upit sekvencijalno: **50 stavki
umesto 21**, a TikTok sam je imao 72.824 pregleda na toj temi. Zaključak je bio
potpuno pogrešan — bio je artefakt pokrivenosti, ne stvarnosti.

**Pouka: pokrivenost izvora određuje zaključak.** To važi i za sam Seismograph.

## 7. Šta ovo znači za sistem

Tri konkretne stvari koje treba razmotriti:

1. **Wave detektor ima slepu tačku.** Ne vidi klastere oko etabliranih sidara.
   Mem0 (24) i LiteLLM (20) su iste veličine kao guardrails talas koji jeste
   video. Popravka nije velika: pustiti detekciju i na susedstva starih anchora.

2. **`SOURCE_EXPANSION.md` treba da razlikuje *vrstu* izvora, ne samo da ih
   broji.** Signal ponude i signal potražnje dolaze iz različitih populacija.
   Dodavanje još jednog builder-kanala ne popravlja slepu tačku.

3. **`jobs` izvor rešava blokadu na lestvici zrelosti** — ali samo delimično.
   `ARCHITECTURE.md` kaže da v1 staje na `distribution` jer jobs/pricing
   kolektori ne postoje, a `ENRICHMENT_REPORT §5b` je našao 964 entiteta sa
   naduvanim `institutional_adoption`. Ovaj alat čita ATS oglase besplatno.
   **Ali kvalitet zavisi od ATS-a:**

   | firma | ATS | rezultat |
   |---|---|---|
   | Langfuse | Ashby | 7 rola, tačni datumi, pun tekst |
   | Helicone | Notion + Dover | 5 stavki, `date unknown`, `confidence: low` |

   Bez `occurred_at` ne može u sistem po invarijanti 1. Pre gradnje pravog
   kolektora treba izmeriti koliko firmi iz seed univerzuma uopšte koristi
   standardni ATS.

## 8. Gde je šta

| fajl | šta sadrži |
|---|---|
| `ENRICHMENT_REPORT.md` | Haiku prolaz — brojke, kvalitet, nađeni problemi |
| `NEXT_REVOLUTIONS.md` | guardrails talas, 60 entiteta, šest slojeva presretanja |
| `MEMORY_GATEWAY_WAVES.md` | memory (24) i gateway (20) klasteri, pun spisak članova |
| `LUKA_DATA_DUMP.md` | 12 company-backed repoa sa karticama i metrikama |
| `LAST30DAYS_RUNBOOK.md` | kako se pokreće alat, ograničenja, podešavanje |
| `graphify-out/GRAPH_REPORT.md` | knowledge graph celog repoa (3.794 čvora) |

## 9. Šta NIJE urađeno / otvoreno

- **Migracije 0013 se sudaraju.** Postoje dve različite `0013` — `0013_waves.py`
  (wave tabele) i `0013_graph_explanations.py`. Dev baza je migrirana preko druge,
  pa `wave_clusters` fizički **ne postoji** i `/waves` ekran puca sa
  `UndefinedTable`. Treba odlučiti kako se to spaja.
- Nalazi iz ovog dokumenta nisu upisani u bazu — žive samo kao `.md` fajlovi.
- `dependabot[bot]` je zaveden kao `entity_type='person'` sa 58 `built_by` grana.
  Kolektor ne proverava `type == "Bot"` iz GitHub API-ja.
- Ostale popravke iz `ENRICHMENT_REPORT §7` i dalje stoje.
