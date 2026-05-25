import type {
  SessionBrowserElement,
} from "../../../../api/client";
import type { ToolBlockStatus, ToolBlockUi } from "../../../../types/chat";
import {
  type BrowserElementMetadata,
  type BrowserState,
  type BrowserVisualEffect,
  type BrowserVisualEvent,
  browserStringValue,
  normalizeBrowserElementMetadata,
  numericValue,
  recordArray,
  recordValue,
} from "./helpers";

export function browserToolEventFromBlock(block: ToolBlockUi): BrowserVisualEvent | undefined {
  const effect = browserToolEffect(block);
  if (!effect) return undefined;
  const data = block.data ?? {};
  const lastAction = recordValue(data.last_action);
  const result = recordValue(lastAction.result);
  const elements = browserToolElements(data);
  const nodeId =
    browserStringValue(lastAction.node_id) ??
    browserStringValue(data.node_id) ??
    browserStringValue(data.target_node_id);
  const mappedTarget =
    normalizeBrowserElementMetadata(lastAction.target, nodeId || "") ??
    (nodeId ? elements.find((element) => element.node_id === nodeId) : undefined);
  const resultTarget = normalizeBrowserElementMetadata(
    { ...result, node_id: nodeId || result.node_id || "browser_result" },
    nodeId || "browser_result",
  );
  const target =
    mappedTarget && resultTarget?.bounds
      ? {
          ...mappedTarget,
          bounds: resultTarget.bounds,
          tag: resultTarget.tag || mappedTarget.tag,
          selector: resultTarget.selector || mappedTarget.selector,
        }
      : mappedTarget ?? resultTarget;
  const x = numericValue(lastAction.x ?? data.x);
  const y = numericValue(lastAction.y ?? data.y);
  return {
    id: `${block.id}:${block.status}:${browserStringValue(data.type) || block.name}`,
    toolName: block.name,
    status: block.status,
    effect,
    browserId: browserStringValue(data.browser_id) ?? browserStringValue(data.active_browser_id),
    pageId: browserStringValue(data.page_id) ?? browserStringValue(data.active_tab_id),
    windowId: browserStringValue(data.window_id),
    url: browserStringValue(data.final_url) ?? browserStringValue(data.url),
    nodeId,
    target,
    elements,
    coordinates: x !== undefined && y !== undefined ? { x, y } : undefined,
    startedAt: browserTimestampValue(data.started_at ?? data.created_at),
    completedAt: block.status === "completed" ? browserTimestampValue(data.completed_at ?? data.finished_at) : undefined,
    data,
  };
}

export function browserToolEffect(block: ToolBlockUi): BrowserVisualEffect | undefined {
  if (!block.name.startsWith("Browser")) return undefined;
  if (block.name === "BrowserListTabs" || block.name === "BrowserCloseTab" || block.name === "BrowserWait") {
    return undefined;
  }
  if (block.name === "BrowserGetElementMap") return "map";
  if (block.name === "BrowserClick") return "click";
  if (block.name === "BrowserType") return "type";
  if (block.name === "BrowserScroll" || block.name === "BrowserHistory") return "scroll";
  if (
    block.name === "BrowserScreenshot" ||
    block.name === "BrowserExtractContent" ||
    block.name === "BrowserReadContentChunk" ||
    block.name === "BrowserGetHtml"
  ) return "extract";
  if (block.name === "BrowserAct") {
    const data = block.data ?? {};
    const action = String(recordValue(data.last_action).action ?? data.action ?? "").toLowerCase();
    if (/click|submit|hover/.test(action)) return "click";
    if (/type|fill|press|select/.test(action)) return "type";
    if (/scroll/.test(action)) return "scroll";
    if (/screenshot|text|html/.test(action)) return "extract";
    return "highlight";
  }
  return "highlight";
}

export function browserVisualEventsFromRecords(value: unknown): BrowserVisualEvent[] {
  return recordArray(value)
    .map<BrowserVisualEvent | undefined>((item, index) => {
      const toolName = browserStringValue(item.toolName) || browserStringValue(item.tool_name) || "BrowserAction";
      const effect =
        browserVisualEffectValue(item.effect) ||
        browserEffectFromToolAction(toolName, browserStringValue(recordValue(item).action));
      if (!effect) return undefined;
      const target = normalizeBrowserElementMetadata(recordValue(item.target), browserStringValue(recordValue(item.target).node_id) || "");
      const x = numericValue(item.x ?? recordValue(item.coordinates).x);
      const y = numericValue(item.y ?? recordValue(item.coordinates).y);
      return {
        id: browserStringValue(item.id) || `browser-view-visual-${index}`,
        toolName,
        status: browserToolStatusValue(item.status),
        effect,
        browserId: browserStringValue(item.browserId) || browserStringValue(item.browser_id),
        pageId: browserStringValue(item.pageId) || browserStringValue(item.page_id),
        windowId: browserStringValue(item.windowId) || browserStringValue(item.window_id),
        url: browserStringValue(item.url),
        nodeId: browserStringValue(item.nodeId) || browserStringValue(item.node_id),
        target,
        elements: browserToolElements({ element_map: item.elements ?? item.element_map }),
        coordinates: x !== undefined && y !== undefined ? { x, y } : undefined,
        startedAt: browserTimestampValue(item.startedAt ?? item.started_at),
        completedAt: browserTimestampValue(item.completedAt ?? item.completed_at),
        data: recordValue(item),
      };
    })
    .filter((event): event is BrowserVisualEvent => Boolean(event));
}

export function browserVisualEventFromProposal(proposal: Record<string, unknown>, browser: BrowserState): BrowserVisualEvent {
  const args = recordValue(proposal.arguments);
  const targetRecord = recordValue(proposal.target);
  const nodeId = browserStringValue(targetRecord.node_id) || browserStringValue(args.node_id) || browserStringValue(args.target_node_id);
  const toolName = browserStringValue(proposal.tool_name) || browserStringValue(args.tool_name) || "BrowserAction";
  const action = browserStringValue(args.action) || browserStringValue(proposal.action);
  const x = numericValue(args.x ?? targetRecord.x ?? recordValue(targetRecord.coordinates).x);
  const y = numericValue(args.y ?? targetRecord.y ?? recordValue(targetRecord.coordinates).y);
  return {
    id: browserStringValue(proposal.proposal_id) || browserStringValue(proposal.approval_id) || `${toolName}:${nodeId || browser.currentUrl}`,
    toolName,
    status: "permission_required",
    effect: browserEffectFromToolAction(toolName, action) || "highlight",
    browserId: browserStringValue(proposal.browser_id) || browser.browserId,
    pageId: browserStringValue(proposal.page_id) || browser.view?.active_tab_id,
    url: browserStringValue(proposal.url) || browser.currentUrl,
    nodeId,
    target: normalizeBrowserElementMetadata(targetRecord, nodeId || "proposal_target"),
    elements: [],
    coordinates: x !== undefined && y !== undefined ? { x, y } : undefined,
    startedAt: browserTimestampValue(proposal.created_at),
    data: proposal,
  };
}

export function browserEffectFromToolAction(toolName: string, action?: string): BrowserVisualEffect | undefined {
  const syntheticBlock: ToolBlockUi = {
    id: toolName,
    name: toolName,
    status: "running",
    title: toolName,
    message: "",
    content: "",
    data: { action },
    isCollapsed: true,
  };
  return browserToolEffect(syntheticBlock);
}

export function browserToolElements(data: Record<string, unknown>) {
  const rawElements = recordArray(data.elements).length ? recordArray(data.elements) : recordArray(data.element_map);
  return rawElements
    .map((item, index) => normalizeBrowserElementMetadata(item, browserStringValue(item.node_id) || `browser_tool_${index}`))
    .filter((item): item is BrowserElementMetadata => Boolean(item));
}

export function browserTimestampValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

export function browserVisualEffectValue(value: unknown): BrowserVisualEffect | undefined {
  if (value === "map" || value === "click" || value === "type" || value === "scroll" || value === "extract" || value === "highlight") {
    return value;
  }
  return undefined;
}

export function browserToolStatusValue(value: unknown): ToolBlockStatus {
  if (value === "queued" || value === "running" || value === "completed" || value === "error" || value === "permission_required") {
    return value;
  }
  return "running";
}
