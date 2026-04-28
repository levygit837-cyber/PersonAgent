# Browser Workspace

## V1 Contract

The Session Panel Browser is a Browser Workspace, not a universal pixel-perfect browser.
It keeps LightPanda as the real runtime, renders the captured page DOM in Electron, preserves
the original page CSS when possible, and overlays PersonAgent controls for inspection,
annotations, actions, and timeline feedback.

V1 stores only lightweight workspace state in `Conversation.metadata["browser_workspace"]`:
annotations, the latest compact element map, active browser id, current URL/title, and a capped
timeline. Full HTML snapshots are runtime data and must not be persisted into conversation
metadata.

## V2 Backlog

- Visual automation recorder with editable replay steps.
- Rich timeline with snapshot diffs, screenshots when Chrome CDP is active, and step-by-step replay.
- Reusable browser workflows scoped by workspace.
- Computed-style snapshot mode for pages where external CSS fails.
- Deeper iframe, Shadow DOM, SPA, authenticated-session, and multi-tab synchronization support.
- Stronger Chrome/Chromium CDP path for pixel-perfect rendering when LightPanda cannot provide enough visual fidelity.
