#!/usr/bin/env tsx

import dotenv from "dotenv";

for (const path of [
	".env",
	".env.local",
	".env.production.local",
	".env.production",
	".vercel/.env.development.local",
]) {
	dotenv.config({ path, override: false, quiet: true });
}

type ControlPlane = typeof import("../api/_lib/handlers/auto-post/controlPlane.js");

interface ParsedArgs {
	command: string;
	workspace?: string;
	reason?: string;
	mode?: string;
	apply: boolean;
	includeManual: boolean;
	json: boolean;
}

function parseArgs(argv: string[]): ParsedArgs {
	const [command = "status", ...rest] = argv;
	const parsed: ParsedArgs = {
		command,
		apply: false,
		includeManual: false,
		json: false,
	};
	for (let i = 0; i < rest.length; i += 1) {
		const arg = rest[i];
		if (arg === "--apply") {
			parsed.apply = true;
		} else if (arg === "--include-manual") {
			parsed.includeManual = true;
		} else if (arg === "--json") {
			parsed.json = true;
		} else if (arg === "--workspace") {
			parsed.workspace = rest[++i];
		} else if (arg === "--reason") {
			parsed.reason = rest[++i];
		} else if (arg === "--mode") {
			parsed.mode = rest[++i];
		} else {
			throw new Error(`Unknown argument: ${arg}`);
		}
	}
	return parsed;
}

function requireWorkspace(args: ParsedArgs): string {
	if (!args.workspace) {
		throw new Error("Missing --workspace <workspaceId>");
	}
	return args.workspace;
}

function requireReason(args: ParsedArgs): string {
	if (!args.reason?.trim()) {
		throw new Error("Missing --reason \"...\"");
	}
	return args.reason.trim();
}

function printStatus(status: Awaited<ReturnType<ControlPlane["getAutoposterControlStatus"]>>) {
	console.log(`Autoposter status for ${status.workspaceId}`);
	console.log(`mode: ${status.mode}`);
	console.log(
		`switches: master=${status.switches.is_enabled} group=${status.switches.group_mode_enabled} ai_fill=${status.switches.enable_ai_queue_fill} hard_disabled=${status.switches.hard_disabled}`,
	);
	console.log(
		`queue: ready=${status.queue.ready} due=${status.queue.due} publishing=${status.queue.publishing} dead_letter=${status.queue.deadLetter}`,
	);
	console.log(
		`publish behavior: non_manual_would_publish=${status.queue.wouldPublishNonManual} non_manual_would_cancel=${status.queue.wouldCancelNonManualAtPublish}`,
	);
	console.log(
		`accounts: publishable=${status.accounts.publishable}/${status.accounts.total} needs_reauth=${status.accounts.needsReauth} blocked=${status.accounts.blocked} inactive_or_other=${status.accounts.inactiveOrOther}`,
	);
	console.log(`warmup: ${JSON.stringify(status.warmup)}`);
	console.log(
		`alerts: unresolved=${status.alerts.unresolved} critical_or_error=${status.alerts.criticalOrError}`,
	);
	console.log(`recent_publish_failures_24h: ${status.recentPublishFailures}`);
}

async function main() {
	const {
		drainAutoposterQueue,
		getAutoposterControlStatus,
		pauseAutoposter,
		resumeAutoposterWarmup,
	} = await import("../api/_lib/handlers/auto-post/controlPlane.js");
	const args = parseArgs(process.argv.slice(2));
	const workspaceId = requireWorkspace(args);

	if (args.command === "status") {
		const status = await getAutoposterControlStatus(workspaceId);
		if (args.json) console.log(JSON.stringify(status, null, 2));
		else printStatus(status);
		return;
	}

	if (args.command === "pause") {
		const result = await pauseAutoposter(workspaceId, {
			reason: requireReason(args),
			apply: args.apply,
			actor: "codex-cli",
		});
		console.log(JSON.stringify(result, null, 2));
		if (!args.apply) {
			console.error("Dry run only. Re-run with --apply to persist the pause.");
		}
		return;
	}

	if (args.command === "resume-warmup") {
		const result = await resumeAutoposterWarmup(workspaceId, {
			reason: requireReason(args),
			apply: args.apply,
			actor: "codex-cli",
		});
		console.log(JSON.stringify(result, null, 2));
		if (!args.apply) {
			console.error("Dry run only. Re-run with --apply to resume warm-up.");
		}
		return;
	}

	if (args.command === "drain") {
		if (args.mode !== "cancel-ready") {
			throw new Error("Drain requires --mode cancel-ready");
		}
		const result = await drainAutoposterQueue(workspaceId, {
			reason: requireReason(args),
			mode: "cancel-ready",
			apply: args.apply,
			includeManual: args.includeManual,
			actor: "codex-cli",
		});
		console.log(JSON.stringify(result, null, 2));
		if (!args.apply) {
			console.error("Dry run only. Re-run with --apply to cancel ready rows.");
		}
		return;
	}

	throw new Error(
		`Unknown command ${args.command}. Use status, pause, resume-warmup, or drain.`,
	);
}

main().catch((error) => {
	console.error(error instanceof Error ? error.message : String(error));
	process.exit(1);
});
