import { Eye, Code2, BookOpen } from "lucide-react";
import { Button } from "../../ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "../../ui/tooltip";
import type { ViewMode } from "./types";
import { isHtmlFile, isMarkdownFile } from "./utils";

interface FileModeActionsProps {
  fileName: string;
  mode: ViewMode;
  onModeChange: (mode: ViewMode) => void;
}

export function FileModeActions({ fileName, mode, onModeChange }: FileModeActionsProps) {
  const html = isHtmlFile(fileName);
  const markdown = isMarkdownFile(fileName);

  if (!html && !markdown) return null;

  return (
    <div className="flex shrink-0 items-center gap-1 border-l border-glass-border/25 pl-2">
      {html ? (
        <>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={mode === "html" ? "secondary" : "ghost"}
                size="iconSm"
                aria-label="Preview HTML"
                onClick={() => onModeChange("html")}
                className="rounded-xl"
              >
                <Eye className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Preview HTML</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={mode === "code" ? "secondary" : "ghost"}
                size="iconSm"
                aria-label="View code"
                onClick={() => onModeChange("code")}
                className="rounded-xl"
              >
                <Code2 className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>View code</TooltipContent>
          </Tooltip>
        </>
      ) : null}

      {markdown ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={mode === "markdown" ? "secondary" : "ghost"}
              size="iconSm"
              aria-label="Markdown preview"
              onClick={() => onModeChange(mode === "markdown" ? "code" : "markdown")}
              className="rounded-xl"
            >
              <BookOpen className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Markdown preview</TooltipContent>
        </Tooltip>
      ) : null}
    </div>
  );
}
