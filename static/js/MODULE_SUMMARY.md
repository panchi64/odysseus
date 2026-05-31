# Module Organization Summary

Per-module index for the Odysseus frontend (`static/js`). One entry per file:
what it owns + its key exports.

> For conventions, the loading model, the cross-module sharing rules (ES imports +
> a few `window.*` globals + `storage.js` + per-feature `state.js`), and gotchas,
> see [`./CLAUDE.md`](./CLAUDE.md). **This file is the per-module index** — it does
> not repeat those conventions.

## Loading

The app boots as **native ES modules** — no bundler, no transpile, no build step.
`static/index.html` ends with a block of `<script type="module" src=...>` tags
(`storage.js`, `ui.js`, ... `app.js` **last**, then `init.js`), with `modulepreload`
hints in the head for `app.js`, `chat.js`, `ui.js`, `sessions.js`, `markdown.js`.
`app.js` is the wiring entry: it imports the feature modules and ties them together
(it has no exports). Modules share via real `import`/`export` (most `export default`),
with a handful also hung on `window.*`. Modules also `import` each other directly, so
not every dependency is listed in index.html.

> Note: there is no per-file `<script src>` load order anymore. The ordered
> `<script>` list in older versions of this doc was wrong.

---

## Chat core

- **app.js** — Entry point. Imports every module, wires event listeners / drag-drop /
  global shortcuts, sets `API_BASE`, and globalizes a few modules on `window.*`. No exports.
- **chat.js** — The big one. Chat submit, streaming orchestration, abort, edit/resend/
  regenerate/fork, background-stream detach/check. `export default chatModule` (`init`,
  `handleChatSubmit`, `abortCurrentRequest`).
- **chatStream.js** — SSE event handlers extracted from chat.js: `ui_control` events,
  background-stream management, completion toasts. `export default chatStream` (`handleUIControl`).
- **chatRenderer.js** — Message rendering helpers extracted from chat.js: attachments, model
  badges/colors, per-message/session cost, timestamps. `export shortModel`, `getModelCost`,
  `getSessionCost`, `updateMessageAttachments`.
- **markdown.js** — Markdown → HTML, code highlighting, thinking/reasoning-block extraction,
  Mermaid render, collapsibles. `export default markdownModule` (`mdToHtml`, `renderContent`,
  `processWithThinking`, `squashOutsideCode`).
- **ui.js** — UI utilities: toasts (`showToast`/`showError`), `el()`, clipboard, scroll
  management, textarea auto-resize, debounce, styled confirm/prompt. `export default uiModule`.
- **init.js** — Boot-time initialization, extracted from index.html inline scripts. No exports (runs on load).

## Sessions & context

- **sessions.js** — Session/chat lifecycle: list render, load, select, direct-chat create,
  pending-session materialize, current model/endpoint accessors. `export default sessionModule`
  (also `window.sessionModule`); `loadSessions`, `selectSession`, `renderSessionList`.
- **memory.js** — AI memory: load/add/edit/delete, tidy, extract-from-session, import/export,
  list render + count. `export default memoryModule` (`loadMemories`, `addNewMemory`).
- **skills.js** — Skills tab in the Memory modal (SKILL.md files under `data/skills/`): list,
  search, view, edit. `export default` (`loadSkills`, `openSkill`).
- **presets.js** — Conversation/character presets + prompt templates: load/save/activate,
  custom-preset modal, character inject. `export default presetsModule` (`PROMPT_TEMPLATES`,
  `loadPresets`, `setActivePreset`).
- **rag.js** — RAG document management: load personal docs, upload files, included files.
  `export default ragModule` (`loadPersonalDocs`, `uploadRagFiles`).
- **group.js** — Group Chat: multi-model conversations (parallel or round-robin).
  `export init`, `startGroup`, `sendMessage`, `stopGroup`.
- **slashCommands.js** — Slash-command handlers + dispatcher (extracted from chat.js); also
  setup wizard. Large. `export default` (`initSlashCommands`, `handleSlashCommand`, `isCommand`).

## Models & providers

- **models.js** — Model & provider scanning/discovery + refresh; cached items.
  `export default modelsModule` (`refreshModels`, `refreshProviders`, `getCachedItems`).
- **modelPicker.js** — Chatbox model-selector dropdown (extracted from sessions.js).
  `export initModelPicker`, `updateModelPicker`.
- **providers.js** — AI provider logo SVGs, regex-matched against model names.
  `export default` (`providerLogo`).
- **search.js** — Web-search settings; reads active provider from admin settings.
  `export default searchModule` (`getCurrentProvider`, `refresh`).
- **search-chat.js** — Ctrl+K command palette to search across conversations.
  `export default searchChatModule` (`openSearch`, `init`).

## Settings / chrome

- **settings.js** — Settings panel (large): user preferences — AI models, search, appearance.
  `export default settingsModule` (`open`, `close`).
- **admin.js** — Admin-only panel: users, endpoints, MCP, RAG, embeddings, tokens, webhooks,
  features. `export default adminModule` (`open`, `close`).
- **theme.js** — Preset + custom themes (colors, font/density, bg effects, frosted glass,
  patterns), persisted to localStorage. `export default themeModule` (also `window.themeModule`);
  `THEMES`, `applyColors`, `saveCustomTheme`.
- **colorPicker.js** — In-house color picker (HSV square, hue bar, eyedropper, harmony) that
  wraps existing `<input type="color">`. `export attachColorPicker`, `initColorPickers`.
- **sidebar-layout.js** — Sidebar icon rail, hamburger cycling, mobile backdrop & swipe.
  `export initSidebarLayout`, `syncRailSide`.
- **section-management.js** — Sidebar section collapse/expand + drag reorder.
  `export initSectionCollapse`, `initSectionDrag`.
- **keyboard-shortcuts.js** — Dynamic global keybind registry. `export initKeyboardShortcuts`.
- **spinner.js** — ASCII spinner / loading-row indicators for AI thinking state.
  `export default spinnerModule` (`create`, `createLoadingRow`).
- **dragSort.js** — Vertical drag-to-reorder with magnetic snap. `export default` (`enable`).
- **langIcons.js** — SVG icons per document language / file type. `export default` (`langIcon`).
- **censor.js** — Sensitive-info censor: blurs emails/keys/tokens in AI output, click to reveal.
  `export default censorModule` (`init`, `censorElement`, `setEnabled`).

## Windowing / modals

- **modalManager.js** — Unified open/minimize/close for tool modals + rail/sidebar buttons.
  `export default` (`register`, `minimize`, `restore`, `toggle`, `close`).
- **modalSnap.js** — Right/edge snap docking for draggable modals (dock as a side panel).
  `export applyRightDock`, `clearRightDock`, `makeRightDockController`.
- **windowDrag.js** — Shared draggable-window helper (drag + snap-to-top fullscreen + edge
  dock); replaces per-page copies. `export makeWindowDraggable`.
- **tileManager.js** — Desktop window tiling for tool modals (drag-to-zone snap).
  `export previewZoneAt`, `snapModalToZone`.
- **emojiPicker.js** — Monochrome icon picker popover (inserts monochrome SVG glyphs).
  `export default` (`createEmojiButton`).

## Input / IO

- **fileHandler.js** — File attachment handling: picker, upload, attachment strip,
  pending-files state, preview/remove. `export default fileHandlerModule`.
- **voiceRecorder.js** — Voice recording: start/stop, audio file creation, mic permission,
  recording UI. `export default voiceRecorderModule`.
- **tts-ai.js** — AI text-to-speech (server TTS + browser Web Speech). `export default ttsModule`
  (`addAITTSButton`, `AITTSManager`).
- **signature.js** — Reusable signature module: `capture` (draw modal) + `pick`.
  `export default` (`capture`, `pick`, `getLastUsed`).
- **codeRunner.js** — Run code blocks (Python/JS/HTML/server) via backend sandbox.
  `export default codeRunnerModule` (`run`, `runPython`, `runServer`).

## Tours

- **tourAutoplay.js** — Auto-fires the matching `/tour-<x>` slash command the first time a
  tool modal opens (one-shot per modal). `export default` (`init`).
- **tourHints.js** — One-time "pro tip" hint on first modal open (snap/fullscreen tip).
  `export default` (`init`).

## Standalone pages (one file per route)

- **notes.js** — Google Keep-style notes & todos, rendered as a sidebar panel (not a modal);
  includes reminder due-badge. `export default notesModule` (`openPanel`/`openNotes`, `closePanel`).
- **tasks.js** — Scheduled recurring LLM prompts. `export default tasksModule` (`openTasks`, `closeTasks`).
- **gallery.js** — Photo backup + AI-generated image library page. `export default galleryModule`
  (`openGallery`, `closeGallery`).
- **galleryEditor.js** — The canvas/layer image editor (large; the actual consumer of the
  `editor/` subdir — imports its canvas/mask/tools/fx submodules). `export default
  galleryEditorModule` (`openEditor`, `closeEditor`, `exportPNG`, `exportToGallery`).
- **document.js** — Multi-document tabbed editor panel alongside chat (the largest module).
  `export default documentModule` (`init`, `openPanel`, `loadDocument`, `createDocument`).
- **documentLibrary.js** — Library modal with Chats / Documents / Research / Archive tabs
  (split out of document.js). `export initLibrary`, `openLibrary`, `closeLibrary`.
- **calendar.js** — CalDAV-backed month/week/year calendar page. `export default calendarModule`
  (`openCalendar`, `closeCalendar`).
- **emailInbox.js** — Email inbox list in the sidebar (opens messages as documents, archive).
  `export init`, `loadEmails`, `openReplyDraft`.
- **emailLibrary.js** — Email library popup modal (grid of emails with search/filter).
  `export initEmailLibrary`, `openEmailLibrary`, `closeEmailLibrary`.
- **assistant.js** — Personal Assistant: sidebar entry + settings modal for a specially-flagged
  CrewMember whose pinned session reuses the chat path. `export default assistantModule`
  (`openAssistantChat`, `openAssistantSettings`).
- **researchSynapse.js** — Live SVG visualization of a deep-research run (query/sub-question/
  source graph). `export default createResearchSynapse`.

### Cookbook family

The Cookbook is a local-model ops workflow ("What Fits?" hardware fit + download/serve/run
of LLM servers), split across these files:

- **cookbook.js** — Main module (v2): "What Fits?" + saved presets, env state, inline action
  panels, backend/parser detection. `export _envState`, `_detectBackend`, plus many helpers.
- **cookbook-hwfit.js** — "What Fits?" hardware/model-fitting UI (GPU toggles, fit table).
  `export _hwfitFetch`, `_hwfitRenderHw`, `_hwfitRenderList`.
- **cookbookDownload.js** — Download tab: SSE streaming model download + command building.
  `export initDownload`, `_runModelDownload`, `_buildDownloadCmd`.
- **cookbookServe.js** — Serve tab: cached-model list, serve-panel building, preset slots, launch.
  `export initServe`, `openServePanelForRepo`, `_fetchCachedModels`.
- **cookbookRunning.js** — Running-tasks tab: task cards, status monitoring, stop/restart,
  auto-fix/retry, background monitor. `export _loadTasks`, `_syncFromServer`, `_serveAutoRetry`.
- **cookbook-diagnosis.js** — Error pattern matching + diagnosis UI for failed runs.
  `export ERROR_PATTERNS`, `_diagnose`, `_showDiagnosis`.

## Utilities / shared

- **storage.js** — `localStorage` wrapper: typed `KEYS` + JSON-safe `get/set/getJSON/
  setJSON/getToggle`. `export default Storage`. Use instead of touching `localStorage` directly.
- (See also the cross-cutting helpers above: **ui.js**, **markdown.js**, **spinner.js**,
  **dragSort.js**, **colorPicker.js**, **emojiPicker.js**, **langIcons.js** — listed in their
  functional groups.)

---

## Feature subdirectories

- **`editor/`** (largest subdir) — implementation modules for the canvas/layer image editor.
  Its consumer/entry is the top-level **galleryEditor.js**, which imports these submodules.
  Groups: canvas
  (`canvas-coords/events/transforms.js`), layers (`layer-helpers/layer-panel.js`), masks
  (`mask-utils.js`, `harmonize-masks.js`), strokes (`stroke-pipeline.js`,
  `stroke-tool-sliders.js`), AI tools (`ai-inpaint/ai-rembg/ai-models/ai-tool-runner/
  ai-tools-misc.js`), `wire-*.js` (bind topbar/controls/import), history (`history-panel.js`),
  and `state.js` (shared editor state). Submodule dirs: `tools/` (brush, clone, eraser,
  gradient, heal, selection, shapes, text), `filters/` (blur, color, distort, noise, sharpen),
  `fx/` (glow, shadow, vignette), `build/` (compose, export, render).
- **`compare/`** — side-by-side multi-model comparison. Entry `index.js`; `state.js` (shared
  mutable state), `panes.js`, `stream.js`, `scoreboard.js`, `vote.js`, `selector.js`,
  `probe.js`, `models.js`, `icons.js`.
- **`research/`** — deep-research UI: `panel.js` (start/monitor jobs side panel),
  `jobs.js` (job list + status polling).
- **`calendar/`** — calendar helpers for the top-level `calendar.js` page: `reminders.js`
  (reminder scheduling/notifications), `utils.js` (date/format helpers).
- **`emailLibrary/`** — helpers for the top-level `emailLibrary.js` page: `state.js` (shared
  mutable state), `utils.js` (formatting helpers), `signatureFold.js`.
