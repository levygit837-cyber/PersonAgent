import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listWorkspaceFiles } from "../../api/client";
import { useAppStore } from "../../stores/app-store";
import { TooltipProvider } from "../ui/tooltip";
import { WorkspacePanel } from "./workspace-panel";

vi.mock("../../api/client", () => ({
  listWorkspaceFiles: vi.fn(),
  readWorkspaceFile: vi.fn(),
}));

const listWorkspaceFilesMock = vi.mocked(listWorkspaceFiles);

describe("WorkspacePanel", () => {
  beforeEach(() => {
    listWorkspaceFilesMock.mockReset();
    useAppStore.setState({
      baseUrl: "http://localhost:8000",
      selectedWorkspace: "/workspaces/WebPilot",
    });
  });

  it("ignores stale file results from the previous workspace", async () => {
    const webPilotRequest = deferred<Array<{ name: string; isDirectory: boolean; path: string }>>();
    listWorkspaceFilesMock.mockImplementation((_baseUrl, _path, workspaceRoot) => {
      if (workspaceRoot === "/workspaces/WebPilot") return webPilotRequest.promise;
      return Promise.resolve([
        { name: "eval.ts", isDirectory: false, path: "/workspaces/Eval/eval.ts" },
      ]);
    });

    const { rerender } = renderWorkspacePanel("/workspaces/WebPilot");

    await waitFor(() => {
      expect(listWorkspaceFilesMock).toHaveBeenCalledWith(
        "http://localhost:8000",
        "/workspaces/WebPilot",
        "/workspaces/WebPilot",
      );
    });

    rerender(workspacePanelTree("/workspaces/Eval"));

    expect(await screen.findByText("eval.ts")).toBeInTheDocument();

    await act(async () => {
      webPilotRequest.resolve([
        { name: "webpilot.ts", isDirectory: false, path: "/workspaces/WebPilot/webpilot.ts" },
      ]);
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.queryByText("webpilot.ts")).not.toBeInTheDocument();
      expect(screen.getByText("eval.ts")).toBeInTheDocument();
    });
  });

  it("rejects file results that do not belong to the active workspace", async () => {
    listWorkspaceFilesMock.mockResolvedValue([
      { name: "webpilot.ts", isDirectory: false, path: "/workspaces/WebPilot/webpilot.ts" },
    ]);

    renderWorkspacePanel("/workspaces/Eval");

    expect(await screen.findByText("A listagem recebida não pertence ao workspace ativo.")).toBeInTheDocument();
    expect(screen.queryByText("webpilot.ts")).not.toBeInTheDocument();
  });

  it("opens a workspace file when a file row is clicked", async () => {
    const onOpenFile = vi.fn();
    listWorkspaceFilesMock.mockResolvedValue([
      { name: "hello.py", isDirectory: false, path: "/workspaces/Eval/hello.py" },
    ]);

    render(
      <TooltipProvider>
        <WorkspacePanel visible workspaceRoot="/workspaces/Eval" onClose={() => undefined} onOpenFile={onOpenFile} />
      </TooltipProvider>,
    );

    fireEvent.click(await screen.findByText("hello.py"));

    expect(onOpenFile).toHaveBeenCalledWith({
      name: "hello.py",
      isDirectory: false,
      path: "/workspaces/Eval/hello.py",
    });
  });
});

function renderWorkspacePanel(workspaceRoot: string) {
  return render(workspacePanelTree(workspaceRoot));
}

function workspacePanelTree(workspaceRoot: string) {
  return (
    <TooltipProvider>
      <WorkspacePanel visible workspaceRoot={workspaceRoot} onClose={() => undefined} />
    </TooltipProvider>
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}
