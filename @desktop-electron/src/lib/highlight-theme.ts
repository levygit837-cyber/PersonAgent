import hljs from "highlight.js";
import githubDark from "highlight.js/styles/github-dark.min.css?inline";
import github from "highlight.js/styles/github.min.css?inline";

const THEME_STYLE_ID = "highlight-theme-style";

/**
 * Loads the appropriate highlight.js theme based on dark/light mode.
 * Injects a scoped style element into the document head.
 * @param isDark - Whether to load the dark theme (true) or light theme (false)
 */
export function loadHighlightTheme(isDark: boolean): void {
  // Remove existing theme style if present
  const existingStyle = document.getElementById(THEME_STYLE_ID);
  existingStyle?.remove();

  // Create new style element
  const style = document.createElement("style");
  style.id = THEME_STYLE_ID;
  style.textContent = isDark ? githubDark : github;

  document.head.appendChild(style);
}

/**
 * Detects language from code block className (e.g., "language-python" -> "python")
 * @param className - The className from the code element
 * @returns The detected language or undefined
 */
export function detectLanguage(className?: string): string | undefined {
  if (!className) return undefined;
  const match = className.match(/language-(\w+)/);
  return match ? match[1] : undefined;
}

/**
 * Checks if a language is supported by highlight.js
 * @param language - The language to check
 * @returns Whether the language is supported
 */
export function isLanguageSupported(language: string): boolean {
  return hljs.getLanguage(language) !== undefined;
}
