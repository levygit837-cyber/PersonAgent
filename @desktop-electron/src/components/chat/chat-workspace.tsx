import { InputDock } from "./input-dock";
import { MessageFeed } from "./message-feed";

export function ChatWorkspace() {
  return (
    <section className="relative flex h-full min-w-0 flex-col overflow-hidden bg-background">
      <div className="relative min-h-0 flex-1">
        <MessageFeed />
        <InputDock />
      </div>
    </section>
  );
}
