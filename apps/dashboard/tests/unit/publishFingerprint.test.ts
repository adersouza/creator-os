import { beforeEach, describe, expect, it, vi } from "vitest";
import {
	buildPublishFingerprint,
	fingerprintMedia,
	findRecentMediaFingerprintAcrossAccounts,
	type DuplicateFingerprintMatch,
	normalizePublishText,
} from "../../api/_lib/handlers/auto-post/publishFingerprint.js";

const mockDbState = vi.hoisted(() => ({
	queueRows: [] as DuplicateFingerprintMatch[],
	signalRows: [] as Array<{
		post_id: string;
		account_id: string | null;
		captured_at: string;
		media_url_hashes: string[] | null;
		perceptual_hashes: string[] | null;
	}>,
}));

class MockQuery {
	constructor(private readonly table: string) {}

	select() { return this; }
	eq() { return this; }
	neq() { return this; }
	not() { return this; }
	in() { return this; }
	gte() { return this; }
	order() { return this; }
	limit() { return this; }

	then(resolve: (value: { data: unknown[]; error: null }) => void) {
		resolve({
			data:
				this.table === "auto_post_queue"
					? mockDbState.queueRows
					: mockDbState.signalRows,
			error: null,
		});
	}
}

vi.mock("../../api/_lib/supabase.js", () => ({
	getSupabaseAny: () => ({
		from: (table: string) => new MockQuery(table),
	}),
}));

describe("autoposter publish fingerprints", () => {
	beforeEach(() => {
		mockDbState.queueRows = [];
		mockDbState.signalRows = [];
	});

	it("normalizes casing, spacing, punctuation, and urls before hashing", () => {
		expect(normalizePublishText("  Hello, WORLD!! https://x.test/a  ")).toBe(
			"hello world",
		);
	});

	it("uses a stable media fingerprint independent of url order", () => {
		expect(fingerprintMedia(["HTTPS://cdn.test/B.jpg", "https://cdn.test/a.jpg"])).toBe(
			fingerprintMedia(["https://cdn.test/a.jpg", "https://cdn.test/b.jpg"]),
		);
		expect(fingerprintMedia([])).toBe("no_media");
	});

	it("scopes publish fingerprints by workspace, account, platform, text, and media", () => {
		const base = buildPublishFingerprint({
			workspaceId: "workspace-1",
			accountId: "account-1",
			platform: "threads",
			content: "Same text",
			mediaUrls: ["https://cdn.test/a.jpg"],
		});
		const same = buildPublishFingerprint({
			workspaceId: "workspace-1",
			accountId: "account-1",
			platform: "threads",
			content: "same   text",
			mediaUrls: ["https://cdn.test/a.jpg"],
		});
		const differentAccount = buildPublishFingerprint({
			workspaceId: "workspace-1",
			accountId: "account-2",
			platform: "threads",
			content: "Same text",
			mediaUrls: ["https://cdn.test/a.jpg"],
		});

		expect(base.normalizedTextHash).toBe(same.normalizedTextHash);
		expect(base.mediaFingerprint).toBe(same.mediaFingerprint);
		expect(base.publishFingerprint).toBe(same.publishFingerprint);
		expect(base.publishFingerprint).not.toBe(differentAccount.publishFingerprint);
	});

	it("finds exact cross-account queue media reuse before publish", async () => {
		mockDbState.queueRows = [{
			id: "queue-dup",
			status: "pending",
			account_id: "account-2",
			threads_post_id: null,
			posted_at: null,
			created_at: new Date().toISOString(),
			publish_fingerprint: "publish-fp",
		}];

		const match = await findRecentMediaFingerprintAcrossAccounts({
			workspaceId: "workspace-1",
			userId: "user-1",
			accountId: "account-1",
			platform: "threads",
			mediaFingerprint: "media-fp",
		});

		expect(match?.id).toBe("queue-dup");
		expect(match?.match_type).toBe("media_fingerprint");
	});

	it("finds cross-account published media URL reuse from originality signals", async () => {
		mockDbState.signalRows = [{
			post_id: "post-dup",
			account_id: "account-2",
			captured_at: new Date().toISOString(),
			media_url_hashes: ["media-url-hash"],
			perceptual_hashes: [],
		}];

		const match = await findRecentMediaFingerprintAcrossAccounts({
			workspaceId: "workspace-1",
			userId: "user-1",
			accountId: "account-1",
			platform: "threads",
			mediaFingerprint: "no_media",
			mediaUrlHashes: ["media-url-hash"],
		});

		expect(match?.id).toBe("post-dup");
		expect(match?.match_type).toBe("media_url_hash");
	});

	it("finds cross-account perceptual media reuse from originality signals", async () => {
		mockDbState.signalRows = [{
			post_id: "post-dup",
			account_id: "account-2",
			captured_at: new Date().toISOString(),
			media_url_hashes: [],
			perceptual_hashes: ["ffffffffffffffff"],
		}];

		const match = await findRecentMediaFingerprintAcrossAccounts({
			workspaceId: "workspace-1",
			userId: "user-1",
			accountId: "account-1",
			platform: "threads",
			mediaFingerprint: "no_media",
			perceptualHashes: ["fffffffffffffffc"],
		});

		expect(match?.id).toBe("post-dup");
		expect(match?.match_type).toBe("perceptual_hash");
	});
});
