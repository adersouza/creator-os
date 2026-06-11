import { describe, expect, it, vi } from "vitest";
import { phaseStorageCleanup } from "../../api/_lib/cron/daily-maintenance/storage-cleanup";

function makeLogger() {
	return {
		debug: vi.fn(),
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
	};
}

function makeSupabaseMock() {
	const oldDate = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString();
	const recentDate = new Date().toISOString();
	const remove = vi.fn().mockResolvedValue({ error: null });
	const list = vi.fn(async (prefix: string) => {
		const dataByPrefix: Record<string, unknown[]> = {
			"": [{ name: "user-a" }, { name: "user-b" }],
			"user-a": [{ name: "post-1" }],
			"user-a/post-1": [
				{ name: "0.jpg", id: "kept", created_at: oldDate },
				{ name: "recent.jpg", id: "recent", created_at: recentDate },
			],
			"user-b": [{ name: "post-9" }],
			"user-b/post-9": [{ name: "0.jpg", id: "orphan", created_at: oldDate }],
		};
		return { data: dataByPrefix[prefix] || [], error: null };
	});

	const query = {
		select: vi.fn().mockReturnThis(),
		not: vi.fn().mockResolvedValue({
			data: [
				{
					media_urls: [
						"https://example.supabase.co/storage/v1/object/public/post-media/user-a/post-1/0.jpg?download=1",
					],
				},
			],
			error: null,
		}),
	};

	return {
		remove,
		list,
		client: {
			from: vi.fn(() => query),
			storage: {
				from: vi.fn(() => ({ list, remove })),
			},
		},
	};
}

describe("phaseStorageCleanup", () => {
	it("recursively deletes only old unreferenced post-media objects", async () => {
		const { client, list, remove } = makeSupabaseMock();
		const result = await phaseStorageCleanup(client as never, makeLogger());

		expect(list).toHaveBeenCalledWith(
			"",
			expect.objectContaining({ limit: 1000 }),
		);
		expect(list).toHaveBeenCalledWith(
			"user-a/post-1",
			expect.objectContaining({ limit: 1000 }),
		);
		expect(remove).toHaveBeenCalledTimes(1);
		expect(remove).toHaveBeenCalledWith(["user-b/post-9/0.jpg"]);
		expect(result).toMatchObject({
			deleted: 1,
			scanned: 3,
			referenced: 1,
			orphaned: 1,
		});
	});
});
