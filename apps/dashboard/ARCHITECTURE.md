# Juno33 Dashboard Frontend Architecture

This package uses shadcn source as editable registry code, but the app-facing
API is Juno-owned.

## Component Ownership Boundary

- `src/components/shadcn/*` is generated or registry-adapted source. Treat it as
  lower-level implementation code that may be refreshed by the shadcn CLI or by
  reviewed registry imports.
- `src/components/ui/*` and `src/components/layout/*` are the stable
  product-facing wrappers. Route, page, and product workflow code should import
  from these directories.
- `src/pages/*` and `src/routes/*` must not import directly from
  `src/components/shadcn/*`. The `compat:check` script enforces this with
  `scripts/check-ui-boundaries.mjs`.

## Registry Review Rule

The configured registries (`@uitripled`, `@kibo-ui`, `@magicui`,
`@motion-primitives`, and `@blocks-so`) are source inputs, not direct product
dependencies. When registry code is useful:

1. Review the generated diff.
2. Remove demo data, hard-coded colors, and assumptions that bypass Juno tokens.
3. Promote the useful behavior into a Juno wrapper under `src/components/ui/*`,
   `src/components/layout/*`, or another app-owned feature boundary.
4. Import the wrapper from product code, never the raw registry output.

This keeps the app visually consistent while preserving the ability to adopt
high-quality registry patterns.
