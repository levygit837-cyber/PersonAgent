/**
 * Custom hook for session panel data loading and state derivation.
 *
 * Extracted from `session-panel.tsx` (session_panel Slice 2).
 * Encapsulates: store selectors, React Query for session panel,
 * cache read/persist effects, and usage merge logic.
 */

import { useEffect, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSessionPanel } from "../../../api/client";
import { useAppStore } from "../../../stores/app-store";
import { useChatStore } from "../../../stores/chat-store";
import type { SessionUsage } from "../../../types/chat";
import { emptySessionUsage } from "../../../types/chat";
import { readSessionPanelCache, persistSessionPanelCache } from "./cache";
import {
  SESSION_PANEL_STREAMING_REFETCH_MS,
  SESSION_PANEL_STALE_MS,
} from "./helpers";

// ---------------------------------------------------------------------------
// mergeUsage — combine persisted snapshot usage with live streaming usage
// ---------------------------------------------------------------------------

export function mergeUsage(snapshot: SessionUsage | undefined, live: SessionUsage): SessionUsage {
  const base = snapshot ?? emptySessionUsage();
  const next = emptySessionUsage();
  for (const key of Object.keys(next) as Array<keyof SessionUsage>) {
    if (key === "context_tokens") {
      const snapshotValue = base[key]?.value ?? 0;
      const liveValue = live[key]?.value ?? 0;
      next[key] = {
        value: Math.max(snapshotValue, liveValue),
        estimated: Boolean(base[key]?.estimated || live[key]?.estimated),
      };
      continue;
    }
    next[key] = {
      value: (base[key]?.value ?? 0) + (live[key]?.value ?? 0),
      estimated: Boolean(base[key]?.estimated || live[key]?.estimated),
    };
  }
  return next;
}

// ---------------------------------------------------------------------------
// useSessionPanelState hook
// ---------------------------------------------------------------------------

export function useSessionPanelState(visible: boolean) {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const paneWorkspaceRoot = useChatStore((state) => state.workspaceRoot);
  const workspaceRoot = paneWorkspaceRoot || selectedWorkspace;
  const conversationId = useChatStore((state) => state.conversationId);
  const isStreaming = useChatStore((state) => state.isStreaming);
  const liveUsage = useChatStore((state) => state.liveSessionUsage);
  const browserToolBlocks = useChatStore((state) => state.browserToolBlocks);
  const addComposerAnnotation = useChatStore((state) => state.addComposerAnnotation);
  const approvePendingTool = useChatStore((state) => state.approvePendingTool);
  const rejectPendingTool = useChatStore((state) => state.rejectPendingTool);

  const queryClient = useQueryClient();

  const cachedPanel = useMemo(
    () => readSessionPanelCache(baseUrl, conversationId, workspaceRoot),
    [baseUrl, conversationId, workspaceRoot],
  );

  const panel = useQuery({
    queryKey: ["session-panel", baseUrl, conversationId, workspaceRoot],
    queryFn: () => getSessionPanel(baseUrl, conversationId!, workspaceRoot),
    enabled: Boolean(visible && baseUrl && conversationId),
    initialData: () => cachedPanel?.snapshot,
    initialDataUpdatedAt: () => cachedPanel?.cachedAt,
    refetchInterval: isStreaming ? SESSION_PANEL_STREAMING_REFETCH_MS : false,
    refetchIntervalInBackground: true,
    staleTime: SESSION_PANEL_STALE_MS,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    const handler = () => {
      void queryClient.invalidateQueries({ queryKey: ["session-panel"] });
    };
    window.addEventListener("personagent:session-panel-changed", handler);
    window.addEventListener("personagent:conversations-changed", handler);
    return () => {
      window.removeEventListener("personagent:session-panel-changed", handler);
      window.removeEventListener("personagent:conversations-changed", handler);
    };
  }, [queryClient]);

  const snapshot = panel.data;
  useEffect(() => {
    if (!snapshot) return;
    persistSessionPanelCache(baseUrl, conversationId, workspaceRoot, snapshot);
  }, [baseUrl, conversationId, workspaceRoot, snapshot]);

  const usage = useMemo(() => mergeUsage(snapshot?.usage, liveUsage), [snapshot?.usage, liveUsage]);

  return {
    baseUrl,
    workspaceRoot,
    conversationId,
    isStreaming,
    browserToolBlocks,
    addComposerAnnotation,
    approvePendingTool,
    rejectPendingTool,
    snapshot,
    usage,
    panelIsLoading: panel.isLoading,
    panelError: panel.error,
  };
}
