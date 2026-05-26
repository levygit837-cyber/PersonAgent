import hljs from "../../../lib/highlight";

export const MAX_HIGHLIGHT_CHARS = 80_000;
export const MAX_HIGHLIGHT_LINES = 1_500;

export const EXT_TO_HIGHLIGHT_LANG: Record<string, string> = {
  bash: "bash",
  c: "c",
  cc: "cpp",
  cjs: "javascript",
  clj: "clojure",
  cpp: "cpp",
  cs: "csharp",
  css: "css",
  csv: "plaintext",
  cxx: "cpp",
  dart: "dart",
  diff: "diff",
  dockerfile: "dockerfile",
  ex: "elixir",
  exs: "elixir",
  go: "go",
  h: "c",
  hpp: "cpp",
  hs: "haskell",
  htm: "xml",
  html: "xml",
  java: "java",
  js: "javascript",
  json: "json",
  jsx: "javascript",
  kt: "kotlin",
  kts: "kotlin",
  less: "less",
  lua: "lua",
  md: "markdown",
  mjs: "javascript",
  php: "php",
  pl: "perl",
  ps1: "powershell",
  py: "python",
  rb: "ruby",
  rs: "rust",
  sass: "scss",
  scala: "scala",
  scss: "scss",
  sh: "bash",
  sql: "sql",
  svelte: "xml",
  swift: "swift",
  toml: "ini",
  ts: "typescript",
  tsx: "typescript",
  txt: "plaintext",
  vue: "xml",
  xml: "xml",
  yaml: "yaml",
  yml: "yaml",
  zsh: "bash",
};

export const FILENAME_TO_HIGHLIGHT_LANG: Record<string, string> = {
  ".dockerignore": "plaintext",
  ".env": "ini",
  ".eslintrc": "json",
  ".gitattributes": "plaintext",
  ".gitignore": "plaintext",
  ".prettierrc": "json",
  "cmakelists.txt": "cmake",
  dockerfile: "dockerfile",
  gemfile: "ruby",
  "go.mod": "go",
  "go.sum": "go",
  makefile: "makefile",
  "package-lock.json": "json",
  "package.json": "json",
  pipfile: "toml",
  "pnpm-lock.yaml": "yaml",
  "pyproject.toml": "toml",
  "requirements.txt": "plaintext",
  "tsconfig.json": "json",
  "vite.config.js": "javascript",
  "vite.config.ts": "typescript",
  "yarn.lock": "yaml",
};

export function highlightContent(content: string, language: string) {
  if (shouldSkipHighlight(content, language)) return escapeHtml(content);
  try {
    const lang = hljs.getLanguage(language) ? language : "plaintext";
    return hljs.highlight(content, { language: lang }).value;
  } catch {
    return escapeHtml(content);
  }
}

export function shouldSkipHighlight(content: string, language: string) {
  if (language === "plaintext") return true;
  if (content.length > MAX_HIGHLIGHT_CHARS) return true;
  if (splitLines(content).length > MAX_HIGHLIGHT_LINES) return true;
  return false;
}

export function splitHighlightedLines(html: string): string[] {
  const raw = html.split("\n");
  const result: string[] = [];
  const openSpans: string[] = [];

  for (const line of raw) {
    const prefix = openSpans.join("");
    const enriched = prefix + line;
    const opens = line.match(/<span[^>]*>/g) || [];
    const closes = line.match(/<\/span>/g) || [];

    for (const tag of opens) openSpans.push(tag);
    for (let index = 0; index < closes.length; index += 1) openSpans.pop();

    result.push(enriched + "</span>".repeat(openSpans.length));
  }

  return result;
}

export function escapeHtml(text: string) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function languageFromFilename(fileName: string) {
  const lower = fileName.toLowerCase();
  const known = FILENAME_TO_HIGHLIGHT_LANG[lower];
  if (known) return hljs.getLanguage(known) ? known : "plaintext";
  const ext = lower.split(".").pop();
  const lang = ext ? EXT_TO_HIGHLIGHT_LANG[ext] : undefined;
  return lang && hljs.getLanguage(lang) ? lang : "plaintext";
}

function splitLines(content: string) {
  return content.length === 0 ? [""] : content.replace(/\r\n/g, "\n").split("\n");
}
