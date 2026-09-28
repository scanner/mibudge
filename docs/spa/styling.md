# Styling

The SPA's look is defined in one place: semantic design tokens in
`frontend/src/styles/tokens.css`, exposed to templates as Tailwind
utilities, and composed into `Base*` primitives in
`frontend/src/components/base/`. To change how something looks, change
its token or its primitive; every place that uses it follows.

---

## 1. Principles

- **Numbers are unmistakable.** Every number a user reads as data is
  set in IBM Plex Mono, whose `0`, `O`, `1`, `l` and `I` all have
  distinct shapes. In a budgeting app, misreading one digit is a real
  error.
- **Calm and legible.** Warm neutrals, white cards on a warm off-white
  canvas, one blue accent, and status colours used only for status.
  Contrast errs toward clear rather than subtle.
- **Semantic over literal.** A class names what the thing *is*
  (`text-fg-muted`, `bg-danger-bg`), never the colour or size it
  happens to be.
- **One role, one token.** All secondary text uses `fg-muted`; all
  cards use `rounded-card`. When one role renders in two shades, one of
  them is a bug.
- **Primitives before markup.** Buttons, inputs, form fields, cards,
  list rows, headers, banners, sheets, toggles, badges and skeletons
  come from `components/base/`. A caller may add classes for
  properties the primitive does not set -- margin, width, flex,
  position, a hover tint, an elevation, a background on a header -- and
  never a class for a property it does set (its colours, type, padding
  or shape); those come from its props. Two utilities for the same
  property resolve by stylesheet order, not by the order they are
  written, so an override would work by accident or not at all.
- **Accessibility floor (WCAG 2.2 AA).**
  - Text is at least 4.5:1 against its background.
  - Meaningful non-text marks (input borders, focus rings, progress
    fills, toggle tracks) are at least 3:1.
  - Every interactive element shows a `focus-visible` ring.
  - Every touch target is at least 44px.

## 2. Architecture

```
palette (private)         semantic token (public)    Tailwind utility    primitive
--palette-ocean-600   ->  --color-accent         ->  bg-accent       ->  <BaseButton>
--palette-neutral-600 ->  --color-fg-muted       ->  text-fg-muted   ->  <BaseListRow>
```

| File                     | Holds                                                                                                                                                                                                                  |
|--------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `src/styles/tokens.css`  | Palette ramps (`--palette-*`) and semantic tokens (`--color-*`, sizes, radii, shadows, motion) under `:root`. Colours are RGB channels (`55 138 221`) so Tailwind's `/<alpha>` modifier works. It is the only file that contains colour literals. |
| `src/styles/forms.css`   | Base styles for inputs, selects and textareas, written with semantic tokens (see below).                                                                                                                              |
| `src/styles/motion.css`  | The shared `fade` and `slide-up` `<Transition>` classes.                                                                                                                                                               |
| `src/styles/interaction.css` | The global `:focus-visible` outline and the `.tap-target` hit area (section 3.15). |
| `scripts/lint-styles.mjs` | `pnpm lint:styles`: rejects colour literals, arbitrary values, palette classes, static styles, stray `<style>` blocks and `!important`; runs in CI and pre-commit. |
| `tailwind.config.ts`     | Defines Tailwind's colours, font sizes, radii, shadows, z-index and motion as the semantic names below, each pointing at a `var(--...)`. Tailwind's numeric spacing scale is kept, with named aliases added.            |
| `src/components/base/`   | The `Base*` primitives, plus `MoneyAmount`, `StatusChip`, `ProgressBar` and `EmptyState`.                                                                                                                              |

- Only semantic tokens read the palette; templates never see it. A dark
  theme is one `[data-theme="dark"]` block that overrides the semantic
  tier.
- `tokens.css` holds every value, and `tailwind.config.ts` only maps
  names to it, so the design is independent of the Tailwind version.
- `@tailwindcss/forms` normalises form controls across browsers.
  `forms.css` restyles its border, background, placeholder, focus ring,
  checkbox colour and select chevron with semantic tokens, so every
  colour a control shows comes from `tokens.css`. The select chevron is
  an SVG data URI, which cannot read a custom property, so it is the
  `--icon-select-chevron` token with `fg-muted` written into it.

## 3. Token reference

### 3.1 Palette (private)

Each ramp has only the steps some role uses.

| Ramp      | Steps                                                                                                                                         |
|-----------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| `ocean`   | 50 `#EAF4FF`, 400 `#378ADD`, 600 `#185FA5`, 800 `#0C447C`                                                                                     |
| `mint`    | 50 `#E1F5EE`, 400 `#1D9E75`, 500 `#1A946F`, 600 `#0F6E56`                                                                      |
| `amber`   | 50 `#FFF5E6`, 400 `#EF9F27`, 500 `#B67418`, 600 `#854F0B`                                                                                     |
| `coral`   | 50 `#FCEBEB`, 400 `#E24B4A`, 600 `#A32D2D`, 800 `#7A2222`                                                                                     |
| `neutral` | 50 `#F5F4F0`, 100 `#F1EFE8`, 200 `#E0DED8`, 300 `#D3D1C7`, 400 `#B4B2A9`, 500 `#888780`, 550 `#71706B`, 600 `#5F5E5A`, 900 `#1A1A1A` |
| white     | `#FFFFFF`                                                                                                                                     |

### 3.2 Colour: text and icons

Contrast is against `surface` (white) unless noted.

| Token          | Class               | Palette     | Contrast                                      | Use for                                                                                             | Not for                                                                 |
|----------------|---------------------|-------------|-----------------------------------------------|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| `fg`           | `text-fg`           | neutral-900 | 17:1                                          | Primary content: names, titles, values, body copy, form labels, secondary-button text.             |                                                                         |
| `fg-muted`     | `text-fg-muted`     | neutral-600 | 6.5:1 (5.9 on canvas, 5.6 on `surface-muted`) | Secondary text: metadata, supporting labels, running balances, form hints, icon-button glyphs.     | Disabled text.                                                          |
| `fg-subtle`    | `text-fg-subtle`    | neutral-550 | 5.0:1 (4.5 on canvas)                         | Tertiary text on `surface` or `canvas`: placeholders, the `--` for a missing value, empty-list notes. | Anything the user must read to act; any background darker than `canvas`. |
| `fg-disabled`  | `text-fg-disabled`  | neutral-400 | 2.1:1                                         | Text of a disabled control (WCAG exempts it).                                                       | Any enabled content.                                                    |
| `fg-on-accent` | `text-fg-on-accent` | white       | 6.5:1 on `accent`                             | Text and icons on `accent`, `danger-solid` and the other solid fills.                              |                                                                         |
| `fg-link`      | `text-fg-link`      | ocean-600   | 6.5:1                                         | Inline links and text buttons ("Manage accounts").                                                  |                                                                         |
| `icon-muted`   | `text-icon-muted`   | neutral-400 | 2.1:1                                         | Decorative icons that repeat adjacent meaning: row chevrons, the swipe hint. WCAG exempts decoration. | An icon that is a control's only label (use `fg-muted`).               |

### 3.3 Colour: surfaces and borders

| Token            | Class                  | Palette     | Use for                                                               |
|------------------|------------------------|-------------|-----------------------------------------------------------------------|
| `canvas`         | `bg-canvas`            | neutral-50  | The app background behind cards (`AppShell`, full-screen sheets).     |
| `surface`        | `bg-surface`           | white       | Cards, sheets, the TopBar, inputs.                                    |
| `surface-sunken` | `bg-surface-sunken`    | neutral-50  | Read-only fields and inset rows inside a card; hover on white rows.   |
| `surface-muted`  | `bg-surface-muted`     | neutral-100 | Skeleton blocks, unselected pills, icon-button hover.                 |
| `surface-strong` | `bg-surface-strong`    | neutral-200 | Hover on `surface-muted`, a disabled button's fill, empty meter segments. |
| `scrim`          | `bg-scrim/40`          | neutral-900 | The overlay behind sheets and dialogs.                                |
| `border`         | `border-border`        | neutral-200 | Card outlines and dividers. Decorative, so no contrast floor applies. |
| `border-subtle`  | `border-border-subtle` | neutral-100 | Row dividers inside a card.                                           |
| `border-emphasis` | `border-border-emphasis` | neutral-300 | A decorative border one step stronger than `border`: hovered selectable cards and chips, neutral badge outlines. |
| `border-strong`  | `border-border-strong` | neutral-500 | Input and select outlines, the off-state toggle track: 3.6:1.         |
| `border-focus`   | `ring-border-focus`    | ocean-400   | The `focus-visible` ring and a focused input's border: 3.6:1.         |

### 3.4 Colour: accent

| Token           | Class                  | Palette   | Use for                                                                                  |
|-----------------|------------------------|-----------|------------------------------------------------------------------------------------------|
| `accent`        | `bg-accent`            | ocean-600 | Primary button fill, on-state toggle, selected segment. White text on it is 6.5:1.       |
| `accent-hover`  | `bg-accent-hover`      | ocean-800 | Hover and active state of an `accent` fill, and hover of `fg-link` and `accent-fg` text.  |
| `accent-subtle` | `bg-accent-subtle`     | ocean-50  | Tinted backgrounds: the "Move money" CTA, avatar circle, selected list row.              |
| `accent-fg`     | `text-accent-fg`       | ocean-600 | Accent-coloured text and icons on white or `accent-subtle`: the active nav tab, CTA label. |
| `accent-border` | `border-accent-border` | ocean-400 | Selected-card outline, the unallocated-row left rule, the dashed "Add account" row.      |

### 3.5 Colour: status

Each status has four tokens:
- `-bg` + `-fg` (+ `-border`) make a banner;
- `-solid` is a filled button;
- inline field errors use `text-danger-fg`.

`-border` is the 400 step at 40% alpha: a light tint of the status
colour that outlines a box without competing with its text. An
`/<alpha>` modifier scales it further: `border-info-border/60` is a
fainter divider inside an info-tinted band.

| Status    | `-bg`    | `-fg`                  | `-border`       | `-solid` (white text)                    |
|-----------|----------|------------------------|-----------------|------------------------------------------|
| `success` | mint-50  | mint-600 (5.5:1 on bg) | mint-400 / 40%  | mint-600                                 |
| `warning` | amber-50 | amber-600 (6.2:1)      | amber-400 / 40% | amber-600                                |
| `danger`  | coral-50 | coral-600 (6.1:1)      | coral-400 / 40% | coral-600 (7.1:1); `danger-solid-hover` coral-800, also the hover of `danger-fg` text buttons |
| `info`    | ocean-50 | ocean-600 (5.9:1)      | ocean-400 / 40% | ocean-600                                |

The classes, written out: `bg-success-bg`, `text-success-fg`,
`border-success-border`, `bg-success-solid`; `bg-warning-bg`,
`text-warning-fg`, `border-warning-border`, `bg-warning-solid`;
`bg-danger-bg`, `text-danger-fg`, `border-danger-border`,
`bg-danger-solid`, `hover:bg-danger-solid-hover`; `bg-info-bg`,
`text-info-fg`, `border-info-border`, `bg-info-solid`.

### 3.6 Colour: domain

| Token             | Palette     | Use for                                                    |
|-------------------|-------------|------------------------------------------------------------|
| `money-positive`  | mint-600    | A positive amount shown `coloured`; "$X free".             |
| `money-negative`  | coral-600   | A negative amount shown `coloured`. A zero amount is uncoloured. |
| `progress-funded` | mint-500    | Progress fill at 100%, not overspent. 3.3:1 on the track.  |
| `progress-active` | ocean-400   | Progress fill at 1-99%. 3.1:1 on the track.                |
| `progress-behind` | amber-500   | A goal behind pace. 3.3:1 on the track.                    |
| `progress-over`   | coral-400   | Overspent. 3.4:1 on the track.                             |
| `progress-paused` | neutral-500 | Paused. 3.1:1 on the track.                                |
| `progress-track`  | neutral-100 | The unfilled track.                                        |
| `row-pending`     | amber-400   | The left rule on a pending transaction row.                |
| `row-unallocated` | ocean-400   | The left rule on a transaction row that needs a budget.    |

Progress fills reach 3:1 against the track, so a bar's state reads on
its own, not only through the chip beside it.

`StatusChip` colour pairs:

| Status   | Chip colours                     |
|----------|----------------------------------|
| funded   | `success-bg` / `success-fg`      |
| progress | `info-bg` / `info-fg`            |
| warn     | `warning-bg` / `warning-fg`      |
| over     | `danger-bg` / `danger-fg`        |
| paused   | `surface-muted` / `fg-muted`     |

### 3.7 Typography

**Fonts.** Both are loaded from `@fontsource`.
- **IBM Plex Sans** is used for words. Its warm, open shapes suit the
  neutral palette.
- **IBM Plex Mono** is used for **every number read as data**. That
  covers monetary amounts and balances, including a balance inside a
  sentence or after a label ("now $833.09"). It also covers account
  numbers, key prefixes and other numeric identifiers.
  - Plex Mono marks its zero and gives `1`, `l` and `I` distinct forms.
  - Plex Sans draws `0` as a plain oval, the same shape as `O`, so it
    is never used for figures.
  - The tabular widths line up amounts in columns.

**Size.** The root font size is 16px, the browser default, so the
user's text-size setting scales the whole app. Every size below is in
rem.

**How a role is applied.** Each role is one `fontSize` entry that
carries the size, line height, letter spacing and weight. Two things
can't go in that entry: the font family and `uppercase`. So:
- the amount roles are always paired with `font-mono`. `MoneyAmount`
  does both for a `Money` value; any other element that takes an amount
  role (a formatted figure, an account number, a key prefix, the
  currency code, the "--" for a missing amount) adds `font-mono` beside
  it;
- `text-overline` is applied only by `BaseSectionHeader`, which adds
  `uppercase`.

| Role           | Class                 | Size / line / weight                   | Font | Use for                                                          |
|----------------|-----------------------|----------------------------------------|------|------------------------------------------------------------------|
| Display amount | `text-display-amount` | 36 / 40 / 500                          | mono | The hero balance on a detail page.                               |
| Title amount   | `text-title-amount`   | 22 / 28 / 500                          | mono | A section-header amount.                                         |
| Amount         | `text-amount`         | 15 / 20 / 500                          | mono | Card and row balances; the TopBar unallocated amount.            |
| Small amount   | `text-amount-sm`      | 12 / 16 / 400                          | mono | Targets, running balances, amounts in meta lines.                |
| Page title     | `text-page-title`     | 22 / 28 / 500                          | sans | The one title of a page.                                         |
| Title          | `text-title`          | 18 / 24 / 500                          | sans | The title of a sheet, dialog, auth card or detail hero.          |
| Item title     | `text-item-title`     | 15 / 20 / 500                          | sans | The name in a card or list row.                                  |
| Body           | `text-body`           | 14 / 20 / 400                          | sans | Standalone prose: explanations, empty states, auth pages.        |
| Body small     | `text-body-sm`        | 13 / 18 / 400                          | sans | Copy inside cards and rows; button labels.                       |
| Label          | `text-label`          | 13 / 18 / 500                          | sans | Form-field labels; emphasised small copy.                        |
| Meta           | `text-meta`           | 12 / 16 / 400                          | sans | Secondary lines under a title; hints; timestamps.                |
| Overline       | `text-overline`       | 11 / 16 / 600, 0.06em                  | sans | The uppercase heading above a group of cards.                    |
| Badge          | `text-badge`          | 10 / 14 / 600                          | sans | Pills and badges (`PENDING`).                                    |
| Input          | `text-input`          | 16 / 24 / 400 below `md`, 14 from `md` | sans | Text in inputs, selects and textareas.                           |

- **Body small (13px)** is the working size for dense financial
  screens. It keeps cards and rows compact while staying readable.
  Body (14px) is for text that stands alone.
- **The TopBar unallocated amount** is reference information the user
  checks occasionally. It uses `text-amount`, so it stays secondary to
  the page's own content; the word "Unallocated" beside it takes the
  same role in Plex Sans so the two read as one line.
- **Inputs are 16px on phones,** so iOS Safari does not zoom the page
  when a field takes focus, and 14px from `md` up.
  - One `fontSize` entry can't change at a breakpoint, so the role is a
    `--text-input` variable in `tokens.css`, redefined under the `md`
    media query.
  - Only `BaseInput`, `BaseSelect` and `BaseTextarea` use it.

**Dates, times and numbers.** How they are displayed is declared once,
in `DISPLAY_FORMAT` (`frontend/src/domain/displayFormat.ts`): the locale,
the date style (`words`, "Jul 17, 2026", or `iso`, "2026-07-17") and the
clock (the locale's own, `12h` or `24h`). Every date formatter and
`formatMoney` read it, so a call site names only *which* form it shows:

| Form         | Words                        | ISO          | Use for                                         |
|--------------|------------------------------|--------------|-------------------------------------------------|
| `month-day`  | Sep 30                       | 2026-09-30   | A date within the current year (list headers, next funding). |
| `date`       | Jul 17, 2026                 | 2026-07-17   | Any other calendar date.                        |
| `month-year` | Aug 2026                     | 2026-08      | A goal's target month.                          |
| `full`       | Tuesday, October 15, 2024 at 2:34 PM | 2024-10-15 14:34 | A transaction's detail heading.     |

A date is set in Plex Sans in either style: it is read as a date, not
digit by digit. A date is never shown as a raw API string; it goes
through a form. A user's display preference, when there is one, is this
same object.

### 3.8 Spacing

The spacing scale is Tailwind's own: at the 16px root, `p-4` is 16px,
as every Tailwind developer expects. Named aliases cover the recurring
layout distances, so a change such as "tighten card padding" is one
edit. Page and card padding are 12px each, which leaves a transaction
row's budget line and balance room to show in full on a phone:

| Alias      | Value | Use for                                             |
|------------|-------|-----------------------------------------------------|
| `page-x`   | 12px  | Horizontal page padding (`px-page-x`).              |
| `card-x`   | 12px  | Card and list-row horizontal padding.               |
| `card-y`   | 12px  | Card and list-row vertical padding.                 |
| `stack-sm` | 8px   | The gap between related items (a label and field).  |
| `stack-md` | 12px  | The gap between cards in a list (`space-y-stack-md`). |
| `section`  | 24px  | The gap between page sections.                      |

### 3.9 Radius

| Token             | Value  | Use for                                                       |
|-------------------|--------|---------------------------------------------------------------|
| `rounded-xs`      | 4px    | Badges, day-grid cells.                                       |
| `rounded-control` | 10px   | Inputs, buttons, sub-cards, chips.                            |
| `rounded-card`    | 14px   | Cards; sheets (only the top corners on phones).               |
| `rounded-pill`    | 9999px | Pills, toggles, icon buttons, avatars.                        |

Every primary and secondary button has the same shape, `rounded-control`,
so buttons read as one family.

### 3.10 Borders

Borders are 1px, so hairlines render consistently and stay visible on
every display.

### 3.11 Elevation

Cards are outlined, not raised. Shadows mark things that float above
the page.

| Token            | Use for                                                      |
|------------------|--------------------------------------------------------------|
| `shadow-none`    | Cards.                                                       |
| `shadow-raised`  | The standalone auth card (login, email-change pages).        |
| `shadow-control` | A toggle thumb.                                              |
| `shadow-overlay` | Sheets and dialogs.                                          |

### 3.12 Layers (z-index)

| Token      | Value | Use for                                              |
|------------|-------|------------------------------------------------------|
| `z-sticky` | 10    | Sticky in-content headers (transaction date groups). |
| `z-nav`    | 30    | The TopBar and BottomNav.                            |
| `z-sheet`  | 40    | Bottom sheets and full-screen edit sheets.           |
| `z-dialog` | 50    | Confirmations and dialogs that open over a sheet.    |

### 3.13 Motion

| Token           | Value                        | Use for                        |
|-----------------|------------------------------|--------------------------------|
| `duration-fast` | 120ms                        | Fades (scrims, popovers), leave transitions; the default for `transition-*` utilities. |
| `duration-base` | 200ms                        | Colour and toggle transitions. |
| `duration-slow` | 250ms                        | Sheet slide-up.                |
| `ease-standard` | `cubic-bezier(0.4, 0, 0.2, 1)` | Transitions that change a state in place (the default). |
| `ease-enter`    | `cubic-bezier(0, 0, 0.2, 1)` | Something appearing: it decelerates into place. |
| `ease-exit`     | `cubic-bezier(0.4, 0, 1, 1)` | Something leaving: it accelerates away. |

`motion.css` defines the one `fade` and one `slide-up` transition that
every `<Transition>` uses. Reduced-motion handling comes with the
planned accessibility work.

### 3.14 Sizing

| Token                           | Value       | Use for                                                 |
|---------------------------------|-------------|---------------------------------------------------------|
| `size-icon-xs`                  | 12px        | Inline icons in meta text (the TopBar chevron).         |
| `size-icon-sm`                  | 16px        | Icons in buttons, rows and chips.                       |
| `size-icon-md`                  | 20px        | Navigation and icon buttons.                            |
| `size-icon-lg`                  | 24px        | Empty states and nav tabs.                              |
| `tap-min`                       | 44px        | The minimum hit area of any control (`min-h-tap-min`).  |
| `h-topbar`                      | 64px        | The TopBar height.                                      |
| `h-bottomnav`                   | 64px        | The BottomNav height.                                   |
| `w-sheet`                       | 480px       | Sheet and dialog width from `md`.                       |
| `max-h-sheet`                   | 80vh        | The tallest a sheet or dialog grows before it scrolls.  |
| `border-l-rule`                 | 3px         | The coloured left rule on a transaction row.            |
| `h-progress-sm` / `h-progress-md` / `h-progress-lg` | 3 / 5 / 8px | Progress bars: the fill-up band, budget card, detail hero (`ProgressBar size`). |

Icons are Tabler (`@tabler/icons-vue`), sized with `size-icon-*`.

### 3.15 Focus and touch

- **Keyboard focus.** Every element focused from the keyboard draws a
  `--focus-ring-width` (2px) outline in `border-focus`, offset by
  `--focus-ring-offset` (2px) so it reads against any fill, and following
  the element's radius (`styles/interaction.css`). Form fields draw
  their own ring instead; a `BaseToggle` draws it on its track.
- **Touch targets.** `.tap-target` gives a control a hit area of at
  least `tap-min` (44px) with an invisible pseudo-element, so a 28px
  icon button keeps its look and is still easy to tap. `BaseButton` and
  `BaseIconButton` carry it; neighbours sit 44px apart centre to centre
  so their hit areas do not overlap.
- **Hover reveals.** `can-hover:` applies only on a device with a
  hovering pointer. A control revealed on hover (a row's remove button)
  is written `can-hover:opacity-0 can-hover:group-hover:opacity-100
  can-hover:focus-visible:opacity-100`, so it is always visible on a
  touch screen and appears for keyboard focus.
- **Sheets.** `BaseSheet` moves focus into the sheet when it opens and
  keeps Tab inside it while it is the topmost modal
  (`useFocusTrap`); Escape closes it and focus returns to where it was.

## 4. Design choices

| Choice                                                       | Reason                                                                                                         |
|--------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------|
| Plex Mono for every number read as data                      | Every digit is unambiguous: a marked zero; distinct `1`, `l` and `I`.                                          |
| 16px root, every size in rem                                 | The user's text-size setting scales the whole app, and Tailwind's spacing means its documented values.         |
| Accent and solid status fills at the 600 step                | White text on them is at least 6.5:1, and primary actions stand out clearly.                                  |
| Three muted levels: `fg-muted`, `fg-subtle`, `icon-muted`    | One shade per role. Both text levels pass AA; decorative icons stay light so they recede.                      |
| Input outlines and the off-state toggle track at `border-strong` | Controls are easy to find and their state is easy to read. A clear boundary beats a subtle one.            |
| Progress fills at least 3:1 on the track                     | A bar's state reads without its chip.                                                                          |
| Status borders as a tint of the status colour                | The box is grouped with its message without the border competing with the text.                               |
| Body small (13px) for copy in cards and rows                 | Dense financial screens stay compact without text getting too small to read.                                  |
| One button shape                                             | Buttons read as one family.                                                                                    |
| 1px borders                                                  | Hairlines render consistently and stay visible on every display.                                               |
| 16px inputs on phones                                        | iOS Safari does not zoom the page when a field takes focus.                                                    |
| One sheet width                                              | Every sheet and dialog opens at the same size from `md` up.                                                    |
| A disabled filled button turns grey; other controls fade to 50% | The change of colour marks the state at a glance; outlined and text controls keep their shape and fade.   |
| Secondary buttons are filled with `surface`                  | They read as buttons on the canvas as well as inside cards.                                                    |
| A field's hint sits below the control                        | Label, control, then help and errors: the order a reader meets them.                                           |

## 5. Purpose -> token / primitive lookup

Find what you are styling in the left column; use what the right column
names. When nothing fits, add a token (section 9) or a primitive variant
(section 10) rather than writing a one-off class.

| Purpose                                                        | Use                                                                                         |
|----------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| Primary content: names, values, body copy                      | `text-fg`                                                                                   |
| Secondary text: metadata, running balances, hints              | `text-fg-muted`                                                                             |
| Tertiary text: placeholders, the "--" for a missing value      | `text-fg-subtle`                                                                            |
| Text of a disabled control                                     | `text-fg-disabled` (a disabled `BaseButton` does this itself)                               |
| Text or an icon on a filled button                             | `text-fg-on-accent`                                                                         |
| An inline link or a text button                                | `BaseButton variant="link"` (`text-fg-link`)                                                |
| A decorative icon (row chevron, swipe hint)                    | `text-icon-muted`                                                                           |
| Accent-coloured text or icon (active tab, CTA label)           | `text-accent-fg`                                                                            |
| The app background                                             | `bg-canvas`                                                                                 |
| A card                                                         | `BaseCard` (`bg-surface`, `border-border`, `rounded-card`)                                  |
| A padded block inside a card                                   | `BaseCardSection`                                                                           |
| A row in a list inside a card                                  | `BaseListRow` (`as="button"` + `chevron` when it opens something)                           |
| A read-only field or an inset row                              | `bg-surface-sunken`                                                                         |
| A skeleton block, an unselected pill, an icon-button hover     | `bg-surface-muted`                                                                          |
| Hover on a `surface-muted` element, empty meter segments       | `bg-surface-strong`                                                                         |
| The overlay behind a sheet                                     | `BaseSheet` (`bg-scrim/40`)                                                                 |
| A divider between rows                                         | `BaseListRow` / `BaseCardSection` draw it (`border-border-subtle`)                          |
| A card outline or a divider between sections                   | `border-border`                                                                             |
| A hovered selectable card or chip; a neutral badge outline     | `border-border-emphasis`                                                                    |
| An input, select or textarea                                   | `BaseInput`, `BaseSelect`, `BaseTextarea` (`border-border-strong`)                          |
| A label, control, hint and error together                      | `BaseFormField`                                                                             |
| A form validation message                                      | `BaseFormField` `error` prop (`text-danger-fg`, `role="alert"`)                             |
| An on/off switch                                               | `BaseToggle` inside a `<label>`                                                             |
| The primary action                                             | `BaseButton` (default `variant="primary"`, `bg-accent`)                                     |
| A secondary action, Cancel                                     | `BaseButton variant="secondary"`                                                            |
| A destructive confirm button                                   | `BaseButton variant="danger"`                                                               |
| A destructive trigger that opens a confirmation                | `BaseButton variant="danger-secondary"`                                                     |
| A tinted text action ("Edit")                                  | `BaseButton variant="ghost"`                                                                |
| A destructive text action ("Revoke", "Cancel invitation")      | `BaseButton variant="link-danger" size="sm"`                                                |
| A button with only an icon                                     | `BaseIconButton` with a `label` (`tone="danger"` to delete, `pressed` to toggle)            |
| A selected segment or tab                                      | `bg-accent` + `text-fg-on-accent`, or `border-accent-border` + `text-accent-fg`             |
| A tinted call-to-action card, a selected row                   | `bg-accent-subtle`                                                                          |
| An error, success, info or warning message                     | `BaseBanner tone="..."`                                                                     |
| A status tag on a row ("PENDING", "SPLIT")                     | `BaseBadge tone="warning"` / `"neutral"`                                                    |
| A budget's status                                              | `StatusChip`                                                                                |
| A budget's progress                                            | `ProgressBar` with `progressTone(status)` and `size`                                        |
| A monetary value                                               | `MoneyAmount` (`size`, `coloured` for `money-positive` / `money-negative`)                  |
| Any other figure read digit by digit                           | an amount role + `font-mono`                                                                |
| A date or time                                                 | a `DateForm` via the formatters in `domain/dates.ts`                                        |
| A page's title                                                 | `BasePageHeader`                                                                            |
| The heading above a group of cards                             | `BaseSectionHeader`                                                                         |
| The header strip across a card                                 | `BaseSectionHeader card`                                                                    |
| A sheet's or dialog's title                                    | `BaseSheet` `title` (`text-title`)                                                          |
| A card or row name                                             | `text-item-title`                                                                           |
| Copy inside a card, a button label                             | `text-body-sm` / `text-label`                                                               |
| Standalone prose (empty states, auth pages)                    | `text-body`                                                                                 |
| A secondary line under a title                                 | `text-meta`                                                                                 |
| A loading placeholder                                          | `BaseSkeleton`                                                                              |
| An empty list                                                  | `EmptyState`                                                                                |
| A modal, bottom sheet or dialog                                | `BaseSheet` (`layer="dialog"` over another sheet)                                           |
| A confirmation before a destructive action                     | `ConfirmSheet`                                                                              |
| Page padding                                                   | `px-page-x`                                                                                 |
| Card and row padding                                           | `px-card-x` / `py-card-y` (the primitives use them)                                         |
| Gap between cards; between page sections                       | `space-y-stack-md`; `section`                                                               |
| An icon                                                        | a Tabler icon with `size-icon-xs` / `-sm` / `-md` / `-lg`                                   |
| A small control that needs a 44px hit area                     | `.tap-target` (`BaseButton` and `BaseIconButton` have it)                                   |
| Content revealed on hover                                      | `can-hover:opacity-0 can-hover:group-hover:opacity-100 can-hover:focus-visible:opacity-100` |
| A sticky in-content header / the nav bars / a sheet / a dialog | `z-sticky` / `z-nav` / `z-sheet` / `z-dialog`                                               |
| A standalone card that floats (auth pages)                     | `shadow-raised`                                                                             |
| An enter / leave transition                                    | `ease-enter` / `ease-exit` with `duration-fast` / `duration-base`; sheets use `motion.css`  |

## 6. Primitive catalogue

Every primitive is in `src/components/base/`, has a header comment and a
test in `tests/components/base/`. A caller passes props for everything
the primitive styles and adds only classes for properties it does not
set (section 1).

**`BaseButton`** -- the one button.
- Props: `variant` (`primary` | `secondary` | `danger` | `danger-secondary` |
  `ghost` | `link` | `link-danger`, default `primary`), `size` (`sm` | `md`),
  `block`, `loading`, `disabled`, `as` (`a`, `"RouterLink"`), `type`.
- `loading` disables it and sets `aria-busy`. A disabled filled button
  turns grey; the others fade. It carries `.tap-target`.
```vue
<BaseButton variant="secondary" class="flex-1" @click="cancel">Cancel</BaseButton>
<BaseButton type="submit" :loading="saving">Save</BaseButton>
<BaseButton as="RouterLink" :to="{ name: 'overview' }" block>Go to overview</BaseButton>
```

**`BaseIconButton`** -- a round button whose only content is an icon.
- Props: `label` (required; the `aria-label`), `size` (`sm` 28px | `md`
  40px), `tone` (`default` | `danger`), `pressed` (a toggle; sets
  `aria-pressed`).
- Its hit area is 44px; keep neighbours 44px apart centre to centre.
```vue
<BaseIconButton label="Search transactions" @click="toggleSearch">
  <IconSearch class="size-icon-md" />
</BaseIconButton>
```

**`BaseInput`, `BaseSelect`, `BaseTextarea`** -- form fields.
- Every attribute and listener lands on the native element; `v-model`
  binds the value; `focus()` is exposed.
- Props: `invalid` (danger border, `aria-invalid`), `mono` (input only),
  `size` (`sm` | `md`, input and select), `inline` (leave the width to the
  caller).
- Inputs use `text-input`: 16px on phones, so iOS does not zoom.

**`BaseFormField`** -- label, control, hint and error, wired together.
- Props: `label`, `id` (generated if omitted), `hint`, `error`, `optional`.
- The default slot receives `{ id, describedBy, invalid }`.
```vue
<BaseFormField label="New password" :error="fieldError('new_password')">
  <template #default="{ id, describedBy, invalid }">
    <BaseInput :id="id" v-model="password" type="password"
      :aria-describedby="describedBy" :invalid="invalid" />
  </template>
</BaseFormField>
```

**`BaseToggle`** -- an on/off switch. `v-model` binds a boolean. Place it
inside a `<label>` that names it; the hidden checkbox has `role="switch"`
and the track shows the focus outline.

**`BaseCard`** -- props `padded`, `as`. **`BaseCardSection`** -- a padded
block with a divider below. **`BaseListRow`** -- props `as`, `chevron`,
`align` (`center` | `start`); interactive when `as` is a button or link.

**`BaseSectionHeader`** -- props `title`, `as` (default `h2`), `card`
(header strip); slot `actions`. **`BasePageHeader`** -- prop `title` (the
page's `h1`); slot `actions`.

**`BaseBanner`** -- prop `tone` (`danger` | `success` | `info` | `warning`).
A danger banner has `role="alert"`, the others `role="status"`.

**`BaseBadge`** -- props `tone` (`warning` | `neutral`), `variant`
(`outline` | `soft`).

**`BaseSkeleton`** -- prop `shape` (`card` | `line`); size it with classes.
Hidden from screen readers.

**`BaseSheet`** -- every sheet and dialog.
- Props: `open`, `title` or `label`, `layer` (`sheet` | `dialog`), `align`
  (`center` | `top`), `fullscreen`. Emits `close`.
- Slots: default (the body), `header-actions`, `footer`.
- Teleports to `body`, locks scroll, closes on Escape and the scrim,
  traps focus while topmost, and returns focus on close.
```vue
<BaseSheet :open="open" title="Move money" @close="emit('close')">
  ...form...
</BaseSheet>
```

**`MoneyAmount`** -- props `amount` (`Money`), `size` (`sm` | `md` | `lg` |
`hero`), `coloured`, `showSign`; Plex Mono, with the raw value as its
`aria-label`. **`ProgressBar`** -- props `value` (0-100), `tone`
(`ProgressTone`), `size` (`sm` | `md` | `lg`). **`StatusChip`** -- props
`status`, `label`. **`EmptyState`** -- props `title`, `message`,
`actionLabel`; the icon goes in the slot; emits `action`.

## 7. Layout conventions

- `AppShell` holds the app chrome: the TopBar, the BottomNav below
  `md`, and the SideNav from `md` (icons, with labels from `lg`). Pages
  render in its main area with `px-page-x`.
- The breakpoints in use are `md` (768px) and `lg` (1024px).
- Form pages are `max-w-lg`, centred.
- Sheets are full width at the bottom on phones and a centred `w-sheet`
  card from `md`; a full-screen sheet slides up over the canvas.
- A strip that runs edge to edge inside the page padding (a search bar,
  tabs, a sticky date header) uses `-mx-page-x px-page-x`.

## 8. How to change an existing style

Each recipe names the one place to edit and what else changes with it.

- **Change the accent colour.** Edit `--color-accent` (and
  `--color-accent-hover`, `--color-accent-fg`) in `tokens.css`, pointing
  at another palette step, or add a step to the palette first. Every
  primary button, selected segment, active tab and link follows. Check
  white text on `accent` stays at least 4.5:1.
- **Make section labels bigger.** Edit `--text-overline` (and
  `--leading-overline`) in `tokens.css`. Every `BaseSectionHeader` follows.
- **Tighten card padding.** Edit `--space-card-x` / `--space-card-y`.
  Every `BaseCard padded`, `BaseCardSection`, `BaseListRow` and banner
  follows.
- **Restyle every primary button.** Edit the `primary` entry in
  `BaseButton.vue`'s `VARIANTS`, or the shape in its `classes`. Every
  primary button follows; secondary and danger keep their own entries.
- **Make one specific label bigger.** Use a different existing role for
  that element (`text-item-title` instead of `text-label`), or add a
  variant to the primitive that renders it. Either way the change is
  named, so say which, and check the role's other users: a local-looking
  change may be global.
- **Change the muted text shade.** Edit `--color-fg-muted` in
  `tokens.css`. All secondary text follows; check it stays at least 4.5:1
  on `surface`, `canvas` and `surface-muted`.
- **Change the sheet animation.** Edit `styles/motion.css` (the `fade` and
  `slide-up` classes) or the `--duration-*` / `--ease-*` tokens it reads.
  Every sheet follows.
- **Change how dates or times read.** Edit `DISPLAY_FORMAT` in
  `domain/displayFormat.ts`. Every rendered date, time and amount follows.

## 9. How to add a token

1. Add the value to `tokens.css`: a palette step if the colour is new,
   then the semantic token referencing it
   (`--color-row-flagged: var(--palette-amber-400);`).
2. Map it in `tailwind.config.ts` (`row: { flagged: token("row-flagged") }`).
3. Add a row to the matching table in section 3 (value, class, use for,
   not for) and to the lookup table in section 5.
4. Run `pnpm lint:styles`, `pnpm type-check` and `pnpm test`, and check
   contrast for any colour that carries text or meaning.

## 10. How to add a primitive or variant

- A primitive lives in `src/components/base/Base<Name>.vue`, named with
  the `Base` prefix. It is presentational: typed props, typed emits, no
  API or store imports, and a header comment saying what it is and what
  each prop does.
- Style comes only from tokens; every property the primitive sets is
  controlled by a prop, so callers never override it.
- A variant is a new value of an existing prop (`variant`, `size`,
  `tone`), with its classes written out literally so Tailwind generates
  them.
- Add a test in `tests/components/base/`: a parametrized case per
  variant asserting its token classes, and one that attributes and
  listeners reach the element.
- Add it to the catalogue (section 6) and the lookup table (section 5).

## 11. Keeping this document current

- A new token or primitive lands in section 3 or 6 and in the lookup
  table in the same change that adds it.
- `frontend/CLAUDE.md` holds the short rules Claude Code follows in the
  SPA; when a rule here changes (the caller-class rule, the lint rules,
  a new primitive family), update it in the same change.
- `docs/spa/screens.md` describes what each screen shows and does; this
  document describes how everything looks.
