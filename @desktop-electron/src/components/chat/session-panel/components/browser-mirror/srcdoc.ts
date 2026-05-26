import type { SessionBrowserElement } from "../../../../../api/client";
import { sanitizeBrowserMirrorHtml } from "./sanitize-html";
import { escapeHtmlAttribute, createCspNonce } from "./utils";
import { buildMirrorScript } from "./build-script";

export function browserMirrorSrcDoc(
  html: string,
  currentUrl: string,
  browserId: string,
  elementMap: SessionBrowserElement[],
  cooperationEnabled = false,
) {
  const sanitizedHtml = sanitizeBrowserMirrorHtml(html);
  const scriptNonce = createCspNonce();
  const base = `<base href="${escapeHtmlAttribute(currentUrl)}">`;
  const csp = [
    "default-src 'none'",
    "img-src http: https: data: blob:",
    "style-src http: https: data: blob: 'unsafe-inline'",
    `script-src 'nonce-${scriptNonce}'`,
    "font-src http: https: data:",
    "frame-src 'none'",
    "object-src 'none'",
    "form-action 'none'",
    "base-uri http: https:",
  ].join("; ");
  const meta = `<meta http-equiv="Content-Security-Policy" content="${escapeHtmlAttribute(csp)}">`;
  const overlayStyle = `<style>
	html[data-pa-browser-mode="annotate"],
	html[data-pa-browser-mode="annotate"] body,
	html[data-pa-browser-mode="annotate"] * {
	  cursor: crosshair !important;
	}
	.pa-browser-inspect-target {
	  scroll-margin: 6px !important;
	}
	.pa-inspector-fill {
	  position: fixed !important;
	  z-index: 2147483646 !important;
	  box-sizing: border-box !important;
	  border: 2px solid #2296ff !important;
	  border-radius: var(--pa-inspector-radius, 3px) !important;
	  background: rgba(34, 150, 255, 0.18) !important;
	  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14), 0 0 0 1px rgba(34, 150, 255, 0.28) !important;
	  pointer-events: none !important;
	  opacity: 1 !important;
	  transform: translate3d(0, 0, 0) !important;
	  transition: left 110ms ease, top 110ms ease, width 110ms ease, height 110ms ease, border-radius 110ms ease, opacity 100ms ease !important;
	}
		.pa-inspector-fill.is-hidden {
		  opacity: 0 !important;
		}
		.pa-inspector-tooltip {
	  position: fixed !important;
	  z-index: 2147483647 !important;
	  left: 0;
	  top: 0;
	  min-width: 176px !important;
	  max-width: min(240px, calc(100vw - 16px)) !important;
	  border: 1px solid rgba(96, 165, 250, 0.32) !important;
	  border-radius: 10px !important;
	  background: rgba(9, 17, 31, 0.96) !important;
	  color: #e5eefb !important;
	  box-shadow: 0 14px 34px rgba(0, 0, 0, 0.34), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
	  font: 500 11px/1.25 Inter, ui-sans-serif, system-ui, sans-serif !important;
	  letter-spacing: 0 !important;
	  padding: 8px !important;
	  pointer-events: none !important;
	  opacity: 1 !important;
	  transform: translate3d(0, 0, 0) !important;
	  transition: opacity 100ms ease, transform 130ms ease !important;
	}
	.pa-inspector-tooltip.is-hidden {
	  opacity: 0 !important;
	}
	.pa-inspector-title,
	.pa-inspector-row {
	  display: grid !important;
	  grid-template-columns: 52px minmax(0, 1fr) !important;
	  gap: 8px !important;
	  align-items: center !important;
	}
	.pa-inspector-title {
	  margin-bottom: 5px !important;
	}
	.pa-inspector-tag {
	  display: inline-flex !important;
	  min-width: 0 !important;
	  justify-content: center !important;
	  border: 1px solid rgba(96, 165, 250, 0.28) !important;
	  border-radius: 999px !important;
	  background: rgba(34, 150, 255, 0.13) !important;
	  color: #f8fafc !important;
	  font-weight: 700 !important;
	  padding: 2px 6px !important;
	  text-transform: lowercase !important;
	}
	.pa-inspector-value {
	  min-width: 0 !important;
	  overflow: hidden !important;
	  text-overflow: ellipsis !important;
	  white-space: nowrap !important;
	}
	.pa-inspector-label {
	  color: #8ea1b8 !important;
	  font-weight: 600 !important;
	}
	.pa-selection-toolbar {
	  position: fixed !important;
	  z-index: 2147483647 !important;
	  display: flex !important;
	  align-items: center !important;
	  gap: 6px !important;
	  border: 1px solid rgba(96, 165, 250, 0.28) !important;
	  border-radius: 999px !important;
	  background: rgba(10, 18, 32, 0.96) !important;
	  box-shadow: 0 16px 36px rgba(0, 0, 0, 0.28) !important;
	  padding: 4px !important;
	  pointer-events: auto !important;
	}
	.pa-selection-toolbar.is-hidden {
	  display: none !important;
	}
	.pa-selection-toolbar button {
	  border: 0 !important;
	  border-radius: 999px !important;
	  background: rgba(34, 150, 255, 0.16) !important;
	  color: #dbeafe !important;
	  cursor: pointer !important;
	  font: 600 11px/1 Inter, ui-sans-serif, system-ui, sans-serif !important;
	  padding: 7px 10px !important;
	}
	[data-pa-comment-count] {
	  outline: 1px solid rgba(249, 115, 22, 0.58) !important;
	  outline-offset: 2px !important;
	  box-shadow: 0 0 0 3px rgba(249, 115, 22, 0.12) !important;
	}
	.pa-comment-anchor {
	  position: relative !important;
	}
	.pa-comment-marker {
	  position: absolute !important;
	  z-index: 2147483647 !important;
	  top: -9px !important;
	  right: -9px !important;
	  display: inline-grid !important;
	  min-width: 18px !important;
	  height: 18px !important;
	  place-items: center !important;
	  border: 1px solid rgba(255, 255, 255, 0.72) !important;
	  border-radius: 999px !important;
	  background: #f97316 !important;
	  color: #111827 !important;
	  font: 700 11px/1 Inter, ui-sans-serif, system-ui, sans-serif !important;
	  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.22) !important;
	  pointer-events: none !important;
	}
	</style>`;
  const script = buildMirrorScript(scriptNonce, browserId, elementMap, cooperationEnabled);
  if (/<head(\s[^>]*)?>/i.test(sanitizedHtml)) {
    return sanitizedHtml.replace(/<head(\s[^>]*)?>/i, (match) => `${match}${meta}${base}${overlayStyle}${script}`);
  }
  return `${meta}${base}${overlayStyle}${script}${sanitizedHtml}`;
}
