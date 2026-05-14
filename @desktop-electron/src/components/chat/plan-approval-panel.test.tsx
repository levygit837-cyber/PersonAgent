import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useChatStore } from "../../stores/chat-store";
import { PlanApprovalPanel } from "./plan-approval-panel";

describe("PlanApprovalPanel", () => {
  it("renders the markdown plan and dispatches the three plan decisions", () => {
    const proceed = vi.fn();
    const continuePlanning = vi.fn();
    const cancel = vi.fn();
    useChatStore.setState({
      isStreaming: false,
      approvePendingPlan: proceed,
      continuePendingPlan: continuePlanning,
      cancelPendingPlan: cancel,
    });

    render(
      <PlanApprovalPanel
        approval={{
          conversationId: "conversation-1",
          approvalId: "approval-1",
          planId: "plan-1",
          planContent: "## Plan\n\n1. Update the backend.",
          planStatus: "awaiting_approval",
        }}
      />,
    );

    expect(screen.getByText("Plan")).toBeInTheDocument();
    expect(screen.getByText("Update the backend.")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Optional feedback before deciding..."), {
      target: { value: "Include tests" },
    });
    fireEvent.click(screen.getByText("Proceed"));
    fireEvent.click(screen.getByText("Continue planning"));
    fireEvent.click(screen.getByText("Cancel"));

    expect(proceed).toHaveBeenCalledWith("Include tests");
    expect(continuePlanning).toHaveBeenCalledWith("Include tests");
    expect(cancel).toHaveBeenCalledWith("Include tests");
  });
});
