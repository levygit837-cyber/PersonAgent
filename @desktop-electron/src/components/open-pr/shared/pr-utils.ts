import type { GitBranchInfo, PullRequestStatus, PullRequestSummary, WorkspaceProject } from "../../../api/client";
import { workspaceName } from "../../../lib/utils";

export function prTotals(pullRequest: PullRequestSummary) {
  return pullRequest.files.reduce(
    (totals, file) => ({
      additions: totals.additions + file.additions,
      deletions: totals.deletions + file.deletions,
    }),
    { additions: 0, deletions: 0 },
  );
}

export function uniqueProjects(
  pullRequests: PullRequestSummary[],
  fallbackName?: string,
  fallbackPath?: string,
  recentWorkspaces: string[] = [],
  backendProjects: WorkspaceProject[] = [],
) {
  const projects = new Map<string, string>();
  for (const project of backendProjects) {
    if (project.path && !projects.has(project.path)) {
      projects.set(project.path, project.name || workspaceName(project.path));
    }
  }
  for (const path of recentWorkspaces) {
    if (path && !projects.has(path)) {
      projects.set(path, workspaceName(path));
    }
  }
  if (fallbackPath && !projects.has(fallbackPath)) {
    projects.set(fallbackPath, fallbackName ?? workspaceName(fallbackPath));
  }
  for (const pullRequest of pullRequests) {
    if (!projects.has(pullRequest.projectPath)) {
      projects.set(pullRequest.projectPath, pullRequest.project);
    }
  }
  if (projects.size === 0 && fallbackName) {
    projects.set(fallbackName, fallbackPath ?? fallbackName);
  }
  return Array.from(projects, ([path, name]) => ({ name, path }));
}

export function uniqueBranches(pullRequests: PullRequestSummary[], projectPath: string, gitBranches: GitBranchInfo[]) {
  const branches = new Set<string>();
  for (const branch of gitBranches) {
    if (branch.name && !branch.name.endsWith("/HEAD")) {
      branches.add(branch.name);
    }
  }
  for (const pullRequest of pullRequests) {
    if (pullRequest.projectPath === projectPath && pullRequest.branch) {
      branches.add(pullRequest.branch);
    }
  }
  return Array.from(branches).sort();
}

export function shortPath(path: string) {
  const pieces = path.split("/");
  return pieces.slice(Math.max(0, pieces.length - 2)).join("/");
}

export function statusText(status: PullRequestStatus) {
  if (status === "approved") return "Approved";
  if (status === "merged") return "Merged";
  if (status === "refused") return "Refused";
  return "Needs review";
}

export function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function clampValue(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}
