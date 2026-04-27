import type { PersonAgentDesktopApi } from "../../electron/preload";

declare global {
  interface Window {
    personAgent?: PersonAgentDesktopApi;
  }
}

export {};
