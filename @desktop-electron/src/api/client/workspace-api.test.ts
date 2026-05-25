import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createWorkspaceGrant,
  listWorkspaceFiles,
  readWorkspaceFile,
  listWorkspaceMentions,
  listBrowserTabMentions,
  getGitStatus,
  listGitBranches,
  getGitRecentActions,
  listWorkspaceProjects,
  listGitPullRequests,
  generateGitCommitMessage,
  gitCreateBranch,
  gitCreateWorktree,
  gitCheckoutBranch,
  gitCommit,
  gitPush,
  gitOpenPr,
  gitCreatePullRequestComment,
} from "./workspace-api";

afterEach(() => {
  vi.restoreAllMocks();
  delete window.personAgent;
});

function mockFetchJson(data: unknown, status = 200) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(data), { status }),
  );
}

describe("createWorkspaceGrant", () => {
  it("posts workspace root and returns grant", async () => {
    const fetchMock = mockFetchJson({ workspace_id: "ws1", root: "/work", source: "desktop-electron", created_at: "2024-01-01", last_used_at: "2024-01-01" });

    const result = await createWorkspaceGrant("http://localhost:8000", "/work");

    expect(result.workspace_id).toBe("ws1");
    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(body).toEqual({ root: "/work", source: "desktop-electron" });
  });
});

describe("listWorkspaceFiles", () => {
  it("fetches files with path param", async () => {
    mockFetchJson([{ name: "file.ts", isDirectory: false, path: "/file.ts" }]);

    const files = await listWorkspaceFiles("http://localhost:8000", "/work");

    expect(files).toHaveLength(1);
    expect(files[0]?.name).toBe("file.ts");
  });

  it("appends workspace_root when provided", async () => {
    const fetchMock = mockFetchJson([]);

    await listWorkspaceFiles("http://localhost:8000", "/work", "/workspace");

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("workspace_root=%2Fworkspace"),
      expect.anything(),
    );
  });
});

describe("readWorkspaceFile", () => {
  it("fetches file content", async () => {
    mockFetchJson({ path: "/work/file.ts", name: "file.ts", content: "export {}" });

    const file = await readWorkspaceFile("http://localhost:8000", "/work/file.ts");

    expect(file.content).toBe("export {}");
  });
});

describe("listWorkspaceMentions", () => {
  it("queries workspace mentions", async () => {
    mockFetchJson([{ type: "file", name: "readme.md", path: "/readme.md", display_path: "readme.md", is_directory: false, score: 1 }]);

    const mentions = await listWorkspaceMentions("http://localhost:8000", "readme", "/workspace");

    expect(mentions).toHaveLength(1);
    expect(mentions[0]?.type).toBe("file");
  });
});

describe("listBrowserTabMentions", () => {
  it("queries browser tab mentions for a conversation", async () => {
    mockFetchJson([{ type: "browser_tab", id: "t1", label: "Tab", token: "tk", browser_id: "b1", tab_id: "t1", page_id: "p1", display_path: "example.com", score: 1 }]);

    const mentions = await listBrowserTabMentions("http://localhost:8000", "conv1", "tab");

    expect(mentions).toHaveLength(1);
    expect(mentions[0]?.type).toBe("browser_tab");
  });
});

describe("getGitStatus", () => {
  it("fetches git status", async () => {
    mockFetchJson({ branch: "main", ahead: 0, behind: 0, modified_count: 1, untracked_count: 0, is_dirty: true });

    const status = await getGitStatus("http://localhost:8000");

    expect(status.branch).toBe("main");
  });
});

describe("listGitBranches", () => {
  it("fetches branch list", async () => {
    mockFetchJson({ is_repo: true, current: "main", branches: [{ name: "main", kind: "local", current: true }] });

    const result = await listGitBranches("http://localhost:8000");

    expect(result.branches).toHaveLength(1);
  });
});

describe("getGitRecentActions", () => {
  it("fetches recent git actions", async () => {
    mockFetchJson({ is_repo: true, actions: [], errors: [] });

    const result = await getGitRecentActions("http://localhost:8000");

    expect(result.is_repo).toBe(true);
  });
});

describe("listWorkspaceProjects", () => {
  it("fetches workspace projects", async () => {
    mockFetchJson({ projects: [{ name: "proj", path: "/proj", is_repo: true }] });

    const result = await listWorkspaceProjects("http://localhost:8000");

    expect(result.projects).toHaveLength(1);
  });
});

describe("listGitPullRequests", () => {
  it("fetches pull requests", async () => {
    mockFetchJson({ is_repo: true, viewerLogin: "user", pullRequests: [], errors: [] });

    const result = await listGitPullRequests("http://localhost:8000");

    expect(result.is_repo).toBe(true);
  });
});

describe("generateGitCommitMessage", () => {
  it("fetches generated commit message", async () => {
    mockFetchJson({ message: "feat: add feature" });

    const result = await generateGitCommitMessage("http://localhost:8000", "/workspace");

    expect(result.message).toBe("feat: add feature");
  });
});

describe("gitCreateBranch", () => {
  it("posts branch creation", async () => {
    mockFetchJson({ success: true, branch: "feature" });

    const result = await gitCreateBranch("http://localhost:8000", "/workspace", "feature");

    expect(result.success).toBe(true);
  });
});

describe("gitCreateWorktree", () => {
  it("posts worktree creation", async () => {
    mockFetchJson({ success: true, branch: "feature", path: "/worktree" });

    const result = await gitCreateWorktree("http://localhost:8000", "/workspace", { name: "feature", branch: "main" });

    expect(result.success).toBe(true);
  });
});

describe("gitCheckoutBranch", () => {
  it("posts checkout", async () => {
    mockFetchJson({ success: true, branch: "feature" });

    const result = await gitCheckoutBranch("http://localhost:8000", "/workspace", "feature", "local");

    expect(result.success).toBe(true);
  });
});

describe("gitCommit", () => {
  it("creates approval and posts commit", async () => {
    window.personAgent = {
      security: {
        createActionApproval: vi.fn().mockResolvedValue({
          approval_id: "a1",
          action_kind: "workspace.git_commit",
          args_hash: "h1",
          expires_at: 123,
          approval_signature: "sig",
        }),
      },
    } as unknown as Window["personAgent"];
    mockFetchJson({ success: true, sha: "abc123" });

    const result = await gitCommit("http://localhost:8000", "/workspace", "feat: add feature");

    expect(result.success).toBe(true);
  });
});

describe("gitPush", () => {
  it("creates approval and posts push", async () => {
    window.personAgent = {
      security: {
        createActionApproval: vi.fn().mockResolvedValue({
          approval_id: "a1",
          action_kind: "workspace.git_push",
          args_hash: "h1",
          expires_at: 123,
          approval_signature: "sig",
        }),
      },
    } as unknown as Window["personAgent"];
    mockFetchJson({ success: true });

    const result = await gitPush("http://localhost:8000", "/workspace");

    expect(result.success).toBe(true);
  });
});

describe("gitOpenPr", () => {
  it("creates approval and posts pr", async () => {
    window.personAgent = {
      security: {
        createActionApproval: vi.fn().mockResolvedValue({
          approval_id: "a1",
          action_kind: "workspace.git_pr",
          args_hash: "h1",
          expires_at: 123,
          approval_signature: "sig",
        }),
      },
    } as unknown as Window["personAgent"];
    mockFetchJson({ url: "https://github.com/org/repo/pull/1" });

    const result = await gitOpenPr("http://localhost:8000", "/workspace");

    expect(result.url).toBe("https://github.com/org/repo/pull/1");
  });
});

describe("gitCreatePullRequestComment", () => {
  it("posts a PR comment", async () => {
    mockFetchJson({ success: true });

    const result = await gitCreatePullRequestComment("http://localhost:8000", {
      workspaceRoot: "/workspace",
      number: 1,
      body: "LGTM",
      kind: "human_review",
    });

    expect(result.success).toBe(true);
  });
});
