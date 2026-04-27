import { useEffect } from "react";
import { ChatWorkspace } from "./components/chat/chat-workspace";
import { LabWorkspace } from "./components/lab/lab-workspace";
import { Sidebar } from "./components/layout/sidebar";
import { TitleBar } from "./components/layout/titlebar";
import { useAppStore } from "./stores/app-store";
import { useLabStore } from "./stores/lab-store";

export function App() {
  const initialize = useAppStore((state) => state.initialize);
  const section = useAppStore((state) => state.section);
  const initializeLab = useLabStore((state) => state.initialize);

  useEffect(() => {
    void initialize();
  }, [initialize]);

  useEffect(() => {
    if (section === "lab") void initializeLab();
  }, [initializeLab, section]);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-background text-foreground">
      <TitleBar />
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-hidden">
          {section === "chat" ? <ChatWorkspace /> : <LabWorkspace />}
        </main>
      </div>
    </div>
  );
}
