import { useEffect, useRef, useState, useCallback } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { useTerminalStore } from "../../stores/terminal-store";
import { Bot } from "lucide-react";

interface TerminalViewProps {
  instanceId: string;
  focused?: boolean;
}

export function TerminalView({ instanceId, focused }: TerminalViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const writeToTerminal = useTerminalStore((s) => s.writeToTerminal);
  const resizeTerminal = useTerminalStore((s) => s.resizeTerminal);
  const setPendingSnippet = useTerminalStore((s) => s.setPendingSnippet);

  const [showButton, setShowButton] = useState(false);
  const [selectionText, setSelectionText] = useState("");
  const buttonPosRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  // Initialize terminal
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const term = new Terminal({
      fontFamily: '"JetBrains Mono", ui-monospace, SFMono-Regular, monospace',
      fontSize: 13,
      theme: {
        background: "#0a0a0a",
        foreground: "#e2e2e2",
        cursor: "#e2e2e2",
        selectionBackground: "#3a3a3a",
        black: "#0a0a0a",
        red: "#ff5555",
        green: "#50fa7b",
        yellow: "#f1fa8c",
        blue: "#8be9fd",
        magenta: "#ff79c6",
        cyan: "#8be9fd",
        white: "#bfbfbf",
        brightBlack: "#4d4d4d",
        brightRed: "#ff6e67",
        brightGreen: "#5af78e",
        brightYellow: "#f4f99d",
        brightBlue: "#caa9fa",
        brightMagenta: "#ff92d0",
        brightCyan: "#9aedfe",
        brightWhite: "#e6e6e6",
      },
      cursorBlink: true,
      allowProposedApi: true,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(container);

    requestAnimationFrame(() => {
      try {
        fitAddon.fit();
        resizeTerminal(instanceId, term.cols, term.rows);
      } catch {
        // ignore
      }
    });

    term.onData((data) => {
      writeToTerminal(instanceId, data);
    });

    term.onResize(({ cols, rows }) => {
      resizeTerminal(instanceId, cols, rows);
    });

    // Detect selection changes
    term.onSelectionChange(() => {
      const selected = term.getSelection();
      if (selected && selected.trim().length > 0) {
        setSelectionText(selected);
        setShowButton(true);
      } else {
        setShowButton(false);
        setSelectionText("");
      }
    });

    termRef.current = term;
    fitAddonRef.current = fitAddon;

    // IPC listeners
    let cleanupData: (() => void) | null = null;
    let cleanupExit: (() => void) | null = null;

    if (window.personAgent?.terminal) {
      cleanupData = window.personAgent.terminal.onData((id, data) => {
        if (id === instanceId) {
          term.write(data);
        }
      });

      cleanupExit = window.personAgent.terminal.onExit((id) => {
        if (id === instanceId) {
          term.writeln("\r\n\x1b[31mProcess exited.\x1b[0m");
        }
      });
    }

    return () => {
      cleanupData?.();
      cleanupExit?.();
      term.dispose();
      termRef.current = null;
      fitAddonRef.current = null;
    };
  }, [instanceId, writeToTerminal, resizeTerminal]);

  // Focus and refit when becoming active
  useEffect(() => {
    if (focused && termRef.current) {
      termRef.current.focus();
      requestAnimationFrame(() => {
        if (fitAddonRef.current && termRef.current) {
          try {
            fitAddonRef.current.fit();
          } catch {
            // ignore
          }
        }
      });
    }
  }, [focused]);

  // ResizeObserver
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver(() => {
      if (fitAddonRef.current && termRef.current) {
        try {
          fitAddonRef.current.fit();
        } catch {
          // ignore
        }
      }
    });

    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  // Track mouse position for button placement
  const handleMouseUp = useCallback((event: MouseEvent) => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    const rect = wrapper.getBoundingClientRect();
    buttonPosRef.current = {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }, []);

  // Hide button on Escape or when clicking outside (but not during selection)
  const handleKeyDown = useCallback((event: KeyboardEvent) => {
    if (event.key === "Escape") {
      setShowButton(false);
      setSelectionText("");
      termRef.current?.clearSelection();
    }
  }, []);

  // Clear button when clicking on the terminal canvas (not selecting)
  const handleMouseDown = useCallback(() => {
    // Small delay: if this mousedown starts a selection, onSelectionChange
    // will re-show the button. If it's just a click, button hides.
    setTimeout(() => {
      const term = termRef.current;
      if (!term) return;
      const selected = term.getSelection();
      if (!selected || selected.trim().length === 0) {
        setShowButton(false);
        setSelectionText("");
      }
    }, 50);
  }, []);

  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;

    wrapper.addEventListener("mouseup", handleMouseUp);
    wrapper.addEventListener("mousedown", handleMouseDown);
    window.addEventListener("keydown", handleKeyDown);

    return () => {
      wrapper.removeEventListener("mouseup", handleMouseUp);
      wrapper.removeEventListener("mousedown", handleMouseDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [handleMouseUp, handleMouseDown, handleKeyDown]);

  const handleSendToAgent = useCallback(() => {
    if (!selectionText) return;
    setPendingSnippet(selectionText);
    setShowButton(false);
    setSelectionText("");
    termRef.current?.clearSelection();
  }, [selectionText, setPendingSnippet]);

  // Compute button position: place it below the mouse, clamped inside wrapper
  const computeButtonStyle = (): React.CSSProperties => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return {};
    const rect = wrapper.getBoundingClientRect();
    const btnW = 120;
    const btnH = 32;
    const padding = 8;

    // Place below the mouse cursor
    let x = buttonPosRef.current.x - btnW / 2;
    let y = buttonPosRef.current.y + 16;

    // Clamp
    x = Math.max(padding, Math.min(x, rect.width - btnW - padding));
    y = Math.max(padding, Math.min(y, rect.height - btnH - padding));

    return { left: x, top: y };
  };

  return (
    <div ref={wrapperRef} className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full p-2" />

      {showButton && selectionText && (
        <div
          data-terminal-send-btn
          className="absolute z-50"
          style={computeButtonStyle()}
        >
          <button
            type="button"
            onMouseDown={(e) => e.stopPropagation()}
            onClick={handleSendToAgent}
            className="flex items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/90 px-2.5 py-1.5 text-[11px] font-medium text-primary-foreground shadow-floating backdrop-blur-xl transition-all hover:bg-primary hover:scale-[1.02] active:scale-[0.98]"
          >
            <Bot className="h-3 w-3" />
            Send to Agent
          </button>
        </div>
      )}
    </div>
  );
}
