// Thin fetch helpers. All requests go same-origin to /api, which the Next.js
// rewrite proxies to the backend (destination baked at build via INTERNAL_API_URL).

const API = "/api";

async function throwFromResponse(r: Response, path: string): Promise<never> {
  let detail = `${path} -> ${r.status}`;
  try {
    const j = await r.json();
    if (j?.detail) detail = j.detail; // FastAPI HTTPException detail
  } catch {
    /* non-JSON body */
  }
  throw new Error(detail);
}

export async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) await throwFromResponse(r, path);
  return r.json() as Promise<T>;
}

export async function putJSON<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) await throwFromResponse(r, path);
  return r.json() as Promise<T>;
}

export async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) await throwFromResponse(r, path);
  return r.json() as Promise<T>;
}
