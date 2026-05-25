import { PersonAgentApiError, extractApiErrorEnvelope } from "../errors";

const fallbackBaseUrls = ["http://localhost:8000", "http://localhost:8001"];

export async function personAgentAuthHeaders(): Promise<Record<string, string>> {
  if (window.personAgent?.auth?.getHeaders) {
    const headers = await window.personAgent.auth.getHeaders();
    if (headers.Authorization) return headers;
  }
  const token = import.meta.env.VITE_PERSONAGENT_LOCAL_AUTH_TOKEN?.trim();
  if (!token) return {};
  return {
    Authorization: `Bearer ${token}`,
    "X-PersonAgent-Client": "desktop-electron",
  };
}

export async function resolveBackendUrl(current?: string | null) {
  const candidates = Array.from(new Set([current, ...fallbackBaseUrls].filter(Boolean))) as string[];
  for (const candidate of candidates) {
    try {
      const response = await fetch(`${candidate}/health`, { signal: AbortSignal.timeout(3000) });
      if (response.ok) return candidate;
    } catch {
      continue;
    }
  }
  throw new Error("No PersonAgent backend answered on the configured ports.");
}

export async function requestJson<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const method = init?.method?.toUpperCase() ?? "GET";
  const hasBody = init?.body !== undefined && init.body !== null;
  const shouldSendJsonContentType =
    hasBody && (typeof FormData === "undefined" || !(init?.body instanceof FormData));
  const authHeaders = await personAgentAuthHeaders();
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      ...authHeaders,
      ...(shouldSendJsonContentType && method !== "GET" && method !== "HEAD" ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      // Non-JSON error bodies keep status text.
    }
    throw new PersonAgentApiError(
      extractApiErrorEnvelope(body, response.status, response.statusText),
    );
  }
  return (await response.json()) as T;
}

export async function fetchBackendText(url: string, init?: RequestInit): Promise<string> {
  const authHeaders = await personAgentAuthHeaders();
  const response = await fetch(url, {
    ...init,
    headers: {
      ...authHeaders,
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      // Non-JSON error bodies keep status text.
    }
    throw new PersonAgentApiError(
      extractApiErrorEnvelope(body, response.status, response.statusText),
    );
  }
  return response.text();
}

export function webSocketBaseUrl(baseUrl: string) {
  const url = new URL(baseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString().replace(/\/$/, "");
}
