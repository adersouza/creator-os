# Creator OS — Frontend Audit (2026-06-16)

Scope: the two UI surfaces — **ThreadsDashboard / Juno33** (production SaaS, `juno33.com`) and **ContentForge** (internal Next.js tool). Read-only audit. Reviewer stance: evidence-based and pessimistic where risk is not yet controlled.

This audit is a companion to `AUDIT_2026-06-16.md`. It intentionally avoids duplicating backend, pipeline, contract, scheduling, publishing, inventory, or security findings from that audit unless a frontend boundary directly depends on them.

---

## Current Evidence Snapshot

Evidence re-checked against `creator-os` on 2026-06-16:

| Evidence | Current value |
|---|---:|
| Dashboard `apps/dashboard/src` TS/TSX files | 727 |
| Dashboard `apps/dashboard/src` LOC | 171,712 |
| Dashboard `src/components/ui` TS/TSX files | 87 |
| Dashboard `src/components/shadcn` TS/TSX files | 50 |
| `src/pages/Composer.tsx` | 5,901 LOC |
| `src/pages/Autopilot.tsx` | 4,374 LOC |
| `src/pages/Listening.tsx` | 1,844 LOC |
| `src/pages/Analytics.tsx` | 1,586 LOC |
| Imports from unified `radix-ui` package | 40 |
| Imports from granular `@radix-ui/react-*` packages | 0 |
| Direct granular `@radix-ui/react-*` dependencies | 0 |
| Route lazy imports | concentrated in `apps/dashboard/src/routes/routeRegistry.tsx` via `lazyWithRetry` |

The prior audit's older size, component-count, and "7 lazy files" claims are stale. Route-level lazy loading is now materially present through the route registry; the remaining risk is not "no lazy loading", it is whether the built chunks match the intended route and below-the-fold boundaries.

Branch update on `codex/frontend-cleanup`: before the Radix cleanup, `HEAD` had 29 granular Radix source imports and 20 direct granular Radix dependencies. The current branch has converged app source to unified `radix-ui` imports and removed direct granular dependencies from `apps/dashboard/package.json`. `vite build --mode analyze` emits the Radix code in a single `radix` manual chunk (`93.36 kB`, gzip `28.91 kB`, brotli `24.89 kB`), and the visualizer data shows one resolved copy of each Radix primitive version. Granular `@radix-ui/react-*` packages still appear transitively through `radix-ui`, `cmdk`, and `vaul`, which is expected.

Verification on this branch: `pnpm --filter juno33 run check:ui-boundaries`, `pnpm --filter juno33 compat:check`, `pnpm --filter juno33 typecheck`, `pnpm --filter juno33 test -- --run`, and `pnpm --filter juno33 build` all pass after the cleanup.

---

## Scorecard

| Area | Rating | One-line |
|------|--------|----------|
| Stack choice (TD) | 8.5/10 | React 19 + Vite + Tailwind v4 + TanStack + shadcn/Radix is the right SaaS stack for owned UI. |
| UI library hygiene (TD) | 7.5/10 | The `shadcn/` source plus `ui/` wrapper split is now documented and route-level raw shadcn imports are guarded; Radix source imports have been standardized. |
| Test/quality tooling (TD) | 9/10 | Vitest, Playwright, Storybook/Chromatic, Lighthouse CI, and custom lint/compat guards are unusually strong. |
| Code structure (TD) | 5.5/10 | The highest real frontend risk is still very large route files, especially Composer and Autopilot. |
| Dependency consistency | 6.75/10 | Radix import convergence is complete on this branch; Zod-major convergence, registry workflow discipline, and icon provenance remain cleanup items. |
| ContentForge frontend | n/a | Still a separate, thinner UI stack; acceptable if it stays internal and small. |

**Overall TD frontend: 7.6/10.** The stack and governance are solid. This branch has closed the Radix import and wrapper-boundary risks; the remaining problems are maintainability, page decomposition, Zod convergence, registry provenance, and deeper bundle/performance review — not a failed frontend foundation.

---

## ThreadsDashboard / Juno33

**Stack:** React 19 · Vite · TypeScript · Tailwind v4 (`@theme` in `src/index.css`, no `tailwind.config.js`) · react-router-dom 7 · TanStack Query 5 · TanStack Table 8 · TanStack Virtual 3 · Zustand 5 · react-hook-form 7 · Zod 4 app dependency · Recharts 3 · shadcn style `nova` on Radix · cmdk · sonner · vaul · lucide.

Current dashboard size: 727 TS/TSX files and 171,712 LOC under `apps/dashboard/src`.

### What's strong

- **Library direction is sound.** shadcn copy-in source plus app-owned wrappers is a good fit for a Tailwind-token product UI because the app controls the final component API and styling.
- **Route lazy loading exists.** Protected and public route components are centralized in `apps/dashboard/src/routes/routeRegistry.tsx` and loaded via `lazyWithRetry`.
- **Quality tooling is above average.** The repo has custom guardrails in addition to unit, browser, visual, and performance tooling. `compat:check` is a real asset and should be extended, not bypassed.
- **The current source layout is now documented and guarded.** `src/components/shadcn` maps to the shadcn CLI alias, while `src/components/ui` acts as the Juno-owned public wrapper layer. `apps/dashboard/ARCHITECTURE.md` documents this boundary, and `compat:check` now runs `scripts/check-ui-boundaries.mjs` to reject raw route imports from generated shadcn source.

### Problems and risks

1. **Component ownership is now documented; enforce it continuously.**
   - Current state: `src/components/ui` has 87 TS/TSX files; `src/components/shadcn` has 50.
   - `components.json` aliases `ui` to `@/src/components/shadcn`.
   - This is not automatically a bug: generated shadcn source in `shadcn/` and stable app wrappers in `ui/` is a reasonable architecture.
   - Branch status: `apps/dashboard/ARCHITECTURE.md` defines the ownership rule, and `compat:check` rejects direct route imports from `src/components/shadcn/*`.
   - Remaining risk: new registry or shadcn additions can still drift unless reviewers keep promoting useful code into Juno-owned wrappers.

2. **Radix import strategy is standardized on this branch.**
   - Current code has 40 imports from unified `radix-ui` and 0 source imports from granular `@radix-ui/react-*` packages.
   - Direct granular Radix dependencies have been removed from `apps/dashboard/package.json`; `radix-ui` is the only direct Radix dependency.
   - Bundle analysis confirms the app emits a single Radix manual chunk and one resolved copy of each primitive version. Transitive granular packages remain expected implementation details of `radix-ui`, `cmdk`, and `vaul`.

3. **Third-party shadcn registries are a supply-chain review surface.**
   - `components.json` includes `@uitripled`, `@kibo-ui`, `@magicui`, `@motion-primitives`, and `@blocks-so`.
   - This is acceptable only if registry additions are treated as source imports requiring diff review.
   - Mitigation: route code should never import raw registry output directly. Promote useful registry source into Juno-owned wrappers, replace demo data/hard-coded colors, and review generated diffs before commit. This rule is now documented in `apps/dashboard/ARCHITECTURE.md`; a more explicit registry-intake checklist is still worth adding.

4. **Monster route components remain the main maintainability risk.**
   - `Composer.tsx` is 5,901 LOC.
   - `Autopilot.tsx` is 4,374 LOC.
   - `Listening.tsx` is 1,844 LOC.
   - `Analytics.tsx` is 1,586 LOC.
   - The top priority is decomposition into route shells, focused panels, colocated hooks, and testable feature components. This will reduce re-render blast radius and make visual/behavior changes safer.

5. **Bundle risk should be measured, not inferred from lazy-file counts.**
   - The old "only 7 lazy files" finding is no longer accurate because route lazy loading is centralized in `routeRegistry.tsx`.
   - Initial branch evidence: `vite build --mode analyze` emits route chunks for Composer, Calendar, Autopilot, Analytics, Dashboard, Content, Layout, and other lazy routes, plus a dedicated `radix` chunk.
   - Remaining action: review the chunk sizes and dependency placement for Composer, Calendar, Autopilot, Analytics, charts, media/upload modules, and the static `toast` import warning from Vite.

6. **Zod-major convergence is still a cleanup item.**
   - `apps/dashboard/package.json` uses `zod ^4.4.3`, while package overrides/transitive tooling still reference Zod 3 ranges.
   - `npm ls zod ...` currently reports peer/invalid resolution noise rather than a clean single-major tree.
   - Keep the API-route import rule (`api/_lib/zod`) until the dependency tree is intentionally converged. This is a shim tax and correctness guard, not a frontend blocker.

7. **`lucide-react ^1.17.0` should be verified during dependency hygiene.**
   - It is listed in `apps/dashboard/package.json`.
   - This is low-risk, but still worth checking as part of dependency provenance because the app leans heavily on Lucide icons.

---

## ContentForge

- **No shadcn/Radix baseline is visible in this audit.** ContentForge remains a thinner internal UI surface compared with ThreadsDashboard.
- **As-is verdict:** acceptable if it stays a small internal tool.
- **If it grows:** use the ThreadsDashboard pattern: generated shadcn source behind app-owned wrappers, shared tokens, and a small shared `packages/ui` only after the monorepo is promoted as the runtime baseline.

---

## Recommended frontend fixes

1. **Document and enforce the shadcn source vs Juno wrapper boundary. — done on `codex/frontend-cleanup`**
   - `src/components/shadcn`: generated or registry-adapted source.
   - `src/components/ui` and `src/components/layout`: app-facing wrappers.
   - Product routes import wrappers only.

2. **Add/extend an audit for route-level imports. — done for raw shadcn route imports**
   - Ban direct product-route imports from raw registry files and generated shadcn primitives unless explicitly allowlisted.
   - Keep third-party registry output behind Juno-owned wrappers.

3. **Standardize Radix import strategy after bundle verification. — done on `codex/frontend-cleanup`**
   - App source now uses unified `radix-ui`.
   - Direct granular Radix dependencies are removed.
   - Bundle analysis shows one resolved primitive copy per Radix package version.

4. **Decompose Composer and Autopilot first.**
   - They are the largest route files and the highest maintainability risk.
   - Split by behavior boundary: shell, editor/forms, media/upload, preview, actions, diagnostics, and route-specific hooks.

5. **Run a bundle analysis. — first pass done; deeper review remains**
   - Verify route chunks and heavy dependencies instead of relying on lazy-call counts.
   - Calendar, Composer, Analytics, Autopilot, chart-heavy panels, and media/upload modules are the first targets.

6. **Converge Zod versions deliberately.**
   - Keep `api/_lib/zod` discipline while the dependency tree is mixed.
   - Retire shim tax only after app/API/tooling packages agree on one supported major or an intentional compatibility plan.

7. **Treat registry additions as code-review events.**
   - Check generated diffs.
   - Remove demo data and hard-coded design assumptions.
   - Wrap before route use.

8. **Verify icon/dependency provenance as part of dependency hygiene.**
   - Especially `lucide-react ^1.17.0` and any registry-provided dependencies.

None of these require a frontend rewrite. The frontend stack is directionally correct; the work is ownership, decomposition, dependency hygiene, and measured bundle tightening.
