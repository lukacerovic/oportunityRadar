// Mirrors src/seismo/api/models.py. In production these are generated from the OpenAPI schema
// with `openapi-typescript` (doc 10 §1) so the two codebases can't drift; hand-written for v0.

export type MomentumState =
  | "dormant"
  | "simmering"
  | "accelerating"
  | "breakout"
  | "fading";

export interface RadarEntity {
  id: number;
  name: string;
  entity_type: string;
  category: string | null;
  state: MomentumState;
  velocity_pctl: number | null;
  maturity_stage: string | null;
  one_liner: string | null;
  provisional: boolean;
  sparkline: number[];
  sources: string[]; // collectors that touched it: github/hn/arxiv/hf/seed/…
}

export interface RadarResponse {
  as_of: string;
  count: number;
  entities: RadarEntity[];
  source_counts: Record<string, number>;
}

export interface SearchHit {
  id: number;
  name: string;
  entity_type: string;
  category: string | null;
  state: MomentumState | null; // null until momentum is computed (e.g. a fresh launch)
}

export interface SparkPoint {
  day: string;
  value: number;
}

export interface MetricSeries {
  metric: string;
  points: SparkPoint[];
}

export interface MomentumPoint {
  day: string;
  state: MomentumState;
  score: number | null;
}

export interface MaturityRung {
  stage: string;
  promoted_at: string;
}

export interface Card {
  version: number;
  as_of: string;
  status: string;
  model: string;
  what_it_is: string | null;
  function: string | null;
  claimed_advantage: string | null;
  replaces_or_enables: string[];
  maturity_stage: string | null;
  who_is_behind: string | null;
  open_questions: string[];
  confidence: string | null;
  category: string | null;
  category_disputed: boolean;
}

export interface EvidenceItem {
  source: string;
  kind: string;
  title: string | null;
  url: string | null;
  text: string | null;
  score: number | null;
  occurred_at: string;
}

export interface EntityDossier {
  id: number;
  name: string;
  entity_type: string;
  category: string | null;
  anchors: Record<string, string>;
  owner: string | null;
  first_seen: string;
  tracking_tier: string;
  state: MomentumState;
  velocity_pctl: number | null;
  provisional: boolean;
  cohort_n: number | null;
  description: string | null;
  themes: string[];
  maturity: MaturityRung[];
  metrics: MetricSeries[];
  momentum_history: MomentumPoint[];
  evidence: EvidenceItem[];
  card: Card | null;
  card_versions: number[];
  community: CommunityResearch[];
}

export interface CommunityThread {
  title: string;
  source: string; // github | hn | hf
  channel: string; // "GitHub Issues", "Hacker News", "HF Discussions"
  url: string;
  score: number | null;
  comment_count: number | null;
  created_at: string | null;
  relevance_score: number | null;
  comments: string[];
}

export interface CommunityKpis {
  sources: string[];
  thread_count: number;
  comment_count: number;
}

export interface CommunityResearch {
  source: string; // github | hf | hn | summary (cross-source AI verdict)
  status: string; // found | not_found | failed
  summary: string;
  sentiment: string | null;
  sentiment_score: number | null; // 0-100, on the 'summary' verdict
  confidence: string | null;
  main_points: string[];
  concerns: string[];
  positive_signals: string[];
  notable_quotes: string[]; // on the 'summary' verdict
  kpis: CommunityKpis | null; // on the 'summary' verdict
  threads: CommunityThread[];
  researched_at: string;
}

export interface MiniEntity {
  id: number;
  name: string;
  entity_type: string;
  category: string | null;
  owner: string | null;
}

export interface QueueItem {
  id: number;
  entity_a: MiniEntity;
  entity_b: MiniEntity;
  confidence: number;
  evidence: Record<string, unknown>;
  status: string;
}

export interface HealthResponse {
  ok: boolean;
  checks: { name: string; ok: boolean; detail: string }[];
}

export interface GateComponents {
  M: number | null;
  R: number | null;
  N: number | null;
  score: number | null;
  peak_state: string | null;
  p_peak: number | null;
  category: string | null;
  reach_lines: number | null;
  reach_core: boolean | null;
  reason: string | null;
}

export interface GateDecisionItem {
  entity_id: number;
  name: string;
  entity_type: string;
  category: string | null;
  decision: string;
  score: number;
  components: GateComponents;
}

export interface GateWeekResponse {
  week: string;
  briefs_budget: number;
  passed: GateDecisionItem[];
  suppressed: GateDecisionItem[];
  map_gaps: Record<string, number>;
  available_weeks: string[];
}

export interface BriefTransmissionStep {
  from_node: string;
  to_node: string;
  effect: string;
}

export interface BriefObservable {
  statement: string;
  source: string;
  system_metric: string | null;
  horizon: string;
  direction_if_thesis_holds: string;
}

export interface BriefExposure {
  kind: string;
  ref: string;
  revenue_line: string | null;
  direction: string;
  magnitude_class: string;
}

export interface Brief {
  id: number;
  entity_id: number;
  entity_name: string;
  version: number;
  as_of: string;
  status: string;
  model: string | null;
  reviewed_at: string | null;
  reject_reason: string | null;
  entity_ref: string | null;
  mechanisms: string[];
  transmission_path: BriefTransmissionStep[];
  exposures: BriefExposure[];
  counter_mechanism: string | null;
  observables: BriefObservable[];
  confidence: string | null;
  horizon: string | null;
  summary: string | null;
  evidence_refs: number[];
  versions: number[];
}

export interface BriefListItem {
  id: number;
  entity_id: number;
  entity_name: string;
  version: number;
  status: string;
  as_of: string;
  created_at: string;
  mechanisms: string[];
  n_exposures: number;
  summary: string | null;
}

export interface ChangeItem {
  kind: string;
  entity_id: number | null;
  text: string;
  payload: Record<string, unknown>;
}

export interface ChangesResponse {
  day: string;
  groups: Record<string, ChangeItem[]>;
  total: number;
  available_days: string[];
}

export interface CalibrationPoint {
  day: string;
  value: number | null;
  sample_n: number;
}

export interface CalibrationResponse {
  series: Record<string, CalibrationPoint[]>;
  latest: Record<string, CalibrationPoint>;
}

export interface ObservableEval {
  statement: string;
  source: string;
  system_metric: string | null;
  direction_if_thesis_holds: string;
  status: string;
  detail: string;
}

export interface ExistingScore {
  materialized: string | null;
  falsifier_tripped: boolean | null;
  verdict: string | null;
  counter_was_better: boolean | null;
  falsifier_observable: string | null;
}

export interface ScorePacketResponse {
  brief_id: number;
  entity_id: number;
  entity_name: string;
  version: number;
  published_at: string | null;
  horizon: string | null;
  days_elapsed: number;
  summary: string | null;
  counter_mechanism: string | null;
  exposures: BriefExposure[];
  observable_evals: ObservableEval[];
  metric_history: Record<string, [string, number][]>;
  auto_summary: string;
  existing_score: ExistingScore | null;
}
