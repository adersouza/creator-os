import { describe, expect, it } from "vitest";
import {
	isFleetResetMainNavPath,
	mainSidebarRoute,
	scopedRoute,
} from "./scopedRoutes";

const scopedAccount = {
	id: "acct_123",
	handle: "@aurora",
	platform: "instagram" as const,
};

describe("scopedRoutes", () => {
	it("keeps main sidebar Dashboard and Analytics links fleet-scoped", () => {
		expect(isFleetResetMainNavPath("/dashboard")).toBe(true);
		expect(isFleetResetMainNavPath("/analytics")).toBe(true);
		expect(mainSidebarRoute("/dashboard", { scopedAccount })).toBe(
			"/dashboard",
		);
		expect(mainSidebarRoute("/analytics", { scopedAccount })).toBe(
			"/analytics",
		);
	});

	it("keeps non-reset sidebar routes scoped to the selected account", () => {
		expect(mainSidebarRoute("/calendar", { scopedAccount })).toBe(
			"/calendar?accountId=acct_123&account=aurora&platform=instagram",
		);
	});

	it("still builds explicit account analytics links", () => {
		expect(scopedRoute("/analytics", { scopedAccount, timeframe: "30d" })).toBe(
			"/analytics?accountId=acct_123&account=aurora&p=ig&d=30d",
		);
	});
});
