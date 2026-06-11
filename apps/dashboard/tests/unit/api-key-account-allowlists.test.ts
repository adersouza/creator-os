import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const ROOT = path.resolve(__dirname, "../..");

function read(relativePath: string) {
	return fs.readFileSync(path.join(ROOT, relativePath), "utf8");
}

describe("API key account allowlists", () => {
	it("stores and returns account allowlists on developer API keys", () => {
		const handler = read("api/_lib/handlers/developer/keys.ts");
		const migration = read("supabase/migrations/20260524164000_api_key_account_allowlists.sql");

		expect(migration).toContain("allowed_account_ids text[]");
		expect(migration).toContain("idx_api_keys_allowed_account_ids");
		expect(handler).toContain("allowed_account_ids");
		expect(handler).toContain("normalizeAllowedAccountIds");
		expect(handler).toContain("parsed.data.allowed_account_ids !== undefined");
	});

	it("enforces allowlists in public API-key middleware", () => {
		const middleware = read("api/_lib/withApiKey.ts");

		expect(middleware).toContain("allowed_account_ids");
		expect(middleware).toContain("extractRequestedAccountId");
		expect(middleware).toContain("API key is not allowed to access this account");
		expect(middleware).toContain("allowedAccountIds");
	});

	it("filters public list endpoints by key account allowlist", () => {
		const accounts = read("api/_lib/handlers/v1/accounts.ts");
		const posts = read("api/_lib/handlers/v1/posts.ts");
		const settingsService = read("src/services/api/settingsDeveloper.ts");
		const settingsUi = read("src/components/settings/APITabContent.tsx");

		expect(accounts).toContain("user.allowedAccountIds");
		expect(posts).toContain("user.allowedAccountIds");
		expect(settingsService).toContain("allowed_account_ids");
		expect(settingsUi).toContain("Limited to");
	});
});
