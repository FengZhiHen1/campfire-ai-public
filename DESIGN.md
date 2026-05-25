# Campfire-AI — Crisis-First Companion

## North Star: "The Trusted Ember"
A warm, authoritative companion for caregivers of autistic individuals during behavioral emergencies. Dense, high-stakes information made immediately actionable through tonal warmth, radical readability, and zero cognitive friction. Every pixel must whisper: *"You are not alone, and this guidance is grounded in real cases."*

## Colors

### Light Mode (Default)
- **Primary (`#B45309`):** The ember core. Used exclusively for primary actions, focus states, streaming cursors, and active voice-input rings. Never as a background wash.
- **On Primary (`#FFFFFF`):** Text and icons sitting on primary surfaces.
- **Primary Container (`#FEF3C7`):** Warm highlight backgrounds for selected tags, active streaming blocks, and confidence badges of "high trust".
- **On Primary Container (`#92400E`):** Text on primary container surfaces.
- **Secondary (`#64748B`):** Slate mist for expert identifiers, metadata labels, and secondary actions. Injects rational calm against the warmth.
- **On Secondary (`#FFFFFF`):** Text on secondary surfaces.
- **Tertiary (`#059669`):** Moss green for success states, safe confirmations, and "based on N similar cases" trust indicators.
- **On Tertiary (`#FFFFFF`):** Text on tertiary surfaces.
- **Error (`#DC2626`):** Brick red reserved strictly for high-risk keyword alerts (self-injury, medication, elopement) and the human-escalation trigger. Used sparingly to avoid secondary panic.
- **On Error (`#FFFFFF`):** Text on error surfaces.
- **Background (`#FDF8F3`):** Warm parchment. Softer than pure white to reduce visual sting during late-night usage.
- **On Background (`#1C1917`):** Warm charcoal for primary text. Avoids the harshness of pure black.
- **Surface (`#FFFFFF`):** Cards, modals, and elevated containers.
- **Surface Variant (`#F5F0EB`):** Slightly recessed panels, input backgrounds, and alternating list rows.
- **Surface Dim (`#EBE5DE`):** Deepest surface tier for sticky headers or footer escort bars.
- **Outline (`#78716C`):** Warm stone. Used only at 15% opacity as "Ghost Borders" when absolutely necessary.
- **On Surface Variant (`#78716C`):** Captions, timestamps, case-source footnotes.

### Dark Mode (Reserved)
- **Background (`#1C1917`):** Charcoal night.
- **Surface (`#292524`):** Elevated dark card.
- **Surface Variant (`#44403C`):** Recessed dark panel.
- **On Background (`#FDF8F3`):** Warm parchment text.
- **Primary (`#F59E0B`):** Brighter amber for dark-mode visibility.
- **Error (`#EF4444`):** Slightly lifted red for dark surfaces.

### Color Usage Rules
- **No-Line Rule:** Never use 1px solid borders to separate content. Define boundaries exclusively through background color shifts (`surface` → `surface-variant` → `surface-dim`).
- **High-risk alerts** are the only exception: a 2px left accent bar in `error` color may be used on critical intervention steps.
- All text/background pairings must maintain WCAG AA contrast (≥ 4.5:1).

## Typography

- **Stack:** `system-ui, -apple-system, "PingFang SC", "Noto Sans SC", "Helvetica Neue", sans-serif`. Leverage native system fonts to minimize WeChat Mini Program bundle size.
- **Headlines:** `font-weight: 600` (semibold). Large (`20px`–`24px`), generous line-height (`1.6`), warm charcoal (`on-background`). Avoid `700` to reduce perceived aggression.
- **Body:** `16px` minimum, line-height `1.75`. Non-negotiable baseline for crisis readability. Color: `on-background`.
- **Emergency Advice Core:** `18px`, line-height `1.8`. The most critical paragraphs (immediate action, soothing scripts) receive extra size and air.
- **Labels / Metadata:** `14px`, line-height `1.5`, color `on-surface-variant`. Expert names, case IDs, timestamps.
- **Source Footnotes:** `11px` minimum (WeChat Mini Program safe floor), line-height `1.4`, color `outline` at 70% opacity. Expandable on tap.
- **Voice Input Prompt:** `14px`, italic style allowed via `font-style: italic` for tone-of-voice hints.

## Elevation

- **Depth through tonal layering, not shadows.** Stack surface tokens (`surface` → `surface-variant` → `surface-dim`) for natural elevation.
- **Diffuse Shadow (Cards):** `0 4px 24px rgba(28, 25, 23, 0.06)`. Simulates the natural halo of ember light in darkness. No sharp offsets.
- **Deep Shadow (Modals / Human Escalation Drawer):** `0 8px 40px rgba(28, 25, 23, 0.08)`, tinted `on-surface`.
- **Ghost Border:** If an edge must be explicitly drawn, use `outline` at 15% opacity, `1px`.
- **Corner Radius:** `16px` (`1rem`) for main containers and bottom sheets; `8px` (`0.5rem`) for buttons, input fields, and badges; `4px` (`0.25rem`) for inline code or case-ID pills.

## Motion & Streaming

- **Typewriter Cursor:** A `2px` wide vertical bar in `primary`, pulsing `opacity 1 → 0.4` over `1.5s` `ease-in-out` `infinite`. Positioned at the exact SSE token boundary. Never use a blinking block cursor—it implies selection, not generation.
- **Token Reveal:** Characters appear one-by-one at `40ms` per glyph during SSE streaming. Use `opacity 0 → 1` + `translateY(2px) → translateY(0)` with `duration 150ms`, `ease-out`. Creates a "settling" feel rather than a jarring pop.
- **Paragraph Breathing:** After each structured section completes (Immediate Action → Soothing Script → Observation Index → Medical Judgment), auto-insert a `12px` vertical spacing transition (`height 0 → 12px`, `200ms` `ease-in-out`) before the next section begins rendering. Prevents wall-of-text panic.
- **Confidence Badge Reveal:** Once streaming ends, the badge fades in with `opacity 0 → 1`, `translateY(4px) → 0`, `300ms` `ease-out`.
- **Page Transitions:** Soft fade-in only (`opacity 0 → 1`, `200ms`). Avoid lateral slides—they induce disorientation in crisis states.
- **Loading Skeletons:** Never use shimmering gray skeletons. Use a static `surface-variant` block with a subtle `primary` pulse border to indicate "the ember is warming up."

## Components

### Emergency Input
- **Container:** `surface` background, `16px` radius, `12px` internal padding.
- **Text Area:** `16px` body size, `1.75` line-height. No internal borders; focus state is a `2px` `primary` ring with `4px` spread.
- **Voice Input Button:** Circular `48px` touch target, `primary` background, white microphone icon. Positioned bottom-right inside the input container. Always visible—caregivers may have only one free hand.
- **Placeholder Text:** `on-surface-variant` at 60% opacity. Example: *"Describe what is happening right now..."*

### Stream Output Card (The Plan)
- **Structure:** Four stacked sections, each preceded by a `4px` left accent bar:
  - Immediate Action: `tertiary` (moss green) bar.
  - Soothing Script: `primary` (amber) bar.
  - Observation Index: `secondary` (slate mist) bar.
  - Medical Judgment: `error` (brick red) bar if escalation recommended; otherwise `secondary`.
- **Section Header:** `14px` semibold, color matching the accent bar.
- **Section Body:** `18px` regular, `1.8` line-height.
- **Background:** `surface` with `diffuse shadow`.
- **Spacing:** `16px` between sections internally; `24px` margin to screen edges.

### Confidence Badge
- **Shape:** Pill, `8px` radius, `8px 12px` padding.
- **High Trust (≥ 0.85):** `tertiary` background, white text. *"Based on 4 similar cases"*
- **Medium Trust (0.70–0.84):** `primary-container` background, `on-primary-container` text. *"Based on 2 related cases"*
- **Low Trust (< 0.70):** `surface-variant` background, `error` text. Triggers automatic expansion of the Human Escalation Button.

### Source Footnote
- **Appearance:** `11px`, `on-surface-variant`, underlined on tap.
- **Position:** Collapsed to a single line below the plan card; expands into a `surface-variant` panel on tap showing case IDs, expert names, and archive dates.
- **Behavior:** Tapping a case ID opens a non-blocking bottom sheet (not a full-screen jump) to preserve the caregiver's current context.

### Human Escalation Button
- **Default State:** A subtle text link at the bottom of the plan card: *"Need a human expert?"* `secondary` color.
- **Triggered State (Low Confidence / High-Risk Keywords):** Transforms into a full-width, sticky bottom bar (`error` background, white text, `16px` radius top corners). Height `56px`, `font-size: 16px`, `font-weight: 600`. Tapping generates a ticket immediately—no confirmation dialog. Speed is safety.

### Disclaimer Bar
- **Appearance:** A `surface-dim` strip, `12px` padding, `11px` text, `on-surface-variant` at 80% opacity.
- **Content:** *"AI-generated guidance based on archived cases. Not a medical diagnosis. Always consult professionals for severe episodes."*
- **Behavior:** Collapsed to one line with a "Read more" chevron. Never rendered as a blocking modal or alert.

### Chat Bubble (History View)
- **User Bubble:** `primary-container` background, `on-primary-container` text, right-aligned, `16px` radius with sharp bottom-right corner.
- **AI Bubble:** `surface` background, `on-background` text, left-aligned, `16px` radius with sharp bottom-left corner.
- **Timestamp:** `11px`, `on-surface-variant`, centered between clusters, `8px` vertical spacing.

### Tag / Badge (Profile & Case Filters)
- **Shape:** Pill, `8px` radius, `6px 10px` padding.
- **Default:** `surface-variant` background, `on-surface-variant` text.
- **Active / Selected:** `primary-container` background, `on-primary-container` text, `1px` ghost border in `primary` at 30% opacity.

## Layout & Spacing

- **Safe Area:** Respect WeChat Mini Program `env(safe-area-inset-bottom)`. All primary actions and the Human Escalation sticky bar must sit above the safe zone.
- **Touch Targets:** Minimum `44px × 44px` for all interactive elements. The voice button is `48px` to accommodate glove/dark usage.
- **Single-Handed Zones:** Place primary actions (voice input, submit, escalate) in the bottom 40% of the screen. Avoid top-right corner actions.
- **Whitespace as Structure:** Use `24px` section margins, `16px` card internal padding, and `12px` paragraph breathing gaps. Never compress information to save scroll length—anxiety increases with density.

## Rules

1. **Crisis-First Typography:** Body text never drops below `16px`; emergency advice core never drops below `18px`. Line-height never below `1.75`.
2. **Zero Interruption During Streaming:** While SSE is active, suppress all pop-ups, toast notifications, and modal dialogs. The typewriter cursor is the only status indicator.
3. **One Primary Action Per View:** The consult screen has one dominant action (voice/text submit). The plan screen has one dominant action (human escalation, if triggered). Secondary actions (share, copy, save) are hidden behind a `···` menu or bottom sheet.
4. **No Sharp Corners:** Minimum `8px` radius on any interactive element. Main cards and bottom sheets use `16px`.
5. **Warmth Without Frivolity:** No illustrations of cartoon characters, no gamification badges, no celebratory animations. Use abstract warmth (tonal color, generous radius, soft shadow) rather than literal "campfire" graphics.
6. **Dark Mode Ready:** All color tokens must possess a dark-mode counterpart. Even if the MVP ships light-only, components must consume tokens, not hardcoded hex values, to enable future dark-mode toggling without refactoring.
7. **Accessibility Minimums:** Every text/background pair must pass WCAG AA. The `error` on `surface` pairing must pass WCAG AA for high-risk alerts (it does: `#DC2626` on `#FFFFFF` = 6.14:1).
8. **Source Traceability:** Every generated plan must display at least one collapsed source footnote. Trust is the product; transparency is the UI.

---

*This document is the authoritative visual contract for the Campfire-AI WeChat Mini Program. All frontend implementations in `apps/mini-program/src/views/` and `apps/mini-program/src/logics/` must consume design tokens from this system.*