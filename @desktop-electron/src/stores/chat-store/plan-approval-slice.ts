import {
  approvePlan,
  cancelPlan,
  continuePlan,
} from "../../api/client";
import { errorMessage } from "../../api/errors";
import { useAppStore } from "../app-store";
import type { ChatSet, ChatGet } from "./internal";
import { setConversationStatus } from "./internal";
import { updatePlanApprovalArtifact } from "./streaming-helpers";

export function createPlanApprovalSlice(
  set: ChatSet,
  get: ChatGet,
) {
  return {
    isProcessingPlanDecision: false,

    approvePendingPlan: async (feedback?: string) => {
      const pending = get().pendingPlanApproval;
      if (!pending || get().isStreaming || get().isProcessingPlanDecision) return;
      set({ isProcessingPlanDecision: true });
      try {
        const response = await approvePlan(useAppStore.getState().baseUrl, {
          conversationId: pending.conversationId,
          approvalId: pending.approvalId,
          feedback,
        });
        set((state) => ({
          pendingPlanApproval: undefined,
          error: undefined,
          messages: updatePlanApprovalArtifact(state.messages, pending.approvalId, response.plan_status ?? "approved", feedback),
        }));
        setConversationStatus(set, pending.conversationId, "running");
        const injected = response.injected_message?.trim();
        if (injected) await get().sendMessage(injected);
      } catch (error) {
        set({ error: errorMessage(error) });
        setConversationStatus(set, pending.conversationId, "error");
      } finally {
        set({ isProcessingPlanDecision: false });
      }
    },

    continuePendingPlan: async (feedback?: string) => {
      const pending = get().pendingPlanApproval;
      if (!pending || get().isStreaming || get().isProcessingPlanDecision) return;
      set({ isProcessingPlanDecision: true });
      try {
        const response = await continuePlan(useAppStore.getState().baseUrl, {
          conversationId: pending.conversationId,
          approvalId: pending.approvalId,
          feedback,
        });
        set((state) => ({
          pendingPlanApproval: undefined,
          error: undefined,
          messages: updatePlanApprovalArtifact(state.messages, pending.approvalId, response.plan_status ?? "draft", feedback),
        }));
        setConversationStatus(set, pending.conversationId, "running");
        const message = response.suggested_message?.trim();
        if (message) await get().sendMessage(message);
      } catch (error) {
        set({ error: errorMessage(error) });
        setConversationStatus(set, pending.conversationId, "error");
      } finally {
        set({ isProcessingPlanDecision: false });
      }
    },

    cancelPendingPlan: async (feedback?: string) => {
      const pending = get().pendingPlanApproval;
      if (!pending || get().isStreaming || get().isProcessingPlanDecision) return;
      set({ isProcessingPlanDecision: true });
      try {
        await cancelPlan(useAppStore.getState().baseUrl, {
          conversationId: pending.conversationId,
          approvalId: pending.approvalId,
          feedback,
        });
        set((state) => ({
          pendingPlanApproval: undefined,
          error: undefined,
          messages: updatePlanApprovalArtifact(state.messages, pending.approvalId, "cancelled", feedback),
        }));
        setConversationStatus(set, pending.conversationId, "idle");
      } catch (error) {
        set({ error: errorMessage(error) });
        setConversationStatus(set, pending.conversationId, "error");
      } finally {
        set({ isProcessingPlanDecision: false });
      }
    },
  };
}
