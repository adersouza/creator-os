# Creator OS — Frontend Audit (2026-06-16)

Scope: the two UI surfaces — **ThreadsDashboard / Juno33** (production SaaS, `juno33.com`) and **ContentForge** (internal Next.js tool). Read-only audit. Reviewer stance: blunt, evidence-based, pessimistic. Companion to `AUDIT_2026-06-16.md`; no overlap with backend/pipeline findings except where the UI touches them.

---

## Scorecard

| Area | Rating | One-line |
|------|--------|----------|
| Stack choice (TD) | 8.5/10 | Modern, correct, no runtime-lib lock-in. React 19 + Vite + TanStack + shadcn/Radix is the right SaaS stack. |
| UI library hygiene (TD) | 5/10 | Right libraries, sloppy state — split component dirs, mixed Radix imports, 5 third-party registries. Active bug + supply-chain risk. |
| Test/quality tooling (TD) | 9/10 | Vitest + Playwright matrix + Storybook a11y + Chromatic + Lighthouse CI + a real custom lint-guard suite. Genuinely strong. |
| Code structure (TD) | 5.5/10 | Monster page components (Composer 5.9k LOC, Autopilot 4.4k), thin code-splitting (7 lazy files / 742). Maintainability + bundle risk. |
| Dependency consistency | 6/10 | Mixed zod majors (v3 + v4 → shim tax), `lucide-react ^1.17.0` to verify, half-finished Radix unification. |
| ContentForge frontend | n/a | No shadcn/Radix; bare Tailwind v3. Fine as a thin tool; a consolidation cost if it grows. |

**Overall TD frontend: 7/10.** Foundation is strong and well-tested. The drop is hygiene and a couple of structural smells — fixable without rearchitecting.

---

## ThreadsDashboard / Juno33

**Stack:** React 19.2 · Vite 8 · TypeScript · Tailwind v4 (`@theme` in `src/index.css`, no `tailwind.config.js`) · react-router-dom 7 · TanStack Query 5 (+ persist-client, devtools) · TanStack Table 8 · TanStack Virtual 3 · Zustand 5 · react-hook-form 7 · Zod 4 · Recharts 3 · shadcn (style `nova`) on Radix · cmdk · sonner · vaul · lucide.

Size: 742 `.ts/.tsx` files, ~107k LOC in `src`.

### What's strong (credit where due)

- **Library choice is correct.** shadcn (copy-in, you own the source) over MUI/Chakra/antd is the right call for a Tailwind-token design system — no runtime component lib to fight, full restyle control. TanStack Query for server state + Zustand for client state is the idiomatic 2026 split. No Redux bloat. No styled-components/emotion runtime cost.
- **Test/quality tooling is above most production SaaS.** Vitest 4 (58 test files), Playwright with segmented projects (`critical`, `scale`, `mobile-chrome`, `smoke` against prod, `public`), Storybook 10 with `addon-a11y` + Chromatic visual regression, Lighthouse CI (`test:perf`), promptfoo AI evals.
- **`compat:check` is a real governance asset.** Custom guard suite blocks banned APIs (`crypto.randomUUID`, `Array.at(-n)`), enforces Zod-import discipline, service boundaries, client-API-fetch rules, RLS-first routes, privileged-DB boundaries, schema-drift boundaries, lazy-route integrity, and pipeline-contract sync. This is the kind of CI most teams don't have. Keep it; extend it (see fixes).

### Problems (evidence-backed)

1. **Split-brain component directories.**
   - `src/components/ui` = **99** files; `src/components/shadcn` = **51** files.
   - `components.json` aliases `ui` → `@/src/components/shadcn`, but the majority of components live in `ui/`.
   - Two homes for the same component class = drift. New `shadcn add` writes to `shadcn/`; legacy hand-rolled components rot in `ui/`. Pick one directory, migrate, delete the other, fix the alias.

2. **Mixed Radix import styles — duplicate-instance footgun.**
   - Both the unified `radix-ui ^1.4.3` meta-package **and** 20 granular `@radix-ui/react-*` packages are installed.
   - Code is split: **13** imports `from "radix-ui"`, **25** `from "@radix-ui/*"`.
   - Risk: two copies of the same primitive → mismatched React context → broken portal/focus/dialog behavior + bundle bloat. shadcn migrated to the unified package; this is a half-finished migration. Standardize on the meta `radix-ui` package, drop the granular duplicates.

3. **Five third-party shadcn registries wired = supply-chain surface.**
   - `components.json` registries: `@uitripled`, `@kibo-ui`, `@magicui`, `@motion-primitives`, `@blocks-so`.
   - `shadcn add @magicui/x` pulls code from third-party URLs **directly into the tree** — unvetted code into a production SaaS. Given the secret-exposure findings in the main audit, this matters. Mitigation: treat any registry `add` as a code-review event (diff before commit); pin what's already present; don't add from a registry to prod without review.

4. **Monster page components.**
   - `src/pages/Composer.tsx` = **5,905 LOC**; `Autopilot.tsx` = **4,390**; `Analytics.tsx` = **2,050**; `Listening.tsx` = **1,845**.
   - A 5.9k-LOC component is a re-render and maintainability liability — every state change risks wide re-renders, and the file is hard to test in isolation. Decompose into feature sub-components + colocated hooks. This is the single highest-effort frontend item.

5. **Thin code-splitting relative to bundle size.**
   - Only **7** files across 742 use `React.lazy`/`lazy(`. With Composer alone at 5.9k LOC, the initial bundle likely carries far more than first paint needs.
   - `check-lazy-routes.mjs` exists (routes may be lazy at the router level), but verify the heavy pages (Composer, Autopilot, Analytics) are actually route-split and not eagerly imported. Confirm with a bundle analysis (`vite build` + visualizer) — don't assume.

6. **Mixed Zod major versions.**
   - `zod ^4.4.3` at top level, but `^3.25.76` and `^4.4.3` resolve in nested/override positions. This is the reason for the Zod shim (`api/_lib/zod`, `zodCompat.ts`) flagged in `CLAUDE.md`.
   - The shim is a tax, not a bug — but converging on one Zod major removes a whole class of "import from the wrong zod" mistakes that `compat:check` currently has to police.

7. **`lucide-react ^1.17.0` — verify provenance.** Installed resolves to 1.17.0. Confirm it's the genuine `lucide-react` and not a version typo / look-alike. Low effort; worth a glance given finding #3.

---

## ContentForge

- **No shadcn, no Radix, no `components.json`.** Tailwind v3 (`^3.4.1`) only. Entirely different stack from TD.
- **As-is verdict:** fine if CF stays a thin internal tool — don't add a component system for a handful of buttons.
- **Consolidation cost:** if creator-os monorepo merges these, you maintain two UI systems (TD = shadcn/Radix/Tailwind v4; CF = bare Tailwind v3) — double the component work, no shared design language.
- **If CF grows real UI surface:** adopt the same shadcn baseline and share a `packages/ui` workspace so components and tokens are defined once.

---

## Recommended frontend fixes (priority order)

1. **Standardize Radix imports** on the unified `radix-ui` package; remove the granular `@radix-ui/react-*` duplicates. (Bug risk — do first.)
2. **Consolidate the two component directories** into one (`shadcn/` per the alias, or pick `ui/` and fix `components.json`); migrate and delete the other.
3. **Decompose Composer.tsx and Autopilot.tsx** into feature sub-components + hooks. Highest effort, highest maintainability payoff.
4. **Run a bundle analysis**; lazy-load the heavy pages if they aren't already route-split. Confirm, don't assume.
5. **Converge on one Zod major** to retire the shim tax.
6. **Treat registry `add`s as code review** (`@magicui` etc.); document which registries are approved.
7. **Verify `lucide-react` provenance.**
8. **ContentForge:** leave as-is unless its UI grows; if it does, share a `packages/ui` with TD.

None of these are foundation-level. The stack and test discipline are sound — this is cleanup, not a rebuild.
