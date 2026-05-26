export function sanitizeBrowserMirrorHtml(html: string) {
  const parser = new DOMParser();
  const document = parser.parseFromString(html || "<!doctype html><html><body></body></html>", "text/html");
  for (const element of Array.from(
    document.querySelectorAll(
      [
        "script",
        "iframe",
        "object",
        "embed",
        "base",
        "meta[http-equiv]",
      ].join(","),
    ),
  )) {
    element.remove();
  }
  for (const link of Array.from(document.querySelectorAll("link"))) {
    const rel = link.getAttribute("rel")?.toLowerCase() ?? "";
    const as = link.getAttribute("as")?.toLowerCase() ?? "";
    if (rel === "modulepreload" || (rel === "preload" && (as === "script" || as === "worker"))) {
      link.remove();
    }
  }
  for (const element of Array.from(document.querySelectorAll("*"))) {
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase();
      if (name.startsWith("on") || name === "srcdoc" || isUnsafeMirrorUrlAttribute(element, name, attribute.value)) {
        element.removeAttribute(attribute.name);
      }
    }
  }
  return `<!doctype html>\n${document.documentElement.outerHTML}`;
}

function isUnsafeMirrorUrlAttribute(element: Element, name: string, value: string) {
  if (!["href", "src", "action", "formaction", "xlink:href"].includes(name)) return false;
  const normalized = value.trim().replace(/[\u0000-\u001f\u007f\s]+/g, "").toLowerCase();
  if (normalized.startsWith("javascript:") || normalized.startsWith("vbscript:")) return true;
  if (!normalized.startsWith("data:")) return false;
  const tagName = element.tagName.toLowerCase();
  return !(name === "src" && tagName === "img" && /^data:image\/(?:png|jpe?g|gif|webp);/i.test(normalized));
}
