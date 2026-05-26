import type { SessionBrowserElement } from "../../../../../api/client";
import { escapeHtmlAttribute, scriptJson } from "./utils";
import { SCRIPT_CORE } from "./script-core";
import { SCRIPT_UI } from "./script-ui";
import { SCRIPT_EVENTS } from "./script-events";

export function buildMirrorScript(
  scriptNonce: string,
  browserId: string,
  elementMap: SessionBrowserElement[],
  cooperationEnabled: boolean,
) {
  const knownElements = scriptJson(
    elementMap
      .filter((element) => element.node_id && element.selector)
      .slice(0, 500)
      .map((element) => ({
        node_id: element.node_id,
        role: element.role || "",
        selector: element.selector || "",
        frame_id: element.frame_id || "main",
        shadow_path: element.shadow_path || [],
      })),
  );

  return `<script nonce="${escapeHtmlAttribute(scriptNonce)}">
(() => {
  const browserId = ${JSON.stringify(browserId)};
  const knownElements = ${knownElements};
  let mode = "browse";
  let cooperationEnabled = ${JSON.stringify(cooperationEnabled)};
  let annotationCounts = {};
  let selectedNodeId = "";
${SCRIPT_CORE}${SCRIPT_UI}${SCRIPT_EVENTS}\t</script>`;
}
