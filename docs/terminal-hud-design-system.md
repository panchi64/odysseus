# Terminal-HUD Design System

*A dense, deterministic, semantically-colored interface language in the FUI / Swiss-typographic tradition.*

**Version 0.1** · Status: Foundation spec

---

## 0. Reading this document

This is a foundation spec, not a component library. It defines the *rules* and the *tokens* — the atomic decisions everything else inherits from. A designer should be able to open a blank artboard (or an empty CSS file) and reproduce the look from the values below without guessing. Where a value is a judgment call rather than a fixed number, it's marked **[choose]** with guidance.

Two surface modes are defined throughout: **Phosphor** (dark, terminal/cockpit) and **Paper** (light, data-design). They share structure, grid, and type — only the color tokens differ. Build one component once; it works in both by swapping the token set.

---

## 1. Design principles

These are the non-negotiables. Every later decision traces back to one of them.

1. **High data-ink ratio.** Every pixel earns its place by carrying information or enforcing structure. No decorative gradients, no drop shadows for mood, no ornamental dividers. If removing an element loses no meaning, remove it.
2. **Determinism over delight.** Numbers align in columns. Fields don't reflow or jump. State is always visible, never implied by hover or animation. The interface should feel like a readout, not a toy.
3. **Strict hierarchy.** At a glance, the eye must find the single most important value. Hierarchy is built with size, weight, and brightness — never with color (color is reserved, see §4).
4. **Semantic color only.** The base palette is monochrome. Color appears exclusively to mean something: alert, active, error, nominal. A screen at rest is grayscale.
5. **Systematic, not bespoke.** Iconography, naming, spacing, and microcopy follow consistent rules so that a screen the user has never seen still feels familiar. The world is internally consistent.

---

## 2. Grid & spacing

### Base unit
**4px.** All spacing, sizing, and positioning are multiples of 4. This is the single rule that makes density feel intentional rather than cramped.

### Spacing scale
| Token | px | Typical use |
|---|---|---|
| `space-0` | 0 | Flush elements |
| `space-1` | 4 | Intra-component padding, label-to-value gaps |
| `space-2` | 8 | Default padding inside dense cells |
| `space-3` | 12 | Group separation within a panel |
| `space-4` | 16 | Panel padding |
| `space-6` | 24 | Section separation |
| `space-8` | 32 | Major region separation |

### Layout grid
- **Columns:** 12-column for app layouts; for dense instrument bands, drop the column model and use a **fixed baseline grid** instead (everything snaps to 4px vertical rhythm).
- **Gutters:** `space-2` (8px) in dense views, `space-4` (16px) in spacious views.
- **Margins:** `space-4` minimum at viewport edge.
- **Density target:** dense views should feel ~2–3× denser than typical SaaS. Aim for tight 4–8px padding inside cells, not the 16–24px of consumer apps.

### Borders & rules
- **Hairline:** 1px. This is the workhorse divider. Use it liberally to define cells and regions — it's "free" ink because it enforces structure.
- **Emphasis border:** 2px, used only to mark a *selected* or *primary* region (see image 4's focused tile, image 5's active search circle).
- Corners are **square by default** (`radius-0`). A small radius (`radius-1` = 2px) is permitted only on interactive controls. Never round panels.

---

## 3. Typography

### Typefaces
The system uses two families only.

- **Mono** (primary): a monospaced grotesque for all data, labels, readouts, and microcopy. Tabular figures are the whole point — numbers must align in columns.
  - **[choose]** Recommended: *Berkeley Mono*, *JetBrains Mono*, *IBM Plex Mono*, or *Departure Mono* for a more CRT flavor. Pick one and commit.
- **Display** (accent, optional): a heavy condensed grotesque for large titles (image 3's "ONBOARDING MANUAL", image 4's "OBSERVATION FIELD").
  - **[choose]** Recommended: *Helvetica Now Display Bold/Condensed*, *Suisse Int'l*, or a condensed grotesque. Use sparingly — most of the system is Mono.

### Type scale
Based on a tight scale; sizes in px / line-height in px (line-height also snaps to the 4px grid).

| Token | Size/LH | Weight | Use |
|---|---|---|---|
| `type-micro` | 10 / 12 | Regular | Microcopy, asset IDs, legal, ambient telemetry |
| `type-label` | 11 / 16 | Medium, +0.08em tracking, UPPERCASE | Field labels, status flags |
| `type-body` | 13 / 16 | Regular | Default data values |
| `type-readout` | 20 / 24 | Medium | Primary numeric readouts |
| `type-readout-lg` | 32 / 36 | Bold, tabular | Hero readout (one per screen max) |
| `type-display` | 48 / 48 | Display Bold | Section titles only |

### Rules
- **Labels are UPPERCASE with positive tracking** (+0.08em). Values are sentence/natural case.
- **Always use tabular (monospaced) figures** for any number that might change or align with others.
- **Left-align, ragged right.** No justification. No centering except for single isolated readouts.
- Hierarchy = size + weight + brightness, in that priority order. Resist using color.

---

## 4. Color

Color is the most disciplined part of the system. The base is monochrome; semantic color is rationed.

### 4.1 Phosphor mode (dark)

**Neutrals** (the entire resting interface lives here):
| Token | Hex | Use |
|---|---|---|
| `bg` | `#0A0C0B` | App background (near-black, faint warm/cool tint allowed) |
| `surface` | `#121514` | Panels, cells |
| `surface-raised` | `#1A1E1C` | Selected/raised cells |
| `line` | `#2A2F2C` | Hairline borders |
| `text-dim` | `#5A635E` | Ambient telemetry, inactive labels |
| `text` | `#A8B3AD` | Default text |
| `text-bright` | `#E6EDE9` | Primary readouts, active values |

**Semantic accents** (used only to carry meaning):
| Token | Hex | Meaning |
|---|---|---|
| `accent-nominal` | `#39FF6A` → tone to `#5Bd47E` | Active / OK / phosphor primary |
| `accent-warn` | `#FFB020` | Caution, warning |
| `accent-alert` | `#FF3B3B` | Error, critical, "CNF" |
| `accent-info` | `#3BA9FF` | Secondary signal / live data |

> The classic cockpit look (images 6–7) is built almost entirely from `bg` + `accent-nominal` at varying brightness, with `accent-alert` red as the *only* second color. The amber variant (image 1) swaps `accent-nominal` for `accent-warn` as the base signal color.

### 4.2 Paper mode (light)

| Token | Hex | Use |
|---|---|---|
| `bg` | `#F4F4F2` | Background (image 5's off-white) |
| `surface` | `#FFFFFF` | Panels |
| `line` | `#D8D8D4` | Hairlines |
| `text-dim` | `#9A9A95` | Ambient/inactive |
| `text` | `#3A3A38` | Default text |
| `text-bright` | `#0A0A0A` | Primary, near-black |
| `accent-alert` | `#1A1A1A` | In paper mode, "alert" is often just full black weight |

Paper mode leans even harder on the monochrome rule — image 5 uses essentially *no* hue, deriving all hierarchy from black/gray weight and a single bold "Warning" label.

### Color usage rules
1. A screen at rest shows **zero accent color.** If everything is nominal, everything is neutral.
2. Each accent maps to **exactly one meaning** system-wide. Never reuse `accent-warn` amber as a brand color.
3. Brightness, not hue, separates active from inactive (`text-bright` vs `text-dim`).
4. Maximum **two** accent colors visible in one region at one time. More reads as decoration.

---

## 5. Iconography

- **Stroke-based, 1.5px**, on a 16px grid. Geometric, not friendly.
- Derived from instrumentation vocabulary: compass roses, registration crosshairs (`+` at frame corners, image 3), triangular warning glyphs, dotted tracking circles, buoy/marker symbols (image 5).
- No filled, rounded, or skeuomorphic icons. No emoji.
- **Registration marks** (corner `+`, target reticles, diamond nodes) are a signature — use them as framing devices on full-screen layouts, even when non-interactive. This is diegetic detail (§7).

---

## 6. Components

Each component is specified by anatomy + tokens. Build these and you have the system.

### 6.1 Field (label + value)
The atomic unit. A `type-label` (uppercase, dim) above or left of a `type-body`/`type-readout` value (bright).
```
PILOT          MAVERICK
RANK           10 / 14
```
- Label and value separated by `space-1`.
- In tabular groups, values left-align to a shared column.

### 6.2 Panel
A bordered region (`line` hairline, `surface` background, square corners, `space-4` padding) containing fields. Optional header bar: `type-label` left, status/meta right.

### 6.3 Instrument band
A full-width horizontal strip of densely packed fields, separated by hairlines (images 6–7). No padding luxury — `space-1`/`space-2` only. Often mirrored/repeated to fill width. This is where density is most aggressive.

### 6.4 Readout
The hero value. `type-readout-lg`, `text-bright`, tabular. One per screen. May sit alone with a single dim `type-label` beneath.

### 6.5 Status flag
A small uppercase `type-label` chip. Default: `text-dim` on `surface`. Active: `text-bright` or, if it carries a state, the mapped accent (e.g. `accent-nominal` for "LIVE"). Image 7's "LIVE TARGET" toggles.

### 6.6 Tile / nav card
A square `surface` cell with a large mono glyph/letter top-left and a `type-label` name (image 4: "O / OBSERVATION FIELD"). Selected state: 2px `text-bright` border, lifted to `surface-raised`.

### 6.7 List row
Single-line: `type-label` left, optional status/icon right, hairline below. Locked/disabled rows use `text-dim` + a lock/`x` glyph (image 4's "LOCKED FILE").

### 6.8 Map / spatial view
Monochrome line-art base, custom markers with coordinate microcopy, one emphasized focus ring (2px), `type-micro` for labels (image 5). Coordinates shown to full precision as diegetic detail.

### States (all components)
| State | Treatment |
|---|---|
| Default | `text` / `surface` / `line` |
| Inactive | drop to `text-dim` |
| Active/selected | `text-bright` + 2px emphasis border |
| Alert/error | `accent-alert`, applied to value or border only |
| Loading | `type-micro` "LOADING…" / "NO DATA" / "UPDATING…" in `text-dim` — never a spinner |

---

## 7. Diegetic detail (microcopy)

The "authentic" feel is mostly content, not styling. Bake in:
- **Asset/version IDs:** `RCM-OB-01.3 EDITION 02`, `LOG SERIES 0341`
- **Coordinates & precision:** `37.7576793 -122.5076391`
- **Technical fine print:** protocol/standards notes, "UNAUTHORIZED DISTRIBUTION PROHIBITED"
- **Plausible telemetry:** uplink latency, percentages, mem matrices — values that imply a working system off-frame.
- **Consistent naming conventions:** decide a scheme (e.g. `[DIVISION]-[SUBSYSTEM]-[VERSION]`) and use it everywhere.

This content should look real but reward no scrutiny — it sets atmosphere, not function.

---

## 8. Motion (minimal)

- **No easing flourishes.** Transitions are instant or linear, ≤120ms.
- Permitted: value tick-overs (numbers updating), cursor blink, dim→bright on activation.
- Forbidden: bouncing, sliding panels, fades for decoration, spinners.
- The interface should feel *responsive and mechanical*, never animated.

---

## 9. Accessibility notes

- The semantic-color discipline doubles as accessibility: never encode meaning in hue alone — pair every accent with a label or position change (already required by §4).
- Verify `text` on `bg` and `text-bright` on `bg` meet WCAG AA (4.5:1) in both modes; the tokens above are tuned to pass but confirm after any hue adjustment.
- Tabular figures and high density help low-vision scanning *if* contrast holds — don't let "dim" telemetry drop below 3:1.

---

## 10. Token summary (copy-paste starting point)

```css
:root {
  /* grid */
  --space-1: 4px;  --space-2: 8px;  --space-3: 12px;
  --space-4: 16px; --space-6: 24px; --space-8: 32px;
  --radius-0: 0;   --radius-1: 2px;
  --line-w: 1px;   --line-emphasis: 2px;

  /* type */
  --font-mono: "Berkeley Mono", "JetBrains Mono", monospace;
  --font-display: "Suisse Int'l", "Helvetica Now", sans-serif;
  --type-micro: 10px/12px;   --type-label: 11px/16px;
  --type-body: 13px/16px;    --type-readout: 20px/24px;
  --type-readout-lg: 32px/36px; --type-display: 48px/48px;

  /* phosphor mode */
  --bg: #0A0C0B;        --surface: #121514;   --surface-raised: #1A1E1C;
  --line: #2A2F2C;      --text-dim: #5A635E;  --text: #A8B3AD;
  --text-bright: #E6EDE9;
  --accent-nominal: #5BD47E; --accent-warn: #FFB020;
  --accent-alert: #FF3B3B;   --accent-info: #3BA9FF;
}
```

---

## Appendix A — One-line brief

> A dense, dark (or paper-light), monospaced interface on a strict 4px modular grid; high data-ink ratio with no decorative chrome; hierarchy from size/weight/brightness only; a monochrome palette where color appears solely to carry semantic meaning; tabular figures and fixed-width fields for a deterministic, scannable readout; framed with diegetic registration marks and technical microcopy — terminal/HUD aesthetic executed with Swiss-typographic rigor.
