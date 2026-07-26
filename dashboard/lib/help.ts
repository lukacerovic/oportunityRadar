// Per-page "what am I looking at?" content, rendered by <InfoButton> (components/InfoModal.tsx).
// Plain serialisable data so server components can import it and hand it to the client modal.
// Each page explains what every value means and — in `analyse` — how to actually read it.

export type HelpRow = { term: string; desc: string };
export type HelpSection = { title?: string; rows: HelpRow[] };
export type HelpContent = {
  title: string;
  intro?: string;
  sections: HelpSection[];
  analyse?: string[];
};

const MOMENTUM_STATES: HelpRow[] = [
  {
    term: "Breakout",
    desc: "The hottest state — velocity, corroboration breadth, and maturity promotions are all firing at once. Rare and the strongest signal.",
  },
  {
    term: "Accelerating",
    desc: "Sustained upward velocity in its cohort. The workhorse 'this is rising' state; this and Breakout are the only states the gate will brief.",
  },
  {
    term: "Simmering",
    desc: "Some heat but not yet acceleration. Also the ceiling for a young cohort still warming up (it can look hot on thin data, so it is capped here).",
  },
  {
    term: "Fading",
    desc: "Was ≥ simmering, now cooling — velocity below the floor for 14 days, or no activity for 30. A former riser losing steam.",
  },
  {
    term: "Dormant",
    desc: "Flat or quiet. Most entities read dormant until the daily heartbeat accumulates enough snapshots to compute velocity.",
  },
];

export const HELP: Record<string, HelpContent> = {
  radar: {
    title: "Reading the Radar",
    intro:
      "Every tracked entity (a repo, model, paper, or package), ranked by momentum first and velocity second. This is the watchlist — the top-left is where attention should go.",
    sections: [
      {
        title: "On each card",
        rows: [
          { term: "Name · category · type", desc: "The entity, its assigned category, and what kind of thing it is (project / model / paper)." },
          { term: "State chip", desc: "Its momentum state (see below). The colored left edge and dot repeat the same state — colour always means momentum here, nothing else." },
          { term: "One-liner", desc: "The headline from its comprehension card (the AI 'what is this'). 'No comprehension card yet' means it hasn't crossed the trigger to be summarised." },
          { term: "Velocity", desc: "Growth-velocity percentile within its category cohort. 82% = growing faster than 82% of its peers. The core 'is it moving' number." },
          { term: "Stage", desc: "The highest maturity rung it has reached, from idea/paper up to institutional adoption." },
          { term: "Sparkline", desc: "A mini trend of its headline metric (usually GitHub stars) over the tracked window." },
          { term: "·prov tag", desc: "Provisional — its cohort is still warming up, so the state is tentative and can never spend a brief. Don't over-trust it." },
        ],
      },
      { title: "Momentum states (hot → cold)", rows: MOMENTUM_STATES },
      {
        title: "Filters",
        rows: [
          { term: "State pills", desc: "Subset the grid by momentum state; the number on each pill is how many entities are in that state right now." },
        ],
      },
    ],
    analyse: [
      "Start at Breakout / Accelerating with a high velocity AND a real one-liner — that combination is a genuine riser, not noise.",
      "Treat Dormant as background; it's most of the list until the pipeline has run daily for a while.",
      "A ·prov (provisional) breakout on thin data is a maybe, not a yes — open it and check the cohort size.",
      "Fading on something you were watching is your exit cue: the thesis is cooling.",
    ],
  },

  entity: {
    title: "Reading an entity dossier",
    intro:
      "Everything the system knows about one entity: its identity, momentum, maturity, and the AI comprehension card. Use it to decide whether a Radar blip is real.",
    sections: [
      {
        title: "Header",
        rows: [
          { term: "Category / owner / first seen", desc: "Its classification, who is behind it, and when we first observed evidence of it." },
          { term: "Tier", desc: "Tracking tier — active / slow / archived — how aggressively we re-poll it for fresh snapshots." },
          { term: "Anchors", desc: "The registry IDs (github:owner/repo, arxiv:…, hf:…) that prove this is one identity across sources." },
        ],
      },
      {
        title: "KPI tiles",
        rows: [
          { term: "Velocity Percentile", desc: "Where its growth velocity ranks within its cohort. High = moving fast relative to peers." },
          { term: "Momentum", desc: "Its current state word; 'provisional cohort' vs 'committed' tells you how much to trust it." },
          { term: "Maturity", desc: "Highest ladder stage reached, with how many rungs it has climbed." },
          { term: "Cohort Size", desc: "How many peer entities the percentile is computed against — the denominator. A tiny cohort makes percentiles noisy." },
        ],
      },
      {
        title: "Comprehension Card (AI checkpoint 1)",
        rows: [
          { term: "What it is / Function", desc: "The plain-language summary of the entity and what it does." },
          { term: "The Pitch", desc: "Its claimed advantage and what it replaces or enables — the bull case, as the project states it." },
          { term: "Open Questions", desc: "What the evidence does NOT yet establish. Deliberately placed next to the pitch so scepticism travels with the claim." },
          { term: "Category disputed / status", desc: "Flags if classification is uncertain or the card is pending/failed rather than 'ok'." },
          { term: "Version drift note", desc: "Multiple card versions mean the described function changed — often a sign the project is pivoting." },
        ],
      },
      {
        title: "Trajectory & ladder",
        rows: [
          { term: "Metric trajectory", desc: "The headline metric (e.g. stars) over time; dots on the line mark maturity promotions." },
          { term: "Maturity Ladder", desc: "The 6 rungs from idea_paper → institutional_adoption, lit and dated up to the highest reached." },
        ],
      },
    ],
    analyse: [
      "High velocity + a coherent card + climbing the ladder = a real, compounding rise.",
      "High velocity but empty 'what it is' or many open questions = attention without substance; wait.",
      "Check cohort size before trusting the percentile — a percentile over 3 peers means little.",
      "A jump in ladder stage (e.g. public_code → distribution) is a stronger commitment signal than stars alone.",
    ],
  },

  changes: {
    title: "Reading the Changes view",
    intro:
      "A deterministic daily diff of what moved — momentum shifts, promotions, and the brief lifecycle. No narrative model: every line is a templated fact, boring on purpose.",
    sections: [
      {
        title: "Calibration strip (the detector grading itself)",
        rows: [
          { term: "Breakout survival", desc: "Share of breakout calls ≥90 days old that are still alive. Healthy ≥ 50% (green). Low means the detector cries wolf." },
          { term: "Fade false-alarm", desc: "Share of 'fading' calls that re-accelerated within 60 days. Lower is better — a high number means we give up on risers too early." },
          { term: "n=", desc: "Sample size behind each ratio. Reads n=0 / — until the system has ~a quarter of history to grade." },
        ],
      },
      {
        title: "Change groups",
        rows: [
          { term: "New — survived the 7-day gate", desc: "A new entity that has lived 7 days with enough corroborating evidence — a real arrival, not a one-day spike." },
          { term: "Momentum ↑ / ↓", desc: "State transitions since the previous day (heated up / cooled down)." },
          { term: "Maturity promotions", desc: "An entity climbed a ladder rung (e.g. reached a usable artifact or distribution)." },
          { term: "Briefs drafted / published", desc: "Impact-brief lifecycle events for the day." },
          { term: "Gate — week rollup", desc: "A Monday summary of that week's significance-gate outcome." },
        ],
      },
    ],
    analyse: [
      "Scan 'New survived' and 'Momentum ↑' first — that's where fresh opportunity surfaces.",
      "Use the calibration strip as a trust dial: if breakout survival is low, weight the Radar's breakout calls more sceptically.",
      "Every row links to the entity — click through to verify a move against its card and trajectory.",
      "A day of all-promotions with no momentum moves is usually a batch/cold-start artifact, not real acceleration.",
    ],
  },

  gate: {
    title: "Reading the Significance Gate",
    intro:
      "The deterministic (no-LLM) weekly selector that decides which risers are worth an impact brief. Its value is auditability: you see what passed AND what was withheld, with the reason.",
    sections: [
      {
        title: "The score",
        rows: [
          { term: "Score = M × (0.4 + 0.6·R) × (0.4 + 0.6·N)", desc: "Momentum, Reach, and Novelty combined. R and N are floored at 0.4 so an eligible entity is never zeroed by one weak factor." },
          { term: "M — Momentum", desc: "Peak state × velocity — how hot it got this week." },
          { term: "R — Reach", desc: "Exposure-map coverage. 1.0 if it touches ≥3 revenue lines or a 'core' one, else 0.5. Hover shows the line count." },
          { term: "N — Novelty", desc: "A cohort-pioneer proxy — is it early/novel versus its peers." },
          { term: "Score (right)", desc: "The combined number. The top few by score pass, up to the weekly budget." },
        ],
      },
      {
        title: "Sections",
        rows: [
          { term: "Passed — brief queued", desc: "Earned a slot this week; impact briefs are generated from here." },
          { term: "Suppressed", desc: "Considered but not briefed. Trust comes from seeing what the gate held back — and why." },
          { term: "{passed}/{budget}", desc: "Briefs allotted this week versus the weekly ceiling." },
        ],
      },
      {
        title: "Suppression reasons",
        rows: [
          { term: "No map surface", desc: "Its category touches no company in the exposure map — hard-excluded before scoring (we can't say who's exposed)." },
          { term: "Card pending", desc: "No comprehension card yet — the gate never briefs an un-summarised entity." },
          { term: "Below weekly cut", desc: "Eligible and scored, but outside the top few for the week's budget." },
        ],
      },
      {
        title: "Map gaps",
        rows: [
          { term: "Category ×N", desc: "Categories with rising entities but no exposure-map coverage. The prioritised worklist for growing the map so those risers become brief-able." },
        ],
      },
    ],
    analyse: [
      "Read Passed as 'what to research this week'; read Suppressed to sanity-check the gate isn't hiding something real.",
      "A high-M entity suppressed for 'No map surface' is not unimportant — it's a map gap, i.e. work to do, not a dead end.",
      "Compare M vs R vs N on a row: a pass driven purely by novelty with weak reach is a softer signal than one strong on all three.",
      "Watch the map-gaps list over weeks — the same category recurring is the clearest signal of where to expand coverage.",
    ],
  },

  briefList: {
    title: "Reading the brief inbox",
    intro:
      "Every drafted impact brief: who is exposed to each rising entity, how, and what to watch. The guardrail — we explain exposure, never predict prices — and a human reviews every brief before it publishes.",
    sections: [
      {
        title: "On each row",
        rows: [
          { term: "Entity · vN", desc: "The entity the brief is about and its version (briefs are re-drafted as evidence grows)." },
          { term: "Summary", desc: "One-line thesis of who is exposed and how." },
          { term: "Mechanism tags", desc: "The economic mechanism(s) at play — substitution, cost collapse, commoditization, enablement, dependency risk." },
          { term: "Exposures count", desc: "How many parties (tickers / sectors) the brief names as affected." },
        ],
      },
      {
        title: "Status",
        rows: [
          { term: "Draft — needs review", desc: "Generated, awaiting a human decision." },
          { term: "Published", desc: "A reviewer approved it; now eligible for forward scoring." },
          { term: "Rejected", desc: "A reviewer declined it (with a reason recorded)." },
          { term: "Failed validation", desc: "The model output didn't satisfy the schema/post-checks even after a retry." },
          { term: "Pending (budget)", desc: "Deferred because the monthly LLM budget ceiling was hit." },
        ],
      },
    ],
    analyse: [
      "Work the 'Draft — needs review' items first; the inbox is a review queue, not an archive.",
      "Rows with more mechanisms and exposures are richer theses — but breadth isn't correctness; open and judge them.",
      "Failed / pending statuses are process signals (model or budget), not findings about the entity.",
    ],
  },

  briefDetail: {
    title: "Reading an impact brief",
    intro:
      "The full exposure thesis for one entity. It explains WHO is affected, through WHAT mechanism, in WHICH direction, and WHAT would prove it wrong — and never quotes a price target.",
    sections: [
      {
        title: "Header",
        rows: [
          { term: "vN · status", desc: "Version and where it sits in the review lifecycle." },
          { term: "as of / model / confidence / horizon", desc: "The evidence cut-off date, which model wrote it, its self-rated confidence, and the time horizon of the thesis." },
        ],
      },
      {
        title: "Body",
        rows: [
          { term: "Mechanisms + Summary", desc: "The economic mechanism(s) and the prose thesis built only from the entity's evidence." },
          { term: "Exposures table", desc: "Party (a ticker or a sector class), the Revenue line affected, the Direction (negative / positive / ambiguous), and the Magnitude (marginal / material / structural)." },
          { term: "Transmission path", desc: "The explicit numbered chain from the entity to each affected revenue line — no hand-waving from cause to effect." },
          { term: "Counter-mechanism", desc: "The strongest case AGAINST the thesis, stated fairly. Enforced to be a real argument — a one-sided brief is marketing." },
          { term: "Observables", desc: "Dated falsifiers that would settle the thesis. Tagged 'system' (machine-measurable, with the metric) or 'manual', each with a horizon and the direction expected if the thesis holds." },
          { term: "Evidence", desc: "The raw events the brief is grounded in." },
        ],
      },
      {
        title: "Actions",
        rows: [
          { term: "Review", desc: "Publish or reject-with-reason (access-controlled)." },
          { term: "Forward scoring", desc: "Only on published briefs — the quarterly retrospective: did the exposure materialise, did a falsifier trip, was the counter-mechanism the better story? System observables auto-evaluate." },
        ],
      },
    ],
    analyse: [
      "Read the Counter-mechanism before the thesis — if it's weak or hand-wavy, distrust the whole brief.",
      "An 'ambiguous' direction is a legitimate, honest finding, not a failure to decide.",
      "Prefer briefs whose observables are dated and 'system'-measurable — those can be scored objectively later.",
      "Direction (who's hurt vs helped) matters more than magnitude words; a 'material' negative on a core revenue line is the sharpest call.",
    ],
  },

  queue: {
    title: "Reading the Merge Queue",
    intro:
      "Where a human resolves ambiguous identity matches — pairs the automatic rules think MIGHT be the same entity but aren't confident enough to merge on their own.",
    sections: [
      {
        title: "Each item",
        rows: [
          { term: "Entity A ≟ Entity B", desc: "The two candidate entities, side by side, each clickable through to its dossier." },
          { term: "rule", desc: "Which name-backed rule (R4–R5) proposed the match." },
          { term: "confidence", desc: "The rule's confidence that they're the same thing — the model's estimate, not proof." },
        ],
      },
      {
        title: "Actions (keyboard M / N / S)",
        rows: [
          { term: "Merge (M)", desc: "They ARE the same entity — fold them into one." },
          { term: "Reject (N)", desc: "They're genuinely different — keep them separate." },
          { term: "Skip (S)", desc: "Decide later; leaves it in the queue." },
        ],
      },
    ],
    analyse: [
      "Open both dossiers when unsure — owner, anchors, and category usually settle it fast.",
      "High confidence is a hint, not a verdict; a wrong merge is hard to see later, so reject when genuinely unsure.",
      "This is the safety valve: automation merges the obvious cases, you arbitrate the rest.",
    ],
  },
  graph: {
    title: "Reading the Graph",
    intro:
      "Two different kinds of relation between entities, drawn on top of each other but never merged: one is provable, one is a model's opinion. The colour of a line tells you which.",
    sections: [
      {
        title: "Edge colours",
        rows: [
          { term: "Teal line", desc: "Deterministic — built_by, cited, or depends_on. Every one of these is derived from a specific raw event (a GitHub contributor list, a README citation, a PyPI dependency list); it can always be traced back to proof." },
          { term: "Purple line", desc: "LLM-reasoned — semantically_similar_to or conceptually_related_to. A model judged these two things are related; no rule could have derived it. Treat as a lead worth checking, not a fact." },
        ],
      },
      {
        title: "Nodes",
        rows: [
          { term: "Coloured circle", desc: "A tracked entity, coloured by its category." },
          { term: "Grey circle", desc: "A concept an LLM pass named (e.g. \"Claude Code\", \"MCP\") that isn't itself a tracked entity — it only exists here because something was compared to it." },
          { term: "Size", desc: "Bigger = more connections. A large node is a hub worth understanding first." },
          { term: "🔥 prefix", desc: "A trending node — it ever passed the significance gate or is currently breakout/accelerating. Same signal as the Radar's Gated pill and 🔥 Taking off strip." },
        ],
      },
    ],
    analyse: [
      "This graph is a one-time snapshot (see GRAPH_PLAN.md) — it does not update itself as new entities are tracked.",
      "Click a node for its connection count and, for a tracked entity, a link to its full dossier.",
      "A purple-only cluster with no teal edges at all is the most interesting case: a correlation no rule could ever have found.",
      "🔥 Trending only prunes the graph to gated/breakout entities plus their direct neighbors — use it when the full graph is too dense to read; long-tail nodes with no earned signal (e.g. a citation-only paper stub) disappear unless they sit next to something that matters.",
    ],
  },
};
