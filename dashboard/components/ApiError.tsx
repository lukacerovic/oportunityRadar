import { API_BASE } from "@/lib/api";

export function ApiError({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="panel mx-auto mt-16 max-w-lg p-6 text-center">
      <div className="text-lg font-semibold text-text">Can’t reach the API</div>
      <p className="mt-2 text-sm text-muted">
        The dashboard talks to the FastAPI service at{" "}
        <code className="text-accent">{API_BASE}</code>. Start it with{" "}
        <code className="text-accent">uv run seismo serve</code>.
      </p>
      <p className="mt-3 text-xs text-faint">{msg}</p>
    </div>
  );
}
