# Interface styles

The interface uses local CSS without a global component framework.

- `app/static/css/tokens.css` defines theme colors, semantic statuses, typography,
  spacing, radii, control sizes, layout dimensions, shadows and layer ordering.
- `app/static/css/custom.css` defines shared components and responsive layout.
- Templates describe content and use component classes. Do not put visual styles
  or component dimensions in template attributes or JavaScript.

Use `.app-control` for inputs and selects, `.box-field-stack` for labeled fields,
`.btn` for primary actions, `.btn--secondary` for secondary actions, and `.icon-btn`
for icon controls. Panels use `.box`, `.box__pad` and `.box__section`. Empty output
uses `.empty-state`; wide tables use a labeled, keyboard-focusable `.table-scroll`.

Light and dark themes share the same semantic variables. To change a color or
dimension throughout the interface, edit its token rather than adding overrides.
Status values keep both text labels and theme-aware colors.

JavaScript only supplies the calculated `--browse-depth` value from `data-depth`
for lazy tree nodes. The indentation step is a CSS token; popover placement and
appearance are entirely CSS. SVG viewBox coordinates describe icon artwork,
while rendered icon dimensions come from tokens.

Responsive thresholds (560, 800 and 1100 px) stay in media queries because native
CSS custom properties cannot be used in media-query conditions. At narrow widths,
forms stack and tables scroll within their own region. Navigation defaults to a
compact rail, and its toggle opens the full sidebar. Job details become an overlay
below 1100 px. Focus rings, Escape dismissal, current navigation markers and
reduced-motion preferences are supported.

Verification: `python -m pytest -q`, then check Browse, Compare and Settings in both
themes, including a narrow viewport, lazy tree expansion, filters and job details.
