import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PullRequestSummary } from "../../api/client";
import { useAppStore } from "../../stores/app-store";
import { useGitBranches, useGitCreatePullRequestComment, useGitPullRequests, useWorkspaceProjects } from "../../stores/git-store";
import { OpenPrWorkspace } from "./open-pr-workspace";

vi.mock("../../stores/git-store", () => ({
  useGitBranches: vi.fn(),
  useGitPullRequests: vi.fn(),
  useWorkspaceProjects: vi.fn(),
  useGitCreatePullRequestComment: vi.fn(),
}));

const useGitBranchesMock = vi.mocked(useGitBranches);
const useGitPullRequestsMock = vi.mocked(useGitPullRequests);
const useWorkspaceProjectsMock = vi.mocked(useWorkspaceProjects);
const useGitCreatePullRequestCommentMock = vi.mocked(useGitCreatePullRequestComment);

describe("OpenPrWorkspace", () => {
  const createComment = vi.fn();

  beforeEach(() => {
    createComment.mockReset();
    createComment.mockResolvedValue({ success: true });
    useAppStore.setState({
      selectedWorkspace: "/home/user/PersonAgent",
      recentWorkspaces: ["/home/user/PersonAgent", "/home/user/WebPilot"],
      section: "openPr",
    });
    useGitBranchesMock.mockReturnValue({
      data: {
        is_repo: true,
        current: "main",
        branches: [
          { name: "main", kind: "local", current: true },
          { name: "feature/context-attachments", kind: "local", current: false },
          { name: "fix/git-feedback", kind: "remote", current: false },
        ],
      },
      error: null,
      isLoading: false,
      isFetching: false,
      refetch: vi.fn(),
    } as never);
    useGitPullRequestsMock.mockReturnValue({
      data: {
        is_repo: true,
        viewerLogin: "levy",
        pullRequests: pullRequestsFixture,
        errors: [],
      },
      error: null,
      isLoading: false,
      isFetching: false,
      refetch: vi.fn(),
    } as never);
    useWorkspaceProjectsMock.mockReturnValue({
      data: {
        projects: [
          { name: "PersonAgent", path: "/home/user/PersonAgent", is_repo: true },
          { name: "WebPilot", path: "/home/user/WebPilot", is_repo: true },
        ],
      },
      error: null,
      isLoading: false,
      isFetching: false,
      refetch: vi.fn(),
    } as never);
    useGitCreatePullRequestCommentMock.mockReturnValue({
      mutateAsync: createComment,
      isPending: false,
    } as never);
  });

  it("renders the live pull request queue without static brief cards", () => {
    render(<OpenPrWorkspace />);

    expect(screen.getByTestId("open-pr-workspace")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Open Pull Requests" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Add context attachments to chat completion/i })).toBeInTheDocument();
    expect(screen.queryByText("AI brief")).not.toBeInTheDocument();
    expect(screen.queryByText("Review focus")).not.toBeInTheDocument();
    expect(screen.queryByTestId("pr-detail-panel")).not.toBeInTheDocument();
  });

  it("opens and closes the right detail panel when the same pull request is selected", () => {
    render(<OpenPrWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: /Add context attachments to chat completion/i }));

    expect(screen.getByTestId("pr-detail-panel")).toHaveAttribute("data-open", "true");
    expect(screen.getByText("PR context")).toBeInTheDocument();
    expect(screen.getByText("Changed files")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Add context attachments to chat completion/i }));

    expect(screen.getByTestId("pr-detail-panel")).toHaveAttribute("data-open", "false");
  });

  it("filters pull requests by project, branch, mine and flagged", () => {
    render(<OpenPrWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Mine" }));

    expect(screen.getByRole("button", { name: /Add context attachments to chat completion/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Stabilize Git action menu feedback/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "All" }));
    fireEvent.click(screen.getByRole("button", { name: "Flagged" }));

    expect(screen.getByRole("button", { name: /Add context attachments to chat completion/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Stabilize Git action menu feedback/i })).not.toBeInTheDocument();
  });

  it("creates standardized pull request comments", async () => {
    render(<OpenPrWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: /Add context attachments to chat completion/i }));
    fireEvent.click(screen.getByRole("button", { name: "AI analysis" }));
    fireEvent.change(screen.getByPlaceholderText("Write a PR comment..."), {
      target: { value: "The DTO boundary needs one more regression test." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Send comment/i }));

    await waitFor(() => {
      expect(createComment).toHaveBeenCalledWith({
        number: 84,
        body: "The DTO boundary needs one more regression test.",
        kind: "ai_review",
        status: null,
      });
    });
  });

  it("starts review mode and replaces the visible diff when a file is clicked", () => {
    render(<OpenPrWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: /Add context attachments to chat completion/i }));
    fireEvent.click(screen.getByRole("button", { name: /Start Review/i }));

    expect(screen.getByText("Files changed")).toBeInTheDocument();
    expect(screen.getByTestId("open-diff-card-chat-dto")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Open diff for .*chat_completion.py/i }));

    expect(screen.getByTestId("open-diff-card-chat-completion")).toBeInTheDocument();
    expect(screen.queryByTestId("open-diff-card-chat-dto")).not.toBeInTheDocument();
  });
});

const pullRequestsFixture: PullRequestSummary[] = [
  {
    id: "pr-84",
    project: "PersonAgent",
    projectPath: "/home/user/PersonAgent",
    number: 84,
    title: "Add context attachments to chat completion",
    author: "levy",
    branch: "feature/context-attachments",
    baseBranch: "main",
    updated: "18m ago",
    updatedAt: "2026-04-28T15:20:00Z",
    url: "https://github.example/pr/84",
    status: "needs_review",
    statusLabel: "Needs review",
    risk: "Medium",
    checkSummary: "8 passing",
    description: "Carries selected context into the backend prompt builder.",
    labels: ["backend", "prompt"],
    commentsCount: 2,
    comments: [
      {
        id: "comment-1",
        kind: "human_review",
        source: "human",
        author: "reviewer",
        body: "Please inspect DTO serialization.",
        createdAt: "2026-04-28T15:21:00Z",
      },
      {
        id: "comment-2",
        kind: "ai_review",
        source: "ai",
        author: "personagent",
        body: "PersonAgent AI analysis: prompt-surface tests need review.",
        createdAt: "2026-04-28T15:22:00Z",
      },
    ],
    files: [
      {
        id: "chat-dto",
        path: "@backend/src/personagent/application/dto/chat_dto.py",
        changeType: "modified",
        additions: 42,
        deletions: 8,
        summary: "Attachment schema enters the request boundary.",
        lines: [
          { number: "44", kind: "context", content: "class ChatCompletionRequest(BaseModel):" },
          { number: "45", kind: "add", content: "context_attachments: list[ContextAttachmentDto]" },
        ],
      },
      {
        id: "chat-completion",
        path: "@backend/src/personagent/application/use_cases/chat_completion.py",
        changeType: "modified",
        additions: 64,
        deletions: 22,
        summary: "Prompt builder receives extra contextual surfaces.",
        lines: [{ number: "118", kind: "add", content: "messages = self.prompt_builder.build(...)" }],
      },
    ],
    isMine: true,
    isFlagged: true,
    reviewDecision: "REVIEW_REQUIRED",
    mergeState: "UNKNOWN",
  },
  {
    id: "pr-79",
    project: "PersonAgent",
    projectPath: "/home/user/PersonAgent",
    number: 79,
    title: "Stabilize Git action menu feedback",
    author: "teammate",
    branch: "fix/git-feedback",
    baseBranch: "main",
    updated: "41m ago",
    updatedAt: "2026-04-28T14:57:00Z",
    status: "approved",
    statusLabel: "Approved",
    risk: "Low",
    checkSummary: "12 passing",
    description: "Keeps commit, push and open PR feedback visible.",
    labels: ["git", "ui"],
    commentsCount: 0,
    comments: [],
    files: [
      {
        id: "git-action-button",
        path: "@desktop-electron/src/components/git/git-action-button.tsx",
        changeType: "modified",
        additions: 92,
        deletions: 28,
        summary: "Operation feedback persists inside dropdown.",
        lines: [],
      },
    ],
    isMine: false,
    isFlagged: false,
    reviewDecision: "APPROVED",
    mergeState: "CLEAN",
  },
];
