import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getGitStatus, gitCommit, gitPush, gitOpenPr } from "../api/client";
import { useAppStore } from "./app-store";

const GIT_STATUS_POLL_MS = 15_000;

export function useGitStatus(enabled: boolean) {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const workspaceRoot = useAppStore((state) => state.selectedWorkspace);

  return useQuery({
    queryKey: ["git-status", baseUrl, workspaceRoot],
    queryFn: () => getGitStatus(baseUrl, workspaceRoot),
    enabled: enabled && Boolean(baseUrl) && Boolean(workspaceRoot),
    refetchInterval: GIT_STATUS_POLL_MS,
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: true,
  });
}

export function useGitCommit() {
  const queryClient = useQueryClient();
  const baseUrl = useAppStore((state) => state.baseUrl);
  const workspaceRoot = useAppStore((state) => state.selectedWorkspace);

  return useMutation({
    mutationFn: async (message: string) => {
      if (!workspaceRoot) throw new Error("No workspace selected");
      return gitCommit(baseUrl, workspaceRoot, message);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["git-status"] });
    },
  });
}

export function useGitPush() {
  const queryClient = useQueryClient();
  const baseUrl = useAppStore((state) => state.baseUrl);
  const workspaceRoot = useAppStore((state) => state.selectedWorkspace);

  return useMutation({
    mutationFn: async () => {
      if (!workspaceRoot) throw new Error("No workspace selected");
      return gitPush(baseUrl, workspaceRoot);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["git-status"] });
    },
  });
}

export function useGitOpenPr() {
  const queryClient = useQueryClient();
  const baseUrl = useAppStore((state) => state.baseUrl);
  const workspaceRoot = useAppStore((state) => state.selectedWorkspace);

  return useMutation({
    mutationFn: async () => {
      if (!workspaceRoot) throw new Error("No workspace selected");
      return gitOpenPr(baseUrl, workspaceRoot);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["git-status"] });
    },
  });
}
