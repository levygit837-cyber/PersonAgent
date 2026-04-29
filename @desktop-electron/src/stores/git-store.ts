import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  generateGitCommitMessage,
  getGitRecentActions,
  getGitStatus,
  gitCheckoutBranch,
  gitCommit,
  gitCreateBranch,
  gitCreatePullRequestComment,
  gitOpenPr,
  gitPush,
  listGitBranches,
  listGitPullRequests,
  listWorkspaceProjects,
  type GitBranchInfo,
  type PullRequestCommentKind,
  type PullRequestStatus,
} from "../api/client";
import { useAppStore } from "./app-store";

const GIT_STATUS_POLL_MS = 15_000;

export function useGitStatus(enabled: boolean, workspaceRootOverride?: string | null) {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const workspaceRoot = workspaceRootOverride || selectedWorkspace;

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

export function useGitBranches(enabled: boolean, workspaceRootOverride?: string | null) {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const workspaceRoot = workspaceRootOverride || selectedWorkspace;

  return useQuery({
    queryKey: ["git-branches", baseUrl, workspaceRoot],
    queryFn: () => listGitBranches(baseUrl, workspaceRoot),
    enabled: enabled && Boolean(baseUrl) && Boolean(workspaceRoot),
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: true,
  });
}

export function useGitRecentActions(enabled: boolean, workspaceRootOverride?: string | null) {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const workspaceRoot = workspaceRootOverride || selectedWorkspace;

  return useQuery({
    queryKey: ["git-recent-actions", baseUrl, workspaceRoot],
    queryFn: () => getGitRecentActions(baseUrl, workspaceRoot),
    enabled: enabled && Boolean(baseUrl) && Boolean(workspaceRoot),
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: true,
  });
}

export function useGitPullRequests(enabled: boolean, workspaceRootOverride?: string | null) {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const workspaceRoot = workspaceRootOverride || selectedWorkspace;

  return useQuery({
    queryKey: ["git-pull-requests", baseUrl, workspaceRoot],
    queryFn: () => listGitPullRequests(baseUrl, workspaceRoot),
    enabled: enabled && Boolean(baseUrl) && Boolean(workspaceRoot),
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: true,
  });
}

export function useWorkspaceProjects(enabled: boolean) {
  const baseUrl = useAppStore((state) => state.baseUrl);

  return useQuery({
    queryKey: ["workspace-projects", baseUrl],
    queryFn: () => listWorkspaceProjects(baseUrl),
    enabled: enabled && Boolean(baseUrl),
    staleTime: 30_000,
    gcTime: 5 * 60_000,
    refetchOnWindowFocus: true,
  });
}

export function useGitGenerateCommitMessage(workspaceRootOverride?: string | null) {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const workspaceRoot = workspaceRootOverride || selectedWorkspace;

  return useMutation({
    mutationFn: async () => {
      if (!workspaceRoot) throw new Error("No workspace selected");
      return generateGitCommitMessage(baseUrl, workspaceRoot);
    },
  });
}

export function useGitCreateBranch(workspaceRootOverride?: string | null) {
  const queryClient = useQueryClient();
  const baseUrl = useAppStore((state) => state.baseUrl);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const workspaceRoot = workspaceRootOverride || selectedWorkspace;

  return useMutation({
    mutationFn: async (name: string) => {
      if (!workspaceRoot) throw new Error("No workspace selected");
      return gitCreateBranch(baseUrl, workspaceRoot, name);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["git-status"] });
      queryClient.invalidateQueries({ queryKey: ["git-branches"] });
    },
  });
}

export function useGitCheckoutBranch(workspaceRootOverride?: string | null) {
  const queryClient = useQueryClient();
  const baseUrl = useAppStore((state) => state.baseUrl);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const workspaceRoot = workspaceRootOverride || selectedWorkspace;

  return useMutation({
    mutationFn: async (branch: Pick<GitBranchInfo, "name" | "kind">) => {
      if (!workspaceRoot) throw new Error("No workspace selected");
      return gitCheckoutBranch(baseUrl, workspaceRoot, branch.name, branch.kind);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["git-status"] });
      queryClient.invalidateQueries({ queryKey: ["git-branches"] });
    },
  });
}

export function useGitCommit(workspaceRootOverride?: string | null) {
  const queryClient = useQueryClient();
  const baseUrl = useAppStore((state) => state.baseUrl);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const workspaceRoot = workspaceRootOverride || selectedWorkspace;

  return useMutation({
    mutationFn: async (input: { message: string; autoGenerateMessage?: boolean }) => {
      if (!workspaceRoot) throw new Error("No workspace selected");
      return gitCommit(baseUrl, workspaceRoot, input.message, input.autoGenerateMessage ?? false);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["git-status"] }),
        queryClient.invalidateQueries({ queryKey: ["git-recent-actions"] }),
      ]);
    },
  });
}

export function useGitPush(workspaceRootOverride?: string | null) {
  const queryClient = useQueryClient();
  const baseUrl = useAppStore((state) => state.baseUrl);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const workspaceRoot = workspaceRootOverride || selectedWorkspace;

  return useMutation({
    mutationFn: async () => {
      if (!workspaceRoot) throw new Error("No workspace selected");
      return gitPush(baseUrl, workspaceRoot);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["git-status"] }),
        queryClient.invalidateQueries({ queryKey: ["git-recent-actions"] }),
      ]);
    },
  });
}

export function useGitOpenPr(workspaceRootOverride?: string | null) {
  const queryClient = useQueryClient();
  const baseUrl = useAppStore((state) => state.baseUrl);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const workspaceRoot = workspaceRootOverride || selectedWorkspace;

  return useMutation({
    mutationFn: async () => {
      if (!workspaceRoot) throw new Error("No workspace selected");
      return gitOpenPr(baseUrl, workspaceRoot);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["git-status"] }),
        queryClient.invalidateQueries({ queryKey: ["git-recent-actions"] }),
      ]);
    },
  });
}

export function useGitCreatePullRequestComment() {
  const queryClient = useQueryClient();
  const baseUrl = useAppStore((state) => state.baseUrl);
  const workspaceRoot = useAppStore((state) => state.selectedWorkspace);

  return useMutation({
    mutationFn: async (input: {
      number: number;
      body: string;
      kind: PullRequestCommentKind;
      status?: PullRequestStatus | null;
    }) => {
      if (!workspaceRoot) throw new Error("No workspace selected");
      return gitCreatePullRequestComment(baseUrl, {
        workspaceRoot,
        number: input.number,
        body: input.body,
        kind: input.kind,
        status: input.status ?? null,
      });
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["git-pull-requests"] }),
        queryClient.invalidateQueries({ queryKey: ["git-recent-actions"] }),
      ]);
    },
  });
}
