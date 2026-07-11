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
}

export interface RadarResponse {
  as_of: string;
  count: number;
  entities: RadarEntity[];
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
  maturity: MaturityRung[];
  metrics: MetricSeries[];
  momentum_history: MomentumPoint[];
  card: Card | null;
  card_versions: number[];
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
