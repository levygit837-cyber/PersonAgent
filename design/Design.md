# PersonAgent Design.md

Status: working source of truth  
Target surface: `@desktop-electron`  
Primary product area: Chat UI  
Created: 2026-04-25

## Purpose

This file is the reusable visual contract for PersonAgent. It should guide every UI change in the Electron desktop app before code is touched.

The Electron client in `@desktop-electron` is the sole design target for PersonAgent desktop UI. All visual decisions and reusable UI contracts belong to the Electron app.

PersonAgent should feel like a local AI workbench: technical, quiet, fast to scan, and built for repeated use. The UI should not feel like a landing page, a generic SaaS dashboard, or a decorative AI demo.

## Research Basis

This design contract is based on current implementation plus these external references:

- W3C Design Tokens Format Module: design tokens are platform-agnostic design decisions with name, value, type, and optional description. Use this model to keep style decisions portable and documented.  
  Source: https://www.w3.org/community/reports/design-tokens/CG-FINAL-format-20251028/
- Tailwind CSS theme variables: design tokens should drive utility classes and runtime CSS variables instead of hard-coded component styling. PersonAgent currently uses Tailwind v3, so the implementation maps CSS custom properties through `tailwind.config.ts`.  
  Source: https://tailwindcss.com/docs/theme
- Radix UI accessibility: primitives are expected to handle ARIA attributes, focus management, and keyboard navigation for complex controls. PersonAgent uses Radix for menus, select, tabs, and tooltips.  
  Source: https://www.radix-ui.com/primitives/docs/overview/accessibility
- Storybook documentation patterns: reusable UI systems should document component states, variants, interaction cases, and accessibility checks. Storybook is not required today, but this file should use the same state-matrix mindset.  
  Source: https://storybook.js.org/docs/9/writing-tests/accessibility-testing

## How To Use This File

1. Start with the product aesthetic and component contracts below.
2. If a visual value is reused, add or update a token before styling individual components.
3. Prefer existing primitives in `@desktop-electron/src/components/ui`.
4. When adding a new component, define its states in this file or in a component-level note before implementation.
5. Validate desktop and compact layouts after every meaningful UI change.

## Current Stack

- Runtime shell: Electron 41
- Renderer: React 19, TypeScript, Vite
- Styling: Tailwind CSS 3, CSS custom properties, `class-variance-authority`
- Primitives: Radix UI, shadcn-style local wrappers
- Icons: `lucide-react`
- State: Zustand, TanStack Query
- Primary paths:
  - `@desktop-electron/src/styles.css`
  - `@desktop-electron/tailwind.config.ts`
  - `@desktop-electron/src/components/ui`
  - `@desktop-electron/src/components/chat`
  - `@desktop-electron/src/components/layout`

## Product Aesthetic

PersonAgent is a focused desktop tool for local model work.

Design attributes:

- Quiet dark interface
- Dense but breathable information
- Clear hierarchy without oversized hero treatment
- Technical English copy
- Compact execution trace
- Transparent, floating composer behavior
- Restraint over glow, gradients, blur, and visual effects

Avoid:

- Marketing-style hero sections
- Decorative orbs, bokeh, abstract gradients, and heavy glow
- Nested cards or section-sized cards
- Large rounded cards for ordinary content
- One-hue palettes dominated by only teal, purple, blue, brown, or gray
- Icon-heavy tool timelines
- Mock-only workflow or chat states in production UI

## Design System Model

Use three token layers:

1. Primitive tokens: raw values such as color scales, spacing units, font families, duration values.
2. Semantic tokens: product meanings such as `background`, `foreground`, `border`, `primary`, `muted`.
3. Component tokens: component-specific values such as dock shadow, shell sidebar width, feed max width.

Implementation rule:

- Semantic tokens live in `@desktop-electron/src/styles.css`.
- Tailwind aliases live in `@desktop-electron/tailwind.config.ts`.
- Components should use semantic Tailwind classes like `bg-background`, `text-muted-foreground`, `border-border`, and `text-teal`.
- New component JSX should not introduce raw hex, raw HSL, or one-off shadow strings. Add a token first.

## Token Registry

Current semantic tokens:

| Token | Current role | Usage rule |
| --- | --- | --- |
| `--background` | app canvas | Default window and chat background |
| `--foreground` | primary text | Main readable text only |
| `--card` | raised dark surface | Composer, chips, command controls, contained tool output |
| `--popover` | floating menu surface | Radix menus, selects, tooltips |
| `--primary` | primary action | Send, active intent, rare emphasis |
| `--secondary` | low emphasis control | Passive buttons and neutral controls |
| `--muted` | secondary surface | Search fields, disabled zones, quiet groups |
| `--muted-foreground` | secondary text | Metadata, labels, helper copy |
| `--accent` | hover or active surface | Selected nav, hover rows, menu focus |
| `--destructive` | destructive and error | Stop, failed tool calls, API errors |
| `--border` | hairline structure | Dividers, controls, menu outlines |
| `--input` | input boundary | Text areas, command fields |
| `--ring` | focus ring | Keyboard focus and active control outline |
| `--success` | completed status | Completed tool status and online state |
| `--warning` | caution state | Warnings, degraded state |
| `--teal` | product accent | Model chip, active trace, primary accent |

Component tokens to preserve:

| Token or value | Role | Rule |
| --- | --- | --- |
| `--radius: 8px` | global radius ceiling | Use `rounded-md` or smaller for most UI |
| `shadow-dock` | floating composer elevation | Use only for the main input dock or a direct successor |
| `260px` sidebar | expanded shell rail | Keep a stable scanning column on desktop |
| `64px` collapsed sidebar | collapsed shell rail | Icon-only state for desktop widths |
| `820px` feed max width | chat content measure | Preserve readable message length |
| `780px` dock max width | composer measure | Composer should align near feed width |

## Color Direction

The current palette is a dark graphite base with teal as the main accent. Keep that relationship, but avoid letting the app become a flat black void.

Use color by function:

- Backgrounds create hierarchy.
- Borders define structure.
- Teal marks active model, focused local-agent affordances, and sparse primary actions.
- Destructive marks real interruption, failure, or danger.
- Success marks completed execution or online state.
- Warning marks degraded state, not decoration.

New accent colors may be introduced only when they solve a semantic problem. Prefer one additional warm or neutral accent for warnings or trace differentiation instead of adding more teal variants.

## Typography

Font families:

- UI sans: `Inter`, `Geist`, system sans
- Technical mono: `JetBrains Mono`, system mono

Type rules:

- Chat content: `15px`, relaxed line height, optimized for reading.
- UI controls: `12px` to `14px`, compact and stable.
- Metadata labels: `10px` to `11px`, mono, uppercase only for scannable system labels.
- Tool output: mono, `11px`, compact line height.
- Do not use viewport-scaled font sizes.
- Letter spacing must never be negative.
- Reserve large type for actual empty states or major headings. Do not use hero-scale type inside panels, cards, or tool surfaces.

## Layout

Desktop shell:

- `TitleBar` owns native window controls and backend status.
- `Sidebar` is the single primary navigation rail.
- `ChatWorkspace` owns chat header, feed, and floating composer.
- `WorkspacePanel` is optional context, not a second navigation system.

Responsive rules:

- The sidebar hides below `720px`.
- Secondary header metadata should hide before it wraps awkwardly.
- The composer remains reachable and readable at `390px` width.
- Text inside buttons and chips must truncate cleanly instead of resizing the layout.
- Fixed-format controls need stable width, height, or max width so hover, loading, and labels do not shift the layout.

## Chat UI Contract

### Message Feed

Current path: `@desktop-electron/src/components/chat/message-feed.tsx`

Rules:

- Keep the feed centered with a max width around `820px`.
- Do not put the entire conversation in a card.
- Preserve bottom-aware auto-scroll: follow new output only when the user is already near the bottom.
- Empty state should be quiet and direct: one heading, one supporting line, no illustrative hero.
- Preserve enough bottom padding for the floating input dock.

Required states:

- Empty
- Streaming response
- Streaming with reasoning
- Streaming with tool events
- Error banner
- Loaded saved conversation
- Compact width

### User Message

Current path: `@desktop-electron/src/components/chat/user-message.tsx`

Rules:

- Keep the `User` label compact and mono.
- User content should be text-first, not a chat bubble unless the entire message system is redesigned.
- Preserve whitespace and readable line height.

### Agent Message

Current path: `@desktop-electron/src/components/chat/agent-message.tsx`

Rules:

- Keep `PersonAgent` as the compact agent label.
- Render Markdown consistently for final assistant content.
- Reasoning, tools, and content must preserve backend emission order.
- Do not wrap assistant output in decorative cards.
- Use prose styles only for generated assistant text, not shell/tool metadata.

### Reasoning

Current path: `@desktop-electron/src/components/chat/reasoning-block.tsx`

Rules:

- Reasoning is an execution-trace event, not a card.
- It should expand while actively streaming.
- It should collapse shortly after output starts or completes.
- The collapsed row must remain visible and manually reopenable.
- Show running state with text plus restrained status indicator.

### Tool Events

Current path: `@desktop-electron/src/components/chat/tool-block.tsx`

Rules:

- Tool events are dense, mono, and mostly icon-free.
- Use status dots plus text, not large cards.
- Completed read/search/shell/web/lsp/todo/task events should group when consecutive.
- Completed groups start collapsed.
- Tool output appears only when expanded, inside compact mono `pre` blocks.
- Running tools must not keep stale `running` labels after terminal status.
- Permission and error states must be explicit in text, not color-only.

Current compact categories:

- `read`: `Read`, `read_file`
- `search`: `Glob`, `Grep`, `search_files`
- `shell`: `shell`
- `web`: `WebFetch`
- `lsp`: `LSP`
- `todo`: `TodoWrite`
- `task`: `Task*`

### Input Dock

Current path: `@desktop-electron/src/components/chat/input-dock.tsx`

Rules:

- The composer floats over the chat content.
- The outer overlay stays transparent; no black side bands.
- Keep the dock max width around `780px`.
- Top control row contains workspace, model, reasoning, and compact endpoint metadata.
- The textarea grows up to a fixed max height, then scrolls.
- Send and stop are icon buttons with clear `aria-label`.
- Controls are disabled during streaming unless they are directly related to stopping.
- Workspace and reasoning controls stay near the input, not hidden in settings.

Required states:

- Empty input
- Text entered
- Streaming
- Disabled controls
- Long prompt
- Narrow width

### Sidebar

Current path: `@desktop-electron/src/components/layout/sidebar.tsx`

Rules:

- Keep one primary sidebar.
- Keep Chat as the primary shell mode.
- Session lists must be compact and scannable.
- Use icons for navigation and destructive actions where they improve recognition.
- Use tooltips for icon-only collapsed controls.
- Avoid adding a second heavy navigation column.

## Controls And Primitives

Use the local shadcn-style wrappers:

- `Button`
- `DropdownMenu`
- `Select`
- `Tabs`
- `Textarea`
- `Tooltip`

Rules:

- Add variants through `cva` in the primitive when the style repeats.
- Do not hand-style a new button shape in feature components.
- Icon buttons need `aria-label`.
- Unfamiliar icon-only actions need a tooltip.
- Radix primitives should own complex focus, menu, popover, tab, select, and tooltip behavior.
- Focus-visible states must use the `ring` token.

## Accessibility Contract

Required for every interactive component:

- Keyboard reachable by Tab or documented arrow-key pattern.
- Visible focus state.
- Accessible name through text, `aria-label`, or labelled trigger.
- Escape closes popovers, menus, and dialogs where relevant.
- Enter or Space activates button-like controls.
- Error and permission states are represented in text.
- Status cannot rely only on color.
- Contrast should meet WCAG AA for normal text wherever possible.

## Motion

Motion should be minimal:

- Use short transitions for hover and focus.
- Avoid ambient loops and decorative animation.
- Streaming indicators should communicate real activity.
- Prefer opacity and color changes over movement.
- Respect reduced-motion if larger animation is introduced.

## Copy

Visible product copy should stay in technical English.

Good labels:

- `New Session`
- `Context Tree`
- `Workspace`
- `Reasoning: Low`
- `Local agent ready`
- `Read 4 files`
- `Search 3 times`

Avoid:

- Marketing claims
- Long instructional text inside the app
- Decorative AI language
- Repeating implementation details that do not help the user act

## Component State Matrix

Every reusable component should have these states documented or tested:

| State | Required? | Notes |
| --- | --- | --- |
| Default | Yes | Normal idle appearance |
| Hover | Yes | Must not resize layout |
| Focus visible | Yes | Keyboard-visible ring |
| Active or selected | When applicable | Uses semantic active surface |
| Disabled | When applicable | Lower opacity, no pointer action |
| Loading or running | When applicable | Real runtime state only |
| Error | When applicable | Text plus destructive token |
| Permission required | Tool controls | Text must be explicit |
| Empty | Data surfaces | Quiet, no fake data |
| Compact width | Chat and shell | Validate near `390px` width |

## Implementation Rules

- Prefer semantic utilities over raw CSS values.
- Add shared styles to primitives before repeating class strings.
- Keep page sections unframed; use cards only for repeated items, modals, menus, or genuinely framed tools.
- Do not put cards inside cards.
- Keep radius at `8px` or below unless a component token explicitly says otherwise.
- Use `lucide-react` icons for recognizable controls.
- Keep tool timelines icon-free unless a specific user-facing action needs an icon.
- Do not introduce mock production states for Chat.
- Preserve backend event order in UI rendering.
- Preserve Markdown support for reasoning, final assistant output, and tool output where applicable.

## Validation

Run for code changes:

```bash
cd @desktop-electron
npm run typecheck
npm test
```

Run when styling or layout changes:

```bash
cd @desktop-electron
npm run build:renderer
```

Manual visual checkpoints:

- `1440x900`: full shell, sidebar, header, feed, dock
- `1280x800`: normal desktop density
- `390x844`: compact chat without sidebar

Keyboard checkpoints:

- Tab through titlebar controls, sidebar controls, header controls, dock controls.
- Open and close dropdowns with keyboard.
- Send a message with Enter.
- Insert a newline with Shift+Enter.
- Stop a streaming response from the composer button.

## Future Documentation

If Storybook is added later, create stories for:

- `Button`
- `DropdownMenu`
- `Select`
- `Tooltip`
- `InputDock`
- `MessageFeed`
- `AgentMessage`
- `ReasoningBlock`
- `ToolBlock`
- `Sidebar`

Each story should include default, compact, disabled, loading/running, error, and long-content cases where applicable.

## Current Design Debt

- The current dark canvas can read as too empty in large idle states. Prefer subtle surface hierarchy over more glow.
- Some layout colors still use one-off hex values in shell components. Migrate repeated values into semantic tokens when touched.
- `Design.md` is now the contract, but component stories do not exist yet.
- Visual regression should eventually be automated for `1440`, `1280`, and `390` widths.
