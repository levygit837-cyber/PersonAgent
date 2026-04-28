import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useAppStore } from "../../stores/app-store";
import { OpenPrWorkspace } from "./open-pr-workspace";

describe("OpenPrWorkspace", () => {
  beforeEach(() => {
    useAppStore.setState({
      selectedWorkspace: "/home/user/PersonAgent",
      section: "openPr",
    });
  });

  it("renders the mocked pull request queue and updates the preview", () => {
    render(<OpenPrWorkspace />);

    expect(screen.getByTestId("open-pr-workspace")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Open Pull Requests" })).toBeInTheDocument();
    expect(screen.getAllByText("Add context attachments to chat completion").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /Stabilize Git action menu feedback/i }));

    expect(screen.getByText("Low-risk UI patch. The main check is whether the popover preserves operation feedback while git status refreshes.")).toBeInTheDocument();
    expect(screen.getByText("Low risk")).toBeInTheDocument();
  });

  it("filters pull requests by project and branch", () => {
    render(<OpenPrWorkspace />);

    openFilterMenu("Project: PersonAgent");
    fireEvent.click(screen.getByRole("menuitemradio", { name: "WebPilot" }));

    expect(screen.getAllByText("Review browser execution flow split").length).toBeGreaterThan(0);
    expect(screen.queryByText("Add context attachments to chat completion")).not.toBeInTheDocument();

    openFilterMenu("Branch: All branches");
    fireEvent.click(screen.getByRole("menuitemradio", { name: "fix/upload-preview" }));

    expect(screen.getAllByText("Fix upload artifact previews").length).toBeGreaterThan(0);
    expect(screen.queryByText("Review browser execution flow split")).not.toBeInTheDocument();
  });

  it("starts review mode and replaces the visible diff when a file is clicked", () => {
    render(<OpenPrWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: /Start Review/i }));

    expect(screen.getByText("Files changed")).toBeInTheDocument();
    expect(screen.getByTestId("open-diff-card-chat-dto")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Open diff for .*chat_completion.py/i }));

    expect(screen.getByTestId("open-diff-card-chat-completion")).toBeInTheDocument();
    expect(screen.queryByTestId("open-diff-card-chat-dto")).not.toBeInTheDocument();
  });

  it("adds another file to the diff area by drag and drop", () => {
    render(<OpenPrWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: /Start Review/i }));

    const dataTransfer = createDataTransfer();
    fireEvent.dragStart(screen.getByRole("button", { name: /Open diff for .*input-dock.tsx/i }), { dataTransfer });
    fireEvent.dragOver(screen.getByTestId("pr-diff-dropzone"), { dataTransfer });
    fireEvent.drop(screen.getByTestId("pr-diff-dropzone"), { dataTransfer });

    expect(screen.getByTestId("open-diff-card-chat-dto")).toBeInTheDocument();
    expect(screen.getByTestId("open-diff-card-input-dock")).toBeInTheDocument();
  });

  it("expands the review agent and records a local review prompt", () => {
    render(<OpenPrWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: /Start Review/i }));

    expect(screen.getByRole("dialog", { name: /Review Agent/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Expand Review Agent/i }));

    const input = screen.getByPlaceholderText("Ask the PR agent...");
    fireEvent.change(input, { target: { value: "Find regressions in this file" } });
    fireEvent.click(screen.getByRole("button", { name: /Send review agent message/i }));

    expect(screen.getByText("Find regressions in this file")).toBeInTheDocument();
    expect(screen.getByText(/I will review dto\/chat_dto.py in PR #84/)).toBeInTheDocument();
  });
});

function createDataTransfer() {
  const store = new Map<string, string>();
  return {
    dropEffect: "copy",
    effectAllowed: "copy",
    getData: (type: string) => store.get(type) ?? "",
    setData: (type: string, value: string) => {
      store.set(type, value);
    },
  };
}

function openFilterMenu(name: string) {
  fireEvent.pointerDown(screen.getByRole("button", { name }), { button: 0, ctrlKey: false, pointerType: "mouse" });
}
