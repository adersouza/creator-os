import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { hashOperatorAuditValue } from "../../api/_lib/operatorAudit.js";

const ROOT = path.resolve(__dirname, "../..");

function read(relativePath: string) {
	return fs.readFileSync(path.join(ROOT, relativePath), "utf8");
}

describe("operator authoritative audit logs", () => {
	it("creates the server-owned operator action audit schema", () => {
		const migration = read("supabase/migrations/20260522133000_operator_action_audit_logs.sql");

		expect(migration).toContain("create table if not exists public.operator_action_audit_logs");
		expect(migration).toContain("actor_user_id uuid not null");
		expect(migration).toContain("phase text not null");
		expect(migration).toContain("action_name text not null");
		expect(migration).toContain("payload_hash text");
		expect(migration).toContain("body_hash text");
		expect(migration).toContain("intent_id uuid references public.agent_action_intents");
		expect(migration).toContain("idempotency_key text");
		expect(migration).toContain("request_id text");
		expect(migration).toContain("Users can read own operator action audit logs");
	});

	it("keeps dry-run, approval, and execute paths wired to the reusable helper", () => {
		const operatorApi = read("api/operator.ts");

		expect(operatorApi).toContain("recordOperatorActionAudit");
		expect(operatorApi).toContain("requireOperatorActionAudit");
		expect(operatorApi).toContain('phase: "dry-run"');
		expect(operatorApi).toContain('phase: "request-approval"');
		expect(operatorApi).toContain('phase: "execute"');
		expect(operatorApi).toContain("auditExecuteAttempt");
		expect(operatorApi).toContain("auditExecuteGateFailure");
	});

	it("fails closed before high-risk execute can advance without audit persistence", () => {
		const operatorApi = read("api/operator.ts");
		const auditAttemptIndex = operatorApi.indexOf("await auditExecuteAttempt");
		const intentUpdateIndex = operatorApi.indexOf('status: "dispatching"');

		expect(operatorApi).toContain("Execution audit persistence is required for high-risk actions");
		expect(operatorApi).toContain("isHighRisk(intent.risk_level)");
		expect(operatorApi).toContain("claimIntentForDispatch");
		expect(auditAttemptIndex).toBeGreaterThan(0);
		expect(intentUpdateIndex).toBeGreaterThan(auditAttemptIndex);
	});

	it("uses stable hashing for equivalent audit bodies", () => {
		const first = hashOperatorAuditValue({ b: 2, a: { d: 4, c: 3 } });
		const second = hashOperatorAuditValue({ a: { c: 3, d: 4 }, b: 2 });

		expect(first).toBe(second);
		expect(first).toHaveLength(64);
	});
});
