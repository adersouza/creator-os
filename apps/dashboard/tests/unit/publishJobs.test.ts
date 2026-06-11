import { beforeEach, describe, expect, it, vi } from "vitest";
import { processPublishJob } from "../../api/_lib/publishJobs.js";

const mockFrom = vi.fn();
const mockHandlePublish = vi.fn();

vi.mock("../../api/_lib/supabase.js", () => ({
	getSupabaseAny: () => ({ from: (...args: unknown[]) => mockFrom(...args) }),
}));

vi.mock("../../api/_lib/handlers/posts/publish.js", () => ({
	handlePublish: (...args: unknown[]) => mockHandlePublish(...args),
}));

vi.mock("../../api/_lib/logger.js", () => ({
	logger: { warn: vi.fn(), error: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

function selectSingle(data: unknown, error: unknown = null) {
	const chain: Record<string, unknown> = {};
	chain.select = vi.fn(() => chain);
	chain.eq = vi.fn(() => chain);
	chain.maybeSingle = vi.fn().mockResolvedValue({ data, error });
	return chain;
}

function updateClaimSingle(data: unknown, error: unknown = null) {
	const chain: Record<string, unknown> = {};
	chain.update = vi.fn(() => chain);
	chain.eq = vi.fn(() => chain);
	chain.in = vi.fn(() => chain);
	chain.select = vi.fn(() => chain);
	chain.maybeSingle = vi.fn().mockResolvedValue({ data, error });
	return chain;
}

function updateOnly() {
	const chain: Record<string, unknown> = {};
	chain.update = vi.fn(() => chain);
	chain.eq = vi.fn().mockResolvedValue({ error: null });
	return chain;
}

function queuedJob() {
	return {
		id: "job-1",
		user_id: "user-1",
		status: "queued",
		stage: "queued",
		payload: { platform: "threads", content: "hello" },
		attempt_count: 0,
		request_id: "00000000-0000-4000-8000-000000000001",
	};
}

describe("processPublishJob", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockHandlePublish.mockImplementation(async (_req, res) => {
			res.status(200).json({ postId: "post-1", platform: "threads" });
		});
	});

	it("claims queued jobs atomically before publishing", async () => {
		const job = queuedJob();
		const claimChain = updateClaimSingle({
			...job,
			status: "publishing",
			stage: "preflight",
			attempt_count: 1,
		});
		const finalUpdate = updateOnly();
		mockFrom
			.mockReturnValueOnce(selectSingle(job))
			.mockReturnValueOnce(claimChain)
			.mockReturnValueOnce(updateOnly())
			.mockReturnValueOnce(finalUpdate);

		const result = await processPublishJob("job-1");

		expect(claimChain.update).toHaveBeenCalledWith(
			expect.objectContaining({
				status: "publishing",
				stage: "preflight",
				attempt_count: 1,
			}),
		);
		expect(claimChain.eq).toHaveBeenCalledWith("id", "job-1");
		expect(claimChain.in).toHaveBeenCalledWith("status", ["queued", "retrying"]);
		expect(claimChain.eq).toHaveBeenCalledWith("attempt_count", 0);
		expect(mockHandlePublish).toHaveBeenCalledTimes(1);
		expect(finalUpdate.update).toHaveBeenCalledWith(
			expect.objectContaining({
				status: "published",
				stage: "published",
				post_id: "post-1",
			}),
		);
		expect(result).toEqual({ skipped: false, status: "published" });
	});

	it("skips publishing when another worker already claimed the job", async () => {
		mockFrom
			.mockReturnValueOnce(selectSingle(queuedJob()))
			.mockReturnValueOnce(updateClaimSingle(null));

		const result = await processPublishJob("job-1");

		expect(mockHandlePublish).not.toHaveBeenCalled();
		expect(result).toEqual({ skipped: true, status: "already_claimed" });
	});

	it("keeps processing Instagram jobs non-terminal", async () => {
		const job = { ...queuedJob(), payload: { platform: "instagram" } };
		mockHandlePublish.mockImplementationOnce(async (_req, res) => {
			res.status(200).json({
				postId: "post-1",
				containerId: "container-1",
				status: "processing",
				platform: "instagram",
			});
		});
		const finalUpdate = updateOnly();
		mockFrom
			.mockReturnValueOnce(selectSingle(job))
			.mockReturnValueOnce(
				updateClaimSingle({
					...job,
					status: "publishing",
					stage: "preflight",
					attempt_count: 1,
				}),
			)
			.mockReturnValueOnce(updateOnly())
			.mockReturnValueOnce(finalUpdate);

		const result = await processPublishJob("job-1");

		expect(finalUpdate.update).toHaveBeenCalledWith(
			expect.objectContaining({
				status: "publishing",
				stage: "processing",
				post_id: "post-1",
			}),
		);
		expect(finalUpdate.update).toHaveBeenCalledWith(
			expect.not.objectContaining({ completed_at: expect.any(String) }),
		);
		expect(result).toEqual({ skipped: false, status: "processing" });
	});
});
