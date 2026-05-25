import type { SessionBrowserElement } from "../../../api/client";

export function browserCssLabel(value?: string) {
  if (value === "pixel") return "Pixel render";
  if (value === "original_embedded") return "Original + Embedded CSS";
  if (value === "embedded") return "Embedded CSS";
  if (value === "computed") return "Computed CSS";
  if (value === "fallback_html") return "Fallback HTML";
  return "Original CSS";
}

export function browserCssBadgeClass(value?: string) {
  if (value === "fallback_html") return "border-warning/40 bg-warning/10 text-warning";
  if (value === "original_embedded") return "border-primary/35 bg-primary/10 text-primary";
  if (value === "embedded") return "border-primary/35 bg-primary/10 text-primary";
  if (value === "computed") return "border-primary/35 bg-primary/10 text-primary";
  if (value === "pixel") return "border-success/35 bg-success/10 text-success";
  return "border-glass-border/35 bg-card/70 text-muted-foreground";
}

export function selectedElementLabel(element: SessionBrowserElement | undefined, nodeId: string) {
  if (!element) return nodeId;
  const role = element.role || element.tag || "element";
  const text = element.text ? ` · ${element.text.slice(0, 90)}` : "";
  return `${role}${text}`;
}
