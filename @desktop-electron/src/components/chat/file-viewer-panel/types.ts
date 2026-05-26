export type ViewMode = "code" | "html" | "markdown";

export interface FileLoadState {
  content?: string;
  error?: string;
}

export interface AnnotationDraft {
  id: string;
  anchorLine: number;
  focusLine?: number;
  text: string;
}
