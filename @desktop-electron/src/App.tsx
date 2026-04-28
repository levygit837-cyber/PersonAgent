import { useEffect } from "react";
import { ChatWorkspace } from "./components/chat/chat-workspace";
import { Sidebar } from "./components/layout/sidebar";
import { TitleBar } from "./components/layout/titlebar";
import { useAppStore } from "./stores/app-store";

export function App() {
  const initialize = useAppStore((state) => state.initialize);

  useEffect(() => {
    void initialize();
  }, [initialize]);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-background text-foreground">
      <TitleBar />
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-hidden">
          <ChatWorkspace />
        </main>
      </div>
    </div>
  );
}
