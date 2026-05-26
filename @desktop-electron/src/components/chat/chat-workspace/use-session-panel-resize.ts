import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";

const SESSION_PANEL_DEFAULT_WIDTH = 430;
export const SESSION_PANEL_MIN_WIDTH = 320;
export const SESSION_PANEL_MIN_CHAT_WIDTH = 360;

export function clampSessionPanelWidth(width: number) {
  if (typeof window === "undefined") return width;
  const maxWidth = Math.max(SESSION_PANEL_MIN_WIDTH, window.innerWidth - SESSION_PANEL_MIN_CHAT_WIDTH);
  return Math.min(Math.max(width, SESSION_PANEL_MIN_WIDTH), maxWidth);
}

export function useSessionPanelResize(sessionPanelOpen: boolean) {
  const [sessionPanelWidth, setSessionPanelWidth] = useState(() => clampSessionPanelWidth(SESSION_PANEL_DEFAULT_WIDTH));
  const [isSessionPanelResizing, setIsSessionPanelResizing] = useState(false);
  const sessionPanelResizeCleanupRef = useRef<(() => void) | null>(null);
  const sessionPanelResizeHandleRef = useRef<HTMLDivElement | null>(null);
  const sessionPanelResizePointerIdRef = useRef<number | null>(null);

  const stopSessionPanelResize = () => {
    sessionPanelResizeCleanupRef.current?.();
    sessionPanelResizeCleanupRef.current = null;
    const resizeHandle = sessionPanelResizeHandleRef.current;
    const pointerId = sessionPanelResizePointerIdRef.current;
    sessionPanelResizePointerIdRef.current = null;
    if (resizeHandle && pointerId !== null) {
      try {
        resizeHandle.releasePointerCapture?.(pointerId);
      } catch {
        // Ignore browsers that already cleared capture or do not support it.
      }
    }
    setIsSessionPanelResizing(false);
    if (typeof document !== "undefined") {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
  };

  const beginSessionPanelResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    stopSessionPanelResize();
    setIsSessionPanelResizing(true);
    if (typeof document !== "undefined") {
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    }

    const updateWidthFromPointer = (clientX: number) => {
      setSessionPanelWidth(clampSessionPanelWidth(window.innerWidth - clientX));
    };

    const stopResize = () => {
      stopSessionPanelResize();
    };

    const onPointerMove = (moveEvent: PointerEvent) => {
      updateWidthFromPointer(moveEvent.clientX);
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopResize);
    window.addEventListener("pointercancel", stopResize);
    window.addEventListener("blur", stopResize);

    sessionPanelResizeCleanupRef.current = () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopResize);
      window.removeEventListener("pointercancel", stopResize);
      window.removeEventListener("blur", stopResize);
    };

    sessionPanelResizePointerIdRef.current = event.pointerId;
    try {
      event.currentTarget.setPointerCapture?.(event.pointerId);
    } catch {
      // The window listeners still cover the resize interaction if capture fails.
    }
    updateWidthFromPointer(event.clientX);
  };

  const handleSessionPanelResizeKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 48 : 24;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setSessionPanelWidth((current) => clampSessionPanelWidth(current - step));
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      setSessionPanelWidth((current) => clampSessionPanelWidth(current + step));
    } else if (event.key === "Home") {
      event.preventDefault();
      setSessionPanelWidth(SESSION_PANEL_MIN_WIDTH);
    } else if (event.key === "End") {
      event.preventDefault();
      setSessionPanelWidth(clampSessionPanelWidth(window.innerWidth));
    }
  };

  useEffect(() => {
    if (!sessionPanelOpen) {
      stopSessionPanelResize();
      return;
    }
    setSessionPanelWidth((current) => clampSessionPanelWidth(current));
    const clampWidth = () => setSessionPanelWidth((current) => clampSessionPanelWidth(current));
    window.addEventListener("resize", clampWidth);
    return () => window.removeEventListener("resize", clampWidth);
  }, [sessionPanelOpen]);

  useEffect(() => {
    return () => {
      stopSessionPanelResize();
    };
  }, []);

  return {
    sessionPanelWidth,
    isSessionPanelResizing,
    sessionPanelResizeHandleRef,
    beginSessionPanelResize,
    handleSessionPanelResizeKeyDown,
    stopSessionPanelResize,
  };
}
