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
          planContent: "## Plano\n\n1. Atualizar backend.",
          planStatus: "awaiting_approval",
        }}
      />,
    );

    expect(screen.getByText("Plano")).toBeInTheDocument();
    expect(screen.getByText("Atualizar backend.")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Feedback opcional"), {
      target: { value: "Inclua testes" },
    });
    fireEvent.click(screen.getByText("Proceder"));
    fireEvent.click(screen.getByText("Continuar planejando"));
    fireEvent.click(screen.getByText("Cancelar"));

    expect(proceed).toHaveBeenCalledWith("Inclua testes");
    expect(continuePlanning).toHaveBeenCalledWith("Inclua testes");
    expect(cancel).toHaveBeenCalledWith("Inclua testes");
  });
});

