import { BookOpen, FileText, Folder, Globe } from "lucide-react";
import type { ComposerMentionKind } from "./mentions";

export function MentionSuggestionIcon({ type }: { type: ComposerMentionKind }) {
  if (type === "directory") return <Folder className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />;
  if (type === "skill") return <BookOpen className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />;
  if (type === "browser_tab") return <Globe className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />;
  return <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />;
}
