import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTerminalStore } from "../../stores/terminal-store";
import { TerminalPanel } from "./terminal-panel";

vi.mock("./terminal-view", () => ({
  TerminalView: ({ instanceId }: { instanceId: string }) => (
    <div data-testid="terminal-view" data-instance-id={instanceId} />
  ),
}));

describe("TerminalPanel", () => {
  beforeEach(() => {
    useTerminalStore.setState({
      leftPane: { instances: [], activeInstanceId: null, nextId: 1 },
      rightPane: null,
      splitMode: false,
      open: false,
      pendingSnippet: null,
      snippetNonce: 0,
    });
  });

  it("renders without unstable external-store snapshots when no right pane exists", () => {
    render(<TerminalPanel open={false} />);

    expect(screen.getByTestId("terminal-panel")).toBeInTheDocument();
  });
});
