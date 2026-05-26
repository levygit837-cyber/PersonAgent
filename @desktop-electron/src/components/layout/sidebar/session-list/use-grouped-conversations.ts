import { useEffect, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listConversations } from "../../../../api/client";
import { useAppStore } from "../../../../stores/app-store";
import { workspaceName } from "../../../../lib/utils";
import type { ConversationSummary } from "../../../../types/chat";
import {
  compareConversationsByRecency,
  compareWorkspaceGroupsByRecency,
  workspaceForConversation,
  type WorkspaceGroup,
} from "./types";

export function useGroupedConversations() {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const convWorkspaceMap = useAppStore((state) => state.convWorkspaceMap);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const queryClient = useQueryClient();

  const conversations = useQuery({
    queryKey: ["conversations", baseUrl],
    queryFn: () => listConversations(baseUrl),
    enabled: Boolean(baseUrl),
  });

  useEffect(() => {
    const handler = () => void queryClient.invalidateQueries({ queryKey: ["conversations"] });
    window.addEventListener("personagent:conversations-changed", handler);
    return () => window.removeEventListener("personagent:conversations-changed", handler);
  }, [queryClient]);

  const { groups } = useMemo(() => {
    const all = conversations.data ?? [];
    const byWorkspace = new Map<string, ConversationSummary[]>();

    for (const conv of all) {
      const ws = workspaceForConversation(conv, convWorkspaceMap, selectedWorkspace);
      if (ws) {
        const list = byWorkspace.get(ws) ?? [];
        list.push(conv);
        byWorkspace.set(ws, list);
      }
    }

    const groups: WorkspaceGroup[] = Array.from(byWorkspace.entries()).map(([ws, convs]) => ({
      workspace: ws,
      name: workspaceName(ws) ?? ws,
      conversations: [...convs].sort(compareConversationsByRecency),
    })).sort(compareWorkspaceGroupsByRecency);

    return { groups };
  }, [conversations.data, convWorkspaceMap, selectedWorkspace]);

  return { groups, isLoading: conversations.isLoading, baseUrl };
}
