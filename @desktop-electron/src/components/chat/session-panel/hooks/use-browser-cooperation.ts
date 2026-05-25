import { useEffect } from "react";
import {
  connectSessionBrowserCooperation,
  ingestSessionBrowserEvents,
  setSessionBrowserCooperation,
  type SessionBrowserCooperationEvent,
  type SessionBrowserCooperationMode,
  type SessionBrowserCooperationWsEvent,
  type SessionBrowserView,
} from "../../../../api/client";
import {
  type BrowserState,
  type BrowserTab,
  browserCooperationFromView,
  recordValue,
} from "../helpers/helpers";

export interface CooperationDeps {
  browserForTab: (tabId: string) => BrowserState | undefined;
  updateBrowserTab: (tabId: string, updater: (browser: BrowserState) => BrowserState) => void;
  setBrowserError: (tabId: string, error: unknown, requestId?: number) => void;
  cooperationSocketsRef: React.MutableRefObject<Record<string, WebSocket>>;
  activeTab: BrowserTab;
  baseUrl: string;
  conversationId: string | undefined;
  visible: boolean;
  approvePendingTool: () => Promise<void>;
  rejectPendingTool: () => Promise<void>;
}

export interface CooperationApi {
  applyBrowserCooperationPatch: (tabId: string, cooperation: SessionBrowserView["cooperation"]) => void;
  setBrowserCooperationMode: (tabId: string, mode: SessionBrowserCooperationMode | "off") => Promise<void>;
  decideBrowserProposal: (
    tabId: string,
    proposal: Record<string, unknown>,
    decision: "approve" | "deny" | "dismiss",
  ) => Promise<void>;
  recordBrowserEvents: (tabId: string, events: SessionBrowserCooperationEvent[]) => Promise<void>;
}

export function useBrowserCooperation(deps: CooperationDeps): CooperationApi {
  const {
    browserForTab,
    updateBrowserTab,
    setBrowserError,
    cooperationSocketsRef,
    activeTab,
    baseUrl,
    conversationId,
    visible,
    approvePendingTool,
    rejectPendingTool,
  } = deps;

  const applyBrowserCooperationPatch = (
    tabId: string,
    cooperation: SessionBrowserView["cooperation"],
  ) => {
    if (!cooperation) return;
    updateBrowserTab(tabId, (current) => {
      const view = current.view;
      if (!view) return current;
      const currentCooperation = browserCooperationFromView(view);
      const nextCooperation = { ...currentCooperation, ...cooperation };
      return {
        ...current,
        view: {
          ...view,
          cooperation: nextCooperation,
          workspace_state: view.workspace_state
            ? { ...view.workspace_state, cooperation: nextCooperation }
            : { cooperation: nextCooperation },
          browser_snapshot: view.browser_snapshot
            ? { ...view.browser_snapshot, cooperation: nextCooperation }
            : view.browser_snapshot,
        },
      };
    });
  };

  const applyBrowserCooperationWsEvent = (tabId: string, event: SessionBrowserCooperationWsEvent) => {
    if (event.type === "error") return;
    const message = event as SessionBrowserCooperationWsEvent & Record<string, unknown>;
    const statePatch = recordValue(message.state_patch);
    const stateCooperation = statePatch.cooperation;
    const cooperationPatch =
      stateCooperation && typeof stateCooperation === "object" && !Array.isArray(stateCooperation)
        ? (stateCooperation as SessionBrowserView["cooperation"])
        : "cooperation" in event
          ? event.cooperation
          : undefined;
    const debugPatch =
      event.type === "snapshot" || event.type === "timeline.patch" || event.type === "event_batch.accepted"
        ? {
            ...(cooperationPatch ?? {}),
            ...(Array.isArray(message.raw_events) ? { raw_events: message.raw_events } : {}),
            ...(Array.isArray(message.useful_timeline) ? { useful_timeline: message.useful_timeline } : {}),
            ...(Array.isArray(message.recent_user_events) ? { recent_user_events: message.recent_user_events } : {}),
            ...(Array.isArray(message.recent_agent_events) ? { recent_agent_events: message.recent_agent_events } : {}),
            ...(Array.isArray(message.pending_action_proposals)
              ? { pending_action_proposals: message.pending_action_proposals }
              : {}),
            ...(message.page_state ? { page_state: message.page_state } : {}),
          }
        : cooperationPatch;
    applyBrowserCooperationPatch(tabId, debugPatch as SessionBrowserView["cooperation"]);
  };

  useEffect(() => {
    return () => {
      Object.values(cooperationSocketsRef.current).forEach((socket) => socket.close());
      cooperationSocketsRef.current = {};
    };
  }, [cooperationSocketsRef]);

  useEffect(() => {
    const browser = activeTab.browser;
    const enabled = Boolean(browserCooperationFromView(browser?.view)?.enabled);
    if (!visible || !baseUrl || !conversationId || !browser || !enabled) return;
    const socketKey = browser.browserId;
    const existing = cooperationSocketsRef.current[socketKey];
    if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) return;
    const socket = connectSessionBrowserCooperation(baseUrl, conversationId, browser.browserId, {
      onMessage: (event) => applyBrowserCooperationWsEvent(activeTab.id, event),
      onClose: () => {
        if (cooperationSocketsRef.current[socketKey] === socket) delete cooperationSocketsRef.current[socketKey];
      },
    });
    cooperationSocketsRef.current[socketKey] = socket;
    const pingInterval = window.setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "ping" }));
      }
    }, 2000);
    return () => {
      window.clearInterval(pingInterval);
      if (cooperationSocketsRef.current[socketKey] === socket) delete cooperationSocketsRef.current[socketKey];
      socket.close();
    };
  }, [
    activeTab.id,
    activeTab.browser?.browserId,
    baseUrl,
    browserCooperationFromView(activeTab.browser?.view)?.enabled,
    conversationId,
    visible,
    cooperationSocketsRef,
  ]);

  const setBrowserCooperationMode = async (
    tabId: string,
    mode: SessionBrowserCooperationMode | "off",
  ) => {
    const browser = browserForTab(tabId);
    if (!browser || !baseUrl || !conversationId) return;
    const enabled = mode !== "off";
    const nextMode = enabled ? mode : browserCooperationFromView(browser.view)?.mode ?? "observe_only";
    const socket = cooperationSocketsRef.current[browser.browserId];
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "mode.set", enabled, mode: nextMode }));
      return;
    }
    try {
      const result = await setSessionBrowserCooperation(baseUrl, conversationId, browser.browserId, {
        enabled,
        mode: nextMode,
      });
      applyBrowserCooperationPatch(tabId, result.cooperation);
    } catch (error) {
      setBrowserError(tabId, error);
    }
  };

  const decideBrowserProposal = async (
    tabId: string,
    proposal: Record<string, unknown>,
    decision: "approve" | "deny" | "dismiss",
  ) => {
    const browser = browserForTab(tabId);
    if (!browser) return;
    const proposalId = String(proposal.proposal_id ?? proposal.id ?? "");
    if (!proposalId) return;
    const socket = cooperationSocketsRef.current[browser.browserId];
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: `proposal.${decision}`, proposal_id: proposalId }));
    }
    if (decision === "approve") {
      await approvePendingTool();
    } else if (decision === "deny") {
      await rejectPendingTool();
    }
  };

  const recordBrowserEvents = async (tabId: string, events: SessionBrowserCooperationEvent[]) => {
    const browser = browserForTab(tabId);
    if (!browser || !baseUrl || !conversationId || !events.length) return;
    if (!browserCooperationFromView(browser.view)?.enabled) return;
    const socket = cooperationSocketsRef.current[browser.browserId];
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "event_batch", events }));
      return;
    }
    try {
      const result = await ingestSessionBrowserEvents(baseUrl, conversationId, browser.browserId, events);
      applyBrowserCooperationPatch(tabId, result.state_patch.cooperation);
    } catch {
      // Event ingestion is best-effort; normal browsing should not be interrupted.
    }
  };

  return {
    applyBrowserCooperationPatch,
    setBrowserCooperationMode,
    decideBrowserProposal,
    recordBrowserEvents,
  };
}
