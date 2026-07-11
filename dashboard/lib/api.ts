import type {
  Brief,
  BriefListItem,
  EntityDossier,
  GateWeekResponse,
  HealthResponse,
  QueueItem,
  RadarResponse,
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
  limit?: number;
} = {}): Promise<RadarResponse> {
  const q = new URLSearchParams();
  if (params.state) q.set("state", params.state);
  if (params.theme) q.set("theme", params.theme);
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

export const API_BASE = BASE;
