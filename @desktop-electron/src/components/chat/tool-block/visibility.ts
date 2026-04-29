import { useState } from "react";

export const TOOL_OUTPUT_VISIBILITY_STORAGE_KEY = "personagent.toolOutputVisibility";

export function useToolOutputCollapsed(
  fallbackCollapsed: boolean,
  options: { autoCollapse?: boolean } = {},
) {
  const [collapsed, setCollapsed] = useState(() => initialToolOutputCollapsed(fallbackCollapsed, options));

  const toggleCollapsed = () => {
    setCollapsed((value) => {
      const next = !value;
      persistToolOutputCollapsed(next);
      return next;
    });
  };

  return [collapsed, toggleCollapsed] as const;
}

function initialToolOutputCollapsed(fallbackCollapsed: boolean, options: { autoCollapse?: boolean }) {
  const persisted = readPersistedToolOutputCollapsed();
  if (options.autoCollapse && persisted === false) return true;
  return persisted ?? fallbackCollapsed;
}

function readPersistedToolOutputCollapsed() {
  if (typeof window === "undefined") return undefined;
  try {
    const value = window.localStorage.getItem(TOOL_OUTPUT_VISIBILITY_STORAGE_KEY);
    if (value === "show") return false;
    if (value === "hide") return true;
  } catch {
    return undefined;
  }
  return undefined;
}

function persistToolOutputCollapsed(collapsed: boolean) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(TOOL_OUTPUT_VISIBILITY_STORAGE_KEY, collapsed ? "hide" : "show");
  } catch {
    // Ignore storage failures; the current click should still update the visible row.
  }
}
