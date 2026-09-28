# CLAUDE.md -- the SPA (`frontend/`)

Rules for working on the SPA. Where code goes is in
[../docs/spa/architecture.md](../docs/spa/architecture.md); how to test
is in [../docs/spa/testing.md](../docs/spa/testing.md); how things look
and why is in [../docs/spa/styling.md](../docs/spa/styling.md).

## Styling

- **To change how something looks, change the token or the primitive,
  not the call site.** Find the element's role in the lookup table in
  `docs/spa/styling.md` (section 5), then edit that token in
  `src/styles/tokens.css` or that primitive in `src/components/base/`
  and let the change propagate.
- **Never write** a hex, `rgb()` or `hsl()` colour, a Tailwind arbitrary
  value (`text-[13px]`, `w-[420px]`), a raw palette or stock colour class
  (`bg-ocean-400`, `text-neutral-500`, `bg-white`, `text-gray-*`), a static
  `style="..."`, a `<style>` block outside `components/base/`, or
  `!important`. `pnpm lint:styles` rejects them.
- **Use a `Base*` primitive** for buttons, icon buttons, inputs, selects,
  textareas, form fields, cards, card sections, list rows, section and
  page headers, banners, sheets, toggles, badges and skeletons before
  writing markup by hand. A `Money` value is `MoneyAmount`; any other
  figure read digit by digit takes an amount role with `font-mono`. A
  budget's progress is `ProgressBar`; its status is `StatusChip`.
- **Pass a primitive props, not overrides.** Add classes only for
  properties it does not set (margin, width, flex, position, a hover
  tint, an elevation); never a class for its colour, type, padding or
  shape.
- **Dates, times and amounts** go through the formatters in
  `src/domain/dates.ts` (a `DateForm`) and `formatMoney` / `MoneyAmount`,
  which read `DISPLAY_FORMAT` in `src/domain/displayFormat.ts`. Never
  format with ad-hoc `Intl` options or show a raw API string.
- **If no token or primitive fits**, add one by the procedure in
  `styling.md` (sections 9 and 10: `tokens.css` -> `tailwind.config.ts`
  -> the doc's tables -> lint), and say in the reply or PR which token or
  variant you added and why. Do not work around the system.
- **A request that sounds local** ("make *this* label bigger") still
  goes through the system: use a different existing role, or add a
  variant to the primitive. Say which, because it may change other
  places. When unsure whether the change is meant globally or locally,
  ask.
- **Accessibility floor:** text at least 4.5:1, meaningful non-text
  marks at least 3:1, a visible `focus-visible` outline (global, from
  `styles/interaction.css`), and 44px touch targets (`.tap-target`;
  `BaseButton` and `BaseIconButton` have it).

## After a change

Run, from `frontend/`:

```bash
pnpm lint:styles
pnpm type-check
pnpm test
```

## Keeping this file current

When a rule in `docs/spa/styling.md` changes, update this file in the
same change.
