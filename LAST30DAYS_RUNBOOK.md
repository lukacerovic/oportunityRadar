# last30days — runbook

*Stanje na 2026-08-19. Sve u ovom fajlu je izmereno na ovoj mašini, ne prepisano
iz dokumentacije skila.*

Eksterni istraživački skill koji vadi diskusiju sa Reddit/HN/GitHub/TikTok/YouTube/
Digg/arXiv/Techmeme/Jobs za poslednjih 30 dana. Koristi se **ručno, za validaciju
nalaza iz baze** — nije kolektor i ne sme da uđe u `daily.sh`: video i društveni
sadržaj nema pouzdan `occurred_at` ni stabilan identitet, pa bi razbio invarijante
1 i 2 (`ARCHITECTURE.md`).

Čemu služi u praksi: Seismograph čita kanale *graditelja* (GitHub, HN, arXiv, HF).
Ovaj alat čita kanale *praktičara*. To su različite populacije i daju različitu
sliku — vidi §"Zašto ovo uopšte koristimo".

## Gde je instalirano

| stvar | putanja |
|---|---|
| skill | `~/.agents/skills/last30days` (symlink za Claude Code) |
| config / ključevi | `~/.config/last30days/.env` |
| Go CLI-jevi | `~/.local/bin/{arxiv,techmeme,digg,trustpilot}-pp-cli` |
| yt-dlp | `/opt/homebrew/bin/yt-dlp` |
| Go (potreban za 4 CLI-ja) | `/opt/homebrew/bin/go` (1.26.6) |
| sačuvani brifovi | `~/Documents/Last30Days/` (default `--save-dir`) |

## Kako se pokreće

**Koristi wrapper** — `scripts/l30d.sh`. On sam postavlja `--save-dir` i
serijalizuje pozive, pa dve najskuplje greške iz Pravila 1 i 6 ne mogu da se
ponove:

```bash
./scripts/l30d.sh "tema"                          # brif, automatski sačuvan
./scripts/l30d.sh --hiring "Ime Kompanije"        # samo jobs izvor
./scripts/l30d.sh --search reddit,hackernews "tema"
./scripts/l30d.sh --doctor                        # health check
./scripts/l30d.sh --library "upit"                # pretraga svih prošlih brifova
./scripts/l30d.sh --feed                          # index.html + feed.xml
```

Ako pokreneš drugi upit dok prvi radi, skript odbija umesto da obori Reddit.

<details><summary>Direktno, bez wrappera (ako baš treba)</summary>

```bash
cd ~/.agents/skills/last30days

# osnovni upit
python3 scripts/last30days.py "tema" --emit md --max-results 25

# health check — uvek ovo prvo ako nešto ne radi
python3 scripts/last30days.py doctor

# ograniči izvore (NE postoji --sources, vidi Pravilo 2)
python3 scripts/last30days.py "tema" --search reddit,hackernews,github

# hiring signals za jednu kompaniju (samo jobs izvor)
python3 scripts/last30days.py "Ime Kompanije" --hiring-signals --emit md

# uključi izvore koji se ne pale sami
python3 scripts/last30days.py "tema" --search threads,linkedin,pinterest
```

**Uvek dodaj `--save-dir`** — bez njega brif nestaje kad se obriše temp folder.
</details>

## Pravila naučena na teži način

**1. NIKAD ne pokretati više upita paralelno.** Tri paralelna upita su oborila
Reddit na HTTP 429 i dva od tri upita su vratila **nula** Reddit stavki. Zaključci
iz tog runa su bili pogrešni — vidi §"Zašto ovo uopšte koristimo". Sekvencijalno,
uvek.

**2. Flag je `--search`, ne `--sources`.** `--sources` ne postoji i skript puca sa
`unsupported Python CLI argument(s)`.

**3. Na ovoj mašini nema `timeout` komande** (zsh/macOS). Ne pisati
`timeout 900 python3 ...` — koristi background + `wait`, ili pusti da traje.

**4. `--hiring-signals` ignoriše ostale izvore.** Jobs-scoped je; ako hoćeš i
community sentiment u istom runu, moraš eksplicitno `--search reddit,x,jobs`.

**6. Bez `--save-dir` brif je izgubljen.** Prvih pet upita ove sesije je otišlo u
privremeni folder koji je obrisan — postoje samo kao tekst u prepisci. Wrapper
`scripts/l30d.sh` to rešava. Usput se gradi i `.last30days-library.db` (SQLite +
full-text), pa brifovi postaju vremenska serija koja se može porediti:
`./scripts/l30d.sh --library "prompt injection"`.

**5. ScrapeCreators backfill za Reddit se NE aktivira na delimičan rezultat.**
Pali se samo kad besplatni put vrati **potpuno prazno**. Zato i sa aktivnim ključem
i dalje dobijamo 422 posle ~12 stavki. Da backfill stvarno preuzme Reddit:
`LAST30DAYS_REDDIT_BACKEND=scrapecreators` ili `LAST30DAYS_REDDIT_SC_MIN_ITEMS=<n>`
u `~/.config/last30days/.env`.

## Ograničenja po izvoru

| izvor | ograničenje | dokle ide |
|---|---|---|
| **Reddit** | **najslabija karika** — HTTP 422/429 posle 8–12 stavki, svaki put | ~12 stavki/upit |
| Hacker News | bez ključa, bez kvote (Algolia) | ograničava samo `--max-results` |
| GitHub | 5.000 zahteva/h preko `gh` tokena | praktično neograničeno |
| TikTok | troši ScrapeCreators kvotu | od 10.000 poziva |
| YouTube | yt-dlp besplatan, može biti throttlovan; **video bez titlova nema transkript** bez Groq ključa | ScrapeCreators je rezerva |
| Digg / arXiv / Techmeme / Trustpilot | Go CLI, bez ključa | bez kvote |
| Jobs | besplatno, bez konfiguracije — ali kvalitet zavisi od ATS-a | vidi napomenu ispod |
| Polymarket | besplatno | rezultat samo ako postoji tržište (na naše teme: 0) |
| Instagram | radi od 2026-08-19 (ranije HTTP 404) | troši ScrapeCreators kvotu |
| Web | ne treba ključ — **host (Claude Code) služi web pretragu** | — |

**Napomena o `jobs`:** kvalitet je vrlo nejednak i zavisi isključivo od toga koji
ATS kompanija koristi.

| kompanija | ATS | rezultat |
|---|---|---|
| Langfuse | Ashby | 7 rola, tačni datumi, pun tekst oglasa |
| Helicone | Notion + Dover | 5 stavki, `date unknown`, `confidence: low` |

Bez `occurred_at` te stavke ne mogu ući u Seismograph po invarijanti 1. Pre nego
što se gradi pravi ATS kolektor (`DATA_SOURCE_OPTIONS.md` ga već ima na listi),
treba izmeriti kolika je pokrivenost standardnih ATS-ova u seed univerzumu.

## Status izvora (2026-08-19)

**Radi (12):** YouTube, Hacker News, Polymarket, GitHub, Digg, Techmeme, arXiv,
TikTok, Instagram, Bluesky, Jobs, library
**Delimično (2):** Reddit (pada na 422/429), Trustpilot (instaliran, nikad pokrenut)
**Pokvareno:** nijedan

**Otključano ali se ne pali samo** (ScrapeCreators ključ ih pokriva):
`threads`, `linkedin`, `pinterest` — treba `--search <ime>`.

**Još isključeno** — uputstva sa linkovima u §"Uključivanje preostalih izvora".

X je najveći preostali dobitak za nula dinara — jedini veliki kanal koji fali.

## Uključivanje preostalih izvora

⚠️ **Dve zamke u `.env` fajlu:**

1. **NIKAD ne prepisuj ga sa `>`** — samo `>>` (dupli redirect). Jedan `>` briše
   ScrapeCreators ključ i sve ostalo.
2. **Nema inline komentara.** Parser NE skida `# ...` sa kraja linije, nego ga
   uvuče u vrednost. `BSKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx  # format: ...`
   daje lozinku od 54 karaktera i HTTP 401. Komentar ide u **zasebnu liniju**.
3. **Skini `#` sa početka linije** kad upisuješ ključ — zakomentarisana linija se
   ignoriše i doctor ključ neće videti.

```bash
test -f ~/.config/last30days/.env && cat ~/.config/last30days/.env   # prvo pogledaj
echo 'KEY=value' >> ~/.config/last30days/.env                        # pa dodaj
```

### X / Twitter — besplatno, najveći dobitak

Četiri puta, od najlakšeg:

```bash
# 1) kolačići iz browsera — ne treba nikakav ključ, samo da si ulogovan na x.com
python3 ~/.agents/skills/last30days/scripts/last30days.py setup --allow-browser-cookies
```
Firefox radi na svim platformama, Safari se na macOS-u detektuje automatski.
Chrome/Brave/Edge/Arc/Vivaldi/Opera/Chromium na macOS-u traže `FROM_BROWSER=auto`
u `.env` (iskoči Keychain dijalog).

```bash
# 2) Grok CLI — besplatno ako imaš Grok nalog, ne treba X kredencijal uopšte
curl -fsSL https://x.ai/cli/install.sh | bash
grok login
```

3. `XAI_API_KEY` — ključ sa <https://api.x.ai> (plaća se)
4. `XQUIK_API_KEY` — ključ sa <https://xquik.com>

### Groq — besplatno, popravlja YouTube transkripte

Bez ovoga, video **bez titlova** nema transkript. Ključ: <https://console.groq.com>

```bash
echo 'GROQ_API_KEY=<tvoj-kljuc>' >> ~/.config/last30days/.env
```

### Bluesky — besplatno

App password (ne glavna lozinka): <https://bsky.app/settings/app-passwords>

```bash
echo 'BSKY_HANDLE=<tvoj-handle>.bsky.social' >> ~/.config/last30days/.env
echo 'BSKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx' >> ~/.config/last30days/.env
```

### Truth Social — besplatno

Uloguj se na <https://truthsocial.com> u browseru, pa isti setup kao za X:

```bash
python3 ~/.agents/skills/last30days/scripts/last30days.py setup --allow-browser-cookies
```

Alternativa: iskopiraj bearer token iz dev tools-a →
`echo 'TRUTHSOCIAL_TOKEN=<token>' >> ~/.config/last30days/.env`

### Xiaohongshu / RED — besplatno ali komplikovano

Traži **lokalni servis** koji vidi tvoju ulogovanu Xiaohongshu sesiju u browseru:
<https://github.com/xpzouying/xiaohongshu-mcp>

Skill sam probа `http://localhost:18060`, pa `http://host.docker.internal:18060`.
`XIAOHONGSHU_API_BASE` postavljaš **samo** ako servis radi na drugom hostu/portu.
Nikad se ne pali sam — treba `--search xhs` po runu, ili
`INCLUDE_SOURCES=xiaohongshu` trajno.

### Ostalo

| izvor | link / komanda | cena |
|---|---|---|
| Amazon (Bright Data) | `npm i -g @brightdata/cli && brightdata login` | 5.000/mes besplatno |
| Perplexity | <https://www.perplexity.ai/settings/api> → `PERPLEXITY_API_KEY` + `INCLUDE_SOURCES=perplexity` | plaća se |
| ScrapeCreators (već aktivan) | <https://scrapecreators.com> | 10.000 poziva besplatno |

Posle bilo koje izmene: `python3 scripts/last30days.py doctor` da potvrdiš da je
izvor prešao u ● WORKING.

Perplexity je **redundantan** dok se koristi iz Claude Code: doctor izričito kaže
`host-native web search active` — host već služi web pretragu. Perplexity bi dodao
engine-side pretragu koja radi otprilike isto, uz naplatu.

## Kvota ScrapeCreators

10.000 poziva besplatno, bez kartice, registrovano preko GitHub device flow-a
(`setup --github-start` → kod → `setup --github-poll`). Ključ je perzistiran
automatski u `~/.config/last30days/.env`, maskiran u ispisu. Pokriva TikTok,
Instagram, Threads, LinkedIn, Pinterest, Reddit backfill i YouTube fallback.

## Zašto ovo uopšte koristimo

Prvi run na temu agent-memory (samo HN + GitHub, Reddit oboren na 429) dao je
21 stavku i zaključak "gomila koda, skoro nikakva diskusija". Isti upit posle
instalacija (8 izvora) dao je **50 stavki**, i TikTok sam je imao 72.824 pregleda
na toj temi. Zaključak je bio pogrešan — bio je artefakt osakaćenog uzorka.

Pouka: **pokrivenost izvora određuje zaključak.** Isto važi i za sam Seismograph —
njegovi kolektori pokrivaju kanale graditelja, pa sistematski ne vide diskusiju
praktičara. Konkretno, ovim alatom su nađene tri stvari kojih u bazi nema:
ClickHouse akvizicija Langfusea, Tencent DB Agent Memory, i eval kompanije
arize/orqai/humanloop/fiddler.

---

*Skill je pri instalaciji označen kao "High Risk" (Gen, Snyk) zbog broja
kredencijala koje traži — 22 različita API ključa. Radi sa punim agent
permisijama. Trenutno mu je dat samo ScrapeCreators ključ dobijen preko GitHub
device flow-a; nijedan drugi kredencijal nije unet.*
