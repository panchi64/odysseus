# Odysseus Frontend — UX Gap Audit

> **Status:** Phase 1 (mock-data UI, no backend wired). This audit reviews the UX *as designed* and flags where mock-only wiring leaves a user-facing gap that must close before — or as part of — Phase 2.
>
> **Method.** One isolated reviewer per page (33 pages), each reasoning through 2–3 user personas (including at least one non-power-user) and judging against the terminal-HUD design system and its primitives. **319 gaps** were found: **73 high / 137 medium / 109 low**. Synthesis (themes, priorities) below; the full per-page list is the appendix.
>
> **How to read.** The body is organized by *cross-cutting theme*, because the same defect repeats across many screens — fixing it once at the component/pattern level closes dozens of gaps. Use the appendix when working a specific screen.

---

## Headline

The UI is visually complete and consistent — the design system is doing its job. The gaps are almost entirely about **acting on what's shown**, not about how it looks. Three sentences capture the whole report:

1. **Controls look alive but aren't.** Across ~15 screens, primary buttons and menu items are stubbed (`onSelect: () => {}`), clear their input instead of submitting, or complete with no visible result. The user can't tell success from no-op from failure.
2. **Failure and danger are undefined.** Destructive actions fire without a confirmation guard; error states are missing even where the data model already has an `error` type; there's no undo/retry/recovery anywhere.
3. **Screens render data but don't support decisions or scale.** Timestamps, sizes, ETAs, exit status, and "what does this mean" context are missing (64 gaps), and lists have no search/filter/sort/bulk for when N grows (≈50 gaps).

None of these need new design language — every fix maps to a primitive that already exists (`Modal`, `StatusFlag`, `EmptyState`, `LoadingText`, `Tooltip`, `Menu`, `ProgressBar`, `Input`, `Tabs`, `Drawer`). The work is wiring discipline and a few shared patterns, not new UI.

### Gaps by theme

| # | Theme | Severity weight | Recurs on |
|---|---|---|---|
| 1 | Destructive actions have no confirmation guard | 🔴 high | ~15 screens |
| 2 | Inert & silent controls ("UI theater") | 🔴 high | ~16 screens |
| 3 | Failure is undefined — missing error states | 🔴 high | ~12 screens |
| 4 | No recovery — undo / retry / reset / account & vault recovery | 🔴 high | ~12 screens |
| 5 | Data without decision-support (information gaps) | 🟠 med | 64 gaps, most screens |
| 6 | Lists don't scale — no search / filter / sort / bulk | 🟠 med | ≈50 gaps, ~15 screens |
| 7 | Unsaved-change protection & dirty state | 🟠 med | ~6 screens |
| 8 | Keyboard, focus & accessibility | 🟠 med | ~10 screens |
| 9 | Responsive dead-ends (critical nav hidden on mobile) | 🔴 high | Chat, Email, Gallery, Documents |
| 10 | First-run is blank — onboarding & domain guidance | 🟠 med | 23 gaps |
| 11 | Phase-1 honesty — preview vs. broken is indistinguishable | 🟠 med | Login, Signup, Dashboard, Research |

---

## Tier 1 — systemic, fix at the pattern level

### Theme 1 — Destructive actions have no confirmation guard

**Pattern.** Delete / remove / stop / revoke / disable fire immediately on click. No "are you sure," no naming of the target, often no undo.

**Where (high):** Research Library (delete report), Documents Library (delete), Knowledge Base/RAG (remove source), Skills (delete), Signatures (delete), Calendar (delete event), Cookbook (stop running server), Memory (delete/merge), Contacts (delete), Tasks (toggle a live scheduled job), **Shell (run `rm -rf` etc. with no gate)**. Plus medium on Gallery (AI edit overwrites), Settings (2FA disable), API Tokens (revoke), Backup (export), Speech (cache wipe), Vault.

**Why it matters.** This is the highest-consequence class in the audit. Reports represent hours of synthesis; memories are a knowledge base; stopping a server drops live sessions; a mistyped shell command is irreversible. The cost of a fat-finger is permanent data/work loss.

**Fix (one shared pattern).** A single `confirmDestructive({ title, detail, confirmLabel, tone:'alert' })` helper built on the existing `Modal` + `Button` (danger variant). Every destructive `onSelect`/`onClick` routes through it; the dialog names the target ("Delete *Q3 Market Research*?") and states irreversibility. For **Shell**, add a heuristic pre-exec confirm for `rm`/`rmdir`/`dd`/`kill -9`/`sudo`. Where feasible (Memory, Notes, Uploads), prefer a brief **undo toast** over a modal — less friction, same safety.

### Theme 2 — Inert & silent controls ("UI theater")

**Pattern.** A control looks interactive but does nothing visible: stubbed handler, input that clears instead of submitting, or an action that completes with zero feedback (no toast, no state change, no error).

**Where (high):** Research Library (all menu actions stubbed), RAG (ADD SOURCE clears the field), Uploads (UPLOAD / BROWSE dead; EXPORT / SAVE FIELDS silent), Signatures (insert actions no-op), Calendar (SYNC silent), Contacts (SYNC silent), Backup (DOWNLOAD non-functional), Email (SEND no handler, no validation), Compare (vote recorded with no confirmation), Skills (TEST produces no result), MCP (no feedback after registering a server), Memory (PIN/EDIT/DELETE silent), Health (REFRESH no result), Shell (silent success on no-output commands).

**Why it matters.** Silence trains distrust. Users re-click, assume the feature is broken, or worse, assume success that didn't happen (a sent email, a saved field). It's the difference between "Phase-1 preview" and "broken app" — and right now the user can't tell.

**Fix.** Establish the missing **feedback primitive**: a transient status flash / toast (there is no `Toast` in `~/ui` today — adding one closes a large fraction of this theme). Then a project rule: *every action resolves to one of {pending → success, pending → error}* visibly. For genuinely-not-yet-wired Phase-1 controls, set `disabled` + a `Tooltip` ("Available in Phase 2") rather than leaving them clickable-but-dead. Make whole `ListRow`s with an `href` navigate on row-click instead of hiding "View" inside a menu.

### Theme 3 — Failure is undefined (missing error states)

**Pattern.** Screens implement *loading* (`LoadingText`) and *content*, but not *error*. Several data models already include an `error`/`alert` status the UI never renders.

**Where (high):** Research Report (model has `error` status; screen only shows loading/not-found and hardcodes "COMPLETE"), Compare (no handling for a failed/timed-out stream), MCP (ERROR flag with no message/timestamp/retry), Integrations (failed test silently re-saves as "configured"), Speech (synthesis/mic-permission failure shows nothing), Backup (export/import failure hangs the bar). Plus Dashboard, Cookbook, Embedding, Code Runner, Contacts, Users.

**Why it matters.** A health/research/infra console that can't show its own failures is the cruel irony users will remember. "Configured: true" on a connection that actually failed is an active trap for background jobs.

**Fix.** Add the third branch everywhere a resource or action can fail: `<Show when={r.error}>` → `Panel state="alert"` / `StatusFlag status="alert"` with the reason + a **Retry**. Bake an `error` arm into the `data.ts` seam contract now so Phase 2 fills it in without screen changes. Block the Integrations "save unverified" path: disable SAVE until a fresh test passes.

### Theme 4 — No recovery (undo / retry / reset / account & vault recovery)

**Pattern.** When something goes wrong or is lost, there's no path back.

**Where (high):** Login (no "forgot password" / account recovery — a locked-out user has no route), Vault (no recovery if master password is forgotten — permanent lockout for a single-user app), Memory (no undo for delete/merge), Tasks (the firefighter lands here *because* a job failed but there's no Retry — run history is read-only), Uploads (no retry for failed extraction), MCP/Integrations (no retry connection). Document Editor version history is read-only (no restore/diff).

**Why it matters.** For a single-user self-hosted system, a dead-end *is* the support channel. "Forgot the vault password" with no answer is catastrophic.

**Fix.** Add recovery affordances even if Phase-1-static: a "Forgot password?" link with guidance (Login, Vault → "re-initialize via /setup"); a **Retry** action on every failed run/connection/extraction; click-to-restore on Document version rows (`Modal` diff + restore-with-confirm).

### Theme 9 — Responsive dead-ends (critical nav hidden on mobile)

**Pattern.** Sidebars and nav panels are `hidden lg:*` with no small-screen fallback, stranding the user.

**Where (high/med):** Chat (session list hidden → can't switch or list sessions once inside one), Email (3-column layout overflows; accounts/folders hidden), Gallery & Documents (album/sidebar hidden, no alternative).

**Fix.** Use the existing `Drawer` as the mobile fallback for any panel that's `hidden lg:*` — a header affordance (session picker, "Accounts", "Albums") opens it. This is a small, repeatable change.

---

## Tier 2 — broad friction, fix per screen against a checklist

### Theme 5 — Data without decision-support (64 gaps)

Screens show the "what" but omit the context needed to decide or act: **Gallery** (no total storage size in a disk-bound local app), **Embedding** (no reindex ETA though docs/sec is in the data), **Tasks** (failure reason truncated to 60 chars, full output unreachable), **Shell** (no exit status / timing), **API Tokens** (scopes like `tools`/`admin` unexplained — leads to over- or under-provisioned tokens), **Health** (latency with no baseline), **Integrations/MCP** ("TEST FAILED" with no reason). Fix per screen: add the missing `Readout`/timestamp/`Tooltip`; make truncated detail expandable via `Modal`/`Drawer`.

### Theme 6 — Lists don't scale (≈50 gaps)

No search / filter / sort / bulk / pagination on lists that will grow: Memory, Skills, Gallery, Uploads, Email, Contacts, Users, API Tokens, Vault, Documents, Research Library, Signatures, Tasks history, Shell scrollback. Fix: a shared list-toolbar pattern (`Input` filter + sort `Select`/`Tabs` + optional multi-select for bulk actions), applied where N is unbounded.

### Theme 7 — Unsaved-change protection & dirty state

Edits can silently vanish: **Document Editor** (SAVE stub, no dirty indicator, no nav warning), **Settings** (the 2FA toggle flips and *stays* flipped if the confirm modal is closed via X/outside-click — UI state diverges from security state), **Uploads** form, **Notes** edit, **Users** privilege drawer (dismiss loses changes). Fix: track dirty vs. loaded; show a dirty marker; disable SAVE until dirty; warn on navigate; make modal X/outside-click === CANCEL (revert).

### Theme 8 — Keyboard, focus & accessibility

No Enter-to-submit on **Login**/**Signup** forms (no `<form>` wrapper — blocks keyboard-first and screen-reader semantics), no Cmd/Ctrl+Enter to run on **Code Runner**, no keyboard nav on **Contacts**/**Email**/**Compare**, no Escape-to-cancel on **Embedding** modal, copy-confirmations that are visual-only/transient (poor for SR users). Fix: real `<form onSubmit>` wrappers, a few keybindings, and non-transient/aria-announced confirmations.

### Theme 10 — First-run is blank (23 gaps)

Domain-heavy screens assume knowledge and give first-timers nothing: **RAG** (what is RAG / why add sources), **MCP** (what is MCP), **Cookbook** (suitability NOMINAL/WARN/ALERT unexplained), **Code Runner** (runtime/libraries/limits), **Embedding**, **Research** (no query examples), **Dashboard** (stats unexplained). Fix: empty-state guidance, one-line explainers, `Tooltip`s on jargon, example prompts.

### Theme 11 — Phase-1 honesty (preview vs. broken)

Mock-only behavior currently *masquerades as real failure or real success*: Login/Signup surface "MOCK: not wired" as an auth **error**; Dashboard shows **"ALL SYSTEMS · nominal"** even when mock services are in `alert`/`warn` (false green — destroys trust in the monitor); Research Report hardcodes "COMPLETE". Fix: compute `StatusFlag` from the data (trivial now that mocks are typed); replace mock-block errors with a single dismissible **info** banner up top; don't ship a green light that can't go red.

---

## Recommended sequence

1. **Two new shared primitives close the most gaps:** a `Toast`/transient-feedback component (Theme 2) and a `confirmDestructive` modal helper (Theme 1). Build these in `~/ui` first.
2. **Wire the seam's failure arm** (`data.ts` → `error`) and add the error branch to the ~12 screens in Theme 3; make `StatusFlag`s data-derived (Theme 11).
3. **Sweep destructive handlers** through `confirmDestructive`; add `Retry`/recovery affordances (Themes 1, 4).
4. **Mobile `Drawer` fallback** for the four hidden-nav screens (Theme 9).
5. **Per-screen Tier-2 pass** using a checklist: error state? dirty/unsaved guard? search/sort if list grows? missing decision-context? first-run guidance? keyboard submit?

A useful guardrail going forward: a screen isn't "done" until every interactive control has a defined **pending / success / error** state and every destructive one a guard.

---
## Appendix — Per-page findings

_Generated from the per-page audit. Each page lists its purpose, the personas the reviewer used, what already works, and every gap found (most important first)._


### Dashboard  
`/` · tier: open

**Purpose.** Landing page providing the admin/owner a quick snapshot of workspace health and status, plus fast navigation to core features. Sets expectations about what Odysseus is (a managed system with monitored services).

**Personas reviewed.**
- _Power-user admin returning after hours_ — Lands on dashboard to check if services are up and running. Needs to immediately spot any alerts and drill into failed systems without friction. Is busy and wants a single glance to know 'everything is fine' or to identify what broke.
- _First-time user landing from marketing/docs_ — New to Odysseus, arrives at / cold. Sees system stats they don't understand (qwen2.5-32b, 82.4 T/S, 32768 CTX) and a list of health checks for services they haven't set up yet. Confused about what's 'required to work' vs. 'optional monitoring.' Doesn't know where to start.
- _User checking workspace after a crash or config change_ — Suspects something went wrong (embedding reindex required). Lands on dashboard; sees service health showing 'ALERT' and 'WARN' states but no explanation of impact, no action button to fix it, and no link from the alert to the config page where they'd actually remediate it.

**Works well.** System telemetry (model, throughput, VRAM, context window) is prominently displayed and scanned in a single glance — the InstrumentBand layout is ideal for at-a-glance status.; Service health list is explicit and diegetic — showing actual service names (VECTOR SEARCH, EMAIL SYNC) with detail (chroma · 4214 docs, imap · last 14m ago) rather than generic 'Service 1' or icons alone.; Quick access tile grid exposes the most frequent features without scrolling; modal depth is zero, supporting the 'admin console' mental model.

**Gaps (8).**

- **🔴 HIGH · error-recovery** — Service health alerts are visible but not actionable
  - _Why:_ The EMBEDDINGS service shows 'alert: reindex required' and EMAIL SYNC shows 'warn: last 14m ago' — but there is no button to 'Reindex' or 'Sync now' on the dashboard. The user sees the problem but must navigate away to a detail page to act. For an owner who is checking on a crash, this is friction.
  - _Fix:_ For critical services (EMBEDDINGS, MODEL ENDPOINT), make the status badge a clickable link to the admin surface where action can be taken (e.g., 'reindex required' links to /models/embedding with an action button pre-focused). For lower-criticality services (EMAIL SYNC), a small 'Retry' or 'Sync now' button inline next to the status is acceptable. Use Tile/Button primitives already in scope.
- **🔴 HIGH · trust-safety** — 'ALL SYSTEMS' status flag is always nominal, no matter what services are down
  - _Why:_ The PageHeader shows 'ALL SYSTEMS · nominal' at all times, even when mocks include alert/warn services. This is a false positive — it erodes trust in the dashboard as a health monitor. The owner will learn to ignore it. The moment a real issue appears, they won't believe the green light.
  - _Fix:_ Make 'ALL SYSTEMS' status computed from the services list: if any service is 'alert', the flag is 'alert'; if any is 'warn', flag is 'warn'; else 'nominal'. Use the existing `Status` type and `StatusFlag` props. (This is now trivial since the mock data is typed.)
- **🟠 MED · onboarding** — No context for first-time users about what these stats mean
  - _Why:_ A new user (or even a returning user after a long break) sees 'VRAM 41.2 GB', 'CTX 32768', 'EMBEDDINGS · alert: reindex required' with no explanation of what matters, what's a problem, or where to go if they want to learn more. The dashboard assumes baseline knowledge of how Odysseus works.
  - _Fix:_ Add tooltips or a help icon next to unfamiliar terms (MODEL, CTX, TOK/S). For STATUS in SERVICE HEALTH, link the service name or the status badge to the relevant config surface (e.g., 'EMBEDDINGS alert' → /models/embedding). If a service has no required action, that's fine; but if it's 'alert', signal where to fix it.
- **🟠 MED · information** — No visual distinction between 'critical for operation' and 'informational' services
  - _Why:_ All 6 services are listed in the same list with the same weight. But MODEL ENDPOINT or EMBEDDINGS being down is an emergency; EMAIL SYNC being slow is a minor inconvenience. The dashboard does not signal severity or urgency — which service matters most?
  - _Fix:_ Group or reorder services by criticality: critical services (MODEL ENDPOINT, EMBEDDINGS) at the top, colored or marked differently. Or use two columns: one for 'Critical' and one for 'Monitoring.' This also reduces cognitive load ('check these first').
- **🟠 MED · missing-state** — Quick access tiles do not respect privilege tiers
  - _Why:_ The quick tile grid shows Chat, Research, Compare (all tier: 'open'), then Documents, Memory, Skills (tier: 'user' or 'admin'). In a single-user app this is fine, but in a household or multi-user future deployment, a tile pointing to an inaccessible feature is confusing. Currently there's no mock of a 'denied' scenario.
  - _Fix:_ Render tiles in the quick-access grid with `locked={true}` if the current user's privilege tier does not grant access (read `tier` from `NAV` item, compare against session store's privileges). The Tile component already supports locked state visually (dim + lock icon). This prepares for multi-user.
- **🟠 MED · error-recovery** — No empty or loading state when services fail to load
  - _Why:_ If `useServices()` or `useSystemBand()` errors (Phase 2 concern), the current code wraps them in `<Suspense fallback={<LoadingText/>}>`, which is good for loading. But if the resource errors, there's no error boundary or fallback shown — the section silently vanishes or the component crashes. For a health dashboard, this is ironic.
  - _Fix:_ Wrap `<Show when={services()}>` in a check for error state (use `<Show when={services.error}>` if SolidJS resources expose it, or add explicit error state to the `data.ts` seam). Render `<EmptyState title="SERVICE DATA UNAVAILABLE" detail="Check backend logs" />` if fetch fails. The ForbiddenView, EmptyState, and LoadingText primitives are already in the design system.
- **⚪ LOW · feedback** — THROUGHPUT panel is static mock; no indication it can go stale or is real-time
  - _Why:_ Shows 'TOKENS / SEC: 82.4' with no timestamp, no indication this is live, and in mock mode there's no refresh mechanism. A user might interpret this as the current rate, not a snapshot from 5 seconds ago.
  - _Fix:_ Either (a) add a small timestamp below the THROUGHPUT panel ('as of 14:32:51'), or (b) wrap it in a `Suspense` with a refresh-on-click pattern (common for admin consoles). In Phase 2, consider a live subscription model if this is critical. For now, a timestamp removes ambiguity.
- **⚪ LOW · consistency** — No indication that this is a mock-data interface (Phase 1)
  - _Why:_ An owner debugging a real issue might try to act on the mock data, not realizing it's a preview. This is low severity because the code clearly documents it, but in a live deployment the gap is zero.
  - _Fix:_ In Phase 1, consider a subtle badge or footer note ('MOCK DATA - Phase 1'). Alternatively, the moment Phase 2 data lands, this closes.


### Login  
`/login` · tier: public

**Purpose.** A public auth surface where users authenticate with credentials and 2FA (TOTP or backup codes) to access the Odysseus workspace. Phase 1 is UI-only; backend auth is not wired.

**Personas reviewed.**
- _Hurried first-timer_ — New Odysseus user navigates to /login, tries to create an account via the link, hits Phase 1 errors, comes back to login confused about what's actually functional vs. mock
- _Locked-out user_ — User forgot their password or lost their 2FA device; they land on login with no visible recovery path, only error messages saying 'MOCK: not wired yet', leaving them stuck
- _Keyboard power user_ — User types username, password, presses Enter expecting form submission, but nothing happens because inputs aren't wrapped in a form—they have to mouse-click the button

**Works well.** Proper 2FA workflow with backup code fallback path is designed in; Clear stage-based UI that separates credentials from 2FA reduces cognitive load; Error messaging clears on input (good UX for retrying), and loading state is text-based per design system

**Gaps (8).**

- **🔴 HIGH · interaction** — No form submission on Enter key
  - _Why:_ Users expect to press Enter after typing a password to submit; forcing a mouse click is friction and breaks accessibility. The screen has no <form> wiring, so Enter does nothing.
  - _Fix:_ Wrap the credentials/TOTP inputs in a <form> with onSubmit handlers. Keep the buttons for click support, but wire the form's submit event so Enter works naturally.
- **🔴 HIGH · trust-safety** — Mock-blocking error presented as real failure
  - _Why:_ On TOTP verification, the mock returns 'MOCK: Auth not wired yet — this is Phase 1 UI only.' This reads like a real auth rejection and could confuse users about whether the system is broken. It undermines trust.
  - _Fix:_ Replace the error with a dismissible, visually distinct **Info banner** (not an alert tone) above the form saying 'Phase 1: Backend authentication is not wired; this UI is a design preview. Login will be functional in Phase 2.' This clarifies the state once, upfront, rather than as a mysterious error after interaction.
- **🔴 HIGH · error-recovery** — No account recovery path visible
  - _Why:_ If a user loses their password or 2FA device, there is no visible way to recover access (password reset, account recovery, admin contact). The signup link is the only other option, which won't help a locked-out user.
  - _Fix:_ Add a 'Forgot password?' or 'Account recovery' link below the credentials form. For Phase 1, it can link to a page explaining how to contact the system admin or recover via alternate means (e.g., 'Contact your system administrator with your username to reset your password'). Use a Markdown/Text component with a subtle link.
- **🟠 MED · consistency** — Inconsistent navigation button styling
  - _Why:_ The 'Back' and 'USE AUTHENTICATOR APP / USE BACKUP CODE' buttons on the TOTP screen are raw HTML <button> elements with inline Tailwind classes, while the primary submit buttons use the Button component. This creates visual and behavioral inconsistency.
  - _Fix:_ Replace the raw buttons with Button components: Back button as `variant='secondary'`, and the mode-toggle button as `variant='secondary'` as well. Keep the layout Row structure but use proper Button components for consistency.
- **🟠 MED · content** — No password requirements guidance on login
  - _Why:_ SignupScreen shows 'Minimum 8 characters' as a hint, but LoginScreen has no hint about what a valid password should be. A user on their first login (or after password reset) might not know the requirements.
  - _Fix:_ Add an optional `hint` prop to the PASSWORD input on the credentials stage: 'Minimum 8 characters.' This mirrors the signup screen and sets expectations upfront.
- **🟠 MED · information** — Rate-limit warning is text-only, no enforcement visible
  - _Why:_ The footer says 'Access is rate-limited' but there's no visible countdown, lock message, or way to tell if you're being rate-limited. Users won't know if repeated failures trigger a cooldown.
  - _Fix:_ When a login attempt fails, show a subtle message like 'Too many attempts. Please wait X seconds before retrying.' paired with a disabled button countdown. For Phase 1, if not implemented, remove the rate-limit line and add it back in Phase 2.
- **⚪ LOW · content** — TOTP backup code format hint missing
  - _Why:_ The TOTP screen shows different placeholder text for backup mode ('XXXX-XXXX') but no explicit hint about the 8-character format, leaving users to infer from the placeholder.
  - _Fix:_ Add `hint='8-character code, formatted as XXXX-XXXX'` to the BACKUP CODE input when in backup mode, matching the guidance style of SignupScreen.
- **⚪ LOW · feedback** — No clear confirmation of successful 2FA after mock backend arrives
  - _Why:_ The TOTP flow ends with 'MOCK: not wired' and the page stays on the verification screen. Users won't know what a successful 2FA would look like or where they'd be redirected.
  - _Fix:_ Add a comment or docstring above the handleVerify mock explaining the Phase 2 behavior: 'On success, user will be redirected to /app/dashboard.' For the Phase 1 mock, consider showing a success state for 1-2 seconds before showing the mock error, or show a separate 'This is where you'd be redirected to the dashboard' message.


### Signup  
`/signup` · tier: public

**Purpose.** Allow first-time users (or the single admin) to create an account with a username and password. Serve as the on-ramp to the Odysseus workspace for new account holders.

**Personas reviewed.**
- _Single-user Admin (Francisco)_ — Post-deployment, creates their own admin account. Fast, knows the system, expects a clear path to either success or a specific error. Wants feedback immediately.
- _First-time Setup Outsourcer_ — Following deployment docs, creates an account and hands off to admin. May not be technical; unsure if signup was successful or if the next step is login. Needs reassurance.
- _Accidental Signup Visitor_ — Landed on /signup by mistake (bad link in docs, old bookmark, redirect). Realizes it's not intended and wants to get back to login without having to fill out the form.

**Works well.** Client-side validation with instant inline feedback—errors clear on input, password mismatch state shows immediately on the confirm field; Clear, monospace labeling and example placeholders consistent with terminal-HUD design system; Autocomplete and password manager hints present (username, new-password autocomplete; hint text for length)

**Gaps (9).**

- **🔴 HIGH · error-recovery** — Success state is unreachable (Phase 1 mock-only)
  - _Why:_ Submission always shows 'MOCK: Registration not wired yet' error after a 600ms delay. User cannot succeed. They don't know if they filled the form wrong, if the feature is broken, or if the account was created anyway. Blocks the core task of creating an account.
  - _Fix:_ For Phase 1 honesty, either (a) show a mock success state: dismiss the error and navigate to /login with a flash message 'Account created—sign in with your credentials', or (b) remove the form submission and show a LoadingText at the top: 'Account creation coming in Phase 2' to set expectations upfront.
- **🔴 HIGH · interaction** — No form wrapper or keyboard submit (Enter key doesn't work)
  - _Why:_ Form inputs don't respond to Enter key; button requires click. Keyboard-first users are blocked. Also violates semantic HTML—screen readers won't identify this as a form submission context. Accessibility non-compliance.
  - _Fix:_ Wrap inputs and button in `<form onSubmit={handleCreate}>` with `preventDefault()`. Add `type="submit"` to the Button. Users can now Enter to submit; assistive tech understands the form semantics.
- **🟠 MED · feedback** — Disabled button feedback is unclear
  - _Why:_ When password fields don't match, the button becomes disabled (text stays 'CREATE ACCOUNT'). The user may not realize their click won't work. Visual contrast/opacity of disabled state may be subtle, especially under cognitive load.
  - _Fix:_ Add a status message above the button that mirrors the confirm field's mismatch hint: if `passwordMismatch()` is true, show a StatusFlag or Text with `tone="warn"` that says 'Passwords do not match.' This echoes the pattern in LoginScreen (info flag before TOTP code). Alternatively, increase button opacity change on disabled state.
- **🟠 MED · missing-state** — No success or next-steps guidance after signup
  - _Why:_ User submits, sees a mock error, and has no idea what happens next. Should the account have been created? Can they sign in? Do they need to wait for an email confirmation? Outsourcer persona especially needs this—they don't know if the handoff is complete.
  - _Fix:_ In Phase 1, mock a success state: after `handleCreate` succeeds (change error message to a success message), show a Drawer or inline Text block: 'Account created successfully. [SIGN IN →](/login)' with a link. Or use a Modal confirming 'Your account is ready. You can now sign in.' This applies the existing ForbiddenView / EmptyState pattern: provide clear feedback on every outcome.
- **🟠 MED · information** — Rate-limit and admin-disable disclosure is vague
  - _Why:_ The hint says 'Account creation is rate-limited. Admins may disable self-registration.' No details: how often? Per IP, per day, per account? What's the error if triggered? When would an admin disable it? User is unsure if this applies to them or if they need to take action.
  - _Fix:_ Expand the hint with concrete details: 'Account creation is limited to [X] new accounts per day. If you exceed this limit or self-registration is disabled, you'll see an error. Admins manage this setting in Settings > Security.'
- **⚪ LOW · information** — Username format and constraints not documented
  - _Why:_ Placeholder 'operator' hints at a style but no stated rules. User doesn't know: Is it alphanumeric only? Min/max length? Must it be unique? They guess, submit, and get a validation error (or later find a duplicate exists). Friction on initial attempt.
  - _Fix:_ Add a hint under the USERNAME input: 'Must be 3–32 characters, alphanumeric and underscores only. Unique per instance.' (adjust rules to match backend.)
- **⚪ LOW · information** — Password strength requirements are minimal
  - _Why:_ Form only requires 8 chars—no entropy, complexity, or common-pattern check. User may pick a weak password like 'password1' (common, repetitive, guessable). For a single-user admin workspace, weak passwords raise security risk.
  - _Fix:_ Upgrade the PASSWORD hint to specify requirements: 'At least 8 characters. Include uppercase, lowercase, and a number.' Or add a simple visual strength meter (e.g., a small bar showing weak/fair/strong). If the backend enforces stricter rules, validate client-side and show inline errors.
- **⚪ LOW · navigation** — Back/cancel flow is buried
  - _Why:_ The '← SIGN IN' link is at the bottom after the divider. Accidental signup visitor has to scroll or search the page to escape. First-time user may not see it as a navigation option.
  - _Fix:_ Add a 'BACK' button above the form (before the first input), or move the SIGN IN link to the top. Label clearly: '← BACK TO SIGN IN' or '← BACK TO LOGIN'. Tertiary persona (accidental visitor) will appreciate the obvious exit.
- **⚪ LOW · information** — Confirm password hint is conditional and unclear
  - _Why:_ When fields are empty or match, no hint is shown. Only when they don't match does the hint appear. First-time user may not realize confirm-password is required or what triggers the mismatch error. Unclear affordance.
  - _Fix:_ Always show the hint (even when empty/matching): 'Confirm the password above.' This sets expectations upfront and reduces surprise when mismatch is detected.


### Chat  
`/chat` · tier: open

**Purpose.** The main conversational interface where users send messages to an AI agent, receive reasoning and tool-driven answers, and manage multi-turn sessions. It is the core surface of Odysseus.

**Personas reviewed.**
- _Power-user researcher (long sessions, tool-heavy workflows)_ — Running a 2+ hour research session with multiple refinements, switching between past chats for context, copying tool outputs into notes, tracking which model ran each response.
- _First-timer / incidental visitor_ — Landing on /chat for the first time (or by mistake), seeing a blank screen, unsure what to send, who they're talking to, or what model is active. On mobile, the session list is hidden.
- _Error-recovery user (tool failure, stuck state, misclick)_ — A tool call fails (error status), a message is sent by accident, or the page reloads mid-stream. Needs to retry, undo, or clear without losing the whole session history.

**Works well.** Clear message separation by role (user / assistant) with visual distinction (surface background, right-align, labels). Reasoning and tools are properly subordinate (collapsed, dimmer).; Streaming UX is well-designed: reasoning appears first, tool invocations show running→ok with elapsed time, then answer tokens reveal incrementally with a caret. Every state is visible and responsive.; Responsive layout uses flex + Suspense correctly; sidebar hides on mobile, composer pins to bottom, message area scrolls. No spinners; loading is LoadingText and empty is EmptyState.

**Gaps (9).**

- **🔴 HIGH · navigation** — Mobile: no way to navigate to or between sessions
  - _Why:_ The session list sidebar is hidden (`lg:block`) on mobile. Once a user is in a chat, they cannot switch sessions or see the session list. They're locked into the current session with no back path.
  - _Fix:_ Add a collapsible drawer or a session picker at the top of the conversation (in the header, next to the model name) that opens a modal/drawer showing recent sessions. Use the Drawer component (already available) and wire the session list behind Suspense with LoadingText fallback.
- **🟠 MED · onboarding** — No onboarding / first-time guidance on empty session
  - _Why:_ A new user landing on /chat with no messages sees 'NO MESSAGES / Send a message to start the session.' They don't know what to send, who they're talking to, what model is active, or what commands/tools are available. No system prompt or examples.
  - _Fix:_ Enhance the EmptyState to include a system prompt or example query (e.g., 'Type a question or command. You're chatting with [MODEL_NAME]. Try: "What time is it?" or "Search for..."'). Or add a collapsible help section in the header. This is mock-only friction in Phase 1; in Phase 2, real system instructions should appear here.
- **🟠 MED · information** — No model / system context visibility before sending
  - _Why:_ The model is shown in the header (e.g., 'MODEL qwen2.5-coder-32b') but users may not realize it's the active model until after they send a message. No way to change the model mid-session from the UI. If the owner changes the model in settings, users have no signal that subsequent replies are from a different model.
  - _Fix:_ Add a clickable model selector in the composer area (left of the Send button) showing the active model. In Phase 2, this can open a quick-pick of available models or link to settings. For now, make it clear the model is selectable even if clicking does nothing.
- **🟠 MED · error-recovery** — Tool errors and result previews are incomplete
  - _Why:_ If a tool fails (status='error'), the ToolCallCard shows 'ERROR' but provides no error message or reason. The result field is optional; on error, it's likely empty or unpopulated. Users can't diagnose why a tool failed or decide whether to retry.
  - _Fix:_ Extend the ToolInvocation model to include an optional `error?: string` field. Render it in ToolCallCard when status='error', showing the error in the expanded result area. Use StatusFlag status='alert' + a ForbiddenView-like pattern (a red ERROR label + error text) for clarity.
- **🟠 MED · interaction** — No undo, retry, or clear-session actions
  - _Why:_ If a user sends a message by mistake, wants to retry a failed tool, or wants to start fresh, there's no UI affordance. They must reload the page (losing the entire live session) or wait. Undo/retry/clear are frequent workflows in chat UIs.
  - _Fix:_ Add a context menu or header button bar (3-dot menu or action buttons) with: 'Delete last message', 'Retry last tool', 'Clear session'. Use a ConfirmDialog (or a confirm-on-click Button variant) for destructive actions. These are mock-safe in Phase 1 (no server persistence yet) and clarify the feature model.
- **⚪ LOW · navigation** — Sessions list has no search, sort, or grouping
  - _Why:_ For users with dozens of sessions (common in long-lived AI workspaces), the linear list is hard to scan. No search, no sort-by-date/name toggle, no grouping by day/week. The sidebar shows only what fits; no pagination or scroll indicator.
  - _Fix:_ Add a search field at the top of the SESSIONS panel (Input component with an icon='search'). Filter the list by title substring as the user types. Optionally add a 'Sort by: recency / name' toggle. In Phase 1, these can be UI-only (filtering local mocks); Phase 2 wires them to the backend.
- **⚪ LOW · information** — No visual distinction for current message model vs. session model mismatch
  - _Why:_ The session header shows 'MODEL qwen2.5-coder-32b', but if the owner switches the active model mid-session, subsequent assistant messages show a different model in their label (see AssistantTurn: `m().model ?? "ASSISTANT"`). There's no warning or highlight that the session now has mixed-model responses.
  - _Fix:_ If `message.model !== session.model`, add a subtle visual cue (e.g., a warn-tone icon or border highlight on the message label). Or add a banner above the conversation: 'Mixed models in this session' with a count or link to see which. This is rare but confusing when it happens.
- **⚪ LOW · efficiency** — Reasoning and tool calls are not copyable
  - _Why:_ Power users often need to copy reasoning or tool results into notes, docs, or follow-up queries. The content is read-only (plain text in a div). No copy button or selection-friendly formatting.
  - _Fix:_ Add a small 'copy' icon/button next to the ReasoningBlock title and inside each expanded ToolCallCard result. Use a Button variant='ghost' size='small' or an Icon with onClick. When clicked, copy the text to clipboard and show a transient toast or StatusFlag feedback ('COPIED'). This is a polish feature; low priority for Phase 1.
- **⚪ LOW · consistency** — Streaming state can make the UI temporarily confusing
  - _Why:_ While streaming is in progress, the 'STREAMING' status appears in the header, the composer is disabled, and the Send button grays out. But the reasoning block and tool cards are still interactive (can be toggled open/closed) while content is being added. This is correct, but users may expect everything to be frozen.
  - _Fix:_ This is actually fine as-is (the design system says motion is instant, and the caret gives feedback). No change needed, but document this in a comment: 'Tool/reasoning blocks remain interactive during streaming to allow exploration while the answer is still being revealed.'


### Research Library  
`/research` · tier: open

**Purpose.** Central hub for multi-round AI research synthesis. Lets users initiate new deep research queries and browse a library of past reports with their source counts, completion status, and timestamps.

**Personas reviewed.**
- _Kai (technical researcher, task-focused)_ — Arrives at /research wanting to quickly check if any research is running, scan the last few reports, and potentially rerun a similar query from the past week.
- _Morgan (new/hurried user, uncertain about the feature)_ — Lands on /research from a navigation click, reads the subtitle, starts typing a research query, then realizes they don't know how specific it should be or what constitutes a 'good' query.
- _Ravi (recovering-from-error user)_ — Accidentally clicks 'Delete' on a report via the row menu, wants immediate feedback: is this permanent? Is there a confirm dialog? Can the action be undone?

**Works well.** Clear two-tab separation of concerns (RUN vs. LIBRARY) reduces cognitive load for users switching between starting new research and reviewing past reports.; Live progress tracking (PhaseTrack, ProgressBar, InstrumentBand) provides real-time visibility into long-running synthesis, building confidence the engine is working.; Report list displays essential metadata (title, source count, timestamp, status flag) in a compact, scannable format using the terminal-HUD aesthetic consistently.

**Gaps (9).**

- **🔴 HIGH · trust-safety** — Delete menu action has no confirmation guard
  - _Why:_ Ravi (recovering-from-error user) clicks Delete and gets no confirmation dialog. Research reports represent hours of synthesis and source gathering; deleting one is destructive and irreversible. Without a guard, accidental clicks result in lost work with no undo.
  - _Fix:_ Replace the empty `onSelect: () => {}` handler on the 'Delete' menu item with a call to a Modal or confirmation dialog. The dialog should state what's being deleted (the report title), confirm intent, and offer Cancel/Delete buttons. Use a danger tone on the Delete button. See existing Modal/confirm patterns in the codebase for the implementation.
- **🔴 HIGH · interaction** — Menu action handlers are stubbed (onSelect: () => {})
  - _Why:_ None of the menu actions (View Report, Archive, Delete) do anything. Kai clicks 'Archive' expecting a state change; Ravi clicks 'Delete' expecting a dialog. The page shows no feedback — no toast, no reload, no error. The feature is unusable until Phase 2 wires the backend, but users get no signal that the action failed.
  - _Fix:_ Add temporary Phase 1 handlers that log to console or show a Toast ('Action pending backend integration'). Better: move the 'View Report' action outside the menu — make the entire ListRow clickable (it already has `href`), and keep only Archive/Delete in the menu. Or, for Menu items that aren't yet functional, add a `disabled: true` prop (check ListRow/Menu component definitions) and show a reason in a tooltip.
- **🟠 MED · onboarding** — Query input has no examples or best-practice guidance
  - _Why:_ Morgan (new users, hurried users) doesn't know what makes a 'good' research query. The placeholder text 'What do you want to research? Be specific…' is too vague. Without examples, she might run overly broad queries (wasting synthesis rounds) or too narrow/poorly-framed ones that yield low-quality reports.
  - _Fix:_ Add a `hint` or tooltip to the Textarea with 1–2 concrete examples of well-formed queries (e.g., 'Best practices for Pydantic AI agent loops with local models' or 'Comparative performance: ChromaDB vs Qdrant for vector retrieval'). Alternatively, link from the placeholder text to a separate guidance page or collapse the examples inline below the textarea.
- **🟠 MED · efficiency** — No search/filter for report library when list grows large
  - _Why:_ Kai has run 50+ research reports by month 6. The library now shows all reports in a single scrolling list. Finding 'that research about ChromaDB performance from three weeks ago' requires manual scanning or browser find (Cmd+F), which is tedious and error-prone.
  - _Fix:_ Add a search input above the LIBRARY tab's report list that filters by title/query text (client-side, no backend call needed in Phase 1). Example: `<Input placeholder='Search reports…' onChange={…} />` above the Panel. Alternatively, add sorting controls (newest/oldest, by source count, by status) if the mocked list is large enough to showcase the problem.
- **🟠 MED · consistency** — RunPanel's 'VIEW REPORT' button is hardcoded to r-007
  - _Why:_ After running a research query, the completion screen shows a 'VIEW REPORT' button that always navigates to `/research/r-007` (a mock ID), regardless of what query was run. On Phase 2 wiring, this will point to a stale mock report, confusing users. The button should navigate to the newly-created report's ID.
  - _Fix:_ Pass the created report's ID from the `run()` callback result to RunPanel. Update RunPanel to store the result ID and use it in the href: `href={`/research/${reportId()}`}`. This requires modifying createResearchRun to return the report ID and RunPanel to accept it as a prop (or via a store). Alternatively, mock the ID in Phase 1 by incrementing a counter or using the query hash.
- **🟠 MED · error-recovery** — No explicit error state for failed research runs
  - _Why:_ The model defines ResearchStatus = 'running' | 'complete' | 'archived' | 'error', but RunPanel has no explicit UI for when a run fails mid-synthesis. The progress panel only shows loading/done states. If the research hits an error (network, timeout, bad query), the user sees no error message or recovery path.
  - _Fix:_ Add a Show block in RunPanel to render when props.state.phase has an error flag (or when running() becomes false with a failed status). Display a message like 'SYNTHESIS FAILED: {error message}' with a Retry button that reruns the same query. Alternatively, use an alert-tone StatusFlag to surface the failure in the header.
- **⚪ LOW · information** — LIBRARY tab shows report count but not total sources or key stats
  - _Why:_ Kai wants a quick sense of research productivity. The Panel meta shows '7 REPORTS', but he doesn't see total sources gathered or any aggregate stats. This is a small awareness gap for power users.
  - _Fix:_ Extend the Panel meta to show: '{N} REPORTS · {M} SOURCES · {P} AVG SOURCES/REPORT' using token-backed utilities. Example: `<Text variant='micro' tone='dim'>{summaries()?.length ?? 0} REPORTS · {totalSources} SRC</Text>`. This requires a small derived calculation; add it to the screen.
- **⚪ LOW · information** — No indication of what report status values mean (archived vs. error vs. complete)
  - _Why:_ Morgan sees a report with status='archived' or status='error' and doesn't know what it implies. Is archived = manually archived by the user, or auto-archived after N days? Does error = the research failed, or a transient glitch?
  - _Fix:_ Add a Tooltip to the StatusFlag in each ListRow. Tooltip content: 'complete = synthesis finished successfully', 'running = currently in progress', 'archived = manually archived by you', 'error = synthesis encountered a failure (review report for details)'. Alternatively, add a legend/key in a collapsed section above the list.
- **⚪ LOW · feedback** — Progress bar and phase tracking stop updating after 'DONE' phase
  - _Why:_ After a research completes and the user navigates away and back to the RUN tab, the progress bar and phase display freeze at 'DONE' / 100%. The user doesn't see a clear 'ready for next run' signal. Subsequent runs should reset these visuals.
  - _Fix:_ When a new research run starts (in createResearchRun's run() function), explicitly reset the phase/progress/sources counters. This is already partially done ('s.phase = PLANNING; s.round = 1…'), but verify the phase track and progress bar reset visually. If they don't, add a Suspense/Show boundary that clears the progress panel between runs.


### Research Report  
`/research/:id` · tier: open

**Purpose.** Display a completed deep-research synthesis report with sections, cited sources, relevance scores, and metadata. Users read findings and can start a follow-up conversation with the report loaded as context.

**Personas reviewed.**
- _Researcher (power user)_ — Uses reports to drive technical decisions; wants to drill into sources, compare findings across reports, and send results to collaborators or feed back to chat for follow-up.
- _Hurried Validator_ — Landed on a report link from chat or email; needs to verify if this report answers their original question in <30 seconds; doesn't need to read every section, just scan headers and confirm relevance.
- _Error-Recovery User_ — Clicked a report link that was archived, deleted, or never finished (error state). Expects clear guidance on what happened and a path forward.

**Works well.** Proper loading and not-found states (Suspense + Show + EmptyState) prevent blank screens.; Sources are listed with domain, relevance score (color-coded by tone), and direct links—supports quick validation of source quality.; InstrumentBand metadata (rounds, sources, findings, duration, created timestamp) gives context without cluttering the report body.

**Gaps (9).**

- **🔴 HIGH · missing-state** — No error state for failed/partial reports
  - _Why:_ The model includes a 'error' ResearchStatus type, but ResearchReportScreen only shows loading and 'not found'. A report that errored mid-synthesis (failed source fetch, LLM timeout, etc.) will render as if complete, confusing users about report quality. The Hurried Validator or Error-Recovery User won't know the report is incomplete or unreliable.
  - _Fix:_ Add a Show when={r().status === 'error'} fallback before the content that renders a StatusFlag with status='alert' + explanation text + a 'RETRY' or 'BACK TO LIBRARY' button. Alternatively, show a warning banner at the top if status is not 'complete' (e.g., 'PARTIAL SYNTHESIS — some sources failed to retrieve').
- **🟠 MED · navigation** — No way to navigate back to library from report
  - _Why:_ The page has no back button or breadcrumb. Users who arrive via deep link (email, chat history, bookmark) cannot get back to the library without using browser back or typing /research. The Hurried Validator or Error-Recovery User has a dead-end flow.
  - _Fix:_ Add a back button in PageHeader actions or a breadcrumb 'DEEP RESEARCH > [Report Title]' that links back to /research. Or add a 'BACK TO LIBRARY' button in the footer panel.
- **🟠 MED · efficiency** — No way to copy/share the report or access its URL
  - _Why:_ The Researcher wants to send this report to others or cite it in chat/docs. The page has no copy-URL button, share action, or export option. Currently impossible to share without manually copying the URL.
  - _Fix:_ Add a 'SHARE' or 'COPY LINK' button in PageHeader actions. Alternatively, add a Menu with options like 'Copy Report Link' and 'Open in New Tab'.
- **🟠 MED · interaction** — Sources are not filterable or sortable by relevance
  - _Why:_ The Hurried Validator wants to skim only high-confidence sources (≥90% relevance) but must scan all 31 sources. The Researcher wants to sort by relevance descending to prioritize reading. The sources list is a flat For loop with no filter/sort UI.
  - _Fix:_ Add a 'RELEVANCE' toggle or select in the CITED SOURCES panel meta (alongside the source count) to filter by threshold: 'ALL' / '90%+' / '80%+'. Or add a small sort icon that cycles through sort modes (relevance desc / asc / title / domain). Use a thin text label, not a dedicated control.
- **🟠 MED · missing-state** — Report status is hardcoded to 'COMPLETE' regardless of actual status
  - _Why:_ The PageHeader shows a hardcoded StatusFlag status='nominal' > 'COMPLETE' even if the report.status is 'archived', 'running', or 'error'. Users cannot see the true state of the report at a glance.
  - _Fix:_ Map report.status to a StatusFlag: 'complete' → 'nominal' / 'COMPLETE'; 'archived' → 'idle' / 'ARCHIVED'; 'error' → 'alert' / 'ERROR'; 'running' → 'info' / 'RUNNING'. Use the statusMap pattern from ResearchLibraryScreen.
- **⚪ LOW · efficiency** — No way to archive or delete a report from the report page
  - _Why:_ The library screen has a Menu with Archive and Delete actions, but the report detail page has no such menu. Users must go back to the library to manage a report, adding friction.
  - _Fix:_ Add a Menu button in PageHeader actions (next to FOLLOW-UP) with options like 'Archive', 'Delete', and 'View in Library'. Or add a Panel at the bottom with a 'MANAGE' row.
- **⚪ LOW · feedback** — No indication if report is archived (visual or in content)
  - _Why:_ An archived report renders identically to a complete one. Users may not realize they are viewing old/inactive research and might make decisions based on stale data.
  - _Fix:_ If report.status === 'archived', add a subtle badge or banner below the PageHeader: 'ARCHIVED — This report is no longer active.' Use tone='dim' for subtle vs tone='warn' if you want emphasis.
- **⚪ LOW · navigation** — No section numbering or table of contents for long reports
  - _Why:_ A report with 6+ sections (like the mock with 7 sections) requires scrolling to find a specific section. The Hurried Validator has no quick way to jump to a section or see the structure at a glance.
  - _Fix:_ Add a simple 'CONTENTS' panel or list at the top (before SYNTHESIS) showing section headings as links, or number each section (e.g., '1. EXECUTIVE SUMMARY'). For Phase 2, add an 'anchor' to each section heading so users can deep-link to a section.
- **⚪ LOW · interaction** — Source relevance score is visual only; no quantitative filter
  - _Why:_ Relevance is shown as a color-coded percentage (tone: nominal/default/dim based on score threshold), but there is no way to filter to only high-relevance sources. A user interested in only sources ≥85% relevance must manually scan.
  - _Fix:_ Add a Checkbox or Toggle in the CITED SOURCES meta: 'HIGH RELEVANCE ONLY' (≥90%). Or add a Select with options: 'All Sources', 'High (≥90%)', 'Medium (70-89%)', 'Low (<70%)'.


### Compare  
`/compare` · tier: open

**Purpose.** Enable blind side-by-side model evaluation: enter a prompt, watch two models respond anonymously, vote for the better answer, then see the vote recorded on a leaderboard and model identities revealed.

**Personas reviewed.**
- _Maria (Enthusiast / Frequent Comparer)_ — Running 15-20 comparisons per session to benchmark models on coding tasks. After each vote, she wants to run another comparison immediately. She needs quick feedback that votes counted and wants to track her voting history and patterns over time.
- _Dev (New to Compare / Accidentally Found It)_ — First visit to Compare, unfamiliar with the blind-vote mechanic. Enters a prompt, models respond, but is confused why model names are hidden. After voting, unsure if the vote was recorded or what the next step is. Wants reassurance the action worked.
- _Admin (System Health Monitor)_ — Wants to verify the feature is working, check if the leaderboard data is sensible, see how many total comparisons have been run, and identify any errors or data quality issues. Needs metadata and audit info, not just the leaderboard.

**Gaps (9).**

- **🔴 HIGH · feedback** — No visual confirmation that vote was recorded
  - _Why:_ After voting, the screen transitions to show the winner, but there's no toast, banner, or explicit success message. A user (especially Dev on first visit) cannot tell if the vote was persisted or if it's just a UI state refresh. Destructive actions and state changes must have unmistakable feedback.
  - _Fix:_ Add a brief success toast or confirmation banner immediately after vote is recorded (e.g., 'VOTE RECORDED' in a StatusFlag with tone='nominal' for 1-2s), or add a green checkmark in the WINNER instrument band before prompting for the next comparison.
- **🔴 HIGH · error-recovery** — No error handling for failed comparisons
  - _Why:_ If a model inference fails or times out during streaming (Phase 2), the UI has no way to show the error or offer a retry. The user will see a stuck 'STREAMING' state or an incomplete response and not know what happened. This is a critical gap for production.
  - _Fix:_ Add an error state to CompareCandidate (e.g., `error?: string`). If streaming fails, show a LoadingText with tone='alert' and a 'RETRY' button, or a brief error message in the candidate Panel. Use Tooltip or inline text to explain what went wrong (e.g., 'Model timed out—try again').
- **🟠 MED · onboarding** — No explanation of the blind-vote mechanic on first visit
  - _Why:_ The subtitle says 'Blind side-by-side evaluation' but doesn't explain *why* identities are hidden or what the user is supposed to learn from the comparison. A first-time user (Dev) may think it's a bug or not understand the purpose, reducing confidence in the feature.
  - _Fix:_ Add a Tooltip or inline hint on the 'MODEL A / MODEL B' labels explaining: 'Model names are hidden until you vote to prevent bias. Vote for the response you think is better, then identities will be revealed.' This educates without cluttering the UI.
- **🟠 MED · information** — No history or previous-comparisons view
  - _Why:_ Maria (frequent comparer) has no way to review past comparisons, her voting patterns, or which prompts she's already tested. She can't see a list of previous runs, their timestamps, or her vote. This friction compounds over dozens of comparisons—she might re-compare the same thing.
  - _Fix:_ Add a 'HISTORY' panel below or adjacent to the leaderboard showing the last 5-10 comparisons (prompt snippet, timestamp, winner, date). Tap a row to expand and see the full response text. This surfaces recent activity without requiring a separate page.
- **🟠 MED · information** — Leaderboard has no metadata about the data
  - _Why:_ Admin and power users cannot see when the leaderboard was last updated, how many total comparisons have been run, or how many votes each model has received (only W/L visible). They can't assess data quality or freshness, and the leaderboard feels static/opaque.
  - _Fix:_ Add an InstrumentBand above the leaderboard showing: 'TOTAL COMPARISONS: 17 | LAST UPDATED: 2h ago' (or similar). If a model has no votes yet, show that in the EmptyState hint ('Run a comparison and vote to populate the leaderboard').
- **🟠 MED · interaction** — No way to cancel or stop a streaming comparison
  - _Why:_ If the user realizes their prompt was malformed or wants to stop the comparison mid-stream, there's no STOP or CANCEL button. They must wait for both responses to finish. This is friction for impatient or mistake-recovery scenarios.
  - _Fix:_ While active() is true, show a 'STOP' button next to the COMPARE button in the Panel meta area, or a cancel icon in the Prompt panel. Clicking it clears active state and resets the run without clearing the prompt, allowing the user to edit and re-submit.
- **⚪ LOW · interaction** — Vote buttons have confusing disabled state styling
  - _Why:_ The VOTE buttons are disabled before both models finish streaming AND disabled after voting. The disabled state looks the same in both cases, so a user might not realize they need to wait for both responses to complete, or might think they've already voted when actually they're still waiting.
  - _Fix:_ Add a Tooltip to each VOTE button that displays different text based on context: 'Waiting for both responses…' (disabled while streaming), 'Vote to reveal' (enabled when bothDone), or 'You voted for this model' (after vote is revealed). This removes ambiguity.
- **⚪ LOW · interaction** — Prompt is locked during voting decision, creating confusion
  - _Why:_ After both models respond, the prompt textarea is disabled (disabled={!run.revealed}) until the user votes and reveals. This prevents the user from reading or editing their prompt while deciding, and the UI doesn't explain *why* it's locked. A user might think it's a bug.
  - _Fix:_ Remove the disable lock on the prompt textarea during the 'awaiting vote' phase. The textarea should only be disabled while active() is true (streaming). Allow read-only access to the prompt during voting. Alternatively, add a hint explaining 'Edit and re-run a comparison, or vote to reveal.'—but allowing read access is cleaner.
- **⚪ LOW · efficiency** — No keyboard shortcuts for voting
  - _Why:_ Maria votes 15-20 times per session. She has Ctrl+Enter for COMPARE, but no shortcut for voting (e.g., 'A' for Model A, 'B' for Model B, or arrow keys). Every vote requires a mouse click, which compounds friction.
  - _Fix:_ Listen for 'a', 'A', 'b', or 'B' key presses and call handleVote() with the matching slot when bothDone() is true and !run.revealed. Add a hint on the VOTE buttons ('Press A or B') to surface the shortcut.


### Documents Library  
`/documents` · tier: user

**Purpose.** A personal knowledge base and notes surface where users can create, organize, search, and archive documents. Serves as a central repository for working notes, technical docs, and reference material.

**Personas reviewed.**
- _Hurried/Distracted User_ — Quickly searches for documents, accidentally archives the wrong one, and realizes immediately but has no quick undo—must navigate to the Archived tab, find the doc, and manually restore it.
- _First-Timer / Accidental Visitor_ — Lands on /documents without context; sees tabs and search but no clear explanation of what kind of content belongs here (is it code snippets, research notes, wiki entries?) or why they should use it vs. external tools.
- _Power User / Bulk Operator_ — Needs to clean up 5-10 archived documents at once or mass-restore from archive. Must click the menu and delete/restore each individually—no bulk selection, no batch operations.

**Works well.** Strong foundation: LoadingText, EmptyState, and Suspense are all correctly wired to handle async states—loading and empty are not forgotten.; Clean interaction model: Tab switching (ACTIVE/ARCHIVED) and search work together; filtering logic is sound and shows the right empty state for each tab.; Consistent information hierarchy: InstrumentBand shows total/active/archived counts at a glance; ListRow displays title, word count, updated time, and status flag—all the essential metadata is present and well-ordered.

**Gaps (8).**

- **🔴 HIGH · trust-safety** — DELETE action has no confirmation dialog
  - _Why:_ Deletion is permanent and irreversible. A distracted user or accidental click will permanently lose work with no recovery path. This is a high-consequence failure mode that the design system (Modal component) can prevent.
  - _Fix:_ Add a Modal that triggers on DELETE menu selection. Show the document title, a warning message ('This action cannot be undone.'), and two buttons: 'DELETE' (alert tone) and 'CANCEL'. Only confirm deletion if the user explicitly clicks DELETE in the modal.
- **🟠 MED · feedback** — No feedback on archive/restore success
  - _Why:_ When a user archives or restores a document, there is no visible confirmation—no toast, no status change, no indication the action succeeded. On slow networks, the user will be uncertain whether the action took effect and may click again (double-submit), or think the UI is broken.
  - _Fix:_ After archive/restore completes, show brief inline feedback. Either: (a) flash the StatusFlag on the affected row to 'ARCHIVED'/'ACTIVE' briefly, or (b) show a transient toast notification ('Document archived. Undo?' with a link back to ACTIVE tab) to confirm the action succeeded.
- **🟠 MED · information** — Empty state message is ambiguous when search returns zero results
  - _Why:_ If the user types 'xyz' and no documents match, they see 'NO ACTIVE DOCUMENTS'—the same message they'd see if the tab truly has no documents. They won't realize it's a search filter issue and may think 'I should create a document' when they just need to refine their search.
  - _Fix:_ When the query is non-empty and filtered results are empty, show a contextual EmptyState message: 'NO DOCUMENTS MATCHING "<query>"' (e.g., 'NO DOCUMENTS MATCHING "xyz"'). Compute the message dynamically from the query() signal.
- **🟠 MED · efficiency** — No bulk/multi-select actions for batch operations
  - _Why:_ Users with 10+ archived documents cannot delete or restore them in bulk. Each action requires one menu open + one click, multiplied by the number of documents. This is repetitive friction for a common cleanup task.
  - _Fix:_ Add a checkbox to the left of each ListRow (visible only when there are documents). When any boxes are checked, show a sticky action bar at the bottom ('X documents selected' + 'DELETE SELECTED' button). Support shift-click range-select and a 'select all' checkbox in the header row to speed batch operations.
- **🟠 MED · navigation** — No sort/pagination for large libraries
  - _Why:_ With 50+ documents, the flat scrolling list becomes tedious to browse. Users rely only on search to narrow the list. No sort options (by date, title, word count) or pagination means finding 'the document I edited last month' requires scrolling through all documents or remembering part of the title.
  - _Fix:_ Add a 'SORT BY' dropdown next to the search input with options: 'RECENTLY UPDATED' (default), 'TITLE (A–Z)', 'TITLE (Z–A)', 'WORD COUNT'. Implement pagination or virtualization if the list exceeds ~50 items to keep the DOM lightweight.
- **⚪ LOW · consistency** — OPEN menu item is redundant and creates interaction confusion
  - _Why:_ The OPEN menu item does exactly what clicking the ListRow already does (navigate to the document). Users may not realize they're the same action and could spend cognitive load deciding which path to take. It also adds visual clutter to the menu.
  - _Fix:_ Remove the OPEN menu item from the menu. Make the entire ListRow clickable (or at least the title/label area) to navigate to the document. Keep only ARCHIVE and RESTORE in the menu, since those are secondary/contextual actions not available via row click.
- **⚪ LOW · feedback** — No visual indication that menu actions are not wired in Phase 1
  - _Why:_ All menu item onSelect handlers are empty stubs (`onSelect: () => {}`). Clicking them produces no feedback—no loading state, no toast, no disabled appearance. A user may assume the UI is broken or wonder why nothing happened.
  - _Fix:_ Until Phase 2 wiring is complete, either: (a) disable the menu items and add a Tooltip explaining 'Coming soon', or (b) add a temporary one-line toast when clicked ('Not yet implemented') to surface that this is a Phase 1 stub, not a bug. This prevents user confusion and sets the right expectation.
- **⚪ LOW · onboarding** — No context/guidance for first-time users about document purpose
  - _Why:_ The subtitle 'Personal knowledge base and working notes' is vague. A new user doesn't know whether documents are for code snippets, research notes, wiki-style reference material, or something else. They may not understand why this feature exists vs. external tools, leading to underuse.
  - _Fix:_ Add a brief hint or guidance section when the library is empty. Show an EmptyState with a message like 'NO ACTIVE DOCUMENTS' + hint 'Create a document to store working notes, research, or technical reference material. Use search and archive to keep your library organized.' This sets expectations and encourages creation.


### Document Editor  
`/documents/:id` · tier: user

**Purpose.** Edit a single document with AI-assisted writing suggestions, view edit history, and manage document metadata (title, status, word count). The editor is the primary interface for creating and refining personal working notes and knowledge base entries.

**Personas reviewed.**
- _Distracted Technical Owner_ — Opens a technical document mid-research, makes edits over 10 minutes, sees an interesting AI suggestion and dismisses it, then closes the tab. Returns 2 hours later unsure if changes were saved or lost.
- _Recovering-from-Mistake User_ — Accidentally deletes a critical 2-paragraph section from a 3000-word architecture document. Sees the version history panel but cannot click, diff, or restore from any version. Needs to manually reconstruct lost content.
- _Efficiency-Focused Operator_ — Using REWRITE and SUMMARIZE frequently; receives a 50-word suggestion to insert into the middle of a 10-section document. APPLY just appends to the end; user must manually cut, navigate, and paste in the right location.

**Works well.** Clean split layout (editor + sidebar) works well for dual focus; AI assist panel is visually distinct and won't distract during focused writing; Version history is visible and timestamped; StatusFlag correctly distinguishes active/archived status at a glance; AI assist buttons are clear and responsive; streaming UI with the pulsing caret gives instant feedback that work is happening

**Gaps (8).**

- **🔴 HIGH · feedback** — No save confirmation or dirty-state feedback
  - _Why:_ The SAVE button has no onClick handler (Phase 1 stub), so users cannot tell if their edits persisted. Combined with no visual indicator (e.g., asterisk on title, unsaved dot, disabled-until-dirty state), users risk losing work without realizing it. On every close/navigate, they wonder: 'Did that save?'
  - _Fix:_ Add visual feedback: (1) Track whether body differs from detail.body; show a small dot or asterisk next to the title when dirty. (2) On SAVE click (when backend is wired), briefly flash a StatusFlag (green 'SAVED') or change the button text to 'SAVED ✓' for 2 seconds. (3) Warn on navigate/close if unsaved (browser beforeunload). For now (Phase 1), at least add the dirty-state dot and disable the SAVE button if not dirty.
- **🔴 HIGH · interaction** — Version history is read-only; no way to restore or diff
  - _Why:_ The version list shows past snapshots with timestamps and labels, but ListRow items are not clickable and no modal/drawer offers to show diff or restore. A user who accidentally deletes content or wants to review what changed between versions has no path forward except manual reconstruction or guessing at content.
  - _Fix:_ Make each ListRow in the version history clickable. On click, open a Modal or Drawer showing: (1) a read-only view of that version's body text, (2) a diff highlight vs. current version (using the UI Markdown/code display), and (3) a RESTORE button (with a confirm dialog: 'Replace current version with this snapshot?'). Store/mock the full body for each version in the model.
- **🟠 MED · efficiency** — No way to insert AI suggestions at a specific location
  - _Why:_ APPLY appends suggestions to the end of the body. For longer documents with multiple sections, suggestions often belong in a specific paragraph or section, not at the end. Users must manually cut/paste the suggestion into the right place, defeating the speed advantage of AI assist.
  - _Fix:_ Add a second button next to APPLY: 'INSERT AT CURSOR' (or similar). This inserts the suggestion at the cursor position in the textarea instead of appending. For Phase 1 with mock data, just add the button; wire it to get/set textarea selectionStart in Phase 2. Alternatively, offer a simple modal that asks 'Where?' (Before/After/At end) with a one-sentence preview of context.
- **🟠 MED · error-recovery** — No unsaved-changes warning on navigation
  - _Why:_ If a user edits the document, then clicks the back button or a sidebar link, they leave the page with no confirmation. Silent loss of edits is high friction and erodes trust in the editor.
  - _Fix:_ Wire a beforeunload handler (or SolidJS router guard) that checks if body !== detail.body. If dirty and user tries to leave, show a confirm dialog: 'Unsaved changes will be lost. Leave anyway?' Only allow leaving if user confirms or if SAVE succeeds. (Phase 1: stub the handler to always allow leaving, but add the check logic.)
- **🟠 MED · content** — No clear action on archived documents
  - _Why:_ The status flag shows 'ARCHIVED', but there's no indication that the editor is read-only or that the user should restore it if they want to make edits. If a user lands on an archived document, they may type edits, click SAVE, and be confused when nothing happens (or a backend error occurs in Phase 2).
  - _Fix:_ If status is 'archived', render a banner at the top of the editor (or as an info StatusFlag) saying 'This document is archived. Restore it to make edits.' Add a 'RESTORE' button that toggles the status (wire to backend in Phase 2; for now, just mock toggling the status signal). Alternatively, disable the textarea with a tooltip: 'Archived documents are read-only. Restore to edit.'
- **⚪ LOW · information** — Version history does not show total count or indicate current version
  - _Why:_ The version list is a plain loop with no heading or indication of which version is the one currently being edited. For a document with many versions, it's unclear if you're viewing the latest snapshot or an old one, and there's no summary of 'You are on v15 of 30 versions.'
  - _Fix:_ Add a label above the version list: 'VERSION HISTORY (3 SNAPSHOTS)' or, if applicable, highlight or badge the latest version with 'CURRENT' or a checkmark icon. Add a section header using Text: 'VERSIONS: 3' at the top of the Panel.
- **⚪ LOW · navigation** — AI Assist panel collapses on mobile; no responsive fallback
  - _Why:_ The aside is `hidden w-72 shrink-0 flex-col gap-4 lg:flex`, so on tablet/mobile the entire AI assist panel (and version history) disappears. Users on smaller screens have zero access to AI tools or version history without a modal or drawer.
  - _Fix:_ Provide a fallback for mobile: either (1) move the AI Assist into a bottom drawer that slides up when the user taps an 'AI' icon in the toolbar, or (2) keep it in the sidebar but make the sidebar a slide-in panel on mobile. Version history could be a link 'View 3 versions' that opens a modal. This is lower priority if Odysseus is desktop-only.
- **⚪ LOW · efficiency** — No keyboard shortcuts for AI assist actions
  - _Why:_ Users cannot apply or dismiss AI suggestions via keyboard (no hotkey for APPLY/DISMISS/REWRITE/SUMMARIZE), and cannot select a specific passage to rewrite or summarize—the buttons always act on the entire document body.
  - _Fix:_ For Phase 2: (1) Add hotkeys (e.g., Ctrl+Return to APPLY, Esc to DISMISS). (2) Allow selecting text in the textarea and triggering 'Rewrite Selection' or 'Summarize Selection' so AI tools target just that passage. For Phase 1, this is nice-to-have polish.


### Memory  
`/memory` · tier: user

**Purpose.** Curate and browse persistent facts, preferences, and context the system has learned about the user and their environment. Provides type-based filtering, duplicate detection/merging, and pin/edit/delete actions for knowledge management.

**Personas reviewed.**
- _Active Knowledge Gardener_ — Technical owner regularly opens Memory to review what the AI knows (filtered by PROJECT), spots duplicates via DEDUP AUDIT, merges them, edits stale facts, and pins important preferences for long-term retention.
- _First-Timer / Accidental Visitor_ — Lands on Memory via nav exploration, reads the subtitle to understand purpose, wonders how memories are created (no visible pathway), clicks menu options expecting immediate feedback, gets confused when nothing changes.
- _Recovering from Error_ — Accidentally deletes a memory or merges the wrong dedup pair, realizes the mistake seconds later, but has no undo/recovery option. The action is permanent and the user has lost knowledge.

**Works well.** Type-based semantic color coding (user/feedback/project/reference) with clear visual distinction via StatusFlag; InstrumentBand summary metrics give instant overview of distribution; Dedup audit modal with side-by-side comparison, similarity %, and clear two-option choice (MERGE / KEEP BOTH); well-structured for the core decision; Proper use of pin/lock iconography and relative timestamps (e.g. '2 hours ago') to communicate recency and importance

**Gaps (10).**

- **🔴 HIGH · interaction** — Menu actions are visually stubbed with zero feedback
  - _Why:_ User clicks PIN/EDIT/DELETE and nothing happens; zero visual confirmation. They don't know if it worked, is loading, or if they're not permitted. Dangerous for DELETE (destructive action with no guard). Erodes trust in the button.
  - _Fix:_ For Phase 1, either disable menu items with dim appearance, or show a Toast confirming 'Memory pinned' / 'Memory deleted'. For DELETE, add a Modal confirmation: 'Delete memory? This cannot be undone.' + Button (danger variant) + cancel. Use Modal/Toast/Button primitives available.
- **🔴 HIGH · error-recovery** — No undo for destructive actions (delete, merge)
  - _Why:_ Deleting a memory or merging duplicates is permanent with no recovery. A mis-click on DELETE is irreversible; knowledge is lost forever. This is a trust/safety gap, especially for a knowledge base where accuracy matters.
  - _Fix:_ Add undo: implement a brief undo buffer (last 3–5 deletions/merges) and show 'Undo' in a Toast after destructive actions. At minimum, add confirmation Modal before DELETE/MERGE using Modal + Button (danger). Phase 2 can implement full trash/recovery, but don't ship without a guard.
- **🟠 MED · information** — Opaque feedback on how memories are created
  - _Why:_ Subtitle says 'system has learned' (passive/automatic), but ADD MEMORY button suggests manual creation. User is unsure: do they add manually, or does Odysseus auto-capture from chat? This ambiguity breaks the mental model, especially for a first-timer.
  - _Fix:_ Add a hint under PageHeader subtitle (Text component, tone='dim', variant='micro'): 'Manually add memories or import from chat interactions.' Or clarify in a Tooltip on the ADD MEMORY button. Phase 2 can remove this once behavior is live.
- **🟠 MED · interaction** — Dedup modal doesn't confirm merge outcome
  - _Why:_ User clicks MERGE, modal stays open, no toast/confirmation, no change visible. They don't know if merge succeeded, what happened to the loser memory, or if they can undo. Ambiguous state erodes confidence.
  - _Fix:_ After MERGE, show a Toast: 'Merged: kept <text A>, removed <text B>.' Optionally gray/disable that row and offer Undo. After all pairs resolved, show count ('Merged 3 pairs, removed 3 memories') and optionally close modal or refresh the dedup list.
- **🟠 MED · efficiency** — No full-text search for memory content
  - _Why:_ User can filter by type but not by content. With 10+ memories, if they remember a fragment ('Apple Silicon') but not the type, they must scan all categories manually. For a knowledge base, searchability is critical to usability.
  - _Fix:_ Add a search Input above or inline with the Tabs (placeholder='SEARCH MEMORIES…'). Filter memories in real-time by text content, independent of type filter. Use simple substring match (Phase 1) or semantic search (Phase 2).
- **⚪ LOW · information** — Empty state message is confusing when there are zero memories total
  - _Why:_ EmptyState shows 'NO MEMORIES' + 'No memories match the current filter.' When memories are truly empty (not a filter result), the second line is technically correct but misleading. No guidance on how to create the first memory.
  - _Fix:_ Differentiate: if `memories().length === 0`, show message='NO MEMORIES YET' + hint='Click ADD MEMORY or import from chat.' If filter is applied and finds zero, show current message. Use conditional Text in EmptyState or a Show/switch on the condition.
- **⚪ LOW · information** — Dedup similarity threshold and algorithm are unexplained
  - _Why:_ User sees '91% SIMILARITY' but doesn't know the threshold, how it's calculated, or why Odysseus recommends merging. Without transparency, they may distrust the recommendations.
  - _Fix:_ Add a hint line in the modal (Text variant='micro' tone='dim') explaining: 'Pairs above 70% similarity using semantic embeddings.' This sets expectations without cluttering the UI. Phase 2 can link to docs.
- **⚪ LOW · interaction** — Long memories are truncated with no way to read full text
  - _Why:_ ListRow shows only memory.text on one line. If a memory is 200+ characters, the user cannot read it without clicking something. Minor but impacts usability for longer context.
  - _Fix:_ Make ListRow clickable to expand into a Drawer/Modal showing full memory text, type, created date, pinned status. Or truncate text at 100 chars + '…' and add a visual expand indicator. Use Drawer or Modal component for detail view.
- **⚪ LOW · efficiency** — No bulk actions (pin/delete multiple at once)
  - _Why:_ Deleting or pinning 5 memories requires 5 menu interactions. For power users with large memory bases (50+), this is repetitive friction without scaling.
  - _Fix:_ Add optional multi-select mode (toggle via toolbar button 'SELECT MULTIPLE'). Show Checkboxes on ListRows in select mode. Add sticky action bar at bottom: 'PIN ALL (3)', 'DELETE ALL (3)', 'CANCEL'. This is Phase 2 polish but design system has Checkbox already.
- **⚪ LOW · efficiency** — No temporal sorting or filtering (oldest/newest/date range)
  - _Why:_ Memories are listed in fixed order (presumably creation date DESC). User cannot reorder by date, view oldest first, or filter by date range. For an evolving knowledge base, temporal context is valuable for reviewing growth.
  - _Fix:_ Add a sort menu next to Tabs: 'SORT: Newest / Oldest / Recently Modified.' Or add date-range filters ('Past Week / Month / All Time'). Use a compact Select or Tabs-style toggle to keep the UI dense. This is Phase 2 nice-to-have.


### Skills  
`/skills` · tier: user

**Purpose.** Display all reusable AI procedures (skills) the assistant can invoke by trigger phrase, allowing users to view, test, publish, and manage their automation library.

**Personas reviewed.**
- _Skill author / tuner_ — Just wrote a draft skill with a trigger phrase, now wants to test it, see if it works, then publish. Opens Skills, sees the skill is DRAFT, clicks to view details, then needs to test and edit without leaving the page.
- _Hurried operator_ — Quickly checking which automation skills are published and active before starting a research task. Needs to scan status, confirm setup is live, then return to the previous feature without friction.
- _First-time discoverer_ — New to Odysseus, exploring what skills do. Opens this page, sees 'AUTO' and 'DRAFT' labels with no explanation, unclear what 'AUTO-Tag Memory' does automatically or if they should create new skills. Needs guidance on what triggers are and how the system works.

**Works well.** Visual status overview via InstrumentBand (total + per-status counts with semantic color coding) enables quick scanning.; Detail drawer with full skill definition (trigger, body, timestamps) gives complete context without leaving the page.; Semantic StatusFlag colors (nominal/warn/info) and status tabs provide clear filtering without extra UI clutter.

**Gaps (12).**

- **🔴 HIGH · missing-state** — TEST action has no feedback or result state
  - _Why:_ The TEST button in the skill detail drawer is styled as a primary action (play icon, prominent footer placement) but is wired to a no-op. A skill author clicks TEST expecting to see input/output or a test harness, but nothing happens. No modal, no result display, no error handling. This breaks the core edit-test-publish loop and trains the user that the button does nothing.
  - _Fix:_ Implement a test modal (available `Modal` primitive) that opens on TEST click, prompts for test input (a `Textarea` component), shows a LoadingText state during execution, and displays the result or error in a read-only display. For Phase 1 mock, show a fake result. Wire it fully so clicking TEST → modal → result works end-to-end.
- **🔴 HIGH · error-recovery** — DELETE skill has no confirmation guard
  - _Why:_ Deleting a skill is permanent and destructive. The DELETE menu item calls `onSelect: () => {}` with no confirmation modal. A user can accidentally destroy 'Code Review' or a custom skill they invested time in with a single menu click. This violates safety patterns for dangerous operations.
  - _Fix:_ Add a confirm Modal (primitive exists) on DELETE menu select. Pattern: 'Delete <skillName>?' with a red/alert CONFIRM button and a CANCEL button. Modal body can include a hint like 'This cannot be undone.' Fire the delete after CONFIRM; dismiss on CANCEL.
- **🔴 HIGH · error-recovery** — Publish/unpublish operations lack error states
  - _Why:_ The PUBLISH / UNPUBLISH menu item calls `onSelect: () => {}` (no-op). When Phase 2 wires real API calls, if publish fails (e.g., skill validation fails due to missing trigger or syntax error in body), there is no error boundary. Users see no feedback — skill appears to stay in the same state, but it's unclear if the action succeeded, failed silently, or is still pending.
  - _Fix:_ After publish/unpublish completes (Phase 2), dispatch a success toast or update the skill's status flag in-place with a brief transition (StatusFlag + relativeTime update). On error, show an ErrorState or AlertText in a modal/toast with the error reason (e.g., 'Invalid trigger: regex contains unmatched parentheses'). Until Phase 2 API is ready, disable these menu items or stub them with a toast saying 'Coming soon'.
- **🔴 HIGH · navigation** — No inline edit path from the detail drawer
  - _Why:_ A skill author sees the detail drawer, wants to edit the trigger or body, but the drawer is read-only. The menu row has 'VIEW / EDIT' but clicking it re-opens the same read-only drawer. There is no link to an editor or edit mode. Editing requires leaving the Skills page and finding an editor elsewhere (if it exists), or manually crafting the skill again. This blocks the iterate-and-test workflow.
  - _Fix:_ Add an EDIT button to the drawer footer (next to TEST, before CLOSE) or as a link in the header. This button should navigate to a skill editor view (or open an inline edit drawer if no dedicated editor exists yet). Ensure the path is clear: view detail → TEST / EDIT → back to list.
- **🟠 MED · information** — Draft status lacks explanation of blocking issues
  - _Why:_ The 'Draft Reply' skill has DRAFT status, and its body contains a note ('This skill is in draft — trigger phrases need tuning'), but the UI doesn't explain: Is this draft because validation fails? Is it pending review? Is it the author's choice to keep it unpublished? A first-timer doesn't know if they should ignore drafts, avoid publishing them, or work on them.
  - _Fix:_ Add a `note` or `reason` field to the Skill model (e.g., reason: 'trigger_tuning_needed' | 'validation_failed' | 'author_draft'). In the detail drawer, show a small alert box (using `StatusFlag` with tone='warn' or a custom hint below the status flags) like: 'DRAFT — Trigger phrases need tuning before publish.' This makes the blocker explicit without reading the body.
- **🟠 MED · onboarding** — Auto-generated skills are unexplained
  - _Why:_ Skills like 'Auto-Tag Memory' and 'Auto-Link Documents' are marked with an AUTO badge and `autoGenerated: true`, but a new user doesn't understand: Did the system create these? Are they required/safe to delete? Do they run automatically or on-demand? The trigger text 'AUTO: new memory created' is only visible in the detail drawer and assumes knowledge of how automation works.
  - _Fix:_ In the detail drawer, show a brief explanation for auto-generated skills below the status flags, e.g.: 'This skill is auto-generated by Odysseus and runs automatically when the trigger event occurs (e.g., new memory created). It can be disabled by publishing to draft, but cannot be deleted.' Alternatively, add a Tooltip on the AUTO badge explaining the behavior.
- **🟠 MED · content** — Empty state after filtering provides no recovery path
  - _Why:_ When filtering to DRAFT and the list is empty, the EmptyState says 'NO SKILLS / No skills match the current filter.' This is accurate but doesn't guide the user. A first-timer thinks 'Okay, no drafts exist' but doesn't know how to create one. The hint should suggest a next step.
  - _Fix:_ Update the EmptyState hint based on the active filter. For empty DRAFT filter: 'No draft skills yet. Click NEW SKILL to create one.' For empty AUTO filter: 'No auto-generated skills. They appear when you set up automations.' This uses the existing EmptyState component with a more helpful `hint` prop.
- **🟠 MED · interaction** — NEW SKILL button has no discoverability or hint
  - _Why:_ The NEW SKILL button in the PageHeader is visible but wired to a no-op. A user clicks it and nothing happens. There's no hint about what happens next (modal form? navigation to editor?). A first-timer tries clicking and feels lost.
  - _Fix:_ Until Phase 2 wires the editor, add a click handler that shows a toast or modal saying 'Coming soon: Skill editor' or stub it with a Modal that says 'Skill creation form will open here.' In Phase 2, wire it to the skill editor. This prevents the 'dead button' UX.
- **🟠 MED · efficiency** — No search/filter by name or trigger phrase
  - _Why:_ With 6 mock skills, filtering by status works fine. But a real user could easily have 20–50 skills (custom + auto). Finding a skill by trigger phrase (e.g., 'Which skill handles email?') requires scanning the list or opening each detail. No search by name or trigger text is available.
  - _Fix:_ Add a search input above the status tabs (in the Panel header). Filter the list by name, trigger, or description using a simple substring match. Example: user types 'email' and sees only 'Draft Reply' (trigger contains 'email'). Use the existing `Input` component with a leading search icon.
- **⚪ LOW · efficiency** — No bulk operations for publishing or deleting
  - _Why:_ A user with many draft skills who wants to batch-publish them must click the menu and select PUBLISH for each one individually. This is tedious for a power-user workflow but not blocking for small numbers of skills.
  - _Fix:_ Add a checkbox to the left of each ListRow (or a select-all toggle in the tab bar). Show a sticky action footer when items are selected with PUBLISH / DELETE buttons. This is a Phase 2 enhancement but is worth noting for future iteration.
- **⚪ LOW · consistency** — Timestamp formats are inconsistent between list and drawer
  - _Why:_ List rows show relativeTime ('2d ago'), while the drawer shows a full `timestamp()` (ISO 8601). For audit purposes, this works, but the inconsistency is confusing. Also, there's no 'created' timestamp, only 'updated', so a user can't tell if a skill is new to them or recently changed.
  - _Fix:_ Either: (a) show relative time in both list and drawer for consistency (e.g., 'LAST UPDATED 2 days ago'), or (b) show full timestamps in both. For audit trails, consider adding a 'createdAt' field to the model and displaying both 'Created' and 'Last Updated' in the drawer.
- **⚪ LOW · interaction** — Detail drawer lacks back/close affordance for iteration
  - _Why:_ If a user opens detail → TEST (future: gets result) → wants to EDIT, they must close the drawer, re-find the skill in the list, and either open detail again or navigate to an editor. This is a minor friction point for the author workflow.
  - _Fix:_ After TEST completes (Phase 2), show the test result inline in the drawer (extend the drawer height or use a collapsible section). If the user decides to edit, they click EDIT and open the editor without closing. This keeps them in the drawer/editor context until ready to return to the list.


### Gallery  
`/gallery` · tier: user

**Purpose.** Browse and manage a personal media library (AI-generated, captured, and imported images/videos) by album, with inline favorites marking and a detail drawer for metadata and AI editing actions.

**Personas reviewed.**
- _Diligent Organizer_ — Wants to audit storage usage and find large files to clean up; filters by album and needs to understand total library size and sort by file size.
- _Accidental Visitor (non-technical household member)_ — Landed on Gallery by mistake; sees tiles and a detail drawer with AI edit buttons (Upscale, Inpaint, Denoise) but has no idea what those do, whether they're safe, or if they modify the original file.
- _Power User Recovering from Error_ — Suspects a file was corrupted or deleted; opens the drawer to check metadata (creation date, tags), run an AI edit, and needs to understand whether the operation is reversible or destructive.

**Works well.** Proper Suspense + EmptyState pattern when media list is empty; Responsive two-tier layout (sidebar on desktop, tabs on mobile) with album filtering and tile grid; Semantic color coding (favorite marker in warn tone, type/status flags in detail drawer)

**Gaps (11).**

- **🔴 HIGH · information** — Missing total storage size in header metrics
  - _Why:_ In a local-first app where disk space is finite, the user needs to know total library size to decide whether to clean up. The InstrumentBand shows item counts (TOTAL, IMAGES, VIDEO, FAVORITES) but no bytes/size aggregates — critical context missing.
  - _Fix:_ Add a fifth InstrumentBand item: { label: 'STORAGE', value: formattedBytes(totalSizeBytes()), tone: 'nominal' } (or 'warn' if approaching quota, once quota is configurable).
- **🔴 HIGH · efficiency** — No sort/filter options for file size, date, or type
  - _Why:_ User wants to find largest files to free space or oldest/newest media, but can only filter by album. Without sort-by-size or sort-by-date, finding a target file is a tedious manual scan.
  - _Fix:_ Add a sort control (dropdown or row of buttons) above the grid: 'SORT: DATE | SIZE | NAME' (with an up/down arrow for direction). Persist choice to localStorage. This is cheap to implement: sort filtered() result before rendering.
- **🔴 HIGH · missing-state** — AI edit actions lack intent/safety/result clarity
  - _Why:_ Buttons labeled UPSCALE, INPAINT, DENOISE, STYLE XFER are shown without explanation. A first-time or cautious user doesn't know: Does this modify the original? Is it reversible? Does it upload the file? Is there a cost/quota? A destructive/risky action triggered by a tap is unsafe.
  - _Fix:_ Add a tooltip or modal description per action. Use an InfoIcon next to 'AI EDIT' label, or replace the label with a Drawer subheader that explains: 'These operations process and save a new version; the original is preserved.' Show operation cost/duration if applicable (Phase 2 binding). At minimum, add a Tooltip to each button: <Tooltip><Button ...>UPSCALE</Button><span>Increase resolution 2x; saves as new variant</span></Tooltip>.
- **🟠 MED · error-recovery** — No confirmation or undo for AI edit operations
  - _Why:_ When an AI edit completes (the progress bar fills), the action state clears silently. The user has no feedback on whether the result was saved, overwritten, or lost. If they close the drawer, they won't know the result is or isn't in the gallery.
  - _Fix:_ After operation completes (progress === 100), show a brief StatusFlag toast or drawer state change: 'NEW VARIANT SAVED: [new_title_or_link]' (with a View/Open button if a new tile appeared in the grid, or a Gallery refresh). If Phase 1 mock only, at least show a static success message for 3 seconds: <Show when={progress() === 100}><StatusFlag status='nominal'>COMPLETE</StatusFlag></Show>.
- **🟠 MED · information** — No timestamp display on tiles; date only in drawer
  - _Why:_ When skimming a large grid by album, the user has no visible age indicator on tiles themselves (only size + tags). To find 'that image I took yesterday,' they must open the drawer for each candidate. In a power-user scenario (checking for recent backups or corruption), missing timestamps slow scanning.
  - _Fix:_ Add a date readout to the tile footer, below the file size. Format as relative time or ISO-date depending on space: <Text variant='micro' tone='dim'>{relativeDate(item.createdAt)}</Text> or just 'YYYY-MM-DD' if brief. Check text truncation on small tiles.
- **🟠 MED · feedback** — IMPORT button leads nowhere; no success feedback
  - _Why:_ The IMPORT button exists in the PageHeader but clicking it in the current mock produces no visible action or confirmation. If a user imports a file, they have no way to verify it was added to the gallery (no toast, no grid refresh, no new tile appeared).
  - _Fix:_ For Phase 1 mock: when clicked, show a brief loading state (setLoading(true) during a fake 1-2s delay, then show a toast/StatusFlag: 'Imported X file(s)'), then refresh the grid. Phase 2: wire to actual file-upload handler. At minimum: disable the button briefly, then flash a success message.
- **🟠 MED · trust-safety** — Destructive AI edit with zero undo/rollback path
  - _Why:_ If STYLE XFER or INPAINT is applied and saved, and the user realizes mid-workflow 'I didn't mean to edit that,' there is no undo, no 'previous version' link, no 'revert to original.' In a power-user context, this could cause data loss concerns.
  - _Fix:_ Clarify in UX: (1) preserve the original file always; (2) save results as new variants (with a naming convention: 'neural_grid_v3_upscaled.png'); (3) in the detail drawer, optionally show a 'VARIANTS' section listing all edits of this file (Phase 2 backend work, but mock now). For Phase 1, just document in the tooltip that originals are preserved.
- **🟠 MED · efficiency** — No bulk selection or multi-select actions
  - _Why:_ If a user wants to delete, export, or tag multiple files at once (e.g., select all renders, bulk-delete), there's no affordance. Each action is single-item only. In a large library, this is tedious friction.
  - _Fix:_ Add a checkbox to tile header (or shift-click to multi-select). Show a floating action bar when items are selected: 'N SELECTED | [DELETE] [EXPORT] [ADD TAG]'. For safety, DELETE triggers a modal confirm: 'Delete N items? (originals preserved in archive)' (once trash/archive is in scope). Phase 1: implement checkbox UI + selection state; Phase 2: wire actions.
- **⚪ LOW · navigation** — Mobile: no explicit back/close signaling from detail drawer
  - _Why:_ On mobile, when the detail drawer opens (full-screen or overlay), the user may not realize the close button exists or how to navigate back. A clear back affordance (header with back arrow, or swipe-to-close hint) helps.
  - _Fix:_ Ensure Drawer component renders a visible close button in the header (it likely does). Optionally add a back-arrow + 'BACK' label in the drawer title for extra clarity on mobile: <Drawer title={<Row><Icon name='chevron-left' /> BACK</Row>} />. Check existing Drawer implementation in ui/.
- **⚪ LOW · accessibility** — Favorites marker uses 'dot' icon but meaning unclear without label
  - _Why:_ The favorite button shows a dot icon (filled when favorite=true, outline when false) without a label. A keyboard-only user or someone unfamiliar with the icon convention may not know what it does.
  - _Fix:_ Add a Tooltip to the favorite button, or replace the icon with a named variant (e.g., 'star' or 'heart'). Alternatively, add aria-label: 'Toggle favorite' and ensure Tooltip wraps it: <Tooltip tip='Toggle favorite'><Button .../></Tooltip>.
- **⚪ LOW · navigation** — Album sidebar hidden on small screens; discoverability at risk on mobile
  - _Why:_ On desktop, the album list is always visible in a sidebar. On mobile, it's replaced by tabs. If a user has many albums, the mobile tabs may overflow or be hard to navigate. There's no affordance to 'see all albums' or search within them.
  - _Fix:_ On mobile, if album count > 5, show only popular/recent tabs and add a '+MORE' button that opens a modal/drawer listing all albums (searchable if many). Phase 1: leave as-is (small mock data); Phase 2: refactor Tabs to handle overflow gracefully or add a pill-menu for album selection.


### Uploads  
`/uploads` · tier: user

**Purpose.** Store, organize, and extract content (OCR, text, form fields) from uploaded PDF and image documents. Extracted text and detected form fields can be edited and exported for use in chat, memory, and other workflows.

**Personas reviewed.**
- _Power user (researcher / RAG curator)_ — Uploads 20 research papers for batch extraction, needs to search by name to find one a week later, spot-check OCR quality, correct errors in extracted text, and export cleaned results to feed a memory/RAG system.
- _Hurried user (time-constrained)_ — Uploads 5 files quickly; 3 extract successfully, 2 fail. Needs to retry the failed ones but is uncertain whether clicking the file again re-uploads it or tries extraction. Worries about duplicates.
- _First-timer (cautious, unfamiliar)_ — Lands on Uploads page cold, drags a file into the DropZone expecting immediate upload, but sees no confirmation or progress. Clicks EXPORT and SAVE FIELDS expecting downloads or persists to a file manager, but nothing visible happens (mock). Leaves uncertain whether actions worked.

**Works well.** Status visibility: InstrumentBand and StatusFlags clearly show extraction states (QUEUED, EXTRACTING, DONE, ERROR) at a glance.; Extracting progress: ProgressBar shows extraction percentage in-line for active jobs, reducing anxiety during wait.; Detail-rich panel: Two-tab detail view surfaces both raw extracted text and structured form fields, with editable inputs to correct OCR errors.

**Gaps (12).**

- **🔴 HIGH · missing-state** — No delete / remove action on files
  - _Why:_ Users accumulate uploads over time; without delete, the list grows unbounded. In Phase 2, when real uploads persist to disk, the inability to clean up becomes a storage and UI clutter problem. Even in Phase 1 (mock), it sets an expectation that files are permanent.
  - _Fix:_ Add a trash/delete icon to the right of each ListRow (or a context menu). Show a confirm Modal before deletion: 'Delete <filename>? This cannot be undone.' Use existing Button, Icon, and Modal primitives.
- **🔴 HIGH · efficiency** — No search or filter in the file list
  - _Why:_ With 20+ uploads, finding a specific file by eye is tedious. Users need to locate by name, date, status, or MIME type. Power users especially rely on quick lookup to verify OCR quality across a batch.
  - _Fix:_ Add a search Input at the top of the FILES panel that filters by file name in real-time. Optional: add a Filter / Tabs bar to show only DONE, EXTRACTING, ERROR, or all. Use existing Input and Tabs primitives.
- **🔴 HIGH · interaction** — Upload and Browse buttons do not work (dead-end interaction)
  - _Why:_ Visitors click 'UPLOAD' in the header or 'BROWSE FILES' in DropZone expecting a file picker, but nothing happens. Even though Phase 1 is mock-data, buttons should not appear clickable if they're non-functional—or should show feedback ('Coming in Phase 2'). Currently, the interaction is silently broken.
  - _Fix:_ Either disable the UPLOAD button and BROWSE FILES button with a disabled state + Tooltip explaining 'File upload in Phase 2', or wire them to mock behavior (e.g., open a file picker, add a mock file to the list, and show a toast). Use existing Button disabled state and Tooltip.
- **🔴 HIGH · missing-state** — No feedback on EXPORT or SAVE FIELDS actions
  - _Why:_ Buttons exist but clicking them has no visible effect (no toast, no state change, no download). Users don't know if the action succeeded. 'SAVE FIELDS' is especially risky—did my edits persist or vanish? In Phase 2, this must show success/error feedback.
  - _Fix:_ On EXPORT or SAVE FIELDS click, show a transient success toast (e.g., 'Exported as text.txt' or 'Fields saved'), or a brief state change (button becomes 'SAVED' with a check icon, then reverts). Use a Toast/notification primitive (if available) or StatusFlag state.
- **🟠 MED · interaction** — No retry action for failed extractions
  - _Why:_ When extraction fails (error status), the detail panel says 'Try re-uploading or use a different file' but offers no button to retry or re-upload the same file. Users must drag/browse the same file again, risking confusion ('Will this duplicate?').
  - _Fix:_ When upload().status === 'error', show a Button in the detail panel: 'RETRY EXTRACTION'. Clicking it resets status to queued and re-triggers extraction. In Phase 1, mock it by toggling status to 'extracting' then 'done'. Use existing Button.
- **🟠 MED · information** — No timestamps or upload/extraction metadata
  - _Why:_ Files lack upload date, extraction start/end time, or file age. Users can't tell if a file is fresh or stale, or sort by recency. Over weeks, a large library becomes unsorted and hard to navigate.
  - _Fix:_ Add uploadedAt and completedAt timestamps to the Upload model (ISO 8601). Display uploadedAt as a Readout in the DOCUMENT DETAIL panel, and optionally as a sortable column or filter in the FILES list. Use existing Text/Readout component for display.
- **🟠 MED · interaction** — DropZone lacks visual feedback on drag-over or acceptance
  - _Why:_ The DropZone says 'DROP FILES HERE' but when a user drags a file over it, there's no visual change (no highlight, no 'drop accepted' state). The hover styles are subtle (`hover:border-dim hover:bg-raised`). Users can't tell if the zone will accept the file until they release it (and it fails, because upload is mocked).
  - _Fix:_ Enhance the DropZone with an onDragOver handler that applies a stronger visual state (e.g., `border-info bg-info/10` or use a StatusFlag-like highlight). Revert on dragLeave. Wire onDrop to accept files (Phase 1: mock by adding them to the uploads list; Phase 2: upload them).
- **🟠 MED · information** — No per-file error details (why extraction failed)
  - _Why:_ Error status shows only 'EXTRACTION FAILED' with generic advice. Users can't diagnose: was it a timeout, unsupported format, corrupted file, or size limit? Different failures need different fixes (re-upload, try a different file, check file size).
  - _Fix:_ Add an errorReason?: string field to the Upload model. Display it in the detail panel's EmptyState when status === 'error' (e.g., 'File too large (120MB > 50MB limit)' or 'Unsupported format'). Provide actionable hints per error type.
- **🟠 MED · missing-state** — No indication of unsaved changes in form fields or extracted text
  - _Why:_ Users edit extracted text or form fields, then click SAVE FIELDS, but there's no before/after comparison or 'unsaved' indicator. They don't know if changes were persisted or if the save action is idempotent. Risk of losing corrections if they navigate away.
  - _Fix:_ Track dirty state: add a flag when extractedText or formValues diverges from the original (props.upload.extractedText / props.upload.formFields). Show a subtle indicator (e.g., a yellow dot or text 'UNSAVED CHANGES') while dirty. After SAVE FIELDS, clear the flag and show a toast.
- **⚪ LOW · efficiency** — No bulk actions (select multiple files, batch delete, batch re-extract)
  - _Why:_ Workflows involving many files (e.g., 20 uploads to review, or 5 failed extractions to retry) require single-file actions repeated many times. No way to select all, delete all errored files, or re-extract a batch.
  - _Fix:_ Add checkboxes to ListRow components. When selected, show a floating action bar at the bottom with buttons: DELETE SELECTED, RE-EXTRACT SELECTED. Use existing Checkbox and Button primitives. Phase 1 can mock; Phase 2 calls batch endpoints.
- **⚪ LOW · information** — Ambiguous EXPORT button behavior and format
  - _Why:_ EXPORT button has no hint about what format it exports or what filename it uses. Users expect a download dialog but mock behavior is silent. Does it export .txt, .md, .json, or copy to clipboard?
  - _Fix:_ Add a Tooltip to the EXPORT button explaining format (e.g., 'Export as plain text'). After EXPORT, show a toast confirming the action (e.g., 'Copied to clipboard' or 'Download started: document.txt'). Wire to real behavior in Phase 2.
- **⚪ LOW · onboarding** — Detail panel empty state doesn't guide next steps
  - _Why:_ When no file is selected, the EmptyState says 'SELECT A FILE' and hints 'Choose a document from the list…' but the hint assumes files exist. First-timers see a blank right panel and don't know the flow: upload → extract → review → edit → save.
  - _Fix:_ Enhance the empty state hint to suggest the flow: 'Drop files above to get started, or select a document from the list to view extracted content.' Or, if FILES list is also empty, provide a brief walkthrough (e.g., 'Upload PDFs or images. Odysseus will extract text and detect form fields.' with a link to docs).


### Knowledge Base (RAG)  
`/rag` · tier: user

**Purpose.** Manage indexed document collections and configure the embedding index. Users add folder paths, monitor indexing status, and maintain the knowledge base that powers retrieval-augmented generation (RAG) in chat and research contexts.

**Personas reviewed.**
- _Carmen, a researcher managing a growing document library_ — Carmen has 4 indexed sources totaling ~4,500 docs. She notices the '/home/panchi/projects/docs' source shows 'ERROR' with 0 docs indexed (last attempt 6 days ago). She wants to understand why indexing failed and reindex it. She clicks the REMOVE menu option by mistake and has no confirmation before data is lost.
- _Leo, a first-time user visiting the Knowledge Base page accidentally_ — Leo is exploring the app and lands on /rag. The page shows sources and statistics but no indication of what this feature does or how it connects to chat/research. He sees the 'ADD SOURCE' panel but doesn't know whether his personal notes folder is in a format this system accepts. He adds a path, clicks ADD, nothing happens, and the input clears — no feedback on success, failure, or pending state.
- _Alex, a power user who maintains the system and occasionally recovers from indexing issues_ — Alex has two sources showing 'STALE' (last indexed 10 days and 9 days ago). She needs to reindex both quickly but there's no bulk-action way to do this. She must open the menu on each row individually. When she clicks REINDEX, there's no confirmation or progress indication. The REBUILD INDEX button in the header is her only tool, but it rebuilds *everything*, not just the stale ones.

**Works well.** Clear, semantic use of StatusFlag colors (nominal/warn/alert) — users instantly know which sources are healthy; Rebuild progress is visible with a ProgressBar showing percentage — users aren't left in the dark during long operations; InstrumentBand displays key stats (total docs, collections, embedding model, store size) at a glance without opening a settings panel

**Gaps (9).**

- **🔴 HIGH · trust-safety** — Destructive action (REMOVE source) has no confirmation dialog
  - _Why:_ Removing a source is irreversible and deletes indexed documents from the knowledge base, potentially breaking retrieval for dependent chats/research. A accidental click in the menu (or misreading the options) immediately destroys data with no warning or undo.
  - _Fix:_ Wire the REMOVE menu item to open a Modal (using the existing Modal primitive) with a confirmation dialog, similar to the REVOKE TOKEN pattern in ApiTokensScreen. Show the source path and doc count, then require the user to confirm with a danger-variant button before deletion.
- **🔴 HIGH · interaction** — ADD SOURCE button clears input instead of submitting
  - _Why:_ Clicking ADD clears the newPath signal but never actually adds the source — no network call, no handler. Users type a path and click ADD expecting the source to be created, but nothing happens except the input empties. This is UI theater — the button appears functional but is inert.
  - _Fix:_ Replace the onClick handler (currently `() => setNewPath('')`) with a real submission: emit the path to a handler function that would (in Phase 2) POST to the backend. For now in Phase 1 mock, call a handler that shows a success message (StatusFlag or a brief Panel with 'SOURCE ADDED'), adds the new source to the mock list, and clears the input on success.
- **🟠 MED · interaction** — REINDEX and VIEW DOCS menu items have empty handlers, no feedback
  - _Why:_ Both menu items call `onSelect: () => {}` — doing nothing. Users click REINDEX expecting the source to re-index (at least showing a loading state), or click VIEW DOCS expecting to navigate or see a list. The menu closes but nothing happens, leaving users uncertain whether the action registered.
  - _Fix:_ For REINDEX: show a temporary status change on that row (e.g., briefly highlight the StatusFlag or show a loading state) and trigger a mock reindex animation (reuse the rebuild progress pattern). For VIEW DOCS: either navigate to a documents list filtered to that source (requires a new route `/documents?source=<id>`) or show a drawer/modal with a preview of docs in that source. If the destination isn't decided yet, add a Tooltip on the menu item explaining the action is not yet implemented ('Coming in Phase 2').
- **🟠 MED · feedback** — No success/failure feedback when adding a source path
  - _Why:_ When the ADD button is wired to actually submit, users need confirmation that the path was accepted and indexing started. Without it, they won't know if the path is valid, the folder is accessible to the server, or if indexing is queued. Especially important because the hint mentions 'Paths must be accessible to the Odysseus server process' — a common failure mode.
  - _Fix:_ After a successful add, show a temporary LoadingText or StatusFlag above the input ('INDEXING…') for a few seconds, or add the new source to the list immediately with status 'indexing'. If submission fails (path not accessible), display an error message in the panel or show a Tooltip on the button with the failure reason (e.g., 'Path not found' or 'Permission denied').
- **🟠 MED · information** — REINDEX action is ambiguous — no indication it's per-source or what it triggers
  - _Why:_ The menu option 'REINDEX' doesn't clarify whether it triggers a fresh index of just that source or a full rebuild. The header's 'REBUILD INDEX' button rebuilds everything, so the distinction is unclear. A user may click REINDEX expecting the same behavior as the header button.
  - _Fix:_ Rename the menu item to 'REINDEX THIS SOURCE' for clarity. Add a Tooltip on the menu item ('Re-index just this source without rebuilding the entire index') or a brief microcopy in the modal if you implement a confirmation dialog. Visually indicate progress on that row (e.g., change the StatusFlag to 'indexing' and show a small spinner or highlight).
- **🟠 MED · error-recovery** — Error state (error source) lacks actionable guidance
  - _Why:_ The '/home/panchi/projects/docs' source shows 'ERROR' and 0 docs, last attempt 6 days ago. The INDEX HEALTH panel warns 'One or more sources are stale or unreachable. Retrieval quality may be degraded for affected collections.' but doesn't explain *why* the source failed or what the user should do. Is it a path permissions issue? File encoding? Disk full? The error is reported but not debugged.
  - _Fix:_ In the INDEX HEALTH panel, expand the error display to show a brief reason if available (e.g., 'PATH NOT FOUND', 'PERMISSION DENIED', 'PARSE ERROR: unsupported file type'). Add a Tooltip or a help icon next to the error StatusFlag with context. Optionally, provide a quick action: a 'RETRY' button on the error row that re-runs indexing, or a 'REMOVE' button to clean up unreachable sources.
- **⚪ LOW · onboarding** — No explanation of RAG or why users should add sources
  - _Why:_ The page opens with a subtitle 'RAG source collections and index configuration' — technical jargon that doesn't explain the purpose to a non-technical user (or to someone new to the app). Why would Leo add his notes folder here? How does this help him? What happens when he does?
  - _Fix:_ Add a brief explanatory sentence in the PageHeader subtitle or a separate help Panel at the top: 'Knowledge Base: Index your documents and folders to enable retrieval-augmented generation. Chat with the AI about your indexed content.' Or add a Tooltip on the 'KNOWLEDGE BASE' title that explains the feature in plain language.
- **⚪ LOW · navigation** — VIEW DOCS has no destination or preview
  - _Why:_ Clicking VIEW DOCS is supposed to show the documents in that source, but there's no handler and no linked route. It's unclear whether it should show a count, a list, a search interface, or just a path. Without a destination, the menu item is a dead-end.
  - _Fix:_ Either implement a drawer/modal that shows a filtered list of documents from that source (with doc name, type, size, indexed date) using the existing ListRow component, or route to a `/documents?source=<id>` page if one exists. For now, add a Tooltip on the menu item: 'Coming in Phase 2' or remove the option if it's not a priority.
- **⚪ LOW · information** — STALE status provides 'last indexed' timestamp but no indication of what triggers an update
  - _Why:_ A source marked 'STALE' (e.g., last indexed 10 days ago) doesn't explain *why* it's stale. Are source files automatically re-indexed on a schedule? Does the user need to manually reindex? Is staleness a problem or just informational?
  - _Fix:_ Add microcopy near the STALE StatusFlag or in the INDEX HEALTH warning: 'STALE: This source has not been indexed in over 7 days. Click REINDEX or use REBUILD INDEX to update.' This clarifies that staleness is the user's responsibility to resolve, not an automatic background process.


### Code Runner  
`/code` · tier: open

**Purpose.** Write and execute code scripts (Python, JavaScript, HTML) in-browser without server access, with real-time output and a history of past runs.

**Personas reviewed.**
- _Sheena, hurried Python tester_ — Pastes a 20-line data processing script, needs to run it, check output, tweak a line, rerun — wants zero friction and keyboard shortcuts.
- _Marcus, first-timer landing from nav_ — Sees 'Code Runner' in the sidebar, opens it, has no idea what 'sandboxed in-browser' means, doesn't know which libraries are available for Python, feels lost.
- _Riley, debugging after a failure_ — Last script errored. Needs to see the full stack trace, copy part of it, edit the code, rerun, confirm the fix worked.

**Works well.** Real-time output streaming with LoadingText feedback while running — no mystery state; Semantic coloring: error output panel borders alert, success shows nominal StatusFlag — meaning is visible at a glance; Language switcher auto-seeds starter code, eliminating the blank-slate friction when switching contexts

**Gaps (9).**

- **🔴 HIGH · onboarding** — No onboarding hint for what languages/libraries/limitations are available
  - _Why:_ Marcus opens the page, sees Python/JavaScript/HTML options but has no idea if NumPy is available, what Python version it is, or why he can't run shell commands. The subtitle only says 'sandboxed in-browser' — jargon to a first-timer.
  - _Fix:_ Replace or expand the PageHeader subtitle with a more concrete hint like 'Python 3 (Pyodide), JavaScript (native), HTML (rendered). No host access, no file I/O.' Or add a collapsible/expandable 'About this environment' section below the header with runtime details, available packages (if known), and a link to docs.
- **🟠 MED · efficiency** — No keyboard shortcut to run (Ctrl+Enter/Cmd+Enter)
  - _Why:_ Sheena must reach for the mouse or Tab+Enter to run code, breaking flow for rapid iteration. Shell feature has this; Code Runner should too.
  - _Fix:_ Add onKeyDown handler to the Textarea catching Ctrl/Cmd+Enter → runCode(), same pattern as Shell's handleKeyDown at line 42 of ShellScreen.tsx.
- **🟠 MED · efficiency** — No way to copy output or select/copy the full error text
  - _Why:_ Riley sees a long traceback, wants to copy the error to search Stack Overflow or paste into a debugging tool. The output div is readable but the text inside has no copy button and selecting is awkward (line-by-line layout).
  - _Fix:_ Add a copy-to-clipboard icon button in the OUTPUT panel's meta (next to the StatusFlag). Use the Icon + Button primitives; onClick reads the full output string and copies to navigator.clipboard. Or mark the output container with user-select-all (Tailwind: select-all) to make triple-click work.
- **🟠 MED · efficiency** — History sidebar is read-only; can't re-run a past script directly
  - _Why:_ Sheena sees a successful run in the history, wants to re-run it or edit it without re-typing. Clicking a history row does nothing. This is a UX trap — it looks clickable but isn't.
  - _Fix:_ Make ListRow items clickable (add onClick handler); clicking a row populates the editor with that run's source code and language. Use the same visual feedback as Shell's history interaction (if it has one) — or add a subtle hover state (border/background token from Panel) to signal interactivity.
- **🟠 MED · error-recovery** — No error recovery guidance when execution fails
  - _Why:_ Riley's script fails, sees 'ERROR' status and the traceback, but no hint on next steps: 'Edit your code above and press RUN to retry' or 'Copy the error and search docs.' The panel just ends at the bottom of output.
  - _Fix:_ Add a one-line helper Text below the output panel: 'Fix your code above and run again.' Or, when status='error', show a subtle secondary Button in the OUTPUT meta: 'Copy error to clipboard' alongside the StatusFlag.
- **⚪ LOW · onboarding** — Empty editor state is ambiguous — no default template on first load
  - _Why:_ Marcus lands on the page, sees an empty editor, isn't sure if he should paste code or if there's a template. The data.ts seeds starterCode['python'], but the UI doesn't reflect that clearly on mount.
  - _Fix:_ Confirm the editor renders starterCode on mount (it should via createSignal default). If it doesn't, add a comment or assertion. If it does, no change needed. Low priority because the code looks correct; this is a verification.
- **⚪ LOW · missing-state** — Execution is instant mock data — no visible timeout or cancellation for long-running real code
  - _Why:_ Phase 2: when real code execution happens, long-running scripts will hang. Currently, clicking RUN while running=true is blocked (button disabled), but there's no way to cancel. A user might assume their code is frozen.
  - _Fix:_ Add a 'CANCEL' button variant that appears only when running=true, next to the RUNNING text in the editor panel meta. This is a future-proofing gap; for Phase 1 mock data, this is polish.
- **⚪ LOW · navigation** — Run History counts could cause infinite scroll friction
  - _Why:_ If 100+ runs accumulate, the history sidebar will become a long scrollable list with no way to search, filter, or pagination. Marcus can't find a specific run easily.
  - _Fix:_ For Phase 1, this is low priority (mock has 4 items). For Phase 2, consider: (a) a search/filter field in the RUN HISTORY panel header, or (b) a 'Clear history' button + a count badge, or (c) limit display to last N runs with a 'Show older' button. The primitive Tab component could also split history by language if relevant.
- **⚪ LOW · trust-safety** — No confirmation or undo for clearing the editor
  - _Why:_ If a user accidentally types/pastes and wants to reset, there's no Undo or 'Revert to last run' button. They have to re-select the language or manually clear the text. Low risk because code is ephemeral (not saved), but friction is real.
  - _Fix:_ Add a 'Reset to template' button in the EDITOR meta (next to the language select and RUN button), that restores the starter code. Or use browser undo (Ctrl+Z), which should work natively. No new primitive needed.


### Signatures  
`/signatures` · tier: user

**Purpose.** Allows users to create, view, and manage digital signatures for use in PDF documents and email footers. Displays saved signatures with use counts and provides quick actions to insert them into PDFs/emails or delete them.

**Personas reviewed.**
- _Hurried Professional_ — Needs to add a quick signature for an urgent PDF document, expecting the 'Insert into PDF' action to actually insert it and complete their workflow.
- _First-time User (Accidental Arrival)_ — Landed on the Signatures page by clicking the nav item out of curiosity; doesn't actually need signatures yet and is unclear why this feature exists or when they'd use it.
- _Curator / Cleanup User_ — Has accumulated several signatures and wants to reorganize them—sorting by date, finding old unused ones, and bulk-deleting unused signatures to keep the collection clean.

**Works well.** Proper loading state coverage (Suspense + LoadingText) and empty state with inline guidance when no signatures exist.; Modal creation flow is self-contained with a clear name input, drawing area placeholder, and disabled Save button until required fields are met.; InstrumentBand quickly communicates key metrics (count, total uses, capability flags) at a glance.

**Gaps (9).**

- **🔴 HIGH · error-recovery** — No confirmation before destructive delete action
  - _Why:_ The delete menu item triggers immediately on select with no confirmation prompt. A user can accidentally delete a signature (especially one with high use count) and have no way to undo it. This is irreversible data loss without a guard.
  - _Fix:_ Wrap the onDelete handler in a confirm dialog: add a ConfirmModal / confirm-on-click that shows the signature name and use count, with 'Delete Permanently' (danger tone) and 'Cancel' buttons. Only call props.onDelete if the user confirms.
- **🔴 HIGH · missing-state** — Insert actions do nothing, misleading user success
  - _Why:_ The 'Insert into PDF' and 'Insert into Email' menu actions are defined but have empty onSelect handlers (onSelect: () => {}). A user clicks Insert, nothing happens, and they assume either the action succeeded silently or the feature is broken—creating confusion and distrust.
  - _Fix:_ Until Phase 2 wires these to real PDF/email flows: display a ForbiddenView or Toast (if available) saying 'Signature insertion not yet available—backend integration coming in Phase 2.' Alternatively, disable these menu items with a disabled: true flag and show a Tooltip on hover explaining Phase 2.
- **🟠 MED · navigation** — No way to search/filter signatures by name
  - _Why:_ With only 3 mocks, this isn't painful, but in production (10+ signatures) a user has no way to find a specific signature. They must scroll the grid and scan visually, especially if naming conventions aren't consistent.
  - _Fix:_ Add a text input above the grid (or in the PageHeader actions row) to filter signatures by name. Use the Input component with a 'search' icon (or magnifying glass if available). Update the displayed grid in real-time as the user types. Show an EmptyState if no matches.
- **🟠 MED · efficiency** — No sort/order options for signature list
  - _Why:_ Signatures are shown in creation order (or arbitrary mock order). A user managing multiple signatures might want to sort by 'Most Used' to identify which ones matter, or by 'Newest' to see recent additions. Without this, they can't prioritize.
  - _Fix:_ Add a Select dropdown in the PageHeader (label: 'SORT BY') with options: 'Created (Newest)', 'Created (Oldest)', 'Most Used', 'Least Used'. Update the signatures() signal sort order on change.
- **🟠 MED · efficiency** — No bulk delete or multi-select capability
  - _Why:_ If a user has accumulated unused signatures and wants to clean up (common with 'Primary', 'Casual', 'Initials' type variants), they must delete one at a time. This is repetitive friction.
  - _Fix:_ Add a Checkbox to each SignatureTile (or a 'Select All' toggle in the InstrumentBand header). When selected, render a floating action bar at the bottom showing 'Delete X Selected' (danger button). On click, show a ConfirmModal listing the selected names before bulk-deleting.
- **🟠 MED · onboarding** — Draw area placeholder UI doesn't guide the real interaction
  - _Why:_ The modal shows 'Click or draw here to sign' but the actual phase-2 behavior (pen input, touch support, mouse drag) is completely unknown. A user on a trackpad or phone may try to interact and get nothing, then assume the feature is broken.
  - _Fix:_ Replace the placeholder text with 'Draw with your mouse or trackpad (Phase 2: touch & pen support). Click CLEAR to reset.' Consider adding an InlineHelp text or tooltip icon that explains the interaction model. The mock currently only detects clicks; note this limitation clearly so users don't expect drag-to-draw.
- **⚪ LOW · information** — Signature preview in tile is text-only, doesn't show actual signature art
  - _Why:_ Each tile shows the signature name in italics where the actual signature would appear. A user can't visually identify which signature is which until they open the tile, making the grid less scannable and harder to match against mental reference.
  - _Fix:_ In Phase 2, render the actual signature image/canvas in the Box (aspect-video). For now, if a real signature SVG/image path is stored, render it; otherwise keep the text placeholder. Consider adding a small 'pen' icon + a semitone background to make it clear it's a placeholder, not a broken image.
- **⚪ LOW · information** — No indication of signature quality or readability
  - _Why:_ A user might create a messy or illegible signature without realizing. The tile doesn't show any feedback about quality (or give them a chance to preview/test the signature before saving).
  - _Fix:_ In the DrawSignatureModal, after the user draws, show a live preview of what the signature will look like on a tile (render it at the expected size/context). This lets them see if it's legible before committing. Add a 'Preview' section below the drawing area.
- **⚪ LOW · trust-safety** — No export or backup option for signatures
  - _Why:_ Signatures are personal and have legal/contractual weight. A user might worry about data loss if the app crashes or they lose their device. No export/backup means no way to recover signatures independently.
  - _Fix:_ Add an 'Export All Signatures' button to the PageHeader (or in a Drawer menu). Let them download a JSON file with all signature data (or PNG/SVG if rendering is available). Label it clearly so they know it's for backup/archival, not for sharing.


### Email  
`/email` · tier: user

**Purpose.** Unified multi-account inbox with AI-powered triage and suggested replies. Lets a technical user scan, filter, and respond to messages across personal and work accounts from a single surface.

**Personas reviewed.**
- _Technical owner (Francisco)_ — Lands on inbox after returning from deep work, checks unread and high-urgency counts to decide priority, wants to read a security alert and decide if action is needed, then move to next task within 2 minutes.
- _Hurried responder_ — Jumps to inbox to reply to sprint planning email before EOD deadline, has a narrow window (may be on iPad), wants to hit 'reply', fill in a few fields, and send — no friction.
- _Mobile/narrow-viewport user_ — Views inbox on a phone or 60% browser window; all three columns (accounts/folders, list, detail) are stacked and require horizontal scrolling or collapse — may not discover reply UI or may give up.

**Works well.** Clear semantic status flags (URGENT, SPAM, tags) and urgency metrics at the top (InstrumentBand) give immediate triage context.; AI Summary + Suggested Replies reduce friction to respond — user sees the quick options before deciding to draft freeform.; Multi-account, multi-folder support with sidebar navigation is well-structured; switching accounts auto-resets to the first folder to avoid confusion.

**Gaps (12).**

- **🔴 HIGH · error-recovery** — Compose button is not visible after reply flow starts; no way to cancel/undo if drawer closes
  - _Why:_ User clicks a reply suggestion, drawer opens with prefilled fields (To, Subject, Body). If the drawer is accidentally closed or user hits Escape, there is NO recovery UI — the draft is gone. The COMPOSE button at the top is not visible in the drawer, so there's no visual cue to reopen. On mobile, this is catastrophic.
  - _Fix:_ Add a persistent, always-visible draft recovery notice when a compose drawer closes with non-empty fields: show a StatusFlag + Button ('DRAFT SAVED', 'RESUME') at the bottom of the page or as a toast-style dismissible banner. Use existing Drawer + Button + StatusFlag primitives.
- **🔴 HIGH · error-recovery** — No validation or confirmation before sending; empty To field will fail silently
  - _Why:_ The SEND button has no onClick handler and doesn't validate required fields (To, Subject). User can fill a body, forget the recipient, hit send, see nothing happen, and have no idea if it failed or succeeded. For a tool that touches email, silent failure is a trust break.
  - _Fix:_ Add validation: On SEND click, check that To is non-empty and a valid email. Show an inline error under the To field if missing (use Field/Input error state if available, or a StatusFlag 'MISSING RECIPIENT'). Only proceed if valid. Add a success toast or drawer footer status after send succeeds (e.g., 'SENT' flag).
- **🔴 HIGH · interaction** — Mobile/narrow viewport: three-column layout is unusable without horizontal scroll or collapse
  - _Why:_ The aside (accounts/folders) is `hidden lg:flex` (hidden on small screens), but the message list (w-72) and reading pane (flex-1) stack vertically and overflow. User on an iPad or narrow window has to scroll left/right to see accounts, then scroll again to see the message list, then scroll again to see the detail. Composing in a drawer may push the entire viewport off-axis.
  - _Fix:_ On mobile (<lg breakpoint), replace the three-column layout with a modal/tabbed navigation: 1) Show a collapsible header with 'Account: [name]' and 'Folder: [name]' with a menu to switch either. 2) Default to message list, with a 'Message' button in header to expand the detail pane as a full modal. Or use a Drawer (already exists) to show the accounts/folders panel on tap. This re-uses existing components and unblocks mobile.
- **🟠 MED · efficiency** — Compose form does not preserve prefilled data when drawer reopens
  - _Why:_ After selecting a reply suggestion and opening compose, the To/Subject/Body are populated. If the drawer closes, the form state is cleared (signal state is still in memory but drawer remounts). User must pick the same suggestion again to repopulate. This is redundant friction for the hurried responder.
  - _Fix:_ Persist compose state in a signal-based store that survives drawer open/close (already partially done with composeTo/composeSubject/composeBody signals at screen level, but Drawer remount clears visual state). Or, add a 'RESUME DRAFT' button in the reply panel that re-opens the drawer with the last saved values.
- **🟠 MED · navigation** — No search, filter, or sort controls for the message list
  - _Why:_ The message list is ordered by recency (fixture order), with no way to find a message by sender, subject, or date. For a user with hundreds of archived emails, this is a dead-end. The UI shows 7 messages in one folder but no control to zoom into a time range, search, or sort by urgency/sender.
  - _Fix:_ Add a FilterBar above the message list with a search input (type to filter by subject/sender), a dropdown to sort (Date ↓, Urgency, Sender, Unread), and optional date-range picker if time permits. Use existing Input + Select + Button primitives. Filter/sort locally in JS given mock data; Phase 2 moves to backend.
- **🟠 MED · efficiency** — Selected message visually highlights in list, but no keyboard navigation or bulk actions
  - _Why:_ User can click to select a message, but cannot use arrow keys to move up/down the list, nor can they archive/delete/snooze a message in bulk. For a power user on a technical machine, this feels incomplete. Each action requires clicking into the detail pane and finding a button (which doesn't exist yet).
  - _Fix:_ Add keyboard shortcuts: arrow up/down to navigate the list, Delete key to mark as spam/delete, 'a' to archive, 'r' to reply, 'e' to mark read. Show a hint tooltip on first hover of the message list ('Arrow keys to navigate'). For now, these can be no-ops in Phase 1 (mock), but the keybindings should be wired for Phase 2. Consider a small action bar below the message detail (Pin, Archive, Delete, Spam, Snooze) using Button components.
- **🟠 MED · interaction** — Attachment UI is a dead button; no file picker or upload feedback
  - _Why:_ The ATTACH FILE button in the compose drawer exists but has no onClick handler. User expects to click it, pick a file, and see it listed in the compose form. Right now it does nothing, breaking the compose workflow. This is fine for Phase 1 mock, but the missing state is a gap.
  - _Fix:_ Wire a click handler to open a file input (HTMLInputElement type='file', or wrap with an Input uploader component if it exists in ~/ui). Show attached files as a list of Tiles or Readouts below the button, with a trash icon to remove. For mock, just append the filename to a list on click (no actual file picker).
- **⚪ LOW · information** — Suggested replies are generic; no context on why they were chosen or when to use each
  - _Why:_ The panel shows 'ACKNOWLEDGE', 'SCHEDULE CALL', 'DECLINE' but does not explain when each is appropriate or how the AI ranked them. A new user might not know which to pick, or might pick one and immediately have to go back and manually compose if it feels wrong.
  - _Fix:_ Add a small tooltip/hint next to each suggestion button (use Tooltip or a micro-text under the label) explaining its use case ('Best for quick confirmations', 'Propose a meeting', 'Politely refuse'). Or, add a subtle 'relevance' badge (e.g., StatusFlag 'idle' for standard, 'bright' for best match) if ranking is available.
- **⚪ LOW · information** — Signature selector defaults to hardcoded name; no UI to add/manage signatures
  - _Why:_ The compose drawer shows a Signature dropdown with only two choices: 'Francisco Casiano' and 'No signature'. No way to customize, add, or remove signatures. This is mock-only friction, but signals that signature management is not accessible from this screen.
  - _Fix:_ Rephrase the label as 'SIGNATURE' (already done) and add a small link/button (e.g., '⚙ MANAGE') next to it that opens a settings drawer or page to add/edit/delete signatures. Or, if signatures are managed elsewhere in Settings, just show a read-only dropdown. For Phase 1, leave as-is but note the gap.
- **⚪ LOW · information** — No visual distinction between read and unread in the message detail pane
  - _Why:_ In the message list, unread messages are bold/bright ('tone={msg.read ? "dim" : "bright"}'); in the detail pane, the text is always 'default' tone, so the user loses the visual cue that they just marked it read. This is a small information gap, but it breaks the semantic consistency of the design system.
  - _Fix:_ In the MESSAGE panel detail header (below subject), add a small status indicator showing 'UNREAD' / 'READ' using a StatusFlag with tone 'bright' for unread (matches the list visual). Or, when the user clicks to open a message, automatically mark it as read in the mock data and add a subtle flash/highlight to confirm the state change.
- **⚪ LOW · feedback** — Account switching clears message selection but gives no feedback about the new folder
  - _Why:_ When the user clicks a different account in the sidebar, `setSelectedMessageId(null)` fires, the detail pane shows 'NO MESSAGE SELECTED', and the folder resets to the first in that account. This is correct behavior, but on a narrow viewport where the sidebar is hidden, the user has no idea which account/folder they're now viewing without scrolling back to the top (InstrumentBand).
  - _Fix:_ When account changes, show a brief inline notification or flash the account/folder names in the InstrumentBand to confirm the switch. Or, add a sticky sub-header in the message list showing the current account and folder, especially on mobile.
- **⚪ LOW · efficiency** — Compose drawer footer is always visible and takes space; no scrollable body
  - _Why:_ On a short viewport (iPad, half-screen), the compose drawer has a fixed footer (CANCEL / SEND buttons) and a fixed body, but the body doesn't scroll if content overflows. User trying to scroll the form or see the bottom field may be blocked by the footer.
  - _Fix:_ Make the Stack inside the Drawer body scrollable: wrap in a `<div class='overflow-y-auto flex-1 min-h-0'>` so the footer stays fixed and the form scrolls. Or, ensure the Drawer component already supports this behavior and just add `flex flex-col min-h-0` to the inner Stack.


### Calendar  
`/calendar` · tier: user

**Purpose.** User views and manages personal events across multiple synchronized calendars (CalDAV, on-call, personal). Provides month-view grid, quick-add, and event detail/creation modals.

**Personas reviewed.**
- _Busy ops engineer_ — During morning standup, checks calendar for on-call shifts and today's critical meetings. Needs to see at a glance what's urgent, know sync health, and quickly create a blocking meeting.
- _New user exploring features_ — Lands on Calendar for the first time; sees three calendars (Personal/Work/Ops) but doesn't understand what they mean. Clicks SYNC expecting visual feedback. Doesn't know what CalDAV is.
- _Fast event creator (distracted)_ — Wants to add a quick blockers meeting Monday 14:00. Tries the quick-add bar at the top (natural affordance for rapid entry), but typing 'Team sync Monday 14:00' and clicking ADD does nothing visible.

**Works well.** Month grid is clean and scannable; semantic color-coding per calendar (tone system) makes at-a-glance triage instant; PageHeader + InstrumentBand supply high-level context (month, event count, calendar count, sync status) without clutter; Sidebar calendars with dot + text status flag clearly show sync health (e.g., 'Ops / On-call' marked WARN/LOCAL)

**Gaps (11).**

- **🔴 HIGH · missing-state** — SYNC button provides zero feedback
  - _Why:_ User clicks SYNC expecting to see loading state, then success/failure. Instead, nothing happens visibly. Does it work? Is it done? Did it fail? Trust in the feature collapses when action seems to have no effect.
  - _Fix:_ On click, show LoadingText overlay or disable the button + change text to 'SYNCING…'. On completion (mock: instant, real: after fetch), restore button + optionally show a brief success state. Use StatusFlag or tone feedback in the InstrumentBand (e.g., SYNC STATUS changes color transiently).
- **🔴 HIGH · trust-safety** — DELETE event button lacks confirmation guard
  - _Why:_ Destructive action in the modal footer with no confirm dialog. User can hit DELETE accidentally and lose calendar data with no undo affordance.
  - _Fix:_ Add a Modal confirm dialog: 'DELETE EVENT: <title>? This cannot be undone.' with CANCEL / DELETE(danger) buttons. Only trigger the delete on confirmed click.
- **🟠 MED · missing-state** — CREATE event button provides no success/failure feedback
  - _Why:_ User fills the form, clicks CREATE, modal closes silently. Did it save? Is there an error? Did they forget the title? No indication the event was added to the calendar.
  - _Fix:_ On submit, validate (e.g., title required). If invalid, show Field error states or a Toast-like message. On success, show a brief LoadingText or use the modal close + visual feedback (e.g., the new event appears in the grid). Until wired to backend, at least console-log success and visually confirm the event lands on the calendar.
- **🟠 MED · interaction** — Quick-add bar doesn't parse or create events
  - _Why:_ Natural affordance for rapid event entry ('Quick add — e.g. Team sync Monday 14:00'), but clicking ADD does nothing. Text is collected (setQuickAdd state exists) but never used. User expects this to work.
  - _Fix:_ Either implement NLP-style parsing (parse 'Team sync Monday 14:00' → infer start/end, use title) and call the same create handler as the full form, or clearly disable/hide the quick-add bar if it's not ready. If disabled, use a Tooltip: 'QUICK ADD coming soon — use NEW EVENT for now.' Do not collect input without action.
- **🟠 MED · interaction** — EDIT button in modal has no handler
  - _Why:_ Button is visible (leading='edit'), but clicking it does nothing. User expects to edit the event in place or open an edit form.
  - _Fix:_ Open a modal identical to NEW EVENT but pre-populated with the event fields (title, start, end, location, recurrence, calendar). Wire the save to an update handler. Or, if not ready, hide the button and use a Tooltip explaining it's coming.
- **🟠 MED · content** — All-day events render with broken time display
  - _Why:_ The 'On-call Shift' event has allDay: true, but the detail modal shows 'START: 2026-06-09 00:00:00  UTC' and 'END: 2026-06-09 23:59:00  UTC'. For an all-day event, time should not be shown; it confuses the user about whether the event spans the whole day or just a few seconds.
  - _Fix:_ In the modal, conditionally render time fields: `<Show when={!evt().allDay}>` before the START/END Field components. Add a separate line for all-day: `<Show when={evt().allDay}><Field label='ALL DAY' value='YES' /></Show>`. Use a formatter (already available: `date(evt.start)`) that strips time for all-day events.
- **🟠 MED · interaction** — New event CALENDAR dropdown is hardcoded + onChange is noop
  - _Why:_ User opens NEW EVENT modal, sees 'CALENDAR' dropdown pre-set to 'cal-1' (Personal). No way to change which calendar the event is created in. onChange handler is `() => {}` (noop). User creates event in wrong calendar by accident.
  - _Fix:_ Implement the calendar selection: add state `const [newCalendarId, setNewCalendarId] = createSignal(calendars()[0]?.id ?? '')` (default to first available). Wire the Select onChange to setNewCalendarId. Pass newCalendarId to the create handler so the event goes to the right calendar.
- **⚪ LOW · interaction** — Week and Day view tabs are inert
  - _Why:_ Tabs show MONTH / WEEK / DAY options, but clicking WEEK or DAY does nothing. The layout doesn't change. User expects a different view of the same data.
  - _Fix:_ Either implement week/day grids (more work), or hide the tabs and render month-only. If week/day are coming, use a Tooltip on the tabs: 'WEEK and DAY views coming soon.' Do not show non-functional UI.
- **⚪ LOW · interaction** — Overflow '+N MORE' indicator is not clickable
  - _Why:_ When a day has >3 events, '+3 MORE' text appears. But clicking it does nothing—no modal, no expand. User can't see the hidden events without scrolling or opening detail modals one by one.
  - _Fix:_ Make the '+N MORE' text a button that opens a modal listing all events for that day, or allow up to 5-6 visible events and scroll within the cell. Alternatively, add a Day view tab that shows all events for a selected day.
- **⚪ LOW · missing-state** — Missing empty state when no events or calendars exist
  - _Why:_ Screen assumes data always exists (mock is populated). If a fresh user has zero calendars or zero events, the screen renders blank grids + empty sidebars with no guidance on what to do next.
  - _Fix:_ Add conditional EmptyState renders: if no calendars, show 'NO CALENDARS CONNECTED — link or sync one' in the sidebar. If no events for the month, show 'NO EVENTS THIS MONTH' in the grid. Use Suspense to distinguish loading from empty.
- **⚪ LOW · efficiency** — Upcoming sidebar arbitrary caps at 5 items
  - _Why:_ Shows 'next 5 upcoming events' but a busy calendar may have 20+ events in the next month. User scrolls the sidebar to see more, or misses important events lurking just outside the window.
  - _Fix:_ Either: (a) increase to 7-10 items if viewport allows; (b) add a 'SEE ALL' link at the bottom to expand/scroll to all; (c) filter to this week or next 7 days only (more actionable). For now, at minimum add a visual indicator '+ 5 more' if there are more.


### Contacts  
`/contacts` · tier: user

**Purpose.** Browse, search, and manage an address book of contacts synced from CardDAV or stored locally. Users can view contact details (email, phone, organization, notes) and create/edit entries.

**Personas reviewed.**
- _Routine lookup user_ — John searches for a contact by name or email mid-email-draft. He expects instant search, keyboard shortcuts (e.g., Enter to open selected contact, Esc to close drawer), and a quick copy-to-clipboard for an email address or phone number.
- _First-time visitor_ — Priya lands on Contacts for the first time and sees a pre-populated list with 'SYNCED' and 'LOCAL ONLY' status flags. She has no context: where did these contacts come from? Is this an import preview? Can she delete them? Is CardDAV set up? She's disoriented.
- _Sync-recovery user_ — Marcus configured CardDAV and sees 3 contacts stuck as 'LOCAL ONLY'. He clicks the SYNC button expecting feedback (spinner, message), but gets nothing—no visual confirmation the sync started, no error if it failed, no count update when it completes.

**Works well.** Alphabetical grouping and search filter reduce cognitive load; incremental search works predictably.; CARDDAV SYNC and LOCAL/SYNCED status flags clearly distinguish contact provenance; InstrumentBand counts provide quick summary.; Detail drawer uses well-organized panels (emails, phones, notes) with ListRow layout; MAIL button hints at future email composition integration.

**Gaps (11).**

- **🔴 HIGH · feedback** — SYNC button wired but silent
  - _Why:_ Marcus clicks SYNC expecting visible feedback (spinner or LoadingText). The button fires but produces no confirmation, error message, or state update. He doesn't know if the sync started, succeeded, or failed. This breaks trust in a critical operation.
  - _Fix:_ Wire the SYNC button to show LoadingText during sync, then update the SYNCED count and StatusFlags on completion. Include error handling: if sync fails, show an alert or error message. Users need to see that something happened.
- **🔴 HIGH · error-recovery** — Delete contact lacks confirmation
  - _Why:_ Marcus can click DELETE in the detail drawer footer. There is no confirmation dialog (no Modal with 'Are you sure?'). He could accidentally remove a contact, especially if his hand slips. This is a destructive action with no guard.
  - _Fix:_ Show a confirmation Modal before deletion: 'Delete [Name]? This cannot be undone.' Only allow deletion after confirmation. Keep the DELETE button red (danger variant, which is already correct) and the modal text clear.
- **🟠 MED · efficiency** — No keyboard navigation or shortcuts
  - _Why:_ John wants to search, arrow down to a contact, and press Enter to open it. Currently, contacts are click-only. No Esc to close the drawer, no Tab order hint. For a contact-heavy workflow (e.g., drafting multiple emails), this is friction.
  - _Fix:_ Add keyboard support: arrow up/down in the filtered list, Enter to open, Esc to close drawer/modal, Ctrl+C or a button next to each email to copy to clipboard. Wire focus management so Enter opens the selected contact's drawer.
- **🟠 MED · efficiency** — No copy-to-clipboard for email/phone
  - _Why:_ Priya needs to email a contact; she has to manually select and copy the address from the drawer. In the MAIL button on each email line, she expects a copy shortcut or the MAIL button to launch compose (not yet wired).
  - _Fix:_ Add a copy icon or second action button next to each email and phone number in the detail drawer. Clicking it copies the value and shows a transient feedback (e.g., 'COPIED' status briefly). Alternatively, make MAIL launch the email feature pre-populated with that address.
- **🟠 MED · feedback** — Save button in EDIT modal doesn't validate or feedback
  - _Why:_ John fills the form and clicks SAVE. The modal closes, but he has no feedback: did the contact save? Was there a validation error (e.g., invalid email)? If an error occurred, the form disappeared and he has lost his edits.
  - _Fix:_ Validate the form before closing. If validation fails, show an error message inline (e.g., 'INVALID EMAIL FORMAT') instead of closing the modal. If save succeeds, show a brief success feedback (e.g., a toast or status message: 'CONTACT SAVED') before closing. Wire the button to call a save handler (currently it just closes).
- **🟠 MED · information** — No way to handle multiple emails/phones in the form
  - _Why:_ The Contact model supports `emails: string[]` and `phones: string[]` (e.g., Alex has two emails). The edit form only offers PRIMARY EMAIL and PRIMARY PHONE—single inputs. Users cannot add a second email or phone without editing the data directly.
  - _Fix:_ Add repeatable field rows for emails and phones (e.g., 'EMAIL 1', 'EMAIL 2', 'EMAIL 3 (optional)' with an 'ADD EMAIL' button). This aligns with the data model and gives users full control. Use a simple list with remove-button per item.
- **🟠 MED · trust-safety** — CardDAV status unclear for first-time users
  - _Why:_ Priya sees 'SYNCED' and 'LOCAL ONLY' labels. She doesn't know what CardDAV is, how to enable it, or why some contacts are not synced. The CARDDAV SYNC field in the detail drawer only shows a status flag—no link to settings or explanation.
  - _Fix:_ In the detail drawer, next to 'CARDDAV SYNC: SYNCED', add a small (?) tooltip or link icon that explains: 'Synced from your CardDAV server. <Configure>' (link to settings). In the page subtitle or as a banner, if any contacts are LOCAL ONLY, add: 'Some contacts are local. <Configure CardDAV> to sync all.'
- **🟠 MED · error-recovery** — No error state if contact fetch fails
  - _Why:_ The Suspense boundary shows LoadingText while fetching contacts. If the fetch fails, Suspense has no fallback for the error case. Users see a spinner forever or a blank screen.
  - _Fix:_ Wrap the contact list in a Show that checks for errors (createResource can return an error state). If the fetch fails, show an EmptyState with an error icon and message like 'FAILED TO LOAD CONTACTS' with a RETRY button that re-runs the fetch.
- **⚪ LOW · onboarding** — EDIT button for new contact doesn't hint at first run
  - _Why:_ Priya sees the NEW CONTACT button but the form (modal) gives no context: is this creating a local-only contact, or does it sync to CardDAV? Should she fill all fields? The field labels are terse ('PRIMARY EMAIL', 'PRIMARY PHONE'), and there's no hint text beyond the placeholder.
  - _Fix:_ In the NEW CONTACT modal, add a subtitle or hint like 'Creates a local contact. Enable CardDAV to sync.' If CardDAV is not configured, show an info banner above the form. For fields, ensure placeholders are clear (they are) and add optional field hints if some fields are not required.
- **⚪ LOW · information** — Search doesn't highlight or show result count clearly
  - _Why:_ John searches for 'elena' and the list updates. The InstrumentBand shows 'SHOWING: 1' but doesn't visually highlight the matched contact or the search term within the results. He has to scan the list to confirm the match.
  - _Fix:_ Highlight the search term in contact names/orgs/emails (e.g., bold or a subtle background color). This is already done partially by the filtered list; consider adding a visual marker (e.g., a highlight bar or accent tone) to the matched row so John can immediately see the result.
- **⚪ LOW · efficiency** — No bulk actions (select multiple, delete, sync, export)
  - _Why:_ If Marcus has 20 local-only contacts and wants to force-sync them all or delete duplicates, he must click each one individually. No bulk selection, no batch operations.
  - _Fix:_ Add checkboxes to ListRows (optional, Phase 2). Show 'SELECT ALL' / 'DESELECT' buttons and bulk actions (SYNC, DELETE, EXPORT) when rows are selected. For now, leave this as a future note unless bulk operations are a stated priority.


### Notes  
`/notes` · tier: open

**Purpose.** A single-user personal notes hub with labeling, pinning, due dates, and checklist tracking. Users quickly capture, organize, and track progress on reminders, project notes, and task lists across labeled categories.

**Personas reviewed.**
- _Power User (Ops/Tech Owner) — Panchi_ — Maintains multiple notes across engineering, ops, and personal labels. Regularly updates checklist progress (e.g., Pydantic AI migration tasks), sets due dates for cost reviews, and pins urgent reminders. Needs to find and modify notes quickly, delete stale ones, and trust that edits stick.
- _Hurried User (End of Sprint)_ — Quickly captures 3-4 scattered thoughts under 'ideas' label, then needs to come back and clean up/delete duplicates or half-finished captures. Opens notes sporadically, expects to see what changed since last visit, and wants to discard notes without friction.
- _New User (First Visit to Notes)_ — Lands on the page, sees 6 pre-seeded notes, doesn't know if they can edit/delete them or if the CHECKLIST actions work. Tries to delete one, can't find the button. Tries to tag a note differently without opening the full edit modal. Gets confused about what's editable where.

**Works well.** Clean, scannable card layout with pinned/other sections clearly separated by visual hierarchy; Rich metadata on-card (due date, checklist progress bar, update timestamp, label + tone) so users see context at a glance without opening modals; Mock data is realistic and diverse (multiline bodies, various labels, mixed checklist/due-date scenarios), showing system depth

**Gaps (10).**

- **🔴 HIGH · missing-state** — No delete action on notes
  - _Why:_ Users will accumulate stale, incorrect, or duplicate notes and need to discard them. Without a delete button/action, notes are permanent and the list becomes cluttered. Especially critical for the hurried user cleaning up old captures.
  - _Fix:_ Add a third icon button to each NoteCard (alongside edit and pin) with a trash/delete icon. On click, show a `Modal` with a confirmation message ('Delete this note? This cannot be undone.') with CANCEL and DELETE buttons. Use `alert` tone on the delete button to signal destructiveness.
- **🔴 HIGH · interaction** — Checklist items can't be edited or deleted individually
  - _Why:_ The edit modal shows checklist as one textarea (one item per line). Users can't delete a single item without retyping the whole list, and there's no UI affordance for item-level edits. A user wanting to keep items 1, 3, 5 and delete 2, 4 must manually rebuild the list.
  - _Fix:_ In the edit modal, replace the checklist textarea with a repeating `Input` component (one per item) with a small delete icon button next to each. This matches the on-card checkbox interaction and makes edits granular. Show an 'Add item' button to append new lines.
- **🟠 MED · information** — Reminder date/time is set but never shown or editable from the card
  - _Why:_ The Note model has `reminderAt`, and the card shows a REMINDER flag, but there's no way to see when the reminder fires or change it without backend integration. Users can't self-serve manage reminder timing.
  - _Fix:_ Add a `datetime-local` input in the edit modal labeled 'REMINDER' (alongside DUE DATE). On the card, show the reminder time (if set) as a second timestamp row, or fold it into the existing metadata row with a 'REMINDER: date' display using `warn` tone.
- **🟠 MED · navigation** — No search or sort within a label filter
  - _Why:_ With many notes in one label, scanning visually for a specific note is slow. There's no way to search by title/body text or sort by due date/recency. A user with 20 engineering notes searching for 'Pydantic' must read every card.
  - _Fix:_ Add a search `Input` above the tab bar or within each tab panel with a `leading='search'` icon. Filter the visible notes by title/body text. Optionally add a small sort menu (by updated, due date, alphabetical) anchored near the tab bar.
- **🟠 MED · feedback** — No confirmation feedback when saving a note
  - _Why:_ Clicking SAVE closes the modal instantly (in mock mode). The user has no confirmation that their note was saved, especially when editing — they can't tell if they overwrote the old note or created a duplicate.
  - _Fix:_ Show a brief `StatusFlag` or toast-like message ('NOTE SAVED') that appears below the modal footer or as an inline confirmation in the main list after the modal closes. Alternatively, briefly highlight the updated card in the list to draw the eye.
- **⚪ LOW · error-recovery** — Editing doesn't show unsaved-changes warning if cancelled
  - _Why:_ If a user types into the form and then clicks CANCEL, all edits silently vanish. For a single-user workspace, this is low risk, but it can be surprising and costly if the user had made substantial edits.
  - _Fix:_ Track form changes with `dirty()` signal. If the user clicks CANCEL and there are unsaved changes, show a confirmation Modal ('Discard changes?') with KEEP EDITING / DISCARD buttons.
- **⚪ LOW · efficiency** — No way to re-tag a note without opening the full edit modal
  - _Why:_ Changing a note's label or tone requires opening the modal, finding the label field, editing, and saving. For a frequent operation (re-organizing notes across categories), this is repetitive friction.
  - _Fix:_ Add a small 'label' or 'tag' menu button on the NoteCard (or make the label flag itself clickable) to quickly change the label/tone. A small `Menu` or `Drawer` with the label options is faster than the full edit modal.
- **⚪ LOW · navigation** — Checklists with >4 items can't be fully viewed or edited on-card
  - _Why:_ The card shows only 4 checklist items, then '+X MORE'. There's no way to see/toggle the rest without opening the edit modal. Users with long checklists can't interact with items beyond the first 4.
  - _Fix:_ Add a collapsible 'Show all items' toggle or expand affordance on the card (e.g., a small '▼' icon next to the count). When expanded, show all checklist items in a scrollable area within the card. Or, make the '+X MORE' text clickable to open an expanded checklist view.
- **⚪ LOW · information** — Due date display is date-only, hides time component
  - _Why:_ The form accepts a full `datetime-local` input, but the card only shows the date via the `date()` formatter. If a user sets a due date with a specific time (e.g., 2pm), the time is invisible on the card.
  - _Fix:_ Check if `dueAt` includes a non-midnight time; if so, display it as 'DUE Jun 15 @ 2:00 PM' using the `relativeTime()` format or a custom formatter. This shows the user's full intent on the card.
- **⚪ LOW · accessibility** — Form doesn't guide users on what makes a valid checklist
  - _Why:_ The 'CHECKLIST ITEMS' field says '(one per line)' but doesn't show an example or validate empty lines. A new user might paste in a block of text with blank lines and be confused by the result.
  - _Fix:_ Add a `hint` or helper text below the textarea: 'e.g., Buy groceries\nFix sidebar layout\nReview PR'. Optionally, when editing, trim/filter blank lines silently so the user doesn't see unexpected empty items on-card.


### Tasks  
`/tasks` · tier: open

**Purpose.** Monitor and manage scheduled automations (cron, recurring, webhooks, one-time jobs) across the workspace, see their status and run history, and create/edit tasks to deliver outputs to chat, notifications, or email.

**Personas reviewed.**
- _Automation Owner (Routine Tuner)_ — Francisco checks the Tasks page daily to confirm background automations are firing on schedule, spot recent errors, and make quick edits to task names, schedules, or delivery targets. He's tuning the system.
- _Firefighter (Error Recovery)_ — At 3am, an automation fails and alerts. Francisco wakes up, opens Tasks to understand why the weekly cost report didn't send, needs to retry it, and maybe disable it until he fixes the root cause. He's under pressure and needs clarity fast.
- _Distracted Browser (Low Context)_ — Between meetings, Francisco wants to find that webhook task he created last week. He's not sure if it's enabled or paused, doesn't fully remember what it does, and might accidentally toggle the wrong task while scanning.

**Works well.** InstrumentBand summary makes task health visible at a glance (enabled/disabled/webhook counts + total run history).; Expandable detail rows reveal rich context (description, full timestamps, detailed run history with status + duration + output) without leaving the page.; Run history shows semantic status (ok/error/running) with appropriate color coding, duration, and output snippet—enough for quick diagnosis of failures.

**Gaps (9).**

- **🔴 HIGH · error-recovery** — No toggle confirmation; risk of accidental enable/disable
  - _Why:_ The toggle has zero friction—one errant click while distracted (e.g., scrolling on mobile, between meetings) disables a critical task like the daily briefing or cost report, and the user won't know until the next scheduled run. The change is instant with no undo, no warning, and no confirmation. For the Firefighter persona reacting to failures at 3am, this is especially risky.
  - _Fix:_ Wrap the toggle in a confirmation dialog for tasks with recent successful runs (e.g., status='ok' in the last 24h). Pattern: show a small Modal with task name + current status + "Disable this task?" + [Cancel] [Disable] buttons. Keep the toggle visual itself unchanged; only the state change requires confirmation. For tasks already disabled or never run, no confirm needed.
- **🔴 HIGH · interaction** — No way to retry a failed task; run history is read-only
  - _Why:_ The Firefighter persona lands on the Tasks screen because a task failed and needs to retry. But there's no Retry button or action—only the ability to view the failure. They must wait for the next scheduled run or manually trigger it elsewhere (if such an interface exists at all). This blocks the core error-recovery workflow.
  - _Fix:_ Add a Retry button to the ListRow of each failed run (icon: 'refresh', size: 'sm', variant: 'ghost'). Clicking Retry immediately re-runs that task and displays a flash confirmation ('Retried: xyz'). For now, this is in-memory state; in Phase 2, it calls the backend. Position the button in the run history ListRow's right side, near the status flag.
- **🔴 HIGH · information** — Failure reason buried in truncated output snippet; full output not accessible
  - _Why:_ The Firefighter sees 'LLM provider timeout after 1200ms. Retry limit exceeded.' in the ListRow, but it's truncated to 60 chars. Many errors are longer (e.g., 'Scanned 4214 docs. Archived 7 duplicates (< 0.12 threshold). WARNING: similarity score variance high; review threshold.' — that's 130+ chars). They can't click to expand the output in-line; they're stuck guessing what went wrong.
  - _Fix:_ Add a click handler to each ListRow in the run history (or a small 'expand' icon) that opens a Modal showing the full output + metadata (ranAt, durationMs, status, taskName). Keep the ListRow as-is for compact scanning, but make the output expandable. Alternatively, show output as a hoverable Tooltip on the output text (up to ~200 chars visible in the tooltip).
- **🟠 MED · information** — Run history truncated to 6 items with no way to see older runs
  - _Why:_ A task might have weeks of run history, but only the last 6 runs are shown in the expanded panel. If a user wants to check if a failure is isolated or recurring, they can't scroll through the history—they hit a wall. Also, the page says 'RUN HISTORY' without indicating that more runs exist beyond the 6 shown.
  - _Fix:_ Replace the hardcoded `.slice(0, 6)` with a Show/Suspense block: show 6 runs by default, then add a 'SHOW MORE' button (variant='ghost', size='sm') below them that expands to show the next batch. Or: add a small 'MORE' indicator like '+ 12 more runs' next to the RUN HISTORY label if there are >6. Phase 2 can paginate; Phase 1 can just expand all-in-memory.
- **🟠 MED · information** — No indication of why a task is disabled or when it was disabled
  - _Why:_ The Distracted Browser sees a disabled task (e.g., 'GitHub PR nag' is disabled in the mock data) with a dim StatusFlag. But they don't know if Francisco disabled it 2 hours ago (deep-work mode) or 3 weeks ago (he forgot). This matters for deciding whether to re-enable it. A field like 'disabled at' would clarify intent.
  - _Fix:_ In the expanded detail panel, add a Field for disabled tasks only: 'DISABLED' (label) + timestamp when it was disabled, or if that's not in the data model, a static hint like 'Manually disabled' (tone='dim'). If the field doesn't exist in the data model, defer to Phase 2, but note in the code a TODO comment.
- **🟠 MED · error-recovery** — Form has no validation; users can save a task with blank name, schedule, or invalid expressions
  - _Why:_ In the New/Edit modal, all fields are optional from the UI's perspective. You can save a task with no name (it becomes 'UNNAMED TASK') or no schedule (cron expression, recurring interval, or webhook path can be empty). When the task runs, the backend will fail silently or throw a cryptic error. The Automation Owner or Firefighter won't understand what went wrong.
  - _Fix:_ Mark TASK NAME and SCHEDULE as required (add a red asterisk or 'required' hint to the Input/Select labels). On save, validate: name.length > 0, schedule.length > 0, and if trigger='cron', do a lightweight check (e.g., regex match for basic cron shape like '^[0-9\*\-\,\/\s]+$' to catch obvious typos). Show inline errors below the field (tone='alert'). Prevent submit if validation fails. Alternatively, show a summary on the modal footer: 'SAVE' button only enables if name + schedule are non-empty.
- **⚪ LOW · efficiency** — No delete action; tasks accumulate forever
  - _Why:_ There's no way to delete a task from the UI. If a user creates a one-off task that runs successfully and is no longer needed, they can't remove it—it clutters the list. They can only disable it. In a list of 50+ automations, this becomes noise.
  - _Fix:_ Add a delete button to the task row (icon='trash', size='sm', variant='ghost', tone='warn') or in the expanded detail panel. Clicking should show a confirmation Modal: 'Delete task "{name}"? This cannot be undone.' + [Cancel] [Delete] (delete button tone='alert'). On confirm, remove from the store. Uses the existing ForbiddenView/destructive action pattern already in the design system.
- **⚪ LOW · onboarding** — Empty state messaging doesn't guide first-time setup
  - _Why:_ When tasks.length === 0, the EmptyState says 'NO TASKS' with hint 'No scheduled tasks configured.' and a 'CREATE TASK' button. But a first-timer won't know what kinds of tasks are possible, what delivery targets do, or how to write a cron expression. They need a nudge toward examples or docs.
  - _Fix:_ Enhance the EmptyState with a secondary text block or link: 'Create tasks to automate briefings, reports, monitoring, or CI notifications. Examples: daily briefing at 8am → chat, weekly cost report → email, deploy webhook → notification.' and keep the CREATE TASK button. Or: add a small '?' icon next to the title that links to a help doc or tooltip explaining task types.
- **⚪ LOW · information** — No status indicator for currently running tasks; 'running' status exists in model but not shown
  - _Why:_ The TaskRun model includes status='running', but the mocks have no running examples. In Phase 2, if a long-running task (e.g., memory dedup taking 30+ seconds) is in progress, the UI will show no visual indicator that it's actively executing. The user might think it's stalled or try to re-trigger it.
  - _Fix:_ In the run history ListRow, when status='running', show a LoadingText-style indicator (e.g., a spinning icon or the text 'RUNNING…' in tone='info') instead of a static StatusFlag. Or use a StatusFlag with status='info' and a pulsing dot (CSS animation). This signals to the Firefighter that the task is actively executing and they should wait before retrying.


### Cookbook  
`/models/cookbook` · tier: admin

**Purpose.** Admin control center for downloading local LLM models, spinning up local inference servers, and configuring remote API endpoints. Displays hardware suitability analysis to help the user choose appropriately-sized models for their machine.

**Personas reviewed.**
- _Marcus, the hurried power-user_ — Marcus works with 8+ models simultaneously and frequently starts/stops servers as he context-switches projects. He's trying to stop a running server because he's moving to another task, but he accidentally clicks STOP on the wrong row — no confirmation modal, so it instantly shuts down. He loses a live session and has to restart.
- _Alex, the first-time setup user_ — Alex just installed Odysseus and opens Cookbook to download models. They see Qwen 2.5 (green NOMINAL) and Llama 3.3 (yellow WARN) side by side. They don't know: (a) what the color difference means in practical terms, (b) whether they can run both simultaneously, (c) why one is warned and the other isn't, or (d) whether clicking GET will automatically configure a server. No hints, no tooltips, no guidance — they guess and potentially download a model that doesn't fit their workflow.
- _Jordan, the remote-endpoint manager_ — Jordan uses Anthropic API as their primary model source and sees it listed with 'NO KEY' (yellow). They expect to click into the row, find an edit button, and paste their API key. Instead, there's no interaction available — the row is read-only. They don't know if they need to navigate to Settings, or if the UI is incomplete, so they waste 10 minutes searching.

**Works well.** Clean, instant visual feedback on hardware fit (suitability flags in semantic color).; Real-time server status (running/stopped/starting) with live throughput metrics (T/S) is clear and actionable.; Download progress bar shows real-time percentage, no spinners — stays true to the terminal-HUD aesthetic.

**Gaps (9).**

- **🔴 HIGH · trust-safety** — Destructive server stop has no confirmation guard
  - _Why:_ Clicking STOP on a running server is instant and irreversible in the UI (though not in reality, restart is one click). A hurried user or accidental mis-click instantly terminates a live inference session. In a real app, this could drop live chat/research/tool calls mid-execution.
  - _Fix:_ Add a Modal confirm before stopping: 'Stop server QWEN2.5-32B-Q4 on :11434? This will disconnect active sessions.' Only show if status === 'running'. Use the existing Modal primitive with a destructive action button (variant='danger').
- **🟠 MED · interaction** — No way to cancel or pause a model download in progress
  - _Why:_ User starts downloading a 20GB model by mistake (hits GET), realizes seconds later it's the wrong one, but there's no cancel button. They must wait for it to finish or hard-stop Ollama externally. Creates frustration and wastes bandwidth.
  - _Fix:_ When progress() !== null && !done(), replace the GET button with a CANCEL button (variant='ghost', icon='x'). Wire it to reset progress/done state and send a cancel signal to the backend (Phase 2).
- **🟠 MED · content** — Suitability status (NOMINAL/WARN/ALERT) unexplained to first-time users
  - _Why:_ A user seeing WARN or ALERT on a 70B model has no context for the decision: Does WARN mean 'don't download it' or 'it will be slow'? Is ALERT an error or a caution? No tooltips or hints — Alex (persona 2) either guesses wrong or leaves the page to search docs.
  - _Fix:_ Wrap each StatusFlag in a Tooltip (or add a help icon next to the suitability label in the panel). Content: 'NOMINAL: fits comfortably in your VRAM. WARN: fits but with little headroom; inference may be slower. ALERT: exceeds VRAM; not recommended without external swap.' Reuse across the page.
- **🟠 MED · interaction** — Remote endpoints are read-only; no way to edit, add, or test
  - _Why:_ Jordan (persona 3) sees 'Anthropic API' with 'NO KEY' but the row is inert — no edit button, no menu, no way to add or configure it. The panel header says 'REMOTE ENDPOINTS' but offers no 'ADD' button. User doesn't know if they should navigate elsewhere or if the feature is incomplete.
  - _Fix:_ Add an 'ADD ENDPOINT' button in the panel header (right side, next to meta text, or as a floating action). Each remote endpoint row should have a trailing menu (⋮ icon, Menu primitive) with 'Edit', 'Test', 'Remove' options. Edit opens a Drawer with name, URL, API key fields. 'Test' triggers a health check and updates the status flag.
- **🟠 MED · onboarding** — Download action provides no next-step guidance
  - _Why:_ User clicks GET on a model; it downloads; they see READY flag. But what happens next? Should they manually create a server, or is there an auto-start option? No hint, no success toast, no indication of next action. In Phase 2 with real downloads (20GB, 1+ hour), this becomes a trust gap — did it actually work?
  - _Fix:_ After download completes (done() === true), show a brief success confirmation next to READY: 'Model ready' or add a secondary button 'START SERVER'. Alternatively, add a Toast component (future primitive) with 'Qwen 2.5 downloaded. Create a server to run it.' This bridges the download→server workflow.
- **🟠 MED · error-recovery** — No error state for failed operations (download, server start, endpoint health check)
  - _Why:_ In Phase 2, downloads can fail (network), servers can fail to start (OOM), endpoints can timeout. Current UI shows no error state—users won't know what went wrong or how to retry. Stops all workflows.
  - _Fix:_ Extend the state machine: add error signals to DownloadRow (progress = 'error', show an alert badge + retry button) and ServerRow (status = 'error', show red alert flag + 'RETRY' button). For remote endpoints, update status to 'error' and add a red Alert icon. Always show a recoverable action (retry, edit, delete).
- **⚪ LOW · navigation** — Model list has no search, filter, or secondary sort
  - _Why:_ Current mock shows 6 models. In production, this could grow to 50+. Marcus (persona 1) looking for a specific model by name has no search. The header says 'SORTED BY FIT' but there's no way to re-sort by name, size, or date. For a long list, this is friction.
  - _Fix:_ Add a search field above the model list (Input component with placeholder 'Filter by name…'). Filter models as the user types. Consider adding a secondary sort option in the meta text: 'SORTED BY FIT [↕ Size]' (icon to toggle), but keep it simple for Phase 1.
- **⚪ LOW · information** — Server performance context incomplete without context length
  - _Why:_ Server row shows '82.4 T/S' (tokens per second) but no context. Is that good? Is it for a 4K context or 128K? The data model has contextLen, but it's not displayed. User can't compare performance across models without this context.
  - _Fix:_ Include contextLen in the server row metadata: '82.4 T/S @ 32K ctx' (if contextLen exists). If not yet configured, show a placeholder or omit it. This gives Marcus enough info to decide which server to use for a task.
- **⚪ LOW · missing-state** — Hardcoded models in ServerRow instead of fetched list
  - _Why:_ Line 168–183 hardcodes two servers in component state instead of fetching them. Out of phase with the feature's data layer (models, hardware, endpoints are fetched). In Phase 2, this becomes a source of truth problem — which server list is canonical?
  - _Fix:_ Replace the hardcoded state with useRunningServers() (the hook exists in data.ts but isn't called). Fetch from the data layer, render with the same Suspense/Show/For pattern as models. Allows Phase 2 to wire real server state without changing the screen.


### Embedding  
`/models/embedding` · tier: admin

**Purpose.** Admin surface for inspecting and configuring vector embedding model for the RAG/memory subsystem. Displays index statistics and allows swapping to alternative models with destructive confirmation.

**Personas reviewed.**
- _Admin tuning search quality_ — Wants to compare embedding models (dimensions, size, provider) before swapping and needs visibility into re-index duration/status to decide when to execute the swap.
- _Non-technical household member_ — Accidentally lands on page via sidebar, doesn't understand embeddings/indexing, confused by warnings and model options, wants to leave without breaking something.
- _Admin in error recovery_ — Initiated a model swap 20 minutes ago; nothing visible changed. Unsure if the re-index is in progress, failed, or stuck. Needs to understand current state and decide to retry/cancel.

**Works well.** Confirmation dialog clearly warns of destructive impact (full re-index required, retrieval degraded during reindex); Active model visually distinguished (ACTIVE badge), clear section layout (active vs available models); Status indicators present: reindex warning in header, provider badges, dimension specs on each model

**Gaps (8).**

- **🔴 HIGH · information** — No estimated re-index duration or cost visibility
  - _Why:_ The confirmation dialog warns that re-index is destructive and retrieval will degrade, but doesn't say HOW LONG it will take. An admin tuning embeddings (persona 1) can't make an informed decision about timing (e.g., 'is 2 min of degradation acceptable, or 2 hours?'). The mock stats include `throughputDocsSec` (80 docs/s) and `indexedDocs` (4,214), which allows calculating ETA, but this isn't shown to the user.
  - _Fix:_ In the confirmation dialog, add an `<Readout>` row showing 'ESTIMATED REINDEX TIME' calculated as `indexedDocs / throughputDocsSec` (formatted e.g. '~53 seconds'). This gives context for the severity of the action.
- **🔴 HIGH · missing-state** — No visibility into active re-index operation
  - _Why:_ Persona 3 (admin in error recovery) clicked 'CONFIRM SWAP' 20 minutes ago but sees no progress indicator, ETA, or 'cancel' button. They can't tell if the re-index is in progress, stuck, or complete. The page only shows the NEW active model (because state changed), but doesn't reflect mid-operation state. This is currently a mock-only limitation, but leaving it unaddressed means the real feature will ship blind.
  - _Fix:_ When a re-index is in progress, show a progress view: replace the 'SET ACTIVE' button with a cancelable 'REINDEXING…' state (use existing `ProgressBar` + 'CANCEL' button), and update InstrumentBand to show 'REINDEX IN PROGRESS' with a live doc count or ETA. The IndexStats model should include an `isReindexing: boolean` and optional `reindexProgress: { docsProcessed, estimatedTimeRemaining }` to support this (Phase 2).
- **🟠 MED · onboarding** — No explanation or help text for first-time visitors
  - _Why:_ Persona 2 (non-technical household member) lands here confused: doesn't know what embeddings are, why there are multiple models, or what the warning means. The page assumes domain knowledge. No 'Learn more' link, no inline explanation of the purpose of this surface.
  - _Fix:_ Add a one-line clarification below the PageHeader subtitle or in a small help icon/tooltip: e.g., 'Vector embeddings power semantic search and memory retrieval. The active model determines search quality and speed.' Also consider a 'Learn' link in the subtitle that could open a doc/help modal (Phase 2).
- **🟠 MED · error-recovery** — Confirmation dialog doesn't name the swap target
  - _Why:_ The dialog says 'Swapping the active embedding model requires a full re-index...' but doesn't name which model you're swapping TO. If an admin is comparing models and clicks multiple 'SET ACTIVE' buttons quickly, the dialog might not clearly remind them which model is about to be activated. Cognitive load on a destructive action.
  - _Fix:_ Update the confirmation text: 'Swap from **[current model name]** to **[pending model name]**?' e.g., 'Swap from all-MiniLM-L6-v2 to BGE Large EN v1.5? This requires re-indexing all 4,214 documents.' This makes the action explicit and unambiguous.
- **🟠 MED · information** — No indication of which models are available vs installed locally
  - _Why:_ The list shows 5 models, 3 local (with sizes) and 2 remote. Remote models lack size fields, and the description says 'OpenAI remote — requires API key' but there's no visual indicator of 'not installed' or 'requires setup'. An admin might try to activate a remote model without realizing it needs to be configured first.
  - _Fix:_ Add a small status icon or text next to remote models: e.g., a 'INFO' StatusFlag or lock icon + text 'Requires API key configuration' (like the local models get a 'local' badge). Alternatively, disable the 'SET ACTIVE' button for remote models that aren't configured, with a tooltip: 'Configure API key in Settings first' (Phase 2).
- **🟠 MED · missing-state** — No empty state handling if models list fails to load
  - _Why:_ The 'AVAILABLE MODELS' panel has `<Suspense fallback={<LoadingText/>}>` and `<Show when={(models() ?? []).length} fallback={<EmptyState/>}>`, which handles empty successfully. However, there's no error state: if the fetch fails (Phase 2, when backend is live), users see LoadingText or EmptyState indefinitely. A failure is indistinguishable from no models available.
  - _Fix:_ Use a resource's `error` property to render a distinct error view. Example: add an error signal to useEmbeddingModels() and in the screen, render a Panel with 'FAILED TO LOAD MODELS' + a 'RETRY' button if models() is a failed resource. (Phase 2: wire the actual API error boundary.)
- **⚪ LOW · interaction** — No way to cancel a confirmation dialog by pressing Escape
  - _Why:_ The confirmation panel can be dismissed by clicking the 'CANCEL' button or outside the panel (if it's a modal), but there's no visible indication that Escape works. For power users used to modal UX, this is expected and not blocking, but for persona 2 (first-timer), it's an unknown escape hatch.
  - _Fix:_ Ensure the Modal/Drawer component wrapping the Panel traps Escape and calls the dismiss handler. If not already done, add a visual hint in the button area: e.g., '⎋ CANCEL' or a small subtitle 'Press ESC to cancel'.
- **⚪ LOW · efficiency** — Active model panel duplicates info already in the list
  - _Why:_ The left 'ACTIVE MODEL' panel shows name, dims, provider, size, description — all the same fields the list row shows for the active model on the right. On a 1024px wide screen (tablet), this side-by-side duplication wastes horizontal real estate and forces two reads of the same data.
  - _Fix:_ On mobile/tablet (lg breakpoint), consider collapsing the 'ACTIVE MODEL' panel to just a 'STATUS' badge or moving it into the list as a header row. Alternatively, populate the left panel with *different* info (e.g., performance metrics, reindex history, model comparisons) that adds value. For now, the duplication is acceptable given the grid layout, but flag it for Phase 2.


### MCP  
`/mcp` · tier: admin

**Purpose.** Allow the admin to register MCP (Model Context Protocol) servers and selectively enable/disable tools that get exposed to the agent. MCP servers provide capabilities like memory, RAG, email, calendar, and integrations.

**Personas reviewed.**
- _The Operator (technical admin, setup-focused)_ — Just registered a new MCP server via the modal. The server appears in the list with DISCONNECTED status. No feedback on whether it's trying to connect, whether connection is automatic or manual, or what to do next. Feels like the action succeeded but nothing happened.
- _The Troubleshooter (under pressure, scanning for failures)_ — Notices 'Image Generation' in ERROR status. Expands to see tools, but there's no error message, no timestamp, no way to see logs or retry. The HTTP URL is displayed but provides no context for WHY it failed or HOW to fix it.
- _The Newcomer (first-time user, non-MCP-fluent)_ — Lands on this page during onboarding. Sees terminology (STDIO, HTTP, tools, transport) with no explanation. The subtitle mentions 'Model Context Protocol' and 'tool management' but doesn't explain WHAT MCP is, WHY they should care, or WHETHER they need to do anything now. Empty of guardrails.

**Works well.** Clean card-based layout with clear visual hierarchy (status flags + tool counts) makes scanning the list intuitive.; Toggle-per-tool UI is precise and low-friction for enabling/disabling capabilities.; Modal uses sensible validation (REGISTER button disabled until name provided) and separates stdio vs HTTP inputs.

**Gaps (8).**

- **🔴 HIGH · feedback** — No feedback or next steps after registration
  - _Why:_ When a user registers a new server, it appears instantly with DISCONNECTED status, but there's no indication of whether the system is trying to connect, whether connection is automatic or requires manual action, or what to do next. The user completes an action but has no idea if it succeeded or what's happening. This is particularly dangerous for custom servers (like the HTTP example) where user intervention may be required.
  - _Fix:_ After successful registration, show a transient success toast or inline confirmation (e.g., 'Server registered. Attempting connection…'). For servers in DISCONNECTED state, add a contextual hint or 'RETRY CONNECTION' button in the card meta. If a server fails to connect after registration, escalate to an alert or error flag immediately visible.
- **🔴 HIGH · error-recovery** — Error status provides no diagnostic information
  - _Why:_ The ERROR status flag tells the user something is wrong but gives no actionable insight: no error message, no timestamp, no logs, no retry button. The user cannot distinguish between a network timeout, invalid credentials, bad config, or a crashed server. This blocks troubleshooting and erodes trust.
  - _Fix:_ On error status, show a Tooltip (on hover) with the last error message and timestamp. Add a 'RETRY' or 'VIEW LOGS' button to the card meta. If the backend tracks error details, surface them inline in the expanded view (e.g., as a secondary panel or red-toned text block with the error reason).
- **🔴 HIGH · missing-state** — No authentication management UI for auth-required servers
  - _Why:_ The AUTH flag indicates some servers need credentials, but there is no UI to provide or update them. The modal text says 'Provide credentials after registration via the server detail panel,' but there is no detail panel and no way to edit credentials. This is a dead end for anyone registering an auth-required server (like Email/Calendar).
  - _Fix:_ For servers with authRequired=true, add a 'CONFIGURE AUTH' button in the card meta (or in the expanded tools list). Clicking it opens a drawer/modal with fields for the specific auth method (API key, username/password, OAuth), persisting encrypted credentials. Alternatively, show the auth fields inline in the expanded view with a 'no credentials provided' placeholder state.
- **🟠 MED · information** — Empty server (zero tools) state is ambiguous
  - _Why:_ The 'Custom Remote Server' in the mocks has tools: [], so clicking 'TOOLS' expands to show nothing. A user might think the server is broken, the tools list isn't loading, or they need to do something to populate it. Without context, an empty tools list is confusing.
  - _Fix:_ When a server has zero tools, either (1) show an inline message in the expanded view ('No tools loaded' or 'Attempting to load tools…'), or (2) disable the TOOLS expand button and replace it with 'NO TOOLS' text in a dim tone. If tools should load on-demand, use LoadingText or a 'LOAD TOOLS' button.
- **🟠 MED · onboarding** — No guidance for new users on what MCP is or why they're here
  - _Why:_ The page subtitle mentions 'Model Context Protocol' and 'tool management' but assumes the reader knows what MCP is and why they should care. A new user landing here has no context, no 'getting started' hint, and no sense of whether they need to do anything now or if this page is just for power users.
  - _Fix:_ Add a one-line explainer in the PageHeader subtitle: 'MCP servers provide specialized tools (like memory, calendar, image generation) to the agent. Register a server to enable its tools.' Optionally, add a small info icon (ⓘ) next to the title that tooltips the concept. For empty state, expand the hint text to set expectations: 'No servers registered yet. MCP servers are optional—register one to unlock additional capabilities.'
- **🟠 MED · efficiency** — No bulk actions or server deletion
  - _Why:_ Users can register servers but cannot delete or disable them (only disable individual tools). For testing, cleanup, or removing broken servers, the user is stuck. There's no way to bulk disable/enable tools across servers either.
  - _Fix:_ Add a 'DELETE' button to the card meta (or a three-dot menu with Delete/Reconnect options). Protect deletion with a confirm modal ('Disabling this server will remove all its tools from the agent—continue?'). Optionally add bulk actions (select multiple servers, disable all tools at once) if common.
- **⚪ LOW · information** — Transport type (STDIO vs HTTP) is shown but not clearly explained
  - _Why:_ The card displays 'TRANSPORT: STDIO' or 'TRANSPORT: HTTP' but doesn't explain what this means or why a user should care about the difference. Combined with the registration modal's 'COMMAND (stdio)' and 'URL (http transport)' fields, it's clear they're mutually exclusive, but the why is missing.
  - _Fix:_ Add a Tooltip to the TRANSPORT row (or omit it if it's only for developers). In the registration modal, clarify with hint text: 'COMMAND (stdio): Run a local command to start the server' and 'URL (http transport): Connect to a remote or local HTTP server.' Or simplify the UI to auto-detect (if URL provided, use HTTP; if command provided, use STDIO).
- **⚪ LOW · information** — Tool descriptions can overflow and are truncated without clear indication
  - _Why:_ In the expanded view, tool descriptions are truncated (max-w-xs truncate) with no ellipsis feedback or tooltip. A long description just cuts off, and the user doesn't know if there's more text or if that's all there is.
  - _Fix:_ On truncated descriptions, add a Tooltip that shows the full text. Or replace truncate with line-clamp-2 and let it wrap naturally (tools are typically described in one sentence, so wrapping is fine).


### Integrations  
`/integrations` · tier: admin

**Purpose.** Enable the admin to configure external service connectors (search, notifications, repositories, storage, project management) so the AI workspace can reach out to APIs and webhooks. Each integration holds a base URL and encrypted credential, testable before saving.

**Personas reviewed.**
- _The careful first-time integrator_ — User is setting up SearXNG for the first time. They paste a URL, a credential, click TEST, and see 'TEST FAILED'. They don't know if the URL is wrong, the credential is wrong, or the host is down. They try re-entering the values, test again, fail again. They abandon the modal unsure whether clicking SAVE would lock in a broken state or wipe the old credential. Eventually they guess and save it broken, which silently breaks search in the chat UI later.
- _The recovering-from-error admin_ — An integration that was working (S3) suddenly shows 'error' status. The test still times out. Admin clicks CONFIGURE, sees the old URL and a password field, but can't tell if a credential is still set or was cleared. They don't have a 'RESET' or 'CLEAR' button to start fresh. They either leave it broken or waste time re-entering a credential they're not sure about.
- _The bulk-rotater under time pressure_ — Security audit requires rotating all API tokens. Admin has six integrations to update. They click each one, change the credential, test, and save—six separate flows. They're rushing and don't notice one test failed. It saves broken. Later, when that feature silently stops working, the failure is invisible and traced back to the wrong place.

**Works well.** Clean list view shows all integrations at a glance with configured/unconfigured status and test health visible on each row; Modal design follows established patterns (PageHeader, LoadingText, EmptyState, StatusFlag, Modal) from the design system and is consistent with Settings/Embedding screens; Test flow is present and the random 70/30 success/failure mock realistically simulates flaky endpoints; Credential field is masked (type=password) and storage assurance message ('AES-256-GCM, never in logs') builds trust; Descriptions displayed in the modal provide context about what each integration does

**Gaps (10).**

- **🔴 HIGH · error-recovery** — Test failures silently re-save unverified state
  - _Why:_ When a test fails (status='error'), saving the config still marks it 'configured: true' and updates lastTestedAt only on success—but clicking SAVE after a failed test persists the baseUrl. User doesn't know whether a failure means 'bad credential' or 'unreachable host', and saving anyway makes it appear configured when it's broken. Critical for integrations, where misconfiguration silently breaks background tasks (research, scheduling, webhooks).
  - _Fix:_ Add a confirmation modal after test failure. Show the error result prominently (use Panel label="CONFIGURE — <name> [ERROR]" with state="alert"), disable SAVE until a new test passes, and require explicit re-test. Pattern: see EmbeddingScreen's "CONFIRM MODEL SWAP" modal (ln 79-100).
- **🔴 HIGH · information** — No test result error details—only 'TEST FAILED'
  - _Why:_ A test fail message doesn't tell the user *why*: DNS failure? Auth rejected? Timeout? They can't distinguish 'wrong credential' from 'host unreachable' from 'endpoint gone'. For a sensitive operation (API credentials, OAuth tokens), lack of diagnostic info frustrates troubleshooting and erodes trust.
  - _Fix:_ Extend model to include error reason: `testResult: {status: 'ok' | 'error', message?: string}`. Display it below the status flag: `<Show when={testResult()?.message}><Text tone="warn" variant="micro">{testResult()?.message}</Text></Show>` (or Markdown if multi-line).
- **🟠 MED · interaction** — Empty credential placeholder confuses intent
  - _Why:_ The API KEY field shows "Leave blank to keep existing" but there's no way to *see* if a credential is already set, only to blind-replace it. A user who wants to verify the current credential (to check for expiry or rotation) can't—they just see a password field, and re-saving with it blank might accidentally clear the secret.
  - _Fix:_ Add a small indicator: if credentialsPresent or lastConfiguredAt exists, show a ReadOnly field or badge next to the input: `<Show when={editing()?.lastConfiguredAt}><Text tone="dim" variant="micro">Credential configured {timestamp(editing()!.lastConfiguredAt!)}</Text></Show>`. Or: "Credential saved on …" as a micro Field label.
- **🟠 MED · interaction** — No way to remove or reset a broken integration
  - _Why:_ Once an integration is configured but broken (error status), there's no 'reset' or 'unconfigure' button. User can keep re-testing, but can't go back to untested/fresh state without backend support. This is friction for the recover-from-error workflow.
  - _Fix:_ Add a 'RESET' button in the modal footer (after CANCEL, before TEST, before SAVE) that clears baseUrl and re-marks status: untested. Pair it with a confirm: click RESET → small confirm tooltip/text 'This will clear the URL; you can reconfigure anytime.' (or a tiny confirm modal like embedded in the button press).
- **🟠 MED · interaction** — Test button doesn't clear stale results when retrying after credential change
  - _Why:_ If user edits the API KEY field and clicks TEST again, the old testResult is still visible—might show 'TEST PASSED' while a new test is running (testing() = true), creating confusion about which result is active.
  - _Fix:_ Clear testResult when the user edits editKey: `onInput={(e) => { setEditKey(e.currentTarget.value); setTestResult(null); }}`
- **🟠 MED · information** — No indication of partial failure or deprecation
  - _Why:_ Mock data includes S3 with status='error' but the cause is invisible. In the real system, this might be a deprecation warning, a credential that will expire, or a transient network blip. The list row flags status but not severity/cause, so a user scanning the list doesn't know whether 'error' is 'fix this now' vs 'keep monitoring'.
  - _Fix:_ Extend ListRow right-side to show a second, more subtle status below the StatusFlag for S3: a Tooltip or micro Text explaining the issue category (e.g., 'CONNECTION TIMEOUT', 'CREDENTIAL EXPIRED', 'DEPRECATED'). Or promote color: use `status="warn"` for deprecation, `status="alert"` only for active failure.
- **🟠 MED · onboarding** — No guidance on which integrations are required vs optional
  - _Why:_ First-timer sees six integrations (SearXNG, ntfy, GitHub, Jira, S3, etc.) but doesn't know which are critical for the app to function. Disabled features that depend on missing integrations don't hint at needing config here.
  - _Fix:_ Add a `required?: boolean` field to the Integration model. Show a small badge next to the name for required ones: `<Show when={int.required}><StatusFlag size="sm" status="alert">REQUIRED</StatusFlag></Show>`. Or group the panel: `CRITICAL SERVICES` (required) and `OPTIONAL CONNECTORS` (optional).
- **⚪ LOW · efficiency** — No way to copy/reference the integration ID or endpoint during config
  - _Why:_ Some integrations require knowing the unique integration ID for webhooks or callbacks. The modal shows the name but not the id. A user setting up a webhook (e.g., ntfy topic name) might need to reference 'int-searxng' in their payload but has to leave the modal, inspect the source, or guess.
  - _Fix:_ Show a small readonly Field or Readout below the integration name in the modal header: `<Field label="ID" value={editing()?.id} readonly />` or inline as `<Text tone="dim" variant="micro">{editing()?.id}</Text>` next to the title.
- **⚪ LOW · information** — Modal doesn't show integration type or purpose
  - _Why:_ When configuring, user sees the name and description (if present) but not the type. Someone setting up 'GitHub' might benefit from seeing 'CODE HOST' as a reminder of its role, especially for less-obvious ones like 'ntfy'.
  - _Fix:_ Show the type in the modal title or as a subtitle: change title to `CONFIGURE — ${editing()?.name ?? ''} (${editing()?.type ?? ''})` or add `<Text tone="dim" variant="micro">{editing()?.type}</Text>` below the description.
- **⚪ LOW · efficiency** — No bulk or batch retry for multiple failures
  - _Why:_ If three integrations are misconfigured (e.g., after rotating credentials), user must edit each one individually, test, save. No 'test all' or 'retry all failed' shortcut.
  - _Fix:_ Add a page-level button in PageHeader actions: 'TEST ALL' → loops TEST on each configured integration, reports pass/fail summary at the top. Minor feature for the occasional mass-update, but valuable for credential rotation workflows.


### Speech  
`/speech` · tier: admin

**Purpose.** Configure and test text-to-speech synthesis and speech-to-text transcription providers, manage voice preferences, and review cached synthesized audio clips.

**Personas reviewed.**
- _Distracted Admin_ — Drops in to quickly test a TTS voice for a system notification, hits Record by accident, and can't tell if the microphone is actually capturing without watching closely.
- _Troubleshooter_ — Lands on Speech page to verify STT is working after switching providers; synthesizes text and records, but doesn't see any error message if synthesis fails—just the button returns to normal state.
- _First-Time User_ — Non-technical household member opens Speech page cold, sees unfamiliar controls (provider, language dropdowns), and doesn't know what a 'Kokoro voice' is or whether they should hit Record or change anything.

**Works well.** Clear two-column layout separates TTS from STT concerns; no cognitive overload.; Audio cache list with truncated text, voice label, duration, and age timestamps are all present and readable.; Play/Stop button on each cached clip is intuitive and provides immediate state feedback (color + label change).

**Gaps (8).**

- **🔴 HIGH · error-recovery** — No error state for failed synthesis or recording
  - _Why:_ If synthesis times out, the API fails, or microphone permission is denied, the user sees the button return to idle and nothing else. They don't know if it worked or why it failed, so they're left guessing whether to retry.
  - _Fix:_ Add an error Panel below each control section (TTS and STT) with `state='alert'` to show failure details. Use `<Show when={ttsError()}>` paired with a signal tracking synthesis/recording failures. Include a Retry button.
- **🔴 HIGH · feedback** — Recording feedback is too subtle for confidence
  - _Why:_ The StatusFlag 'CAPTURING AUDIO' appears only while recording, and disappears the moment it stops. A hurried user (Persona 1) may miss it or not be sure if they tapped the button. Then the transcript appears—but if it's blank or has error text, they don't know if the microphone actually captured anything.
  - _Fix:_ After recording stops, show a transient feedback panel with the transcript and a timestamp. Add a 'CAPTURED AT' label with the recording time. If recording failed (e.g., no microphone), show a brief error in an alert Panel instead of silently showing blank text.
- **🟠 MED · missing-state** — Empty transcript state after failed recording is silent
  - _Why:_ If `sttResult()` is null/empty (e.g., failed record or mic permission denied), the STT section shows the Record button. The user doesn't know if they need to retry or if their mic is broken.
  - _Fix:_ Track a recording error state separately. If `sttError()` is set, show an `<EmptyState icon='alert' message='RECORDING FAILED' hint='Check microphone permissions or retry.' />` with a Retry button. If `sttResult()` is truthy but empty, show `<EmptyState icon='mic' message='NO AUDIO DETECTED' />`.
- **🟠 MED · trust-safety** — No confirmation on destructive cache operations
  - _Why:_ There's no way to delete individual cached audio clips or clear the entire cache (neither UI is present in the code). If these features are planned, adding them without a confirm will let users accidentally wipe cached audio. Even if not built yet, it's a gap for the admin workflow.
  - _Fix:_ When cache-clearing features are added (Phase 2), wrap them in a confirm Modal: 'Clear all cached audio? This cannot be undone.' Only on explicit YES should the action fire.
- **🟠 MED · onboarding** — Provider/voice/language dropdowns lack guidance for first-timers
  - _Why:_ A new user (Persona 3) sees 'Kokoro', 'Piper', 'ElevenLabs', etc., and 'af_heart', 'af_sky', etc., with no hint of what these mean or whether they're local vs. remote. The mocks show '(Local)' and '(Remote)' in labels, but the user still doesn't know what 'af_heart' sounds like or which to pick.
  - _Fix:_ Add a Tooltip or small `(?)` icon next to 'PROVIDER' linking to a help text: 'Local = runs on your machine (faster, private). Remote = calls a cloud API (may cost money, requires auth).' For voices, group them by provider in a visual way, or show a small info badge. Consider a 'Preview voice' button next to voice dropdown that plays a short sample from the cache.
- **⚪ LOW · information** — No indication of cache size limits or when cleanup is needed
  - _Why:_ The InstrumentBand shows 'CACHE SIZE' in bytes (e.g., 128 MB) but doesn't indicate if this is approaching a limit. The admin doesn't know when they should manually prune or if it's automatically managed.
  - _Fix:_ In the InstrumentBand or near the cache section, add a hint: 'Cache auto-cleans when >500MB. Current: 128MB (26% full).' Or use a ProgressBar component showing cache fullness. This gives the troubleshooter (Persona 2) context.
- **⚪ LOW · information** — Synthesize button disables on empty text, but no feedback on why
  - _Why:_ If the user leaves SAMPLE TEXT blank and tries to click Synthesize, the button is greyed out. There's no label or hint saying 'Enter text to synthesize.' They may wonder if the button is broken or what they're supposed to do.
  - _Fix:_ Add placeholder text to the Input (already present: 'Enter text to synthesize…'), but also add a disabled-state hint: wrap the Input in a Field and add `hint='Required'` so the user sees feedback at the disabled state.
- **⚪ LOW · interaction** — STT recording has no cancel/stop explicit action
  - _Why:_ Once you hit Record, you must wait for the 2.5s mock timeout to finish (or close the browser). There's no Stop button or cancel—the button is disabled while recording. A user (Persona 1) may panic thinking they're stuck.
  - _Fix:_ Change the Record button variant to 'danger' while recording (already done in the code), and label it 'STOP RECORDING' so it's clear it's clickable. Add `onClick={() => setRecording(false)}` to let users interrupt early.


### Health  
`/health` · tier: admin

**Purpose.** Gives the admin a live status view of all backend services (vector search, web search, email, model, embeddings, storage, push) and lets them understand degradation/outages at a glance with 10-check history trending.

**Personas reviewed.**
- _Alicia — Proactive Operator_ — Embeddings service went into alert (schema mismatch). She opens Health, sees the issue, and needs to either find a recovery action (reindex button, retry, view logs) or understand what to do next. Currently the page is read-only and gives no next steps.
- _Derek — Distracted Troubleshooter_ — Odysseus feels slow. He checks Health, sees email latency at 512ms with a warn status. He doesn't know if this is acceptable, what the baseline is, or what to do. He leaves without confidence he's understood the problem.
- _Sam — First-Timer in Admin_ — Sam is exploring Health for the first time. They see EMBEDDINGS offline with a degradation note, but the page doesn't explain severity, whether it's safe to ignore, whether it will auto-recover, or who to contact. They're confused about whether to escalate.

**Works well.** Clear visual health summary (InstrumentBand) with counts and last-check timestamp, good at a glance; 10-check history bar per service gives obvious trend visibility (deteriorating vs stable nominal); Degradation notes panel is semantic and grouped, separating explanation from the raw grid

**Gaps (9).**

- **🔴 HIGH · interaction** — No actionable recovery paths for degraded/alert services
  - _Why:_ An admin sees a service is in alert or warn (e.g., 'Collection schema mismatch — new docs not indexed') but the page is read-only. They have no way to trigger a fix (reindex, reconnect, retry), view logs, or understand next steps. This makes the page a read-only status display instead of an operational tool.
  - _Fix:_ Add a context menu or drill-down drawer for each service that exposes service-specific actions. For embeddings: 'Reindex', 'View Logs', 'Retry Connection'. Use Menu (to expose actions on a row) or a Drawer (on click) to avoid cluttering the grid. Actions should be admin-gated and Phase 2 wired to backend triggers.
- **🔴 HIGH · feedback** — Refresh button provides no success/failure feedback
  - _Why:_ The button shows 'CHECKING…' for 1.1s, then reverts to 'REFRESH'. But there's no indication whether the check succeeded, failed, found new issues, or changed any data. An admin won't know if they should trust the displayed status or retry.
  - _Fix:_ After refresh, show a brief success message (e.g., StatusFlag with 'UPDATED AT 14:32' or a small toast-style confirmation) and display any new/resolved issues. If refresh fails (network error), show an alert Panel at the top with error detail and a 'Retry' button.
- **🟠 MED · information** — No baseline or context for latency values
  - _Why:_ A service shows '512MS' latency with warn status. Derek doesn't know if 512ms is slow for that service (normal: 20ms?), how it compares to peers, or if it's acceptable. He can't distinguish 'slow but working' from 'slow and failing'.
  - _Fix:_ Add a 'normal/baseline' latency next to the current value (e.g., '512MS (normal: 20MS)'), or use a ProgressBar to show latency relative to a threshold. Alternatively, only show status warnings if latency exceeds a configurable threshold—if warn is set at 400ms, then 512ms explains itself.
- **🟠 MED · navigation** — Service drill-down missing; all detail on one screen
  - _Why:_ Clicking a service row does nothing. If an admin wants to see logs, recent errors, config, or retry options for a specific service, they're stuck. The page is a flat grid with no depth.
  - _Fix:_ Make service rows interactive: click to open a Drawer showing service detail (logs snippet, config, retry/action buttons, history graph over time). Or add a 'View Detail' icon/button leading to `/health/:serviceId` if a detail route is planned.
- **🟠 MED · missing-state** — Partial/slow/unknown health states not defined
  - _Why:_ The data model has only nominal/warn/alert, but real systems have timeout, partial, or slow states. If a service check times out or returns partial data (e.g., 'healthy but slow'), there's no way to represent it. The mocks show a healthy system only.
  - _Fix:_ Extend HealthStatus to include 'timeout' and 'partial', or add a 'checkedAt' field to ServiceStatus to detect stale checks (if no check in 5m, show 'STALE'). Update mocks to include a service in each state for design completeness.
- **⚪ LOW · efficiency** — No filter/search for large service counts
  - _Why:_ With 7 services today, the list is manageable. But as services grow (external APIs, integrations), admins will want to find problem services fast or focus on a subset.
  - _Fix:_ Add a Filter/Search control above the SERVICE GRID: an Input for service name search, or a Select to filter by status ('Show: All / Alerts / Warnings / Nominal'). Use the existing Input and Select components.
- **⚪ LOW · information** — History bar timestamps and check interval unexplained
  - _Why:_ The bar shows 'Last 10 checks (newest right)' but doesn't say how old the oldest check is, what the check interval is (1m? 10m?), or the absolute times of the bars. A user can't tell if the data is 5 minutes old or 5 hours old.
  - _Fix:_ Add a Tooltip on the history bar showing the time range ('Checks from 13:25 to 13:35, every 1m') or display check times in a legend/label below the bar (e.g., '13:25–13:35 (10 × 1m checks)') using a micro Text element.
- **⚪ LOW · feedback** — Degradation panel updates not visually confirmed
  - _Why:_ The DEGRADATION NOTES panel appears conditionally if any service has a note. If an admin fixes an issue and refreshes, the panel might disappear, but there's no animation or highlight to show the change. The update is silent.
  - _Fix:_ On refresh, if a degradation resolves, fade or highlight the DEGRADATION NOTES panel briefly (e.g., a brief green flash or 'ISSUE RESOLVED' toast), or use a transition to draw attention to the update.
- **⚪ LOW · onboarding** — No guidance for first-time admin users
  - _Why:_ Sam lands on Health as a new admin and sees 'EMBEDDINGS OFFLINE' but doesn't know if it's critical, expected, recoverable, or who to notify. The page has no help text, tooltips, or severity explanation.
  - _Fix:_ Add brief, semantic tooltips to status flags explaining what each status means ('ALERT = service unavailable or critical error'; 'WARN = degraded performance or minor issue'). Or include a small help icon/link opening a Modal with guidance ('Health 101: What to do when you see an alert').


### Settings  
`/settings` · tier: open

**Purpose.** Enable the operator to configure model, language, privacy, two-factor authentication, backup codes, and account details for the Odysseus instance. Act as the single source of truth for account and security state.

**Personas reviewed.**
- _Technical Owner (Setup Phase)_ — Just deployed Odysseus, going through initial setup: pick a model, enable 2FA, save backup codes to a safe place, verify everything is correct before going live.
- _Returning Operator (Routine Audit)_ — Checking in after a week: want to verify current model, confirm 2FA is still active, and spot-check account info. Land on Settings and want a clear read of state without risk of accidental edits.
- _Distracted Operator (Error Recovery)_ — System had an issue; they toggle 2FA off 'just to check' mid-investigation, then realize it was a mistake. Need to undo the change or confirm what state they're actually in.

**Works well.** Tab-based organization is clear and reduces cognitive load per section.; 2FA flow uses a guard modal for destructive toggle, reducing accidental disablement.; Backup codes are displayed in a scan-friendly grid; manual entry secret is available as fallback.

**Gaps (12).**

- **🔴 HIGH · missing-state** — No visual distinction between pending and committed state
  - _Why:_ When user toggles 2FA off/on, the toggle immediately moves in the UI but the change is not yet saved (it's only committed when the modal confirms). If they close the tab or navigate away before confirming the modal, the local state diverges from what a server would see in Phase 2. The SAVED flag only appears on Preferences/Account, not on 2FA changes, so Security tab has asymmetric feedback. Distracted operator cannot tell what is transient state vs. persisted.
  - _Fix:_ Show a 'PENDING' or 'UNSAVED' status flag when toggle state differs from loaded data. On Security tab 2FA panel, add a meta status like "PENDING…" until confirmToggle2FA actually completes. Consider disabling navigation/tab changes until pending changes are confirmed or discarded.
- **🔴 HIGH · interaction** — 2FA toggle is a trap: toggle immediately updates UI even if modal is never confirmed
  - _Why:_ User clicks the 2FA toggle. The toggle flips. A modal appears asking for password. But if they close the modal via 'X' or click outside, the toggle stays flipped, not restored to its prior state. The modal has a CANCEL button that should restore it, but the 'X' close doesn't. This breaks trust: the UI state doesn't match the security state.
  - _Fix:_ On modal open, store the pre-toggle state (twoFAEnabled). Only call confirmToggle2FA when the modal footer CONFIRM button is clicked. On CANCEL or modal close (including 'X'), restore the toggle to its prior state without executing confirmToggle2FA.
- **🟠 MED · interaction** — No way to cancel unsaved changes in Preferences and Account tabs
  - _Why:_ User selects a different model or enters a display name, then regrets it. They must click SAVE PREFERENCES to persist — but there's no 'CANCEL' or 'RESET' button to discard changes without saving. They could close/reopen, but that's not discoverable. Returning operator may land here and think they're reading a static config, then accidentally change it.
  - _Fix:_ Add a 'RESET' button next to 'SAVE PREFERENCES' and 'SAVE ACCOUNT' that clears local state back to last-loaded values (model, language, displayName, toggles). Show it only if unsaved changes exist (compare current state to loaded prefs).
- **🟠 MED · missing-state** — No loading state for async model/language selects
  - _Why:_ In Phase 2, changing the model will likely be an async operation (re-init LLM connection, test it, report errors). Currently, selects are instant. The Suspense fallback shows LoadingText only on initial page load; toggling model has no feedback. User won't know if the change is being processed or failed.
  - _Fix:_ When user changes model or language dropdown, set a transient 'saving' flag and disable the select until the save completes. Show a LoadingText or inline status ('CONNECTING…') near the changed control. On error (Phase 2), show a warn-toned status ('FAILED: could not init model').
- **🟠 MED · efficiency** — Backup codes have no copy-to-clipboard or download affordance
  - _Why:_ Operator needs to store backup codes securely. Currently, they're read-only text in a grid. To save them, user must manually select-all, copy, and paste into a notes app. This is friction for a critical security artifact. Technical owner will do this in setup phase and get annoyed.
  - _Fix:_ Add a 'COPY ALL' button to the Backup Codes panel (top-right, next to REGENERATE) that copies all codes to clipboard in a text format ('8A3F-9C2E\nK7P2-M1X4\n…'). Show a 'COPIED' flash on success (similar to SAVED/REGENERATED pattern).
- **🟠 MED · efficiency** — QR code is a static placeholder; manual entry secret has no copy affordance
  - _Why:_ When setting up 2FA, user must copy the manual entry secret (JBSWY3DPEHPK3PXP) into their authenticator app. Currently, it's display-only. They must manually select and copy it, or retype it. This is error-prone for a 16-character alphanumeric string.
  - _Fix:_ Add a 'COPY' button next to or below the MANUAL ENTRY SECRET (icon: copy). On click, copy the secret to clipboard and show a brief 'COPIED' toast or inline flash. In Phase 2, the QR placeholder becomes a real QR code rendered server-side (or via a library like qrcode.js).
- **🟠 MED · trust-safety** — No confirmation on 2FA disable; warning is weak
  - _Why:_ When toggling 2FA off, the modal warns 'This will reduce your account security,' but doesn't strongly discourage it or ask 'Are you sure?' The button is labeled 'CONFIRM' not 'DISABLE' (which is a bit indirect). For a single-user admin console, disabling 2FA is a serious action that could be done accidentally.
  - _Fix:_ When disabling 2FA, use a more explicit modal footer: replace 'CONFIRM' with 'DISABLE 2FA' (variant='danger'). Add a second confirmation line in the modal body: 'This cannot be undone. Type DISABLE to confirm.' Then require the user to type 'DISABLE' in a read-only check field before the button enables, similar to destructive-action patterns.
- **🟠 MED · missing-state** — SAVED flag only flashes on Preferences and Account; 2FA and backup code actions don't confirm success
  - _Why:_ SAVE PREFERENCES, SAVE ACCOUNT, and REGENERATE show a SAVED / REGENERATED flag for 2 seconds. But regenerating backup codes or enabling 2FA (which are equally important state changes) have no success feedback. User can't tell if clicking REGENERATE actually worked or hung. In Phase 2, these need to be async; lack of feedback now means the pattern isn't established.
  - _Fix:_ On successful 2FA toggle (after modal confirm), show a StatusFlag('nominal') 'ENABLED' or 'DISABLED' for 2 seconds in the panel header. On REGENERATE codes, the button already shows 'REGENERATED' but it flashes back to 'REGENERATE'; persist the success flag for 2 seconds like SAVE does, then reset.
- **🟠 MED · interaction** — Modal close via 'X' or outside-click doesn't have the same effect as CANCEL
  - _Why:_ The 2FA confirmation modal has an explicit CANCEL button, but users can also close it by clicking the 'X' in the top-right or clicking outside the modal (if backdrop-click is enabled). If the toggle is already flipped (prior bug), these close methods won't restore it. Behavior is inconsistent.
  - _Fix:_ Ensure Modal's onClose handler (which runs on 'X' or backdrop click) calls the same cleanup as the CANCEL button: reset toggle state, clear password input. Make all close paths equivalent.
- **⚪ LOW · consistency** — Theme setting is read-only but not clearly marked as such
  - _Why:_ In the MODEL & INTERFACE panel, theme is a Field with value 'Controlled by top-bar toggle (sun/moon icon).' This is correct but uses Field (which is typically for display-only values) mixed with Select and Input (editable controls) in the same panel. User may try to click it or wonder why it's not editable. It doesn't use a visual affordance like an Icon to indicate read-only.
  - _Fix:_ Add an icon hint (e.g., a small 'info' or 'link' icon) next to the theme value to make it clear it's not a setting in this panel but rather a global UI toggle. Or move it to a separate, clearly read-only section at the bottom of the page with a subtitle '(Controlled by top-bar toggle)'.
- **⚪ LOW · onboarding** — No empty state guidance for first-time setup
  - _Why:_ A brand-new Odysseus install hasn't configured anything yet. When user lands on Settings for the first time, they see Preferences, Security, Account tabs with fields pre-filled from mock data. There's no onboarding hint like 'Welcome! Start by choosing a model above' or 'First-time setup? Enable 2FA now.' For a technical owner, it's fine, but the page reads as 'configuration in progress' with no guidance.
  - _Fix:_ On first page load (or if detecting default/mock values), add an inline Banner or alert above the tabs: 'INITIAL SETUP — Choose a model, enable 2FA, and review your account info.' Or on the Preferences tab, add a Panel with a title like 'GETTING STARTED' that collapses once all required settings are filled in.
- **⚪ LOW · error-recovery** — No validation or error states for inputs
  - _Why:_ Display name input has no length limit, no validation, no error message if it exceeds a backend constraint. Password confirm in modal has no feedback for wrong password (Phase 2). User could enter an invalid display name and hit SAVE without knowing it will fail on submit.
  - _Fix:_ Add maxlength to the display name input (e.g., 50 chars). Show remaining character count below input (like TextArea does). In Phase 2, show an inline error under the password field if submission fails ('Incorrect password').


### Users  
`/admin/users` · tier: admin

**Purpose.** The Users page allows the admin operator to create, manage, disable, and grant privileges to workspace users. It's the single place to control multi-user access to features (memory, skills, documents, email, calendar, contacts, RAG, uploads, gallery, code).

**Personas reviewed.**
- _Admin operator (technical, deliberate)_ — Morning: creates a new user 'TEAMMATE', grants memory+documents+rag, verifies they have the right privileges, then disables an inactive user from last quarter. Expects clear feedback when each action succeeds; wants to see who's active vs. stale at a glance.
- _Hurried/distracted operator (multi-tasking, uses muscle memory)_ — Quickly opens Users page on autopilot to revoke a teammate's 'email' privilege after they leave the team. Clicks delete by accident, doesn't read the modal closely, confirms. Needs a clear undo or recent-action recovery.
- _First-time delegator (non-technical household member, no admin experience)_ — Invited to manage workspace after operator goes on leave. Lands on Users page, sees 'CREATE USER' button and 4 users listed. Doesn't know what 'rag' or 'code' privileges mean, tries hovering for help (none), feels lost on whether they're about to break something by toggling privileges.

**Works well.** Delete is guarded by a modal with a clear destructive action and undo path.; Privilege editor (drawer) clearly labels all privilege toggles and shows user status/ID.; List shows relative time (last active), status, and admin badge — useful for at-a-glance staleness.; CreateUser modal validates that username is not empty before enabling the Create button.

**Gaps (11).**

- **🔴 HIGH · information** — Admin cannot see or manage password; user cannot reset their own password
  - _Why:_ No password management UI exists. If a user forgets their password or needs a reset, the admin has no way to trigger one from this page. The user has no self-serve reset option. This is a critical access-control gap — a user could be locked out permanently.
  - _Fix:_ Add 'RESET PASSWORD' option in the menu for each user (alongside EDIT PRIVILEGES, DISABLE, DELETE). Clicking it shows a modal with 'GENERATE NEW PASSWORD' or 'SEND RESET LINK VIA EMAIL' (depending on backend capability). Display the new password prominently so the admin can relay it to the user.
- **🟠 MED · feedback** — No success feedback on create/delete/status-toggle
  - _Why:_ User creates a new user or deletes one, modals close, but there's no visual confirmation (flash, toast, banner, or transient status) that the action succeeded. Especially risky for delete — the list just updates silently, user may not notice if something went wrong.
  - _Fix:_ Add a transient success banner (e.g. 'CREATED USER TEAMATE' or 'DELETED USER ARCHIVIST') that auto-clears after 3s, positioned near the top of the list. Reuse the Markdown/Text component with a semantic status tone (nominal for success, alert for error).
- **🟠 MED · information** — Password field collected but never used or validated
  - _Why:_ The create-user modal has a PASSWORD input, but the code stores a user with no password field, never validates it (min length, complexity), and never shows strength feedback. User may think they're setting a password when they're actually entering nothing that persists.
  - _Fix:_ Either remove the PASSWORD field entirely (backend generates a temporary password), or display a small validation hint below the field ('MIN 8 CHARS'), validate on input, and show real-time feedback (e.g. 'WEAK' / 'OK' in a micro Text component).
- **🟠 MED · information** — No way to see what privileges mean before granting them
  - _Why:_ Privilege names like 'rag', 'skills', 'code' are abbreviations with no explanation. A first-time delegator has no way to know whether granting 'code' means running Python or shell commands, or something else. No hover tooltip, no modal help, no legend.
  - _Fix:_ Add a small tooltip or info icon next to the 'ACCESS PRIVILEGES' label in the drawer. On hover/click, show a brief legend: 'MEMORY: access knowledge base | SKILLS: manage custom tools | CODE: run Python/shell | ...' Reuse the Tooltip primitive if it exists, or a small help modal.
- **🟠 MED · error-recovery** — Privilege toggles have no undo; drawer dismissal loses all changes
  - _Why:_ User opens the privilege drawer, toggles 3 privileges (e.g. accidentally grants 'code' + 'email' by clicking in the wrong row), then realizes the mistake. There's no 'UNDO' or 'REVERT' button — they have to toggle each one back manually, or close the drawer (no confirmation) and reopen to start again.
  - _Fix:_ Add a 'REVERT' button in the drawer footer (alongside 'CLOSE') that resets the privilege list to the last saved state. Or add a confirmation modal on drawer close if any toggles differ from the initial state ('CLOSE WITHOUT SAVING?').
- **🟠 MED · information** — Creating a user requires admin to manage initial password distribution outside the app
  - _Why:_ User creates 'NEWUSER' with a password, but there's no confirmation of what password was set, no way to regenerate it, no 'show initial password' modal, no 'copy to clipboard' button. If the operator and new user are not in the same room, the password handoff is undefined — does it email, does the admin tell them verbally, does the user hit 'forgot password'?
  - _Fix:_ After user creation succeeds, show a modal: 'USER CREATED: [name] | INITIAL PASSWORD: [generated or entered] | [COPY] [DONE]'. Or, if backend generates the password, show 'INITIAL PASSWORD SET — SEND TO USER VIA SECURE CHANNEL' and provide a copy button. Make the password visible (not masked) in this modal so the operator can read and relay it.
- **🟠 MED · error-recovery** — No visible error state if user creation fails in Phase 2
  - _Why:_ Today, all mutations are local (mock data), so there's no failure case. In Phase 2, when create/delete hit the backend, network errors or validation errors will occur. The modal has no error message area — user clicks CREATE, nothing happens, and they don't know if it failed, is loading, or succeeded.
  - _Fix:_ Add error state handling to the create/delete modals: a `Show when={error()}` block displaying the error message (e.g. 'FAILED: USERNAME ALREADY EXISTS') in red text or an alert tone StatusFlag. Pair it with a LoadingText state (show 'CREATING…' while pending) to make the flow clear.
- **⚪ LOW · efficiency** — No search, filter, sort, or pagination for user list
  - _Why:_ Today, mockUsers has 4 users, so the full list fits on screen. In production, with 10–50 users, finding a specific user by eye becomes friction — no way to search 'JOHN' or filter 'disabled users' or sort by 'last active'. Operator has to scroll through the entire list.
  - _Fix:_ Add a search input above the panel (e.g. 'FILTER BY NAME') that filters the list client-side. If sort matters later, add a sort control (3-dot menu or Tabs: 'ALL / ACTIVE / DISABLED'). Start with search only — it's the quickest win and reuses the Input component.
- **⚪ LOW · interaction** — Disabled users have no visual distinction in the list rows themselves
  - _Why:_ A disabled user shows 'DISABLED' status in the right-hand StatusFlag, but the row label is not visually muted or struck-through. This works but is less scannable — a busy operator might not notice they're looking at a disabled user in a long list.
  - _Fix:_ Apply a subtle visual hint to the row label for disabled users: `text-dim` class or faint opacity. This keeps scanning fast without breaking the design system (still uses semantic tone, not arbitrary colors).
- **⚪ LOW · information** — Destroy-on-disable vs. permanent-delete is conflated; user may be confused about DISABLE vs. DELETE
  - _Why:_ The menu shows both 'DISABLE USER' and 'DELETE USER', but it's not immediately clear what the difference is. Does DISABLE mean the account still exists but is inactive (for re-enabling), or is it soft-deleted? Does DELETE mean hard-delete all their data, or just remove the account? A first-timer might think they're the same or pick the wrong one.
  - _Fix:_ Update the delete confirmation modal to be more explicit: 'DELETE USER [name]: Account will be permanently removed. All messages, documents, and data created by this user will be [KEPT / DELETED — your choice]. This cannot be undone.' Or add a hint text in the menu items: 'DISABLE USER (temporary) / DELETE USER (permanent)'. Reuse the micro Text tone=dim component for the hint.
- **⚪ LOW · efficiency** — No bulk actions (disable/enable/delete multiple users at once)
  - _Why:_ If an operator needs to disable 5 inactive users, they must open the menu, click disable, repeat 5 times. No multi-select checkboxes, no 'select all disabled' or bulk action toolbar.
  - _Fix:_ Add optional checkboxes to list rows (behind a feature flag or CTRL+click mode if adding UI weight is a concern). If 2+ users are selected, show a sticky action bar: '[2 SELECTED] [DISABLE ALL] [DELETE ALL]'. This is polish — low priority for Phase 1, but worth noting for when list grows.


### API Tokens  
`/admin/tokens` · tier: admin

**Purpose.** Manage API tokens for programmatic access to Odysseus, including issuance with scope selection, viewing active/revoked tokens and their metadata, and revocation with confirmation.

**Personas reviewed.**
- _Francisco (integrations owner)_ — Needs to rotate a token used by an external automation (Zapier, GitHub Actions) because he wants to tighten scopes or it's been compromised. Current UX offers no bulk export, no search-by-scope, and no 'copy config' shortcut—he manually recreates and updates each dependent service.
- _Francisco (rushed/distracted)_ — About to issue a token, realizes mid-action he selected the wrong scopes, but the modal doesn't preview the grant before submit. Issues the token anyway, then has to revoke (confirm modal) and re-create (type label, re-check boxes). Repeated friction.
- _Francisco (security-conscious)_ — Post-incident, wants to rotate all 'admin' scoped tokens older than 90 days. No filter, sort, or bulk-revoke. Must scan the entire list manually, identify which ones are admin + old, then revoke one by one. Error-prone at scale.

**Works well.** Revoke action is guarded by a confirmation modal that shows the token label and creation date—high-risk operation is not accidental.; Issued token is revealed exactly once, with urgent visual warning (StatusFlag 'warn') and copy-to-clipboard feedback (2s state change)—users won't accidentally lose the secret.; Modal for issuance is simple and clear (label input + scope checkboxes), with disabled submit when required fields are empty.

**Gaps (11).**

- **🔴 HIGH · information** — Scope descriptions are missing—users don't know what each grant
  - _Why:_ Enum values like 'rag', 'memory', 'tools', 'admin', 'read-only' are unexplained. A user creating a token for a specific integration (e.g. Zapier) won't know if 'tools' includes webhooks or if 'admin' is overkill. Risk: over-provisioned tokens (security) or under-provisioned tokens (integration breaks).
  - _Fix:_ Add a Tooltip or info popover to each scope checkbox in the issue modal. Each tooltip should briefly explain the grant: e.g., 'chat: Send messages to the agent. rag: Query knowledge base. tools: Execute system commands, shell, and code runners. admin: Manage users, settings, integrations. read-only: View-only access to all data.'. Alternatively, add a help link ('?') next to SCOPES label → drawer or modal with full scope reference.
- **🔴 HIGH · feedback** — Scope selection in issue modal lacks confirmation—easy to issue with wrong permissions
  - _Why:_ User clicks through the modal quickly, selects scopes without careful review, and issues a token with unintended grants. There's no 'review' step or visual summary before submit. Only catches errors *after* token is generated and must revoke + recreate.
  - _Fix:_ Before the 'ISSUE' button, add a read-only summary row showing selected scopes in a tag or badge list. Or, switch the footer to show a 'REVIEW' button that reveals a confirmation panel listing the label and scopes, with 'ISSUE' on second confirmation. Low-friction: just one extra line in the current modal layout.
- **🔴 HIGH · error-recovery** — No error handling for operation failures (issue/revoke)—user left in ambiguity
  - _Why:_ This is mock data today, but in Phase 2, operations can fail (API error, network timeout, auth revoked, DB locked). If issuance fails, the modal closes but token is never revealed—is it created? If revoke fails, the list may not update. User is left confused about state.
  - _Fix:_ Wrap issuance in a try-catch. On error, keep the modal open and display an error Panel or inline Message above the form (red tone, icon 'alert', text like 'Failed to issue token: [reason]. Please try again.'). Similarly, on revoke failure, show a Modal or Drawer with the error and a 'RETRY' button. Use the existing error patterns: Message (inline), Modal, or Drawer with title + body + action buttons.
- **🟠 MED · navigation** — No way to search, filter, or sort tokens—scale problem for long lists
  - _Why:_ If a user has 20+ tokens (realistic for integrations + scripts), the list is unsorted and unsearchable. To find 'admin' tokens or identify which one is 'old', he must scan manually. Ops tasks (rotate all old tokens, revoke a whole category) become tedious.
  - _Fix:_ Add a simple filter row above the token list: [Scope dropdown (default 'all') | Status dropdown (Active/Revoked/All) | Search input (label/prefix)]. Conditionally render: 'Showing X of Y tokens'. Use existing Select, Input, and Tabs or Button toggles for layout. This is light UI and high-value for admin ops.
- **🟠 MED · efficiency** — Revealed token display lacks persistence for manual entry—copy is only method
  - _Why:_ Copy-to-clipboard is modern, but not fail-safe: clipboard API can be denied, or user may need the token in a specific format (e.g., base64, embedded in JSON for a .env file). No way to manually select/display the full token without clipboard. Users on untrusted systems or strict browser sandboxes are stuck.
  - _Fix:_ Keep the token display (already readable monospace text in the panel). Enhance the copy button feedback: on success, change to '✓ COPIED' and persist the state for 3–5s (longer than 2s to ensure visibility). Or, add a 'REVEAL' toggle to show/hide the token, plus separate 'COPY' and 'DOWNLOAD AS .env' buttons. Use existing Button variant + icon patterns.
- **🟠 MED · information** — Token metadata is minimal—no context for last-use or creation environment
  - _Why:_ 'Last used at: 2 hours ago' tells you it works, but not what it was used for, from where (IP), or by what client. For security audit (did this token leak?) or ops (which script is still using this token?), the data is empty. Encourages retention of unnecessary tokens rather than rotation.
  - _Fix:_ In the list, add optional metadata columns (clickable to expand or a Drawer per token). Include: creation environment (if captured: 'Issued from Firefox on desktop', or just 'Issued by admin'), and optionally last-use IP/user-agent (privacy concern—consider opt-in). For Phase 1, add a 'Created' timestamp column (ISO format) and a read-only 'Notes' field when viewing token details (expandable ListRow or click-to-open Drawer). Allow user to add notes during creation: 'Used by Zapier webhook' → helps ops decide if safe to revoke.
- **🟠 MED · accessibility** — Copy confirmation is visual-only and transient—poor for keyboard/screen-reader users
  - _Why:_ Button text changes 'COPY' → 'COPIED' for 2s. Keyboard user tabbing past it won't register the success; screen reader won't announce the state change reliably (no aria-live). Relying on visual + timing is fragile.
  - _Fix:_ Add `aria-live='polite'` to the copy button. Change 'COPIED' state to persist longer (4–5s) so slower readers catch it. Or use a brief Notification/Toast primitive (if available in the design system) with aria-live='assertive', e.g., a small floating message 'Token copied to clipboard'. Otherwise, add a momentary inline success message next to the button: <Text aria-live='polite'>{copied() ? 'Copied!' : ''}</Text>.
- **🟠 MED · trust-safety** — Revoke is irreversible without trace—high-risk action deserves explicit warning
  - _Why:_ Revoke modal shows the token label and creation date, but doesn't warn about side effects: 'All requests using this token will immediately fail.' While that text exists in the modal, it's easy to miss. For a token powering a production script, revocation = immediate outage with no undo.
  - _Fix:_ Elevate the warning: change the revoke modal's main text to bold 'All requests using this token will IMMEDIATELY FAIL.' or add a StatusFlag 'alert' above the token name. Consider a two-step revoke: first modal asks 'Are you sure?', second modal (if rare, like 'admin' scope) asks for confirmation of side-effects, e.g., 'List integrations using this token' (if you can track it) or 'You will need to update external services.' This prevents accidental revocation of production tokens.
- **🟠 MED · trust-safety** — No token rotation/expiry policy—long-lived credentials are a security risk
  - _Why:_ Tokens are created with no TTL, expiry date, or rotation schedule. In real deployments, long-lived API keys are a common attack vector: leaked token = indefinite access. No way to enforce or encourage rotation.
  - _Fix:_ Add an optional 'Expires after' dropdown in the issue modal (e.g., '30 days', '90 days', 'Never'). Default to '90 days' (recommend security best practice). On the list, show expiry date as a column, highlight tokens expiring in <7 days with a 'warn' StatusFlag (e.g., 'EXPIRES IN 4 DAYS'). Optionally, add a 'Rotate' action that creates a new token with same scopes + invalidates the old one. This defers Phase 2 implementation but prepares the UI for the feature.
- **⚪ LOW · onboarding** — No guidance on secure storage or integration with password managers
  - _Why:_ Modal says 'Store it securely', but doesn't link to how: password manager, .env file, vault, etc. For a self-hosted tool, the owner may not have infrastructure in place and could default to unsafe methods (plaintext file, email, etc.).
  - _Fix:_ After the revealed token panel, add a collapsed section or link 'How to store this token securely'. Expand to show: '1. Save to password manager (1Password, Bitwarden, LastPass). 2. Or add to .env file in your project (never commit to git). 3. Or use Odysseus Vault (if available in Settings) → stores encrypted in data/ and auto-loads.' Keep it brief and link to /settings if vault integration is available. This is onboarding; low severity because it's advisory, but increases security posture.
- **⚪ LOW · efficiency** — Bulk actions are absent—ops tasks (rotate all admin tokens) are tedious
  - _Why:_ Security incident: revoke all 'admin' tokens immediately. Current UX: click menu, confirm revoke, repeat 3 times. For 10 tokens, it's 30 clicks. Bulk-revoke would be one action.
  - _Fix:_ Add checkboxes to token list rows (or a 'Select all' + conditional checkbox reveal). When 1+ tokens selected, show a floating action bar at bottom with 'REVOKE SELECTED' button. One confirm modal for all. Alternatively, add a 'Revoke by scope' action in the main Panel menu: select scope → confirm → revokes all tokens with that scope in one action. Use existing Checkbox and Toolbar/Button patterns. This is polish (low priority), but high-value for ops.


### Vault  
`/vault` · tier: admin

**Purpose.** Secure storage and retrieval of sensitive credentials (API keys, database passwords, service tokens). The admin user unlocks with a master password, then can view, reveal, and copy individual credentials to clipboard.

**Personas reviewed.**
- _Hurried admin grabbing a credential mid-task_ — Needs to grab a DB password quickly for a script. Unlocks vault, finds entry, copies password, locks. Expects this to be less than 10 seconds. If the master password fails silently or locks them out with no retry guidance, workflow breaks.
- _Security-conscious owner reviewing vault health_ — Wants to audit stored credentials: count them, check they match what's running in production, verify no duplicates/orphans, maybe delete obsolete ones. Current UI shows only a list with copy buttons—no way to delete, no bulk operations, no last-modified timestamps to tell which are stale.
- _Owner recovering from accidental password exposure_ — Just revealed a password on screen, now paranoid it's in browser history or memory. Tries to lock the vault to purge the plaintext. Lock button clears JS state, but does it actually clean up the DOM/memory? No confirmation signal tells the user the revealed password is gone.

**Works well.** Lock/unlock state is visually clear with semantic StatusFlag (alert=locked, nominal=unlocked); Copy-to-clipboard feedback with 2-second transient tooltip is efficient and non-intrusive; Per-entry password reveal toggle with masked default respects security-first UI (no passwords plaintext at rest)

**Gaps (11).**

- **🔴 HIGH · error-recovery** — No password validation feedback—wrong master password fails silently
  - _Why:_ Unlock accepts any non-empty string and proceeds. If a user enters the wrong password, they get no 'INVALID MASTER PASSWORD' error; they just see the vault remain locked. They may re-enter 3 times before realizing something is wrong, creating confusion and frustration.
  - _Fix:_ Add validation: simulate rejecting passwords shorter than 8 characters or not matching a mock string, showing 'INVALID MASTER PASSWORD' error hint (same pattern as 'Password cannot be empty'). This signals clear feedback and sets expectations for Phase 2 backend validation.
- **🔴 HIGH · trust-safety** — Revealed passwords rendered as plain text in DOM; can be captured in screenshots and browser recovery
  - _Why:_ Once revealed, passwords appear as plain text in the browser DOM. A screenshot (CMD+Shift+3), browser history recovery, or dev-tools inspection captures them. The Lock action clears JS state but doesn't remove plaintext from the painted page. For an admin vault, this is a critical security gap.
  - _Fix:_ Remove the reveal toggle entirely. Make password access copy-only: clicking the copy button sends password to clipboard and shows 'Copied!' feedback, but never renders plaintext in the DOM. This trades reveal-and-read convenience for security—appropriate for an admin console. If reveal must remain, warn the user: 'Password will be visible. Take care with screenshots.' in a Tooltip or pre-reveal Modal.
- **🔴 HIGH · missing-state** — No delete capability for vault entries; vault is read-only
  - _Why:_ Users can view and copy, but not delete or edit entries. Old/stale credentials (expired API keys, decommissioned services) can't be removed. The vault feels incomplete and suggests it's not user-managed—but Odysseus' design (UserManagement, SettingsScreen) shows the app supports admin edit workflows. Vault should too.
  - _Fix:_ Add a Menu (three-dot button) per entry with 'DELETE ENTRY' option (use danger variant). Show a confirmation Modal before delete (modeled on UserManagementScreen's delete-confirm pattern). Add 'EDIT' if updating credentials is planned. If entries are immutable by design, clarify this in the subtitle.
- **🔴 HIGH · error-recovery** — No recovery path if user forgets master password
  - _Why:_ If the master password is forgotten, users are permanently locked out of the vault. There's no reset, recovery code, or admin override hint. For a self-hosted single-user system, this is a critical dead-end. The UI should surface what happens next or how to recover.
  - _Fix:_ Add a link below the UNLOCK VAULT button: 'Forgot password?' with explanation: 'Master password is stored locally. To reset, go to Settings and re-initialize the vault.' Or inline a brief note: 'If forgotten, access can be recovered through /setup.' This prevents dead-end frustration and sets expectations.
- **🟠 MED · feedback** — No confirmation or feedback when Lock button is pressed; state change is silent
  - _Why:_ Clicking Lock immediately clears revealed passwords and re-locks the vault. The user gets no visual confirmation (toast, pulse, or status change) that the action succeeded. They don't know if their click registered or if the vault is actually locked without re-checking the StatusFlag.
  - _Fix:_ Add transient feedback on lock: brief 'VAULT LOCKED' confirmation message (1-2 sec) in the header StatusFlag or a LoadingText-like confirmation. Keep it instant/mechanical (≤120ms per design rules). Alternatively, let the StatusFlag briefly brighten/pulse to confirm the state change.
- **🟠 MED · efficiency** — No search or filter for entries in a large vault
  - _Why:_ With 4 mock entries it's manageable, but a real vault could have 50+ credentials. Scrolling through an unfiltered list to find 'Production Database' is tedious and error-prone. Other Odysseus screens (chat, research) support search; vault should too for consistency and usability.
  - _Fix:_ Add a search Input at the top of the CREDENTIALS panel (above the list, below PageHeader). Filter entries by name/url/username as the user types. Use existing Input component with 'search' icon. Keep it simple—client-side filter is sufficient for Phase 1.
- **⚪ LOW · consistency** — Empty state uses plain text instead of EmptyState component
  - _Why:_ Lines 226–231 render a custom <div> with raw <Text> when entries are empty. The design system provides EmptyState component for this pattern. Using it aligns with app conventions and improves visual hierarchy across all empty surfaces.
  - _Fix:_ Replace the custom div with <EmptyState label='NO ENTRIES' detail='Your vault is empty. Credentials will appear here.' /> (or adjust labels as needed). This is a one-liner that unifies the look.
- **⚪ LOW · onboarding** — No guidance on master password strength or validation rules
  - _Why:_ The unlock Input has a bullet-point placeholder ('••••••••') but no hint about minimum length, required characters, or purpose. Users don't know what constitutes a valid password or why it matters. Mock accepts any non-empty string, but Phase 2 will enforce rules—users should know them upfront.
  - _Fix:_ Add a hint below the MASTER PASSWORD Input: 'Minimum 8 characters. Used to encrypt vault on disk.' This sets expectations and explains the password's role.
- **⚪ LOW · information** — No clarity on vault encryption, data residency, or auto-lock behavior
  - _Why:_ The subtitle says 'Encrypted credential store' but doesn't explain where data lives (local disk vs. memory), how it's encrypted, or when re-locking is needed. Users might not know if they're encrypted at rest, if they auto-lock after inactivity, or if the master password is required again on restart.
  - _Fix:_ Expand the subtitle or add a brief line below the StatusFlag: 'Credentials encrypted and persisted to disk. Vault locks on app restart or when manually locked.' This clarifies the security model and reduces uncertainty.
- **⚪ LOW · information** — Mask for unrevealed passwords is fixed width and may truncate or show uneven lengths
  - _Why:_ Line 194 uses `w-36` (fixed width) for the password display box, and unrevealed passwords show '••••••••••••' (12 dots). This fixed width doesn't scale with actual password length—a 6-char password and a 30-char password both show 12 dots, giving no hint of relative strength or length. This is a minor UX polish issue, not a blocker.
  - _Fix:_ Consider dynamic bullet count matching password length (e.g., 1 bullet per character, capped at 20): `'•'.repeat(Math.min(entry.password.length, 20))`. This gives users a sense of password strength without revealing plaintext. Or keep the current approach (simpler); it's not critical.
- **⚪ LOW · feedback** — Copy feedback icon persists only 2 seconds; non-obvious on slow clicks
  - _Why:_ The copy button icon changes from 'file' to 'check' and the Tooltip flips to 'Copied!' for 2 seconds, then reverts. On slow reads or casual usage, users might miss the icon/tooltip flicker. The feedback is present but subtle and easy to miss.
  - _Fix:_ Keep the current tooltip. Optionally add a 1-2 second visual pulse or brief confirmation on the button itself (e.g., background briefly becomes nominal-green, then reverts). Current approach is adequate per design rules; this is optional polish.


### Backup  
`/backup` · tier: admin

**Purpose.** Admin export/restore interface: lets the operator back up workspace data (memories, skills, presets, settings, preferences) to a JSON archive, or restore from a previous backup. Shows the last backup timestamp and item counts.

**Personas reviewed.**
- _Marcus: Daily Operator_ — Runs automated weekly backups on his self-hosted Odysseus. Lands on this page to verify the last backup ran successfully and occasionally does an ad-hoc export before a major config change. Expects a low-friction UX with clear confirmation that backups succeeded.
- _Priya: First-Time Restorer_ — Has a backup file from 3 months ago due to a config corruption. Nervous about the overwrite warning. Needs to understand what will be lost, restore safely, and confirm it worked. May need to undo/retry if something goes wrong.
- _Sam: Interrupted User_ — Mid-export, gets a system interrupt (network flicker, browser tab closed). Returns later wondering if the export completed, whether it's safe to re-run, and if partial state will confuse the system. Needs a clear recovery path.

**Works well.** Destructive-operation guard: import modal explicitly warns 'DESTRUCTIVE OPERATION' and requires two-step confirm (select file → modal with danger button).; Clear visual separation: export and import are side-by-side panels with distinct purposes, reducing confusion.; Progress feedback: both export and import show a labeled ProgressBar during execution, so the user isn't left wondering if anything is happening.

**Gaps (10).**

- **🔴 HIGH · missing-state** — No empty state for first-run or missing last backup
  - _Why:_ New users or users whose backups have been deleted land on the page with no context. The 'LAST BACKUP' section shows a Suspense fallback, and the InstrumentBand renders empty. This leaves the user confused about whether backups exist at all or if the feature is broken.
  - _Fix:_ Below the PageHeader, add a check: when lastBackup() is null/undefined, render an EmptyState with message 'NO BACKUPS YET — RUN YOUR FIRST EXPORT TO GET STARTED' and guidance on the export panel. This guards the InstrumentBand from rendering with no data.
- **🔴 HIGH · error-recovery** — Download button is non-functional
  - _Why:_ After export succeeds, a DOWNLOAD button appears but does nothing when clicked. The user sees 'READY' and clicks to get the file, but nothing happens — this is silent failure and looks like a broken feature.
  - _Fix:_ Wire the button to trigger a browser download: `onClick={() => { const blob = new Blob([JSON.stringify(backupData)], {type: 'application/json'}); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'odysseus-backup.json'; a.click(); }}`. Mock the exported data from the export function.
- **🔴 HIGH · error-recovery** — No error state for export/import failures
  - _Why:_ If the backend fails, network drops, or disk is full, the progress bar just hangs or vanishes. The user has no signal that something went wrong and cannot retry. Data loss risk.
  - _Fix:_ Add error state: `const [exportError, setExportError]` / `const [importError, setImportError]`. On failure, render a StatusFlag(status='alert') with error message and a RETRY button. Also disable the main button while in error state (forcing a retry flow).
- **🟠 MED · interaction** — No way to cancel an in-progress export or import
  - _Why:_ Once export/import starts, the action button is disabled and the user is locked in. On slow networks or if the user changes their mind (e.g., realizes they forgot to include a category), they cannot abort — only wait or hard-refresh.
  - _Fix:_ When exportProgress() !== null (or importProgress() !== null), show a CANCEL button next to the ProgressBar. Clicking it aborts the operation, clears the progress state, and resets the UI to pre-action state.
- **🟠 MED · information** — No metadata on selected backup file before restore
  - _Why:_ You select a .json file for import, but the UI only shows filename and size. If you have 10 backups, you cannot tell which is the right one (created date, what it contains) without opening each in an editor. This is especially bad if you're recovering from an error.
  - _Fix:_ After file selection, parse the JSON and display metadata in a Readout row under the drop zone: 'CREATED: 2026-05-20 12:34 | SIZE: 2.4 MB | SECTIONS: memories, skills, presets'. This shows the user exactly what they're about to restore.
- **🟠 MED · information** — Import confirm modal doesn't specify which sections will be restored
  - _Why:_ The modal warns 'will overwrite existing data for all sections included in the archive' but doesn't list them. A user doesn't know which specific data is at risk (just memories? everything?) without recalling or looking up the file.
  - _Fix:_ Add a detail to the modal: render a list or comma-separated row 'SECTIONS: memories, skills, presets, settings' (parsed from the selected file). This removes ambiguity and confirms exactly what will be replaced.
- **🟠 MED · feedback** — No visible success confirmation or next steps after import
  - _Why:_ Import shows 'RESTORE COMPLETE' status, but there's no next action or indication of what changed. The user doesn't know if they should refresh the page, whether new data is now live, or if the restore actually affected the app state (Phase 1 mock limitation).
  - _Fix:_ After importDone() is true, replace the status with a Stack containing: StatusFlag(nominal) 'RESTORE COMPLETE' + Button(primary) 'CLOSE & REFRESH' to trigger a page reload. Alternatively, auto-dismiss the success after 2–3 seconds and show a toast notification in the corner.
- **🟠 MED · trust-safety** — No confirmation modal before export
  - _Why:_ Export is one click with no summary or confirm step. A user can fat-finger the button or fat-click by habit. For an infrequently-touched admin action, a review step adds safety without much friction and builds confidence.
  - _Fix:_ Before runExport() triggers, show a Modal with title 'CONFIRM EXPORT'. List the selected categories (e.g. 'MEMORIES: 412 items, SKILLS: 8 items, ...'), estimate total size if known, and end with a danger-style button 'CONFIRM EXPORT'. This also surfaces the user's choices one more time.
- **⚪ LOW · content** — No help text or tooltips explaining backup categories
  - _Why:_ Checkbox labels ('MEMORIES', 'SKILLS', 'PRESETS', 'SETTINGS', 'PREFERENCES') are admin jargon. New users don't know what's the difference between SETTINGS and PREFERENCES, or what a SKILL counts as.
  - _Fix:_ Add an Icon(question) or Tooltip next to each category label (or a collapsible legend below the list) explaining: 'MEMORIES: RAG documents and embeddings. SKILLS: Custom agent tools. PRESETS: Chat model configs and system prompts. SETTINGS: Admin configuration (models, integrations, auth). PREFERENCES: User UI settings (theme, layout, notifications).'
- **⚪ LOW · efficiency** — No select-all / deselect-all shortcut for checkboxes
  - _Why:_ With 5 categories this is minor, but unchecking items individually is tedious if you want to exclude just one category or reset to all. No power-user affordance exists.
  - _Fix:_ Add two small Button(ghost, size='sm') above the checkbox list: 'ALL' and 'NONE'. Clicking 'ALL' sets includes to ALL_INCLUDES; clicking 'NONE' sets it to []. This saves repeated clicks for bulk changes.


### Shell  
`/shell` · tier: admin

**Purpose.** Allows the single admin operator to execute arbitrary shell commands on the host machine and view the scrollback output. Treated like a low-level admin console for troubleshooting and maintenance.

**Personas reviewed.**
- _Skilled ops engineer_ — Runs diagnostic commands (ps, df, lsof) to troubleshoot system issues, relies on command history to retry/modify previous commands, expects fast execution and clear output.
- _First-time explorer / hurried operator_ — Landed on /shell to check one thing (e.g., disk space), doesn't trust the output, uncertain whether the command succeeded, unsure how to interpret stderr vs. stdout, wants to undo or clear if they made a mistake.
- _Recovering from error_ — Ran a command that failed (connection timeout, permission denied), needs to see the error clearly, understand why it failed, retry with a different command, or see the exact command that was executed to verify it's what they meant.

**Works well.** Arrow-key history navigation is present and documented — standard terminal UX that ops will recognize.; Semantic coloring (commands bright, stderr alert, stdout dim) makes output scannable and errors visually distinct.; Danger notice is prominent (red border, warning icon, clear text) and guards comprehension that this is irreversible.

**Gaps (10).**

- **🔴 HIGH · feedback** — No feedback when command succeeds with no output
  - _Why:_ Many commands (mv, touch, mkdir, deployment scripts) succeed silently. User types `mkdir new-dir`, sees input cleared and status snap to READY, but no confirmation that the command ran at all. They will re-run it, unsure if it took. The running() flag goes false, but there's no visual feedback that the command completed successfully.
  - _Fix:_ When a command finishes with zero output lines, append a dim success marker (e.g., '  [ok]' or '  # success') to the scrollback. Or add a brief (1s) StatusFlag flash to 'info' tone saying 'DONE' before snapping back to READY. Use existing StatusFlag component in the actions row, just change its status prop momentarily.
- **🔴 HIGH · trust-safety** — No confirmation before running dangerous/destructive commands
  - _Why:_ Ops can type `rm -rf /`, hit Enter, and Odysseus will execute it (mock today, real on Phase 2 backend). There is a danger notice at the top, but it's static. A single mistype or muscle-memory mistake is irreversible. No gate, no 'are you sure' for dangerous patterns.
  - _Fix:_ Add a heuristic check: if the trimmed command starts with 'rm ' / 'rmdir' / 'kill -9' / 'truncate' / 'dd', or contains `sudo `, show a Modal confirm dialog before execution: 'Run this command? This cannot be undone.' Make the confirm button red (warn tone). Commander still has full freedom, but one extra click prevents fat-finger disasters.
- **🟠 MED · efficiency** — No way to clear/reset scrollback
  - _Why:_ Long sessions accumulate 50+ lines of output. User cannot clear the terminal to focus on the last command's result. After 20 commands, finding the relevant output becomes a needle-in-haystack problem. Standard terminal users expect `clear` or a UI button to reset view.
  - _Fix:_ Add a 'CLEAR' button next to the STATUS in the PageHeader actions row. It sets `lines` to empty; the user can still re-run `history` or arrow-key back if needed. Use Button variant='secondary' to keep it visually subdued (this is not a primary action).
- **🟠 MED · information** — No per-line timestamps or context
  - _Why:_ ShellLine has an `at` field (ISO timestamp), but it's never rendered. Long runs become undated: user can't tell if output is from 2 hours ago or 2 seconds ago, critical for 'did the task complete' decisions. In ops, time = causality.
  - _Fix:_ Render the timestamp for each line as a dim text on the right margin or as a micro-text prefix (e.g., '13:50:01'). Use a Tooltip or hover to show full ISO. Keep it dim and right-aligned so it doesn't clutter the command/output.
- **🟠 MED · information** — No indication of command execution time or exit status
  - _Why:_ ShellLine has kind='command' but no exit code or duration. User doesn't know if a slow command is hung or still running. No way to distinguish 'command exited 0' from 'command exited 1' (success vs. failure). Phase 2 backend will provide this, but Phase 1 should surface it.
  - _Fix:_ Append exit code as dim text after the command line (e.g., '$ uv sync   [exit 0]') or after the last output line ('[done 2.3s]'). Use Readout or a small dim span. This is critical for trust in the result.
- **🟠 MED · onboarding** — No empty state or getting-started guidance
  - _Why:_ First-time user lands on /shell, sees a blank scrollback and a cursor. They don't know what commands are even valid or what Odysseus can run. The subtitle says 'Execute commands directly on the server host' but doesn't guide them to try something safe (like `whoami`, `pwd`, `df -h`).
  - _Fix:_ If scrollback is empty (only shows mockInitialLines, which are pre-loaded for demo), add a Tile or small Markdown block above the terminal with two-three example commands they can click to run: 'Try: whoami | pwd | df -h'. Or add a comment in the placeholder: 'Tip: run whoami to test, df -h to check disk.' Keep it small; the danger notice is the priority.
- **⚪ LOW · efficiency** — No way to copy or select command for re-use
  - _Why:_ User ran a complex command 5 commands ago, wants to modify it and re-run. Arrow-key history only cycles backward from most recent. They must manually re-type or hope it's still in scrollback. No way to copy a line from output.
  - _Fix:_ Make each output line selectable/copyable. On hover, show a copy icon (or on focus). Alternatively, make the entire scrollback text-selectable (remove `select-none` from the output span and let browser copy work). History navigation is good, but copy-paste is faster for long commands.
- **⚪ LOW · interaction** — Scrollback auto-scroll can get out of sync with user reading
  - _Why:_ Every output line scrolls to bottom (onScrollBottom callback fires 120ms per line). If user scrolls up to re-read an earlier command while new output is still streaming, the view jumps back to bottom, losing their context. Frustrating during long output (e.g., `tail -f` simulation).
  - _Fix:_ Only auto-scroll to bottom if the user is already viewing the bottom of the scrollback. Detect if scrollRef.scrollTop is within ~50px of scrollHeight before each append; if not, skip auto-scroll. Once the user scrolls back to bottom manually, resume auto-scroll. This is a common terminal UX pattern.
- **⚪ LOW · interaction** — No keyboard shortcut to focus input or cancel running command
  - _Why:_ User might scroll far up, want to run a new command, and have to scroll back down and click the input. No Escape to clear the input field. No Ctrl+C to abort a running command (though mocking doesn't support it yet, Phase 2 should).
  - _Fix:_ Add Escape key handler: if input is focused and has text, clear it; if empty, unfocus. Add Ctrl+C handler to set a 'cancel request' flag (Phase 2 backend will kill the process). Focus input on mount (already done), so user can start typing immediately.
- **⚪ LOW · efficiency** — No search or filter within scrollback
  - _Why:_ 100 lines of output; user wants to find when they ran a specific command. Must scroll manually. Browser find (Cmd+F) will search the whole page, not the logical output. No way to grep the scrollback.
  - _Fix:_ Add an optional search field (Input + Icon search, small, above or below the terminal) that filters lines matching the input text. Highlight matches (add a tmp style class on matching spans). Pressing Escape or clicking the X clears the filter. Keep it minimal; only add if scrollback growth becomes a real problem in production.
