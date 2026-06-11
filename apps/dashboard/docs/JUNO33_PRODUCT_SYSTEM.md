# Juno33 Product System

This is the implementation-facing source of truth for the current Juno33 UX direction. It complements the Figma `Juno33 Product System` file; production code remains authoritative.

## North Star

Juno33 is an operator workstation for Instagram and Threads publishing. The interface should feel dense, calm, and execution-oriented: compose first, validate intelligently, schedule clearly, and finish mobile handoffs without guessing.

## Visual System

- Use `src/index.css` Tailwind v4 tokens as the canonical palette, spacing, radius, type, and surface system.
- Keep the graphite operator shell and restrained oxblood/gold/green semantic accents.
- Prefer existing primitives in `src/components/ui`, `src/components/composer`, `src/components/calendar`, and shared page chrome before adding new component styles.
- Untitled UI and Kole Jain resources are references for structure and polish, not replacement design systems.

## Component Strategy

- Keep Composer, Calendar, Handoff, analytics tiles, command surfaces, and app chrome custom to Juno33.
- Use shadcn patterns for forms, dialogs, sheets, command menus, empty states, alerts, badges, focus states, and keyboard behavior.
- New shadcn primitives must live under the configured `@/src/components/shadcn` alias and use Juno33 tokens, not raw color palettes.

## Product Flow Rules

- Classification comes before validation: platform, post type, publish path, then validation.
- Auto-publish uses strict API validation.
- Notify Me uses relaxed native-handoff validation and clear warnings.
- Drag workflows need non-drag alternatives.
- First-time users should see a clear setup path, not blank surfaces.

## QA Rule

For rendered UI changes, run the normal checks plus browser validation: target route loads, app is not blank, no framework overlay, console health is acceptable, screenshots support the claim, and at least one real interaction works.
