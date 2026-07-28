import type {
  Brief,
  BriefListItem,
  CalibrationResponse,
  ChangesResponse,
  EntityDossier,
  GateWeekResponse,
  GraphResponse,
  HealthResponse,
  QueueItem,
  RadarResponse,
  ScorePacketResponse,
} from "./types";

const BASE = process.env.SEISMO_API_BASE ?? "http://127.0.0.1:8000";

// Data changes once a day; short revalidation keeps server components fresh without polling
// (doc 10 DR-10.3). Errors bubble so a page can render an explicit "API unreachable" state.
async function get<T>(path: string, revalidate = 300): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { next: { revalidate } });
  if (!res.ok) {
    throw new Error(`API ${res.status} for ${path}`);
  }
  return res.json() as Promise<T>;
}

export function getRadar(params: {
  state?: string;
  theme?: string;
  source?: string;
  gated?: boolean;
  limit?: number;
} = {}): Promise<RadarResponse> {
  const q = new URLSearchParams();
  if (params.state) q.set("state", params.state);
  if (params.theme) q.set("theme", params.theme);
  if (params.source) q.set("source", params.source);
  if (params.gated) q.set("gated", "true");
  q.set("limit", String(params.limit ?? 200));
  return get<RadarResponse>(`/radar?${q.toString()}`);
}

export function getEntity(id: number): Promise<EntityDossier> {
  return get<EntityDossier>(`/entities/${id}`, 120);
}

export function getQueue(): Promise<QueueItem[]> {
  return get<QueueItem[]>(`/queue`, 60);
}

export function getHealth(): Promise<HealthResponse> {
  return get<HealthResponse>(`/health`, 30);
}

export function getGate(week: string): Promise<GateWeekResponse> {
  return get<GateWeekResponse>(`/gate/${encodeURIComponent(week)}`, 300);
}

export function getBriefs(status?: string): Promise<BriefListItem[]> {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  return get<BriefListItem[]>(`/briefs${q}`, 60);
}

export function getBrief(entityId: number): Promise<Brief> {
  return get<Brief>(`/briefs/${entityId}`, 60);
}

// Most entities have no brief (only gate-passed ones do) — treat a 404 as "none", not an error.
export async function getBriefSafe(entityId: number): Promise<Brief | null> {
  try {
    return await getBrief(entityId);
  } catch {
    return null;
  }
}

export function getChanges(day: string): Promise<ChangesResponse> {
  return get<ChangesResponse>(`/changes/${encodeURIComponent(day)}`, 120);
}

export function getCalibration(): Promise<CalibrationResponse> {
  return get<CalibrationResponse>(`/calibration`, 300);
}

export function getScorePacket(entityId: number): Promise<ScorePacketResponse> {
  return get<ScorePacketResponse>(`/briefs/${entityId}/score-packet`, 30);
}

export function getGraph(
  params: { trending?: boolean; q?: string } = {}
): Promise<GraphResponse> {
  const search = new URLSearchParams();
  if (params.trending) search.set("trending", "true");
  if (params.q) search.set("q", params.q);
  const qs = search.toString();
  // 60s, not an hour: since the Wikidata enrichment landed, the graph gains edges every
  // pipeline run, and a stale cached response makes fresh enrichments invisible (a search
  // result cached at 9 nodes kept serving 9 nodes while the DB held 14).
  return get<GraphResponse>(`/graph${qs ? `?${qs}` : ""}`, 60);
}

export const API_BASE = BASE;
