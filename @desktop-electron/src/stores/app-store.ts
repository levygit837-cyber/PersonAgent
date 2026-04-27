import { create } from "zustand";
import { resolveBackendUrl } from "../api/client";
import type { ModelProvider, ReasoningPreset } from "../types/chat";

const settingsKeys = {
  baseUrl: "personagent_base_url",
  workspace: "personagent_selected_workspace",
  recentWorkspaces: "personagent_recent_workspaces",
  convWorkspaceMap: "personagent_conv_workspace_map",
};

type ApiStatus = "checking" | "online" | "offline";
export type WorkbenchSection = "chat" | "lab";

interface AppState {
  baseUrl: string;
  apiStatus: ApiStatus;
  apiError?: string;
  section: WorkbenchSection;
  sidebarCollapsed: boolean;
  selectedWorkspace?: string;
  recentWorkspaces: string[];
  convWorkspaceMap: Record<string, string>;
  provider: ModelProvider;
  selectedModelId: string;
  reasoningPreset: ReasoningPreset;
  teamMode: boolean;
  initialize: () => Promise<void>;
  checkBackend: () => Promise<void>;
  setSection: (section: WorkbenchSection) => void;
  toggleSidebar: () => void;
  setReasoningPreset: (preset: ReasoningPreset) => void;
  setTeamMode: (enabled: boolean) => void;
  setProvider: (provider: ModelProvider) => void;
  setSelectedModelId: (modelId: string) => void;
  selectWorkspace: (path: string) => Promise<void>;
  pickWorkspace: () => Promise<void>;
  associateConversation: (conversationId: string, workspace?: string) => Promise<void>;
  conversationBelongsToWorkspace: (conversationId: string) => boolean;
}

async function settingsGet<T>(key: string) {
  if (window.personAgent) {
    return window.personAgent.settings.get<T>(key);
  }
  const raw = window.localStorage.getItem(key);
  if (raw == null) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return raw as T;
  }
}

async function settingsSet(key: string, value: unknown) {
  if (window.personAgent) {
    await window.personAgent.settings.set(key, value);
    return;
  }
  window.localStorage.setItem(key, JSON.stringify(value));
}

function normalizeRecent(paths: string[], selected?: string) {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const raw of [selected, ...paths]) {
    const path = raw?.trim();
    if (!path || seen.has(path)) continue;
    seen.add(path);
    result.push(path);
    if (result.length === 8) break;
  }
  return result;
}

export const useAppStore = create<AppState>((set, get) => ({
  baseUrl: "http://localhost:8000",
  apiStatus: "checking",
  section: "chat",
  sidebarCollapsed: false,
  recentWorkspaces: [],
  convWorkspaceMap: {},
  provider: "llama",
  selectedModelId: "local-model",
  reasoningPreset: "low",
  teamMode: false,

  initialize: async () => {
    const savedBaseUrl = await settingsGet<string>(settingsKeys.baseUrl);
    const selectedWorkspace = await settingsGet<string>(settingsKeys.workspace);
    const recentWorkspaces = (await settingsGet<string[]>(settingsKeys.recentWorkspaces)) ?? [];
    const convWorkspaceMap = (await settingsGet<Record<string, string>>(settingsKeys.convWorkspaceMap)) ?? {};
    set({
      baseUrl: savedBaseUrl || "http://localhost:8000",
      selectedWorkspace: selectedWorkspace || undefined,
      recentWorkspaces: normalizeRecent(recentWorkspaces, selectedWorkspace || undefined),
      convWorkspaceMap,
    });
    await get().checkBackend();
  },

  checkBackend: async () => {
    set({ apiStatus: "checking", apiError: undefined });
    try {
      const resolved = await resolveBackendUrl(get().baseUrl);
      await settingsSet(settingsKeys.baseUrl, resolved);
      set({ baseUrl: resolved, apiStatus: "online", apiError: undefined });
    } catch (error) {
      set({
        apiStatus: "offline",
        apiError: error instanceof Error ? error.message : String(error),
      });
    }
  },

  setSection: (section) => set({ section }),

  toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
  setReasoningPreset: (reasoningPreset) => set({ reasoningPreset }),
  setTeamMode: (teamMode) => set({ teamMode }),
  setProvider: (provider) =>
    set({
      provider,
      selectedModelId:
        provider === "llama"
          ? "local-model"
          : provider === "codex" && get().selectedModelId === "local-model"
            ? "gpt-5.5"
            : get().selectedModelId,
    }),
  setSelectedModelId: (selectedModelId) => set({ selectedModelId }),

  selectWorkspace: async (path) => {
    const normalized = path.trim();
    if (!normalized) return;
    const recentWorkspaces = normalizeRecent(get().recentWorkspaces, normalized);
    set({ selectedWorkspace: normalized, recentWorkspaces });
    void (async () => {
      await settingsSet(settingsKeys.workspace, normalized);
      await settingsSet(settingsKeys.recentWorkspaces, recentWorkspaces);
    })().catch((error) => {
      console.error("Failed to persist selected workspace", error);
    });
  },

  pickWorkspace: async () => {
    const current = get().selectedWorkspace;
    const selected = window.personAgent
      ? await window.personAgent.dialog.selectWorkspace(current)
      : window.prompt("Workspace path", current ?? "");
    if (selected) {
      await get().selectWorkspace(selected);
    }
  },

  associateConversation: async (conversationId, workspace) => {
    const ws = workspace || get().selectedWorkspace;
    if (!ws || !conversationId) return;
    const current = get().convWorkspaceMap;
    if (current[conversationId] === ws) return;
    const map = { ...current, [conversationId]: ws };
    set({ convWorkspaceMap: map });
    await settingsSet(settingsKeys.convWorkspaceMap, map);
  },

  conversationBelongsToWorkspace: (conversationId) => {
    const workspace = get().selectedWorkspace;
    if (!workspace) return true;
    const mapped = get().convWorkspaceMap[conversationId];
    return !mapped || mapped === workspace;
  },
}));
