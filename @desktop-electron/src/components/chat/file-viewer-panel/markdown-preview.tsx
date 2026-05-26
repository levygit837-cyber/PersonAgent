import { MarkdownContent } from "../agent-message";

interface MarkdownPreviewProps {
  content: string;
}

export function MarkdownPreview({ content }: MarkdownPreviewProps) {
  return (
    <div className="h-full overflow-y-auto bg-card/95 px-5 py-4">
      <MarkdownContent content={content} />
    </div>
  );
}
