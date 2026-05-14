import { create } from "zustand";

export type TerminalPane = "left" | "right";

export interface TerminalInstance {
  id: string;
  name: string;
  pane: TerminalPane;
  cwd?: string;
  cols: number;
  rows: number;
  alive: boolean;
}

export interface TerminalSnippet {
  id: string;
  content: string;
  timestamp: number;
}

interface TerminalPaneState {
  instances: TerminalInstance[];
  activeInstanceId: string | null;
  nextId: number;
}

interface TerminalState {
  leftPane: TerminalPaneState;
  rightPane: TerminalPaneState | null;
  splitMode: boolean;
  open: boolean;
  pendingSnippet: TerminalSnippet | null;
  snippetNonce: number;

  toggleOpen: () => void;
  closeIfEmpty: () => void;
  addInstance: (pane: TerminalPane, name?: string, cwd?: string) => string;
  removeInstance: (pane: TerminalPane, id: string) => void;
  setActiveInstance: (pane: TerminalPane, id: string) => void;
  toggleSplit: () => void;
  writeToTerminal: (id: string, data: string) => void;
  resizeTerminal: (id: string, cols: number, rows: number) => void;
  markDead: (id: string) => void;
  setPendingSnippet: (content: string) => void;
  clearPendingSnippet: () => void;
  getPaneInstances: (pane: TerminalPane) => TerminalInstance[];
  getPaneActiveId: (pane: TerminalPane) => string | null;
}

function ensureTerminalApi() {
  if (!window.personAgent?.terminal) {
    throw new Error("Terminal API not available");
  }
  return window.personAgent.terminal;
}

function createEmptyPane(): TerminalPaneState {
  return { instances: [], activeInstanceId: null, nextId: 1 };
}

const terminalCommandBuffers = new Map<string, string>();

function trackTerminalInput(id: string, data: string, workspaceRoot?: string) {
  let buffer = terminalCommandBuffers.get(id) ?? "";
  for (const char of data) {
    if (char === "\r" || char === "\n") {
      const command = buffer.trim();
      buffer = "";
      if (/\b(?:git|codex)\b/.test(command)) {
        window.dispatchEvent(
          new CustomEvent("personagent:terminal-state-command", {
            detail: { command, workspaceRoot },
          }),
        );
      }
      continue;
    }
    if (char === "\u007f" || char === "\b") {
      buffer = buffer.slice(0, -1);
      continue;
    }
    if (char >= " " && char !== "\u001b") {
      buffer += char;
    }
  }
  terminalCommandBuffers.set(id, buffer.slice(-500));
}

export const useTerminalStore = create<TerminalState>((set, get) => {
  let exitCleanup: (() => void) | null = null;

  function ensureListeners() {
    if (exitCleanup) return;
    const api = window.personAgent?.terminal;
    if (!api) return;

    exitCleanup = api.onExit((id) => {
      const state = get();
      ["left", "right"].forEach((paneKey) => {
        const pane = paneKey === "left" ? state.leftPane : state.rightPane;
        if (!pane) return;
        const inst = pane.instances.find((i) => i.id === id);
        if (inst) {
          get().markDead(id);
        }
      });
    });
  }

  function killIpcTerminal(id: string) {
    try {
      ensureTerminalApi().kill(id);
    } catch {
      // ignore
    }
  }

  function getPaneState(pane: TerminalPane): TerminalPaneState | null {
    return pane === "left" ? get().leftPane : get().rightPane;
  }

  function setPaneState(pane: TerminalPane, updater: (p: TerminalPaneState) => TerminalPaneState) {
    if (pane === "left") {
      set((state) => ({ leftPane: updater(state.leftPane) }));
    } else {
      set((state) => {
        if (!state.rightPane) return state;
        return { rightPane: updater(state.rightPane) };
      });
    }
  }

  return {
    leftPane: createEmptyPane(),
    rightPane: null,
    splitMode: false,
    open: false,
    pendingSnippet: null,
    snippetNonce: 0,

    toggleOpen: () => {
      const next = !get().open;
      set({ open: next });
    },

    closeIfEmpty: () => {
      const state = get();
      const leftEmpty = state.leftPane.instances.length === 0;
      const rightEmpty = !state.rightPane || state.rightPane.instances.length === 0;
      if (leftEmpty && rightEmpty) {
        set({ open: false });
      }
    },

    addInstance: (pane, name, cwd) => {
      ensureListeners();
      const paneState = getPaneState(pane) ?? createEmptyPane();
      const id = `terminal-${pane}-${paneState.nextId}`;
      const instanceName = name || `Terminal ${paneState.nextId}`;

      setPaneState(pane, (p) => ({
        instances: [
          ...p.instances,
          { id, name: instanceName, pane, cwd, cols: 80, rows: 24, alive: true },
        ],
        activeInstanceId: p.activeInstanceId ?? id,
        nextId: p.nextId + 1,
      }));

      try {
        void ensureTerminalApi().create(id, cwd, cwd);
      } catch {
        // Terminal API not available in browser/dev — keep as mock
      }

      return id;
    },

    removeInstance: (pane, id) => {
      const paneState = getPaneState(pane);
      if (!paneState) return;

      const remaining = paneState.instances.filter((i) => i.id !== id);
      killIpcTerminal(id);

      setPaneState(pane, (p) => ({
        ...p,
        instances: remaining,
        activeInstanceId:
          remaining.length > 0
            ? (remaining.find((i) => i.id === p.activeInstanceId)?.id ?? remaining[0].id)
            : null,
      }));

      // If right pane becomes empty, exit split mode
      if (pane === "right" && remaining.length === 0) {
        set({ splitMode: false, rightPane: null });
      }

      // If all panes empty, close panel
      get().closeIfEmpty();
    },

    setActiveInstance: (pane, id) => {
      setPaneState(pane, (p) => ({ ...p, activeInstanceId: id }));
    },

    toggleSplit: () => {
      const state = get();
      const nextSplit = !state.splitMode;

      if (nextSplit) {
        // Enter split: create right pane with an initial terminal instance
        const rightPane = createEmptyPane();
        const rightId = `terminal-right-${rightPane.nextId}`;
        const rightInstance: TerminalInstance = {
          id: rightId,
          name: "Terminal 1",
          pane: "right",
          cwd: state.leftPane.instances.find((inst) => inst.id === state.leftPane.activeInstanceId)?.cwd,
          cols: 80,
          rows: 24,
          alive: true,
        };
        set({
          splitMode: true,
          rightPane: {
            instances: [rightInstance],
            activeInstanceId: rightId,
            nextId: rightPane.nextId + 1,
          },
        });

        try {
          void ensureTerminalApi().create(rightId, rightInstance.cwd, rightInstance.cwd);
        } catch {
          // Terminal API not available in browser/dev — keep as mock
        }
      } else {
        // Exit split: merge right instances into left
        const rightInstances = state.rightPane?.instances ?? [];
        rightInstances.forEach((inst) => killIpcTerminal(inst.id));
        set({ splitMode: false, rightPane: null });
      }
    },

    writeToTerminal: (id, data) => {
      const state = get();
      const instance =
        state.leftPane.instances.find((item) => item.id === id) ??
        state.rightPane?.instances.find((item) => item.id === id);
      trackTerminalInput(id, data, instance?.cwd);
      try {
        ensureTerminalApi().write(id, data);
      } catch {
        // In browser tests/dev without the Electron API, xterm handles local UI state itself.
      }
    },

    resizeTerminal: (id, cols, rows) => {
      set((state) => {
        const updatePane = (pane: TerminalPaneState): TerminalPaneState => ({
          ...pane,
          instances: pane.instances.map((inst) =>
            inst.id === id ? { ...inst, cols, rows } : inst
          ),
        });
        return {
          leftPane: updatePane(state.leftPane),
          rightPane: state.rightPane ? updatePane(state.rightPane) : null,
        };
      });
      try {
        ensureTerminalApi().resize(id, cols, rows);
      } catch {
        // ignore
      }
    },

    markDead: (id) => {
      set((state) => {
        const updatePane = (pane: TerminalPaneState): TerminalPaneState => ({
          ...pane,
          instances: pane.instances.map((inst) =>
            inst.id === id ? { ...inst, alive: false } : inst
          ),
        });
        return {
          leftPane: updatePane(state.leftPane),
          rightPane: state.rightPane ? updatePane(state.rightPane) : null,
        };
      });
    },

    setPendingSnippet: (content) => {
      set({
        pendingSnippet: {
          id: `terminal-snippet-${Date.now()}`,
          content,
          timestamp: Date.now(),
        },
        snippetNonce: get().snippetNonce + 1,
      });
    },

    clearPendingSnippet: () => {
      set({ pendingSnippet: null });
    },

    getPaneInstances: (pane) => {
      return getPaneState(pane)?.instances ?? [];
    },

    getPaneActiveId: (pane) => {
      return getPaneState(pane)?.activeInstanceId ?? null;
    },
  };
});
