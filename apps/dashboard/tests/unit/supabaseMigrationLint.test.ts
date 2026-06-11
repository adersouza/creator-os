import { describe, expect, it } from "vitest";

describe("Supabase migration replay lint", () => {
	it("flags unguarded replay-unsafe statements", async () => {
		const { analyzeSql } = await import("../../scripts/lint-supabase-migrations.mjs");

		const issues = analyzeSql(`
			ALTER TABLE public.optional_table ADD COLUMN value text;
			DROP POLICY old_policy ON public.optional_table;
			CREATE POLICY new_policy ON public.optional_table FOR SELECT USING (true);
			ALTER VIEW public.optional_view SET (security_invoker = true);
			REVOKE EXECUTE ON FUNCTION public.missing_rpc(text) FROM authenticated;
			ALTER PUBLICATION supabase_realtime ADD TABLE public.optional_table;
			CREATE OR REPLACE FUNCTION public.read_optional()
			RETURNS integer
			LANGUAGE sql
			AS $$ SELECT count(*)::integer FROM public.optional_table $$;
		`);

		expect(issues.map((issue: { category: string }) => issue.category)).toEqual([
			"alter-table",
			"policy",
			"policy",
			"alter-view",
			"function-grant",
			"publication",
			"function-body",
		]);
	});

	it("allows catalog-guarded replay-safe statements", async () => {
		const { analyzeSql } = await import("../../scripts/lint-supabase-migrations.mjs");

		const issues = analyzeSql(`
			ALTER TABLE IF EXISTS public.optional_table ADD COLUMN IF NOT EXISTS value text;

			DO $$
			BEGIN
				IF to_regclass('public.optional_table') IS NOT NULL THEN
					DROP POLICY IF EXISTS old_policy ON public.optional_table;
					IF NOT EXISTS (
						SELECT 1 FROM pg_policies
						WHERE schemaname = 'public'
							AND tablename = 'optional_table'
							AND policyname = 'new_policy'
					) THEN
						CREATE POLICY new_policy ON public.optional_table FOR SELECT USING (true);
					END IF;
				END IF;
			END $$;

			DO $$
			BEGIN
				IF EXISTS (
					SELECT 1 FROM pg_proc p
					JOIN pg_namespace n ON n.oid = p.pronamespace
					WHERE n.nspname = 'public' AND p.proname = 'missing_rpc'
				) THEN
					REVOKE EXECUTE ON FUNCTION public.missing_rpc(text) FROM authenticated;
				END IF;
			END $$;

			DO $$
			BEGIN
				IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime')
					AND to_regclass('public.optional_table') IS NOT NULL THEN
					ALTER PUBLICATION supabase_realtime ADD TABLE public.optional_table;
				END IF;
			END $$;
		`);

		expect(issues).toEqual([]);
	});
});
