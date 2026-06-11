import type { AccountScopeValue } from "@/stores/useAccountScopeStore";

type QueryValue = boolean | number | string | null | undefined;
type RouteAccountScope =
	| AccountScopeValue
	| {
			id?: string | null | undefined;
			handle: string;
			platform: "threads" | "instagram";
	  };

export interface RouteScope {
	scopedAccount?: RouteAccountScope | null | undefined;
	groupId?: string | null | undefined;
	accountIds?: string[] | null | undefined;
	platform?: string | null | undefined;
	timeframe?: string | number | null | undefined;
}

export function isFleetResetMainNavPath(to: string): boolean {
	const [rawPathname] = to.split("?");
	return rawPathname === "/dashboard" || rawPathname === "/analytics";
}

export function mainSidebarRoute(to: string, scope: RouteScope = {}): string {
	const [rawPathname] = to.split("?");
	const pathname = rawPathname ?? "";
	return isFleetResetMainNavPath(to) ? pathname : scopedRoute(to, scope);
}

export function scopedRoute(
	to: string,
	scope: RouteScope = {},
	extra: Record<string, QueryValue> = {},
): string {
	const [rawPathname, rawQuery = ""] = to.split("?");
	const pathname = rawPathname ?? "";
	const params = new URLSearchParams(rawQuery);
	const account = scope.scopedAccount;
	const normalizedPlatform =
		scope.platform === "instagram" ? "ig" : scope.platform;

	if (account?.id) {
		params.set("accountId", account.id);
		params.set("account", account.handle.replace(/^@/, ""));
		params.set(
			"platform",
			pathname === "/analytics"
				? account.platform === "instagram"
					? "ig"
					: "threads"
				: account.platform,
		);
		if (pathname === "/accounts") params.set("id", account.id);
	} else {
		if (scope.groupId) params.set("group", scope.groupId);
		if (scope.accountIds && scope.accountIds.length > 0) {
			params.set("accounts", scope.accountIds.join(","));
		}
		if (scope.platform && scope.platform !== "all") {
			params.set(
				"platform",
				pathname === "/analytics"
					? (normalizedPlatform ?? "")
					: normalizedPlatform === "ig"
						? "instagram"
						: (normalizedPlatform ?? ""),
			);
		}
	}

	if (pathname === "/analytics") {
		const p = params.get("platform");
		if (p) {
			params.set("p", p);
			params.delete("platform");
		}
		if (scope.timeframe) params.set("d", String(scope.timeframe));
	} else if (pathname === "/dashboard") {
		const p = params.get("platform");
		if (p) {
			params.set("p", p === "instagram" ? "ig" : p);
			params.delete("platform");
		}
		if (scope.timeframe) params.set("d", String(scope.timeframe));
	} else if (scope.timeframe) {
		params.set("timeframe", String(scope.timeframe));
	}

	for (const [key, value] of Object.entries(extra)) {
		if (
			value === null ||
			value === undefined ||
			value === false ||
			value === ""
		) {
			params.delete(key);
		} else {
			params.set(key, String(value));
		}
	}

	const query = params.toString();
	return query ? `${pathname}?${query}` : pathname;
}
