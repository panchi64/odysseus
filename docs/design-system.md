# Odysseus Design System — **Instrument**

*A quiet, high-precision interface language: Swiss neo-grotesque structure, pure-neutral surfaces, and a monospaced second voice reserved for the machine.*

**Version 1.0** · Status: Foundation spec · Supersedes *Terminal-HUD 0.1*

---

## 0. Reading this document

This is a foundation spec, not a component catalogue. It defines the *rules* and the *tokens* — the atomic decisions everything else inherits from. Someone should be able to open an empty CSS file and reproduce the look from the values below without guessing.

Two surface modes are defined throughout: **Ink** (dark, default) and **Paper** (light). They share structure, grid, type, and motion — only color and elevation differ. Build a component once; it works in both by swapping the token set.

If this document and the code disagree, this document is wrong and should be fixed. It leads the implementation in `frontend/src/ui/theme/`, and nowhere else declares a raw value.

### What changed from Terminal-HUD 0.1, and why

The previous system was a faithful terminal/FUI pastiche: everything monospaced, everything uppercase, every corner square, no shadows, no easing. It was distinctive and it was *loud* — the density that made a cockpit readout legible made a 19-surface workspace feel like clutter, because every element shouted at the same volume and nothing could recede.

Instrument keeps the skeleton and changes the voice:

| | Terminal-HUD 0.1 | Instrument 1.0 |
|---|---|---|
| Type | Mono everywhere | **Sans for the interface, mono for the machine** (§2) |
| Labels | `UPPERCASE` + tracking, always | Sentence case; uppercase mono reserved for telemetry |
| Color | Green-tinted near-blacks, off-whites | **Pure `#000` / pure `#FFF`**, true neutral grays |
| Accent | Phosphor green, both modes | Green in Ink, **cerulean in Paper** — and rationed harder |
| Elevation | Forbidden (no shadows) | **Subtle shadow**, plus an accent shadow for primary focus |
| Corners | Square, always | Square for data grids; **3px controls, 6px panels** |
| Borders | "Free ink" — everywhere | **The exception** (§7); space and surface value separate first |
| Motion | Hard-cut steps only | **Two registers** — eased for the interface, instant for the machine (§8) |

What deliberately survived, because it was the good part: the 4px grid, the hairline data grid, tabular figures, semantic-only color, registration marks, and diegetic microcopy.

---

## 1. Design principles

1. **Volume is hierarchy.** The old system's failure was that everything was equally loud. Most of the interface should sit at a *low* volume — recessive, neutral, unhurried — so the one thing that matters can be the only thing that is bright, elevated, or colored. If two things on a screen are both shouting, one of them is wrong.
2. **Two voices, never blurred.** The interface speaks in sans. The machine speaks in mono. This is a semantic distinction, not a decorative one (§2).
3. **Precision without density theater.** Numbers align, fields don't reflow, state is always visible rather than implied. But density is no longer a goal in itself — whitespace is a legitimate tool, and an empty region is not wasted ink.
4. **Semantic color only.** The resting palette is pure neutral. Color appears to *mean* something — nominal, warning, alert, info — or to mark the single element holding primary focus. A screen with nothing happening is grayscale.
5. **Systematic, not bespoke.** Spacing, naming, iconography, and microcopy follow consistent rules, so a screen the operator has never seen still reads as familiar.
6. **Not a generic AI app.** The signature devices — the hairline grid, registration marks, diegetic telemetry, the mono/sans split, hard-cut machine motion — are what keep this from resolving into another rounded-card chat interface. Restraint is the goal; anonymity is not.

---

## 2. The two voices

**This is the central idea of the system.** Everything else is in service of it.

### Sans — the interface speaking to the operator

`Helvetica Neue`. Everything the *product* says: page titles, field labels, body copy, button text, menu items, prose, empty states, explanations, errors written for a human.

Sans is what the operator's attention lands on. It is calm, sentence-cased, generously spaced, and it animates smoothly (§8).

### Mono — the machine showing its work

`JetBrains Mono`. Everything the *system* emits: identifiers, hashes, timestamps, durations, token counts, model names, file paths, shell output, code, diffs, coordinates, run states, latency figures, version strings.

Mono is deliberately **used sparingly and sized down**. It is ambient — the texture of a machine calculating in the background, not something to read first. It is often dim, often uppercase, always tabular, and it **never animates smoothly** (§8): mono state changes are instantaneous, because a computer does not ease.

### The test

> Would a person have written this sentence, or did a process emit this value?

Person → sans. Process → mono. A model *name* (`qwen3-30b-a3b`) is emitted by a process: mono. The word "Model" labelling it is the interface talking: sans.

When genuinely ambiguous, choose sans — the failure mode of too much mono is the cluttered terminal look this system exists to leave behind.

```
┌──────────────────────────────────────────┐
│  Active model                     ← sans │
│  Qwen3 30B A3B                    ← sans │
│  QWEN3-30B-A3B-Q4 · 18.2 GB       ← mono │
│                                          │
│  Context used                     ← sans │
│  48%                              ← sans │
│  63,104 / 131,072 TOK             ← mono │
└──────────────────────────────────────────┘
```

---

## 3. Grid & spacing

### Base unit

**4px.** All spacing, sizing, and positioning are multiples of 4. This is unchanged and non-negotiable — it is what makes the layout feel engineered rather than arranged.

### Spacing scale

| Token | px | Typical use |
|---|---|---|
| `space-0` | 0 | Flush elements |
| `space-1` | 4 | Label-to-value gaps, intra-control padding |
| `space-2` | 8 | Padding inside dense cells, icon-to-text |
| `space-3` | 12 | Control padding, group separation |
| `space-4` | 16 | Panel padding (default) |
| `space-5` | 20 | Panel padding, roomy |
| `space-6` | 24 | Section separation |
| `space-8` | 32 | Major region separation |
| `space-12` | 48 | Page-level separation, above a display title |

### Density

Instrument runs at **one step less dense** than Terminal-HUD. Where the old system reached for `space-1`/`space-2` inside a panel, reach for `space-2`/`space-3`. Where a page used `space-4` between sections, use `space-6`.

The exception is **tabular data** — tables, instrument bands, log output, list rows. Density is a virtue there because scanning many rows is the task. Keep those at `space-1`/`space-2` vertical.

### Margins & gutters

- **Gutters:** `space-4` default; `space-2` inside dense tabular regions.
- **Viewport margins:** `space-6` minimum, `space-8` on wide layouts.
- **Reading measure:** prose caps at ~72ch. Nothing forces the operator to track a line across a 2560px display.

---

## 4. Typography

### Typefaces

| Role | Stack | Notes |
|---|---|---|
| **Sans** | `"Helvetica Neue", Helvetica, Arial, system-ui, sans-serif` | The interface voice. Not self-hosted — Helvetica Neue is not licensable for web serving, and it is present on the target machine. Arial/Liberation are metric-compatible enough that the fallback degrades gracefully rather than reflowing. |
| **Mono** | `"JetBrains Mono", ui-monospace, SFMono-Regular, monospace` | The machine voice. Self-hosted woff2, subset (see `fonts.css`), including Braille Patterns for throbbers. |
| **Display** | *= Sans* | There is no separate display face. Oswald is retired: a heavy condensed grotesque was the loudest thing on any screen it appeared on, which §1.1 forbids. Display size is Helvetica at 40px with negative tracking. |

### Two scales: chrome and reading

There are **two anchors**, and keeping them apart is the point.

The **interface scale** (`--type-*`) dresses chrome — rails, labels, readouts,
tables, controls — and stays dense at a 13px body, macOS system-text density.
That is the right register for an instrument panel you *scan*.

The **reading scale** (`--prose-*`) dresses rendered markdown and nothing else —
assistant messages, research reports, documents — and is anchored on 16px/1.5,
the browser default and the size long-form reading is standardized around.

One scale cannot serve both. Pushing chrome up to 16px bloats a nineteen-row rail
into something you scroll; holding prose at 13px asks the operator to read a
five-paragraph answer at rail-label size. The surfaces differ in *how they are
looked at*, so they differ in scale.

#### Interface scale

| Token | Size/LH | Family | Weight | Case | Use |
|---|---|---|---|---|---|
| `micro` | 10 / 14 | Mono | 400 | as-is | Ambient telemetry, fine print, precision coordinates |
| `meta` | 11 / 16 | Mono | 500 | UPPER, +0.08em | Machine labels & state: `RUN-0341`, `LIVE`, `QUEUED` |
| `label` | 12 / 16 | Sans | 500 | Sentence | Field labels, column headers, section eyebrows |
| `code` | 12 / 16 | Mono | 400 | as-is | Code, diffs, patches inside chrome |
| `body` | 13 / 20 | Sans | 400 | Sentence | Default interface text |
| `readout` | 20 / 28 | Sans | 500 | Sentence | Primary values, panel figures |
| `readout-lg` | 32 / 40 | Sans | 500 | Sentence | Hero value — one per screen, tabular figures |
| `display` | 40 / 44 | Sans | 600 | Sentence | Page/section titles, −0.02em tracking |

#### Reading scale (`.ody-prose` only)

| Token | Size/LH | Family | Weight | Use |
|---|---|---|---|---|
| `prose-code` | 14 / 24 | Mono | 400 | Inline and fenced code |
| `prose` | 16 / 24 | Sans | 400 | Paragraphs — 1.5, the WCAG 1.4.12 reading floor |
| `prose-h4` | 16 / 24 | Sans | 600 | `h4`; `h5`/`h6` share it at `text` rather than `text-bright` |
| `prose-h3` | 20 / 28 | Sans | 600 | `h3` |
| `prose-h2` | 24 / 32 | Sans | 600 | `h2`, −0.02em tracking |
| `prose-h1` | 28 / 36 | Sans | 600 | `h1`, −0.02em tracking |

**Four heading levels need four steps.** Rendered markdown used to put `h3` *and*
`h4` at body size, so a heading was separated from its own paragraph by weight
alone — which in a long assistant answer reads as a bolded sentence, not as
structure. `h5`/`h6` are in the ladder too, because markdown emits them and an
unstyled `h6` falls to the browser default of ~10.7px in the one place the
operator does not write the source.

**Prose code runs one step under the sans beside it.** JetBrains Mono's x-height
is large enough that a size-matched inline `code` reads as *bigger* than the
sentence around it; 14/16 is the ~0.875em every prose stylesheet on the web
converges on. Its line-height stays on the prose 24px so an inline span never
opens up the line it sits in.

**Never reach for `--type-*` inside `.ody-prose`, or `--prose-*` outside it.**
That is precisely what re-couples the two scales, and the next time one moves the
other follows silently.

### Rules

- **Labels are sentence case.** "Context used", not "CONTEXT USED". Uppercase is now a *signal* (it means "machine"), and a signal used everywhere signals nothing.
- **Uppercase belongs to `meta` and `micro` only**, always in mono, always with +0.08em tracking, usually dimmed.
- **Display type takes negative tracking** (−0.02em), as do prose `h1`/`h2`. Helvetica at those sizes set at 0 looks loose; this is the single most recognizable Swiss-modernist tell.
- **Tabular figures for anything that changes or aligns.** Set globally; never turn it off in a table or a counter.
- **Left-align, ragged right.** No justification. Centering only for an isolated hero readout.
- Hierarchy is **size → weight → brightness**, in that order. Reach for color last, and usually not at all.
- **A control's height is derived from its type, not chosen.** Line-height plus the padding the size is meant to read as (`Button` sm 24 / md 32 / lg 40 over the interface scale). If a step ever moves, its control heights move with it — a box sized against the old scale clips the new text.

---

## 5. Color

The base is pure neutral. Both modes are built on true black and true white — no green tint, no warm paper, no off-white. The old tints read as a *theme*; pure neutrals read as a *material*.

### 5.1 Ink (dark — default)

| Token | Hex | Use |
|---|---|---|
| `bg` | `#000000` | App background — pure black |
| `surface` | `#0A0A0A` | Panels, cards |
| `surface-raised` | `#161616` | Hover, selected, nested surfaces |
| `surface-sunken` | `#0F0F0F` | A fill *set into* the page, not lifted off it — one speaker's turn in a transcript. Nowhere below black to go, so it steps up. **Matched to Paper perceptually, not by hex delta:** the same raw step off `#000` carries far less perceived lightness than off `#FFF`, so a mirrored value read visibly fainter than its Paper twin. ΔL\* ≈ 4.3 from `bg`, against Paper's ≈ 4.2 |
| `line` | `#212121` | Hairline borders (the default rule) |
| `line-strong` | `#333333` | Emphasized borders, active control outlines |
| `text-dim` | `#6E6E6E` | Ambient telemetry, inactive labels (3.9:1) |
| `text` | `#A8A8A8` | Default text (8.3:1) |
| `text-bright` | `#FFFFFF` | Primary values, active state — pure white |

| Accent | Hex | Meaning |
|---|---|---|
| `accent` | `#34D67F` | **Signature / primary focus.** Phosphor green, retuned off the CRT glow |
| `accent-nominal` | `#34D67F` | Active, healthy, OK |
| `accent-warn` | `#F2A93B` | Caution, degraded |
| `accent-alert` | `#FF5C5C` | Error, critical, destructive |
| `accent-info` | `#5AA2FF` | Live data, secondary signal |

### 5.2 Paper (light)

| Token | Hex | Use |
|---|---|---|
| `bg` | `#FFFFFF` | App background — pure white |
| `surface` | `#FFFFFF` | Panels sit *level* with the page; a hairline and a shadow separate them, not a fill (§6) |
| `surface-raised` | `#F5F5F4` | Hover, selected, nested surfaces |
| `surface-sunken` | `#F4F3F0` | **The one place Paper cannot hold "panels sit level with the page."** A transcript alternates two voices and tells them apart by fill; with `surface` = `bg` = white, that distinction vanishes. So it steps *down* — but only to a tint. Push it further (`#F0EFEC` was tried) and it crosses into a visible panel behind every operator turn, which is the thing this must not become |
| `line` | `#E4E4E1` | Hairline borders |
| `line-strong` | `#CFCFCB` | Emphasized borders |
| `text-dim` | `#8A8A85` | Ambient telemetry (3.5:1) |
| `text` | `#3D3D3A` | Default text (10.9:1) |
| `text-bright` | `#000000` | Primary values — pure black |

| Accent | Hex | Meaning |
|---|---|---|
| `accent` | `#0077B6` | **Signature / primary focus.** Cerulean (4.9:1 on white) |
| `accent-nominal` | `#0E7A46` | Active, healthy, OK |
| `accent-warn` | `#9A6510` | Caution, degraded |
| `accent-alert` | `#C0342B` | Error, critical, destructive |
| `accent-info` | `#0F5FA8` | Live data, secondary signal |

> **The signature accent is mode-dependent and that is intentional.** Phosphor green is the product's lineage and it belongs on black; on white it turns acidic and illegible. Cerulean is the same idea executed for a light substrate — cool, precise, instrument-like. `accent-nominal` stays green in both modes because green *means* "OK" independently of the theme.

> **These five hexes are defaults, not constants.** The operator can set any of them, per mode, from Settings → Appearance (`ui/theme/accent-store.ts`, which overrides the raw `--accent*` custom properties through one scoped stylesheet — so every utility, `shadow-accent`, and every `LedEdge` tone follows without knowing the feature exists).
>
> **What that does and does not relax.** The *set* of accents is closed and the meaning of each is fixed — rules 1–5 below are untouched, because they govern the token, not the hue. An operator choosing a different red for `accent-alert` has restyled "error"; they have not made `accent-alert` available for decoration.
>
> **§12's 4.5:1 floor stops being a guarantee and becomes a warning.** The shipped values are tuned to pass and a test asserts they still do (`ui/theme/contrast.test.ts`), but a chosen value is the operator's call: the editor reports the ratio and says when it is below the floor, and then honours it. Blocking would be the wrong trade — it is their interface, and a contrast ratio is information, not a permission.

### Usage rules

1. **A screen at rest is grayscale.** If nothing is running, failing, or awaiting the operator, no hue appears.
2. **One meaning per accent, system-wide.** `accent-warn` is never a brand color, a chart series, or a highlight.
3. **Brightness separates active from inactive**, not hue (`text-bright` vs `text` vs `text-dim`).
4. **At most two accents visible in a region.** Three reads as decoration.
5. **`accent` marks primary focus, and there is at most one per screen** — the primary action, the live run, the awaiting-approval card. It is the only place an accent-tinted shadow is permitted (§6).

---

## 6. Elevation & shadow

Terminal-HUD banned shadows outright. Instrument uses them, sparingly, and for one purpose: **saying what is on top and what needs attention.** Never for mood, never for a card that is merely present.

The two modes model elevation differently, because they physically must:

- **Paper elevates with shadow.** Surfaces are pure white and level with the background, so a hairline plus a soft shadow is the only thing that lifts them.
- **Ink elevates with surface value.** A black shadow on a black background is invisible. Depth in Ink comes from `surface` → `surface-raised` and the hairline; shadow is added only for true overlays, where it darkens the content beneath.

| Token | Ink | Paper | Use |
|---|---|---|---|
| `shadow-1` | `0 1px 2px rgba(0,0,0,.60)` | `0 1px 2px rgba(0,0,0,.05), 0 1px 1px rgba(0,0,0,.04)` | Resting elevation: cards, popovers, sticky headers |
| `shadow-2` | `0 8px 32px rgba(0,0,0,.80)` | `0 12px 32px -8px rgba(0,0,0,.16), 0 2px 6px rgba(0,0,0,.06)` | Overlays: modals, drawers, menus, lightbox |
| `shadow-focus` | soft white halo, `0 0 8px 1px @22%` + `0 0 22px 5px @11%` | same shape, dark | **Keyboard focus.** A halo, never an outline |
| `shadow-bloom` | wide white aura, blur 24→220px, opacity 10%→3% | same shape, dark | **The screen's primary surface** — the composer |
| `shadow-accent` | `0 2px 12px -2px accent@55%, 0 10px 36px -10px accent@38%` | same formula | Semantic emphasis on a panel: a live run, a blocking approval |
| `shadow-alert` | same shape, `accent-alert` | same formula | A panel whose state is genuinely wrong |

### No zero-blur layers, anywhere

**A shadow layer with no blur is a border.** `0 0 0 1px <color>` does not read as light coming off an element; it reads as an outline drawn around it, and against smoothed corners it reads as a cutout. Every attention shadow in this system — `shadow-focus`, `shadow-bloom`, `shadow-accent`, `shadow-alert` — is built from blurred layers only.

The single exception is the **hairline ring** carried inside `shadow-1`/`shadow-2`/`shadow-bloom` at 5–7% opacity. That is not an attention signal; it is the surface's edge definition, folded into the shadow so it costs no layout (§7). In Paper it is load-bearing: a white card on a white page has no other edge.

### Attention is drawn by luminance, not hue

**`shadow-bloom` is neutral** — white in Ink, dark in Paper — and it is the aura that marks the screen's primary surface. This is not a concession; it is §1.3 and §5 applied honestly. Hierarchy comes from brightness, and hue is reserved for meaning. A *colored* bloom grabs attention using the one channel that is supposed to carry semantics, and it competes with every semantic accent on the same screen. A neutral bloom pulls the eye just as hard and costs the palette nothing.

It follows that the **primary button carries no halo either**. An inverted bright slab is already the brightest thing in its region, and that is the whole signal.

**Wide and faint beats tight and strong.** Blur ramps 24→220px while opacity falls to 3%, and the outer layers carry *positive* spread so the aura grows outward. A tight, strong glow around a large card reads as an edge cutout; a wide, barely-there one reads as light. (Note that any ancestor with `overflow` other than `visible` clips a bloom this wide — its faintness is what keeps that clip from showing as a hard line.)

### Rules

1. **Keyboard focus is a neutral halo, never an outline** — and **text-entry fields get nothing at all.** `input` and `textarea` announce focus with a blinking caret, an unambiguous native indicator no other control has; a shadow on top of it is decoration around the thing the operator is already looking at. Everything else (button, link, select, summary, anything tabbable) keeps the halo, and it must stay *visible*: a focused button has no caret, and a keyboard user who cannot see where they are is the accessibility failure this rule exists to prevent.
2. **`shadow-bloom` is rationed to one surface per screen** — the operator's point of action, which on chat and the home launchpad is the composer. It is applied **at rest**, never behind `hover:` or `focus-within:`: that surface is the point of the screen whether or not the cursor is on it, and a glow that appears only once the operator has committed to acting tells them something they no longer need to know.
3. **`shadow-accent` is for semantic state, not for attention.** It marks a panel that is genuinely *doing* something — a live run, an approval that is blocking. It is not the composer's and not the primary button's.
4. **No shadow on a data grid.** Tables, instrument bands, and list rows sit flat. Shadows separate *layers*, and rows are not layers.
5. **Shadows never replace a surface's hairline.** Every elevated surface keeps the ring folded into its shadow so it stays defined against any backdrop.

---

## 7. Corners & borders

Corners are **smoothed, not rounded.** The intent is a machined edge — a chamfer — not a soft pill.

| Token | px | Applies to |
|---|---|---|
| `radius-0` | 0 | Table cells, instrument bands, list rows, full-bleed regions, anything in a hairline grid |
| `radius-1` | 3 | Controls: buttons, inputs, chips, checkboxes, tabs, menu items |
| `radius-2` | 6 | Containers: panels, cards, modals, drawers, popovers, toasts |
| `radius-full` | 9999 | Status dots and count pills only |

**The grid stays square.** Anything that participates in a shared hairline grid takes `radius-0` — rounding a table cell breaks the ruled structure that makes tabular data scannable, and that structure is a keeper.

### Borders — the exception, not the default

Terminal-HUD called the hairline "free ink" and used it everywhere. It is not free. A border is a line the eye must resolve, and a screen of bordered panels inside a bordered layout beside a bordered rail is the specific thing that made the old interface feel cluttered: **every region announced its own edge, whether or not anything needed dividing there.**

The order of preference for separating two things:

1. **Space.** If a gap says "these are different", that is the whole job. Most separation is this.
2. **Surface value.** A panel one step lighter than the page is an object without being a box.
3. **The shadow's own ring.** `shadow-1` and `shadow-2` carry a 1px hairline ring as part of the shadow, so an elevated surface stays defined without a border in layout — this is what lets panels, tiles, popovers, modals, and toasts drop their borders and still read as distinct.
4. **A real border — last.** Only where a line does work nothing else can.

**A border is justified when:**

- it is a cell edge in a **ruled data grid** — a table, an instrument band, a genuinely tabular list, where the rule aligns values across rows and is doing structural work;
- it is a **control's own edge**, where the border *is* the affordance (a secondary button, a text field's resting state);
- it is a **process timeline** rail, where an unbroken vertical line is the thing being communicated.

**A border is not justified** under a page title, under a tab strip, around every panel, under every list row, between a panel's header and its body, around a chip, or down the side of a nav rail. All of those were borders drawn where the eye had already found the break.

- **Hairline (1px, `line`)** for the justified cases above.
- **`line-strong`** marks an emphasized or hovered edge.
- **2px emphasis borders are deprecated.** Selection is now `surface-raised` + `text-bright` + `shadow-focus`. A 2px border shifts layout by a pixel on state change and reads heavy against smoothed corners.

---

## 8. Motion — the two registers

Motion follows the two voices (§2), and this is the most distinctive rule in the system.

### Human register — sans surfaces

Anything the interface does on the operator's behalf moves **smoothly**: panels, menus, drawers, modals, toasts, hovers, focus rings, disclosure, tab changes, color transitions on sans elements.

```
--motion-fast:  120ms
--motion-base:  180ms
--ease:         cubic-bezier(0.2, 0, 0, 1)   /* decelerate */
```

Short, decelerating, never bouncing. The feel is *refined and settled* — a well-damped mechanism, not a spring. Nothing exceeds 240ms; nothing overshoots.

### Machine register — mono elements

Anything rendered in mono changes **instantly**. No transition, no fade, no interpolation.

```
--motion-machine: 0ms
--ease-machine:   steps(1, end)
```

A token counter ticking, a run state flipping `QUEUED` → `RUNNING`, a latency figure updating, a log line appending, a hash resolving — these snap. The operator should feel the computer acting at machine speed while the interface around it moves at human speed.

**This contrast is the effect.** A mono value that eases into place reads as decoration and undercuts the premise; a sans panel that hard-cuts reads as broken. Match the register to the voice.

### The reveal — how anything in the human voice arrives

One motion, one component (`Reveal`), used for everything the interface puts on screen on the operator's behalf: an overlay opening, a panel revealing, a turn landing in the transcript, a run of answer text arriving.

**It is a blur fade.** Content resolves out of a blur as it fades, and with `rise`, settles the last few pixels into place while it does — so it reads as *materializing into position* rather than as a light being turned up on something that was already sitting there. That distinction is most of the refinement; opacity alone is the generic version of this.

Three parameters, no variants: `distance` (0 for a fade, 4px for an overlay settling, 10px for a turn arriving — beyond that the movement starts reading as decoration), `duration` (180ms default, 240ms ceiling), and `blur` (3px default; `0` opts a very large surface out, where blurring the whole raster costs more than the effect returns).

Two things it deliberately does not do. **It never exits** — an exit animation delays the operator getting what they asked for. **It does not replay on update** — the animation fires on mount, so a streaming block does not re-animate on every delta.

**It must never reach the machine's voice.** The per-character reveal in the answer skips code, samples, **tables** and math outright: a code block or a data grid landing hard *inside* an answer that eases in around it is the two registers visible in a single paragraph, and blurring it in would erase the one contrast the transcript is built on.

A table earns that exclusion three times over — its header band is already mono because a column header names a machine field, its cells are values a process emitted rather than sentences a person wrote (§2), and a grid is read in two dimensions, so a reveal sweeping left-to-right through cells reads as flicker rather than as arrival.

### The construction reveal — how a region the operator opens arrives

`Reveal` says *content materialized here*. Some regions want to say *a place was
made, and then filled*, and that is a different sentence: a region the operator
deliberately opened should read as having been built for them, not as having been
there all along with the light turned up.

So a **construction reveal** draws its own frame before it fills. A single `+` at
the origin corner splits; one half travels the top edge with a hairline drawn
between them; both drop down the sides as the sides close; and the glass surface
resolves inside the frame that has just been described. Closing runs the gesture
in reverse, so the region is taken apart rather than switched off.

Three surfaces use it, and the list is meant to stay short: the chat **View**,
the **settings dialog**, and the **⌘K palette**. It is the arrival of a place, so
it belongs to things that are places. A menu, a toast, a confirm and a form
dialog all keep the ordinary reveal — being *built* would be theatre at that
size, and the gesture stops meaning anything if everything performs it.

It runs at the **stage budget (320ms)**, which is not a new exception to the
ceiling below: the ceiling governs what the operator is waiting on, and a whole
region arriving or leaving already has that budget. Its phases overlap; strictly
sequential beats inside 320ms read as a stutter rather than as one continuous
gesture. The content inside is **one fade, never a per-child stagger**.

The frame is **inset**, not flush to the region's edge. Flush, it lands a hairline
away from whatever edge was already there, and two rules a few pixels apart read
as a mistake rather than as a frame. Where a neighbour's edge collides, the fix
belongs to the neighbour — a splitter beside a self-framing panel hides its own
rule until reached for.

**The frosted surface is the framed region itself**, never a card wrapped around
it. Give the fill a radius and an elevation and it becomes a second container:
the frosted area then reads as a pane the marks are decorating rather than as the
pane the marks describe. Anything inside a framed region is therefore bare — one
glass layer, at the frame's own box.

And be honest about what the blur buys. Over a flat ground it does nothing,
because blurring a uniform field returns that field; translucency and the value
shift are what make it read as a material. It pays where something is genuinely
behind it — an overlay over the transcript, a dialog over a working page.

### Permitted animations

- Eased (human): the reveal above, hover and focus transitions, height on disclosure, ambient state colour (240ms, §10.9).
- Stepped (machine): caret blink, the braille throbber (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) as a "working now" indicator, live-state pulse, value tick-over, **the reasoning wall** (§10.9).

The chat transcript is where the two registers are visible at once, and it is the reference implementation: the mono reasoning wall lands hard, the sans answer beneath it eases in token by token.

### Forbidden

Bouncing, springs, overshoot, staggered cascades, eased *decorative* spinners, parallax, anything over 240ms, and any animation that runs while the operator is not looking at it.

**One stated exception to the 240ms ceiling: the answer's per-character reveal (320ms).** The ceiling governs anything the operator is *waiting on* — a control answering a click, an overlay opening — where a long duration reads as lag. Nothing waits on this one: it is paced to a stream that already takes seconds, and a character is legible well before it finishes settling. Under the ceiling the resolve is over before the eye reaches it. If a second case ever wants this exemption, it has to clear the same bar — nothing is waiting.

**And the reveal's stagger is paced to the arrival rate, not fixed.** A fixed per-character step cannot serve both ends of the range: fast enough for 300 characters a second and it is invisible at 30; slow enough to see at 30 and each run is still resolving when the next three have landed, which puts later characters ahead of earlier ones and scrambles the order outright. Each run is instead spread over roughly the measured gap until the next one, so the reveal front travels at whatever speed the model is producing and looks the same at any of them. A burst too large to stagger inside that gap resolves its overflow together, which bounds how far the reveal can trail the text — the caret sits at the true end, and a reveal that lagged would strand it ahead of anything visible.

### Reduced motion

`prefers-reduced-motion: reduce` collapses the human register to 0ms. The machine register is already 0ms, so it is unaffected — the throbber is the one exception and is retained as a functional live indicator.

---

## 9. Iconography

- **Stroke-based, 1.5px visual weight**, geometric, never friendly or filled. Two source grids (16px bespoke, 24px Iconoir) are normalized to a uniform stroke by the `Icon` primitive, which also supplies round caps and joins.
- **Corners are smoothed, not square.** A rect-based glyph carries `rx="1"` on the 16px grid, so an icon's corners speak the same 3px/6px language as the controls and panels around it (§7). Hard corners survive only where the shape *is* a hard corner — a registration mark, a crosshair.
- **Every glyph fills ~75% of its box.** That is where the Iconoir set sits; a bespoke glyph drawn edge-to-edge reads a full size step larger than its neighbours even though both render at 16px. Optical size, not nominal size, is what the eye compares.
- **Colour comes from `currentColor`**, so an icon takes the tone of the text beside it and re-colours with the theme. Never hardcode a fill or stroke colour.
- **The glyph names the action, not the metaphor everyone else uses.** A paper plane for send and an upload tray for attach are the two most generic marks in messaging UI — the exact look this system is trying not to have, and both were also the busiest shapes in the set at 16px. Send is a **departure arrow** (a diagonal, three straight lines); attaching a document is the **`file` body carrying a `plus`**, because attaching is not uploading — `upload`/`download` keep the arrow-and-tray, and they mean the server.
- **Redraw a pair, or neither.** `upload`/`download` are read as mirrors of each other; changing one alone is how a set starts to drift.
- No emoji, ever.
- **Registration marks are retained** — corner `+` crosshairs, reticles, diamond nodes — and they are one of the system's signatures. Use them at `text-dim` and at `micro` scale so they frame without competing.
- **A registration mark must bracket an object, not the window.** They belong on `PageHeader`, framing the plate that holds the asset id, title, subtitle and status badge; on a hero card; on a lightbox. They do **not** go on the shell's content region — that put two crosses just above the page and two in the bottom corners of the screen, framing the viewport rather than anything in it, which is the one job a registration mark has. Whatever they bracket needs enough inset (~20px) that the marks never collide with the content.
- Icons inherit `currentColor` and follow the text tone they sit beside.

---

## 10. Components

Anatomy plus tokens. These map directly onto `frontend/src/ui/`.

### 10.1 Field — label + value

The atomic unit. A sans `label` (sentence case, `text-dim`) above or beside a `body`/`readout` value (`text-bright`). An optional `meta` line beneath carries the machine detail.

```
Active model                  ← label,   sans 12, dim
Qwen3 30B A3B                 ← readout, sans 20, bright
QWEN3-30B-A3B-Q4 · 18.2 GB    ← meta,    mono 11, dim, uppercase
```

### 10.2 Panel

`surface` fill, `radius-2`, `space-4` padding, `shadow-1` (which carries its own hairline ring). No border. Optional header: sans `label` left, meta/status right. Selected state lifts to `surface-raised` — never a 2px border.

`Composer` takes a `bare` prop too, but it means something narrower: **it drops the fill and keeps the bloom.** For a composer sitting inside another surface (the research intake, in a `Panel`), a fill on a fill is the box-in-a-box §7 exists to stop, and it reads as a grey slab. The bloom is not part of that problem — it is *light, not a surface*, and it is the thing that says "type here". A bare `Panel` around a bare `Composer` leaves exactly one thing on the page: the aura.

A `bare` panel also keeps its **state** shadow (`active`/`alert`) while dropping the resting `shadow-1`. `shadow-1` exists to define a surface and there isn't one; a live or failing state is semantics, and a panel that drops its fill shouldn't go silent about being live.

**`bare` drops the surface entirely** — no fill, no shadow, no ring, no card padding. The panel becomes its label and its content, sitting directly on the page.

This is for regions that should read as *behind* the interface rather than as objects on it: the home page's recent-threads and in-flight lists, the system strip. They are things the operator glances past on the way to the composer, and giving each one a card turned the launchpad into a wall of boxes competing with the single surface that matters. Structure still comes from the label and the spacing — it just stops being a container.

The rule generalizes: **a card is a claim on attention.** Anything ambient — telemetry, recent items, background activity — should be bare, so the operator can look past it to what is live.

### 10.3 Instrument band

Full-width strip of densely packed machine fields, hairline-separated, `radius-0`, `space-2` padding, mono throughout. This is where density stays aggressive and where mono is at its densest — it is explicitly the machine's own readout.

### 10.4 Readout

The hero value: `readout-lg`, sans, `text-bright`, tabular, with a dim sans `label`. One per screen. Its supporting machine detail goes in a `meta` line, not in the readout itself.

### 10.5 Status flag

A small `meta` label — uppercase mono, no fill, no border. This is machine state, so it snaps between values with no transition.

**The dot carries the hue; the label stays dim.** A status flag reports, it does not ask. A whole word in an accent colour reads as a demand for attention wherever it appears, and a screen with a dozen flags then makes a dozen demands — which is how an accent budget (§5.4) gets spent on nothing.

The exception is `warn` and `alert`, which keep the accent on the label too. Those are the two states that genuinely need to interrupt, and a failure the operator can miss is worse than one more colour on the page. That exception is what makes the rule worth having: when only real problems are coloured, a coloured word means something.

### 10.6 Tile / nav card

`surface`, `radius-2`, `shadow-1`, a geometric glyph and a sans `label`. Hover lifts to `surface-raised` with an eased transition. Selected adds `text-bright` and `shadow-focus`.

### 10.7 List row

Single line, `radius-0`, hairline beneath, sans label left, mono meta right. Hover fills `surface-raised`. Disabled drops to `text-dim` with a lock glyph.

### 10.8 Controls (button, input, select, chip, toggle)

`radius-1`, hairline border, `space-2`/`space-3` padding, sans label. Focus is `shadow-focus`, always neutral. A **primary** button — one per view — is the sole carrier of `shadow-accent`.

### 10.9 LED edge — "this region is live"

A container whose **hairline edge can be lit**: an emitter spilling light onto the surface beside it, rather than a border that merely changes colour. `LedEdge`, `lit` + `tone` + `side`.

This is how the system says *a region is running right now* — a streaming block in the chat timeline, an active task, a live pane. It reads as an LED because three things hold:

1. **The glow is directional.** Four shadow layers pushed along *one* axis with a long falloff (`2px` through `26px`, blur 10→96px, opacity 60%→12%). A symmetric glow reads as a halo around a line; only a one-sided falloff reads as light landing on a surface.
2. **The reach is long.** A tight glow is just a coloured border with soft edges. The bloom carries ~90px.
3. **The rule never changes width.** Lit and unlit are both `line-w`, and the border stays in the box model while lit (transparent, with the emitter's own bar painted over it). Lighting a region shifts nothing — the glow is a shadow, so it costs no layout.

**The one thing that breaks it:** any ancestor with `overflow` other than `visible` clips the bloom at its padding box. A lit region inside a scroll container needs padding on that container for the light to spill into, or the glow is cut off flush against the rule and you are back to a hard coloured band.

**Sides.** `left` is the process rail — light falling across the page beside a running block. `top` is a **strip light**: a rule across a surface's upper edge, throwing light up over whatever sits above it. It marks a docked surface as the live one where the ambient bloom of §6.2 would reach too far — the composer in a conversation is the case (§10.12). A surface lit on the top edge squares its top corners, so the strip meets the card's own edges instead of overhanging the curve.

**Spill** — which way the light falls — is separate from which edge it is mounted on, and the two compose. `out` throws away from the container, onto the page beside it. `in` throws **into** it, so the light lands under the container's own content: the element reads as the thing that is running, rather than as an element wearing a coloured border. That is the recents rail's live thread (§10.13) — the row glows from its leading edge, under the title.

An inward spill needs two things the outward one doesn't. The emitter takes a **negative z-index inside a stacking context the container establishes**, so it paints above the container's fill but below its text — without the context it would slide behind whatever surface the container sits on and vanish. And the container needs **`overflow-hidden`**: the glow blooms on every axis, not only the one it travels, so on a short element it bleeds onto its neighbours and a list of them looks smudged rather than lit.

**Tones** map to the semantic accents (`info` by default — "live data / in flight"). Where the light reports *state*, colour is doing real work and is exempt from the neutral-attention rule in §6: the light *is* the state. Where it only says *"act here"* — the composer's strip — the tone is `neutral` white and §6 holds unbroken. White carries its own opacity curve (30%→5%), because at the accent curve it washes out what it should only be grazing.

Direction and intensity are both custom properties (`--led-x`/`--led-y`, `--led-a1..4`), so a side and a tone compose. The four-layer shadow is declared once; a new side or tone sets variables and never restates it.

### 10.10 Reasoning stream

The clearest expression of the two voices in the product, and the reference for how any "the machine is working" surface should behave.

While the model reasons, its trace is **not a message**. It is the computer working *behind* the response area:

- **Mono, `micro` size, barely tinted** — `accent` mixed at ~25% into `text-dim`, held at ~30% opacity. It reads as machine texture, not as content, and never competes with the answer.
- **A flat wall, not an effect.** The subtlety lives entirely in the *color*: one uniform value across the whole block. **No gradient and no mask.** A faded edge would make it a decorated panel; this is meant to be a surface — a dense wall of machine text sitting behind the response.
- **Clipped into the background** of the response area, behind the content, `pointer-events: none`.
- **The stage travels; it does not appear.** The wall's height is a token (`--reasoning-h`), and the region opens and closes over that distance in `--motion-stage` rather than popping in and out at it — a region this large arriving instantly is a jump the reader absorbs twice per turn. Both directions are one token each, so retiming or resizing the state change is a token edit; nothing holds a matching copy, and the component waits on `animationend` rather than a duration of its own.
- **Cascading and bottom-anchored**, so new tokens push older lines up and out of frame. The wall stays filled to its top edge with older reasoning, and the newest line sits at the bottom where the eye already is.
- **Fixed-height stage**, so the transcript does not reflow line-by-line while the trace streams.
- **Machine register (§8)** — tokens land hard as they arrive. No easing, no fade-in per token.
- **Nothing sits in the foreground.** No label, no throbber. Text arriving *is* the signal that the model is working — the most direct one available — and the live rail beside it already says so in light. Both a "THINKING" label and a spinner on top were restating what the wall and the rail were already communicating, which is the clutter this system exists to remove.

**The handoff.** When the turn resolves, the wall **fades to the background over ~320ms** in the human register — that is the interface clearing the stage, not a control responding — and the **collapsed reasoning accordion fades in where it stood**, above the response. Two fades in the same place, so it reads as one movement rather than as a block being swapped out. The accordion holds the full trace, still mono and dim: available, out of the way.

The live layer is `aria-hidden` (it is texture, and a token-by-token live region would be unusable); a polite live region announces that the model is reasoning, and the settled accordion carries the real content.

### 10.11 The answer stream

The counterpart to §10.9, and the other half of the same idea.

The answer is **the interface speaking**, so it belongs to the human register: **each newly arrived run of text fades in over ~220ms**, eased, while everything already on screen stays put. Only genuinely new characters animate — settled text carries no animation even as the markdown block around it re-renders — and a run whose fade is interrupted by the next delta simply lands at full opacity, so the token at the head of the stream is the one that visibly arrives.

Put the two side by side and the system explains itself without a word being read: **the reasoning wall lands hard because it is mono and the machine is thinking; the answer eases in because it is sans and the interface is replying.**

Markdown structure must survive the stream — blocks that have settled keep their DOM across deltas, so only the trailing block re-parses. A streaming answer that renders as plain text and then pops into formatting when it finishes is not acceptable.

### 10.12 The composer

**One component, one layout, two sizes.** The docked input bar and the home page's hero field are the same card — `size` changes padding and the field's resting height, and nothing else. They used to be separate branches (a bordered field nested inside a bordered bar; a 2px box) and that fork was the clearest case of the box-in-a-box §7 exists to stop.

Anatomy, top to bottom, inside one `surface` card on `radius-2` with `shadow-1`:

1. an optional sans `label` title,
2. attachment chips,
3. the field — **transparent, borderless, no focus ring of its own**,
4. an action row: attach and inline controls left, send/stop right.

**The card is the control.** The field carries no chrome because the card around it already is the input; a bordered box inside a bordered box is two lines where one object exists.

**The composer is always marked, at rest.** It *is* the operator's point of action, so "start typing" must be the obvious move the moment the screen appears — never gated on focus or hover (§6), because a cue that only arrives once you have committed to typing is telling you something you no longer need. The mark is neutral, not accented: luminance, not hue.

It takes one of two forms, and the difference is what sits above it (`edge`):

- **`bloom` — the wide ambient aura (§6.2).** For a composer that is the screen: the home launchpad, the research intake. Nothing is behind it for the light to fall on, and the aura reads as the field floating in space.
- **`led` — a strip light on the top edge (§10.9, `side="top"`, `tone="neutral"`).** For the composer docked under a live transcript. The bloom's ~90px of upward reach lands squarely on the last thing the model said and washes it out; a rule of light does the same job in one line and separates the input from the conversation instead of bleeding into it. The card squares its top corners to meet the strip, and keeps `shadow-1` — the bloom's hairline ring goes with the bloom, and in Paper that ring is the only thing between a white card and a white page.

**Docked, it floats.** No rule welded to the bottom edge — the sticky wrapper carries the page background so the transcript scrolls out of sight behind a card that sits above it. No gradient scrim: the ground colour does the job.

### 10.13 The operator’s turn

The operator's own message is **right-aligned and shrink-to-fit, capped at 80%** of the column.

Width follows content: a three-word prompt is a three-word bubble. A fixed-width block would leave a short turn floating in the middle of an empty region, which reads as a layout error rather than as a message. The cap is what keeps a long paste from spanning the full measure.

Alignment of the *block* and alignment of the *words* are separate decisions: the block sits right (that is what marks it as the operator's), the text inside is left-aligned, because right-ragged prose with any internal structure reads as broken.

**Turns glide in.** Every turn — the operator's on send, the assistant's as it opens — fades up 10px over 200ms in the human register. Fast enough to read as a response rather than a reveal, and it fires once on mount, so a streaming turn never re-animates as deltas land. Opening a thread mounts its turns together, so the transcript settles in as one movement rather than a staggered cascade.

One implementation note that is easy to get wrong: the entry animation runs with `animation-fill-mode: both`, and an animated `opacity` outranks a utility class. A turn that is also *dimmed* (above a compaction divider) therefore needs two nodes — one owning the dim, one owning the movement — or the animation silently cancels the dim.

### States — all components

| State | Treatment |
|---|---|
| Default | `text` on `surface`, hairline `line` |
| Hover | `surface-raised`, eased (`motion-fast`) |
| Inactive | drop to `text-dim` |
| Selected | `surface-raised` + `text-bright` |
| Focus (keyboard) | `shadow-focus` — neutral, both modes |
| Primary focus | `shadow-accent` — one per screen |
| Alert | `accent-alert` on the value or border, never a fill |
| Loading | sans "Loading…" or a mono braille throbber — never an eased spinner |
| Empty | sans "No data" / a written sentence explaining what would appear here |

---

## 11. Diegetic detail

The sense that this is a real instrument comes mostly from *content*, not styling — and it now has a natural home, because all of it is machine output and therefore mono, dim, and small (§2). That is what lets it stay without becoming clutter.

Keep:

- **Asset & version IDs** — `RUN-0341-A7`, `IDX-v3.2.1`
- **Precision values** — coordinates, byte counts, token counts, latencies to the millisecond
- **Plausible telemetry** — uplink latency, queue depth, cache hit rate
- **Consistent naming** — pick a scheme (`[DOMAIN]-[SUBSYSTEM]-[SEQ]`) and hold to it

**The budget:** at most one diegetic detail per panel, and it lives at the panel's edge — a footer line, a header's right slot — never between a label and its value. Terminal-HUD's mistake was letting atmosphere sit in the reading path. Set at `micro`/`meta` in `text-dim`, it becomes texture the eye skips until it wants it, which is exactly the intent.

---

## 12. Accessibility

- **Never encode meaning in hue alone.** Every accent is paired with a label, glyph, or position change — already required by §5.
- **Contrast floors:** `text` on `bg` ≥ 7:1, `text-bright` on `bg` ≥ 15:1, `text-dim` on `bg` ≥ 3:1, every accent on `bg` ≥ 4.5:1. The tokens in §5 are tuned to pass; re-verify after any hue change. The accent half of that is now automated — `ui/theme/contrast.test.ts` asserts every shipped accent clears 4.5:1 in its own mode, so retuning one and forgetting to check fails the suite. **A user-set accent (§5) is warned about, never blocked**, and the warning is judged on the *displayed* (one-decimal) ratio so the verdict and the figure beside it can never contradict each other.
- **Focus is always visible.** `shadow-focus` is neutral and high-contrast in both modes; never suppress the ring without an equally visible replacement.
- **Mono is small by design** — so it is never the only carrier of essential information. Anything the operator must read to act is sans at `body` or larger.
- **Reduced motion** collapses the human register (§8).
- Tabular figures and consistent alignment aid low-vision scanning; keep them.

---

## 13. Token summary

```css
:root {
  /* ---- grid ---- */
  --space-0: 0;    --space-1: 4px;   --space-2: 8px;   --space-3: 12px;
  --space-4: 16px; --space-5: 20px;  --space-6: 24px;  --space-8: 32px;
  --space-12: 48px;

  /* ---- corners & borders ---- */
  --radius-0: 0;   --radius-1: 3px;  --radius-2: 6px;  --radius-full: 9999px;
  --line-w: 1px;

  /* ---- the two voices ---- */
  --font-sans: "Helvetica Neue", Helvetica, Arial, system-ui, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, "SFMono-Regular", monospace;

  /* ---- type scale ---- */
  --type-micro-size: 10px;      --type-micro-lh: 14px;
  --type-meta-size: 11px;       --type-meta-lh: 16px;
  --type-label-size: 12px;      --type-label-lh: 16px;
  --type-body-size: 13px;       --type-body-lh: 20px;
  --type-readout-size: 20px;    --type-readout-lh: 28px;
  --type-readout-lg-size: 32px; --type-readout-lg-lh: 40px;
  --type-display-size: 40px;    --type-display-lh: 44px;
  --tracking-label: 0.08em;   /* uppercase mono meta only */
  --tracking-tight: -0.02em;  /* display */

  /* ---- motion: human register ---- */
  --motion-fast: 120ms;
  --motion-base: 180ms;
  --ease: cubic-bezier(0.2, 0, 0, 1);
  /* ---- motion: machine register ---- */
  --motion-machine: 0ms;
  --ease-machine: steps(1, end);

  /* ---- INK (dark, default) ---- */
  --bg: #000000;         --surface: #0a0a0a;      --surface-raised: #161616;
  --surface-sunken: #0f0f0f;
  --line: #212121;       --line-strong: #333333;
  --text-dim: #6e6e6e;   --text: #a8a8a8;         --text-bright: #ffffff;
  --accent: #34d67f;
  --accent-nominal: #34d67f;  --accent-warn: #f2a93b;
  --accent-alert: #ff5c5c;    --accent-info: #5aa2ff;
  --shadow-1: 0 1px 2px rgb(0 0 0 / 0.6);
  --shadow-2: 0 8px 32px rgb(0 0 0 / 0.8);
}

[data-theme="paper"] {
  --bg: #ffffff;         --surface: #ffffff;      --surface-raised: #f5f5f4;
  --surface-sunken: #f4f3f0;
  --line: #e4e4e1;       --line-strong: #cfcfcb;
  --text-dim: #8a8a85;   --text: #3d3d3a;         --text-bright: #000000;
  --accent: #0077b6;
  --accent-nominal: #0e7a46;  --accent-warn: #9a6510;
  --accent-alert: #c0342b;    --accent-info: #0f5fa8;
  --shadow-1: 0 1px 2px rgb(0 0 0 / 0.05), 0 1px 1px rgb(0 0 0 / 0.04);
  --shadow-2: 0 12px 32px -8px rgb(0 0 0 / 0.16), 0 2px 6px rgb(0 0 0 / 0.06);
}

/* mode-invariant, derived. Blurred layers only — a zero-blur layer is a border
   (§6), and these resolve the *live* accent, so one formula covers both modes
   and follows an operator-set hue (§5.2) with no second definition. */
:root, [data-theme="paper"] {
  --shadow-focus:
    0 0 8px 1px color-mix(in oklab, var(--text-bright) 13%, transparent),
    0 0 22px 5px color-mix(in oklab, var(--text-bright) 7%, transparent);
  --shadow-accent:
    0 2px 12px -2px color-mix(in oklab, var(--accent) 55%, transparent),
    0 10px 36px -10px color-mix(in oklab, var(--accent) 38%, transparent);
  --shadow-alert:
    0 2px 12px -2px color-mix(in oklab, var(--accent-alert) 50%, transparent),
    0 10px 36px -10px color-mix(in oklab, var(--accent-alert) 34%, transparent);
}
```

---

## Appendix A — One-line brief

> A quiet, pure-neutral interface on a strict 4px grid, set in Helvetica with a monospaced second voice reserved strictly for machine output; hierarchy from size, weight, and brightness, with color rationed to semantic state and a single mode-dependent accent — phosphor green on black, cerulean on white — marking the one thing that needs attention; separation carried by space and surface value rather than by borders, which survive only inside a ruled data grid; marginally smoothed corners; subtle elevation used only to say what is on top; and motion split into two registers, smooth and decelerating for the interface, instantaneous for anything the computer is doing.
