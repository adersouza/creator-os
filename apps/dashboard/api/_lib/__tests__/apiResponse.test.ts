import { afterEach, describe, expect, it, vi } from "vitest";
import {
	apiError,
	apiSuccess,
	badRequest,
	methodNotAllowed,
	notFound,
	rateLimited,
	unauthorized,
} from "../apiResponse.js";

interface MockResponse {
	status: ReturnType<typeof vi.fn>;
	json: ReturnType<typeof vi.fn>;
}

// biome-ignore lint/suspicious/noExplicitAny: test mock
function mockRes(): any {
	const res = {} as MockResponse;
	res.status = vi.fn().mockReturnValue(res);
	res.json = vi.fn().mockReturnValue(res);
	return res;
}

describe("apiError", () => {
	const originalNodeEnv = process.env.NODE_ENV;

	afterEach(() => {
		process.env.NODE_ENV = originalNodeEnv;
	});

	it("sends correct status and error message", () => {
		const res = mockRes();
		apiError(res, 400, "Bad input");
		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "Bad input", code: "BAD_REQUEST" }),
		);
	});

	it("includes details when provided", () => {
		const res = mockRes();
		apiError(res, 500, "Fail", { details: "db down" });
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ details: "db down" }),
		);
	});

	it("suppresses 500 details in production", () => {
		process.env.NODE_ENV = "production";
		const res = mockRes();
		apiError(res, 500, "Fail", { details: "db down" });
		expect(res.json).toHaveBeenCalledWith(
			expect.not.objectContaining({ details: expect.any(String) }),
		);
	});

	it("uses custom code when provided", () => {
		const res = mockRes();
		apiError(res, 400, "Fail", { code: "CUSTOM" });
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ code: "CUSTOM" }),
		);
	});
});

describe("apiSuccess", () => {
	it("sends 200 with success:true by default", () => {
		const res = mockRes();
		apiSuccess(res, { count: 5 });
		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith({ success: true, count: 5 });
	});

	it("supports custom status code", () => {
		const res = mockRes();
		apiSuccess(res, { id: "abc" }, 201);
		expect(res.status).toHaveBeenCalledWith(201);
	});
});

describe("shortcut helpers", () => {
	it("unauthorized sends 401", () => {
		const res = mockRes();
		unauthorized(res);
		expect(res.status).toHaveBeenCalledWith(401);
	});

	it("badRequest sends 400", () => {
		const res = mockRes();
		badRequest(res, "missing field");
		expect(res.status).toHaveBeenCalledWith(400);
	});

	it("notFound sends 404", () => {
		const res = mockRes();
		notFound(res);
		expect(res.status).toHaveBeenCalledWith(404);
	});

	it("rateLimited sends 429", () => {
		const res = mockRes();
		rateLimited(res);
		expect(res.status).toHaveBeenCalledWith(429);
	});

	it("methodNotAllowed sends 405", () => {
		const res = mockRes();
		methodNotAllowed(res);
		expect(res.status).toHaveBeenCalledWith(405);
	});
});
