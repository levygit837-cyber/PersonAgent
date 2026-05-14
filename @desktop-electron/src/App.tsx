import { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { ChatPaneSurface, ChatWorkspace } from "./components/chat/chat-workspace";
import { Sidebar } from "./components/layout/sidebar";
import { TitleBar } from "./components/layout/titlebar";
import { StateEventBridge } from "./components/system/state-event-bridge";
import { useAppStore } from "./stores/app-store";
import { ChatStoreProvider, createChatStore, type ChatStoreApi } from "./stores/chat-store";

const OpenPrWorkspace = lazy(() =>
  import("./components/open-pr/open-pr-workspace").then((mod) => ({ default: mod.OpenPrWorkspace })),
);
const SkillsWorkspace = lazy(() =>
  import("./components/skills/skills-workspace").then((mod) => ({ default: mod.SkillsWorkspace })),
);

type CompactLaunchContext = {
  conversationId: string;
  workspaceRoot?: string | null;
  title?: string | null;
};

export function App() {
  const initialize = useAppStore((state) => state.initialize);
  const section = useAppStore((state) => state.section);
  const compactMode = isCompactMode();

  useEffect(() => {
    void initialize();
  }, [initialize]);

  if (compactMode) {
    return <CompactApp />;
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-background text-foreground">
      <StateEventBridge />
      <TitleBar />
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-hidden">
          {section === "skills" ? (
            <Suspense fallback={null}>
              <SkillsWorkspace />
            </Suspense>
          ) : section === "openPr" ? (
            <Suspense fallback={null}>
              <OpenPrWorkspace />
            </Suspense>
          ) : (
            <ChatWorkspace />
          )}
        </main>
      </div>
    </div>
  );
}

function CompactApp() {
  const [launchContext, setLaunchContext] = useState<CompactLaunchContext | null>(() => compactContextFromUrl());
  const storeRef = useRef<ChatStoreApi | null>(null);

  const store = useMemo(() => {
    if (!launchContext) return null;
    if (!storeRef.current) {
      storeRef.current = createChatStore({
        paneId: `compact:${launchContext.conversationId}`,
        initialWorkspaceRoot: launchContext.workspaceRoot,
        syncWorkspaceSelection: false,
      });
    }
    return storeRef.current;
  }, [launchContext]);

  useEffect(() => {
    if (!window.personAgent?.compact.getLaunchContext) return;
    void window.personAgent.compact.getLaunchContext().then((context) => {
      if (context?.conversationId) setLaunchContext(context);
    });
  }, []);

  useEffect(() => {
    if (!store || !launchContext?.conversationId) return;
    store.getState().setWorkspaceRoot(launchContext.workspaceRoot);
    if (store.getState().conversationId !== launchContext.conversationId) {
      void store.getState().loadConversation(launchContext.conversationId, launchContext.workspaceRoot);
    }
  }, [launchContext, store]);

  if (!store || !launchContext) {
    return (
      <div className="flex h-full w-full flex-col overflow-hidden bg-background text-foreground">
        <TitleBar compactTitle="Compact" />
        <main className="grid min-h-0 flex-1 place-items-center text-sm text-muted-foreground">Opening session...</main>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-background text-foreground">
      <StateEventBridge />
      <TitleBar compactTitle={launchContext.title || "Compact"} />
      <main className="min-h-0 flex-1 overflow-hidden">
        <ChatStoreProvider store={store}>
          <ChatPaneSurface paneId={`compact:${launchContext.conversationId}`} compact />
        </ChatStoreProvider>
      </main>
    </div>
  );
}

function isCompactMode() {
  return new URLSearchParams(window.location.search).get("mode") === "compact";
}

function compactContextFromUrl(): CompactLaunchContext | null {
  const params = new URLSearchParams(window.location.search);
  const conversationId = params.get("conversationId")?.trim();
  if (!conversationId) return null;
  return {
    conversationId,
    workspaceRoot: params.get("workspaceRoot") || undefined,
    title: params.get("title") || undefined,
  };
}
