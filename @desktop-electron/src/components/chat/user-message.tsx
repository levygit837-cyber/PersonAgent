import type { ChatMessageUi } from "../../types/chat";

export function UserMessage({ message }: { message: ChatMessageUi }) {
  return (
    <article className="mb-9">
      <div className="mb-2 font-mono text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">User</div>
      <div className="whitespace-pre-wrap pl-4 text-[15px] leading-7 text-foreground">{message.content}</div>
    </article>
  );
}
