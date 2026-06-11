import { describe, expect, it, vi } from "vitest";
import { eqOrNull, neqOrNull, neqStrict } from "../../api/_lib/supabaseSafe";

/**
 * The helpers pass through to the Supabase query builder's .or() / .not() /
 * .neq() methods — so we verify the helpers call the right methods with the
 * right PostgREST filter strings, not the SQL the DB eventually runs.
 */

describe("supabaseSafe", () => {
	describe("neqOrNull", () => {
		it("emits or=(col.is.null,col.neq.value)", () => {
			const query = { or: vi.fn().mockReturnThis() };
			neqOrNull(query, "status", "suspended");
			expect(query.or).toHaveBeenCalledWith("status.is.null,status.neq.suspended");
		});

		it("handles numeric values", () => {
			const query = { or: vi.fn().mockReturnThis() };
			neqOrNull(query, "priority", 0);
			expect(query.or).toHaveBeenCalledWith("priority.is.null,priority.neq.0");
		});

		it("handles boolean values", () => {
			const query = { or: vi.fn().mockReturnThis() };
			neqOrNull(query, "needs_reauth", true);
			expect(query.or).toHaveBeenCalledWith(
				"needs_reauth.is.null,needs_reauth.neq.true",
			);
		});

		it("returns the query builder for chaining", () => {
			const chained = { next: vi.fn() };
			const query = { or: vi.fn().mockReturnValue(chained) };
			const result = neqOrNull(query, "status", "suspended");
			expect(result).toBe(chained);
		});
	});

	describe("neqStrict", () => {
		it("chains .not(col, is, null).neq(col, value)", () => {
			const afterNot = { neq: vi.fn().mockReturnThis() };
			const query = { not: vi.fn().mockReturnValue(afterNot) };
			neqStrict(query, "status", "suspended");
			expect(query.not).toHaveBeenCalledWith("status", "is", null);
			expect(afterNot.neq).toHaveBeenCalledWith("status", "suspended");
		});
	});

	describe("eqOrNull", () => {
		it("emits or=(col.is.null,col.eq.value)", () => {
			const query = { or: vi.fn().mockReturnThis() };
			eqOrNull(query, "approval_status", "approved");
			expect(query.or).toHaveBeenCalledWith(
				"approval_status.is.null,approval_status.eq.approved",
			);
		});
	});
});
