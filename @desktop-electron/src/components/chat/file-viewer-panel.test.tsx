import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listWorkspaceFiles, readWorkspaceFile } from "../../api/client";
import { useAppStore } from "../../stores/app-store";
import { useChatStore } from "../../stores/chat-store";
import { TooltipProvider } from "../ui/tooltip";
import { FileViewerPanel } from "./file-viewer-panel";

vi.mock("../../api/client", () => ({
  approvePlan: vi.fn(),
  cancelPlan: vi.fn(),
  continuePlan: vi.fn(),
  forkConversation: vi.fn(),
  getConversation: vi.fn(),
  gitCreateWorktree: vi.fn(),
  listWorkspaceFiles: vi.fn().mockResolvedValue([]),
  readWorkspaceFile: vi.fn(),
  rejectTool: vi.fn(),
  streamApproveTool: vi.fn(),
  streamChatCompletion: vi.fn(),
  streamTeamChat: vi.fn(),
}));

const readWorkspaceFileMock = vi.mocked(readWorkspaceFile);
const listWorkspaceFilesMock = vi.mocked(listWorkspaceFiles);
const originalSendMessage = useChatStore.getState().sendMessage;

describe("FileViewerPanel", () => {
  beforeEach(() => {
    delete window.personAgent;
    readWorkspaceFileMock.mockReset();
    listWorkspaceFilesMock.mockReset();
    listWorkspaceFilesMock.mockResolvedValue([]);
    useAppStore.setState({
      baseUrl: "http://localhost:8000",
      selectedWorkspace: "/workspaces/Eval",
    });
    useChatStore.setState({
      sendMessage: originalSendMessage,
      isStreaming: false,
      messages: [],
      composerAnnotations: [],
    });
  });

  it("renders HTML files as a preview by default and can switch to code", async () => {
    readWorkspaceFileMock.mockResolvedValue({
      path: "/workspaces/Eval/tree.html",
      name: "tree.html",
      content: "<h1>Tree</h1>",
    });

    renderFileViewer("tree.html", "/workspaces/Eval/tree.html");

    expect(await screen.findByTitle("Preview tree.html")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View code" }));

    await waitFor(() => expect(screen.queryByTitle("Preview tree.html")).not.toBeInTheDocument());
    expect(screen.getByText("1 lines")).toBeInTheDocument();
  });

  it("turns the active markdown file into a structured markdown view", async () => {
    readWorkspaceFileMock.mockResolvedValue({
      path: "/workspaces/Eval/README.md",
      name: "README.md",
      content: "# Roadmap\n\n- First step",
    });

    renderFileViewer("README.md", "/workspaces/Eval/README.md");
    fireEvent.click(screen.getByRole("button", { name: "Markdown preview" }));

    expect(await screen.findByRole("heading", { name: "Roadmap" })).toBeInTheDocument();
    expect(screen.getByText("First step")).toBeInTheDocument();
  });

  it("opens a workspace file picker from the plus button", async () => {
    const onOpenFile = vi.fn();
    readWorkspaceFileMock.mockResolvedValue({
      path: "/workspaces/Eval/README.md",
      name: "README.md",
      content: "# README",
    });
    listWorkspaceFilesMock.mockResolvedValue([
      { name: "notes.txt", isDirectory: false, path: "/workspaces/Eval/notes.txt" },
    ]);

    renderFileViewer("README.md", "/workspaces/Eval/README.md", { onOpenFile });

    fireEvent.click(screen.getByRole("button", { name: "Add file" }));
    fireEvent.click(await screen.findByRole("button", { name: "notes.txt" }));

    expect(onOpenFile).toHaveBeenCalledWith({
      name: "notes.txt",
      isDirectory: false,
      path: "/workspaces/Eval/notes.txt",
    });
  });

  it("selects a line range and attaches a persistent annotation to the composer", async () => {
    const sendMessage = vi.fn();
    useChatStore.setState({ sendMessage, composerAnnotations: [] });
    readWorkspaceFileMock.mockResolvedValue({
      path: "/workspaces/Eval/hello.py",
      name: "hello.py",
      content: "one\ntwo\nthree\nfour\nfive",
    });

    renderFileViewer("hello.py", "/workspaces/Eval/hello.py");

    fireEvent.click(screen.getByRole("button", { name: "Request edits" }));
    fireEvent.click(await screen.findByRole("button", { name: "Select line 2" }));
    expect(screen.queryByPlaceholderText("Write a Annotation...")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Select line 4" }));
    fireEvent.change(screen.getByPlaceholderText("Write a Annotation..."), {
      target: { value: "Refactor this block" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add annotation 2-4" }));

    expect(screen.getAllByText("@Annotation#1").length).toBeGreaterThan(0);
    expect(sendMessage).not.toHaveBeenCalled();
    expect(useChatStore.getState().composerAnnotations).toMatchObject([
      {
        id: 1,
        displayPath: "hello.py",
        filePath: "/workspaces/Eval/hello.py",
        startLine: 2,
        endLine: 4,
        text: "Refactor this block",
        selectedLines: "2: two\n3: three\n4: four",
      },
    ]);
  });

  it("removes a persisted annotation from the viewer chip and the composer store", async () => {
    readWorkspaceFileMock.mockResolvedValue({
      path: "/workspaces/Eval/hello.py",
      name: "hello.py",
      content: "one\ntwo\nthree\nfour\nfive",
    });

    renderFileViewer("hello.py", "/workspaces/Eval/hello.py");

    fireEvent.click(screen.getByRole("button", { name: "Request edits" }));
    fireEvent.click(await screen.findByRole("button", { name: "Select line 2" }));
    fireEvent.click(screen.getByRole("button", { name: "Select line 4" }));
    fireEvent.change(screen.getByPlaceholderText("Write a Annotation..."), {
      target: { value: "Refactor this block" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add annotation 2-4" }));

    fireEvent.click(screen.getByRole("button", { name: "Remove @Annotation#1" }));

    expect(useChatStore.getState().composerAnnotations).toEqual([]);
    expect(screen.queryByText("@Annotation#1")).not.toBeInTheDocument();
  });

  it("syncs composer annotation removal back into the file viewer selection", async () => {
    readWorkspaceFileMock.mockResolvedValue({
      path: "/workspaces/Eval/hello.py",
      name: "hello.py",
      content: "one\ntwo\nthree\nfour\nfive",
    });

    renderFileViewer("hello.py", "/workspaces/Eval/hello.py");

    fireEvent.click(screen.getByRole("button", { name: "Request edits" }));
    fireEvent.click(await screen.findByRole("button", { name: "Select line 2" }));
    fireEvent.click(screen.getByRole("button", { name: "Select line 4" }));
    fireEvent.change(screen.getByPlaceholderText("Write a Annotation..."), {
      target: { value: "Refactor this block" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add annotation 2-4" }));

    act(() => useChatStore.getState().removeComposerAnnotation(1));

    await waitFor(() => expect(screen.queryByText("@Annotation#1")).not.toBeInTheDocument());
  });

  it("blocks new selections that overlap persisted annotations", async () => {
    readWorkspaceFileMock.mockResolvedValue({
      path: "/workspaces/Eval/hello.py",
      name: "hello.py",
      content: "one\ntwo\nthree\nfour\nfive\nsix",
    });

    renderFileViewer("hello.py", "/workspaces/Eval/hello.py");

    fireEvent.click(screen.getByRole("button", { name: "Request edits" }));
    fireEvent.click(await screen.findByRole("button", { name: "Select line 2" }));
    fireEvent.click(screen.getByRole("button", { name: "Select line 4" }));
    fireEvent.change(screen.getByPlaceholderText("Write a Annotation..."), {
      target: { value: "Refactor this block" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add annotation 2-4" }));

    expect(screen.getByRole("button", { name: "Select line 2" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Select line 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Select line 5" }));

    expect(screen.queryByText("L1-5")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Write a Annotation...")).not.toBeInTheDocument();
    expect(useChatStore.getState().composerAnnotations).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Select line 5" }));
    fireEvent.click(screen.getByRole("button", { name: "Select line 6" }));

    expect(screen.getByText("L5-6")).toBeInTheDocument();
  });

  it("keeps multiple unsubmitted selections independent and lets each one be canceled", async () => {
    readWorkspaceFileMock.mockResolvedValue({
      path: "/workspaces/Eval/notes.md",
      name: "notes.md",
      content: Array.from({ length: 110 }, (_, index) => `line ${index + 1}`).join("\n"),
    });

    renderFileViewer("notes.md", "/workspaces/Eval/notes.md");

    fireEvent.click(screen.getByRole("button", { name: "Request edits" }));
    fireEvent.click(await screen.findByRole("button", { name: "Select line 2" }));
    expect(screen.queryByPlaceholderText("Write a Annotation...")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Select line 45" }));

    expect(screen.getByText("L2-45")).toBeInTheDocument();
    const line45Row = screen.getByRole("button", { name: "Select line 45" }).closest("tr");
    const draftRow = screen.getByRole("row", { name: /L2-45/ });
    expect(line45Row).not.toBeNull();
    expect(draftRow.compareDocumentPosition(line45Row as HTMLTableRowElement) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Select line 63" }));
    expect(screen.getAllByPlaceholderText("Write a Annotation...")).toHaveLength(1);
    expect(screen.getByText("L2-45")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Select line 102" }));
    expect(screen.getByText("L63-102")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Select line 56" }));
    fireEvent.click(screen.getByRole("button", { name: "Select line 98" }));

    expect(screen.getByText("L56-98")).toBeInTheDocument();
    expect(screen.getAllByPlaceholderText("Write a Annotation...")).toHaveLength(3);

    fireEvent.click(screen.getByRole("button", { name: "Cancel selection 63-102" }));

    expect(screen.queryByText("L63-102")).not.toBeInTheDocument();
    expect(screen.getByText("L2-45")).toBeInTheDocument();
    expect(screen.getByText("L56-98")).toBeInTheDocument();
    expect(screen.getAllByPlaceholderText("Write a Annotation...")).toHaveLength(2);
  });
});

function renderFileViewer(name: string, path: string, props: { onOpenFile?: Parameters<typeof FileViewerPanel>[0]["onOpenFile"] } = {}) {
  return render(
    <TooltipProvider>
      <FileViewerPanel
        tabs={[{ name, path }]}
        activePath={path}
        workspaceRoot="/workspaces/Eval"
        onOpenFile={props.onOpenFile ?? (() => undefined)}
        onSelectTab={() => undefined}
        onCloseTab={() => undefined}
        onClose={() => undefined}
      />
    </TooltipProvider>,
  );
}
