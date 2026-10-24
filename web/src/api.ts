// Hand-written client for the one endpoint the shell needs. CIW-04.1 replaces
// this with the client generated from openapi.yaml.

export interface Health {
  status: "ok" | "degraded";
  db: "ok" | "error";
  agent_enabled: boolean;
  version: string;
}

export async function fetchHealth(): Promise<Health> {
  const response = await fetch("/api/health", { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`GET /api/health returned ${response.status}`);
  }
  return (await response.json()) as Health;
}
