import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const ROOT = path.resolve(__dirname, "../..");

function read(relativePath: string) {
	return fs.readFileSync(path.join(ROOT, relativePath), "utf8");
}

describe("server-side unified inbox aggregation", () => {
	it("uses the authenticated inbox API as the primary frontend path", () => {
		const hook = read("src/hooks/useUnifiedInbox.ts");

		expect(hook).toContain("apiFetch");
		expect(hook).toContain("/api/inbox?action=unified&filter=all&limit=250");
		expect(hook).toContain("conversationFromServerMessage");
		expect(hook).toContain("production schemas settle");
	});

	it("returns account, group, and reply metadata from the unified inbox handler", () => {
		const handler = read("api/_lib/handlers/inbox/unified.ts");

		expect(handler).toContain("accountId");
		expect(handler).toContain("groupId");
		expect(handler).toContain("replyToId");
		expect(handler).toContain("replyKind");
		expect(handler).toContain(".from(\"inbox_dm_cache\")");
		expect(handler).toContain(".from(\"instagram_accounts\")");
		expect(handler).toContain("nextCursor");
	});
});
