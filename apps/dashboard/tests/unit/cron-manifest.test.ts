import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { LOCK_TTL_MAP } from "../../api/_lib/cronUtils";

const ROOT = join(__dirname, "../..");

type VercelConfig = {
	crons: Array<{ path: string; schedule: string }>;
	functions?: Record<string, { maxDuration?: number }>;
};

function loadVercelConfig(): VercelConfig {
	return JSON.parse(readFileSync(join(ROOT, "vercel.json"), "utf8"));
}

function cronNameFromPath(path: string): string {
	return path.replace(/^\/api\/cron\//, "");
}

function healthMonitorExpectedJobNames(): Set<string> {
	const source = readFileSync(join(ROOT, "api/cron/health-monitor.ts"), "utf8");
	return new Set(
		[...source.matchAll(/\{\s*name:\s*"([^"]+)",\s*maxAgeHours:/g)].map(
			(match) => match[1],
		),
	);
}

describe("cron manifest coverage", () => {
	it("has an explicit lock TTL for every Vercel cron", () => {
		const config = loadVercelConfig();
		const cronNames = config.crons.map((cron) => cronNameFromPath(cron.path));

		expect(cronNames.length).toBeGreaterThan(0);
		for (const cronName of cronNames) {
			expect(LOCK_TTL_MAP, `${cronName} is missing from LOCK_TTL_MAP`).toHaveProperty(
				cronName,
			);
		}
	});

	it("keeps lock TTLs above configured maxDuration", () => {
		const config = loadVercelConfig();

		for (const cron of config.crons) {
			const cronName = cronNameFromPath(cron.path);
			const functionKey = `${cron.path.replace(/^\//, "")}.ts`;
			const maxDuration = config.functions?.[functionKey]?.maxDuration;
			if (!maxDuration) continue;

			expect(
				LOCK_TTL_MAP[cronName],
				`${cronName} lock TTL must exceed maxDuration`,
			).toBeGreaterThan(maxDuration);
		}
	});

	it("has freshness monitoring for every Vercel cron", () => {
		const config = loadVercelConfig();
		const expectedJobs = healthMonitorExpectedJobNames();

		for (const cron of config.crons) {
			const cronName = cronNameFromPath(cron.path);
			expect(
				expectedJobs.has(cronName),
				`${cronName} is missing from health-monitor cron freshness`,
			).toBe(true);
		}
	});
});
