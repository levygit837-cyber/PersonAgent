import type { SessionPanelSnapshot } from "../../../../types/chat";

export const SESSION_PANEL_CACHE_STORAGE_KEY = "personagent_session_panel_cache_v1";

const SESSION_PANEL_CACHE_LIMIT = 24;
const SESSION_PANEL_CACHE_TEXT_LIMIT = 12_000;

export type SessionPanelCacheEntry = {
  cachedAt: number;
  snapshot: SessionPanelSnapshot;
};

type SessionPanelCacheStore = Record<string, SessionPanelCacheEntry>;

export function readSessionPanelCache(
  baseUrl?: string,
  conversationId?: string,
  workspaceRoot?: string | null,
): SessionPanelCacheEntry | undefined {
  if (!baseUrl || !conversationId || typeof window === "undefined") return undefined;
  const store = readSessionPanelCacheStore();
  const entry = store[sessionPanelCacheKey(baseUrl, conversationId, workspaceRoot)];
  if (!entry || !isSessionPanelSnapshot(entry.snapshot)) return undefined;
  return entry;
}

export function persistSessionPanelCache(
  baseUrl: string,
  conversationId: string | undefined,
  workspaceRoot: string | null | undefined,
  snapshot: SessionPanelSnapshot,
) {
  if (!baseUrl || !conversationId || typeof window === "undefined") return;
  if (snapshot.conversation_id !== conversationId) return;

  const store = readSessionPanelCacheStore();
  store[sessionPanelCacheKey(baseUrl, conversationId, workspaceRoot)] = {
    cachedAt: Date.now(),
    snapshot: compactSessionPanelSnapshotForCache(snapshot),
  };
  const prunedEntries = Object.entries(store)
    .sort(([, left], [, right]) => right.cachedAt - left.cachedAt)
    .slice(0, SESSION_PANEL_CACHE_LIMIT);

  try {
    window.localStorage.setItem(SESSION_PANEL_CACHE_STORAGE_KEY, JSON.stringify(Object.fromEntries(prunedEntries)));
  } catch {
    // Cache writes are best-effort. The panel can still fetch the live snapshot.
  }
}

function readSessionPanelCacheStore(): SessionPanelCacheStore {
  try {
    const raw = window.localStorage.getItem(SESSION_PANEL_CACHE_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const store: SessionPanelCacheStore = {};
    for (const [key, value] of Object.entries(parsed)) {
      if (!value || typeof value !== "object" || Array.isArray(value)) continue;
      const entry = value as Partial<SessionPanelCacheEntry>;
      if (typeof entry.cachedAt !== "number" || !isSessionPanelSnapshot(entry.snapshot)) continue;
      store[key] = { cachedAt: entry.cachedAt, snapshot: entry.snapshot };
    }
    return store;
  } catch {
    return {};
  }
}

function sessionPanelCacheKey(baseUrl: string, conversationId: string, workspaceRoot?: string | null) {
  return JSON.stringify([baseUrl.trim(), conversationId, workspaceRoot?.trim() || ""]);
}

function compactSessionPanelSnapshotForCache(snapshot: SessionPanelSnapshot): SessionPanelSnapshot {
  return {
    ...snapshot,
    changed_files: snapshot.changed_files.map((file) => ({
      ...file,
      diff: truncateCacheText(file.diff),
      content: truncateCacheText(file.content),
    })),
  };
}

function truncateCacheText(value?: string) {
  if (!value || value.length <= SESSION_PANEL_CACHE_TEXT_LIMIT) return value;
  return `${value.slice(0, SESSION_PANEL_CACHE_TEXT_LIMIT)}\n...`;
}

function isSessionPanelSnapshot(value: unknown): value is SessionPanelSnapshot {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const snapshot = value as Partial<SessionPanelSnapshot>;
  return (
    typeof snapshot.conversation_id === "string" &&
    typeof snapshot.title === "string" &&
    typeof snapshot.updated_at === "string" &&
    Array.isArray(snapshot.changed_files) &&
    Array.isArray(snapshot.sources) &&
    Boolean(snapshot.usage) &&
    Boolean(snapshot.project)
  );
}
