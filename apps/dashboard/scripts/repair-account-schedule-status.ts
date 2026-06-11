import "dotenv/config";
import { syncAccountScheduleStatuses } from "../api/_lib/handlers/auto-post/accountScheduleStatusSync.js";
import { getSupabaseAny } from "../api/_lib/supabase.js";

const args = new Set(process.argv.slice(2));
const apply = args.has("--apply");
const workspaceArg = process.argv
	.slice(2)
	.find((arg) => arg.startsWith("--workspace="));
const workspaceId =
	workspaceArg?.slice("--workspace=".length) ||
	process.env.WORKSPACE_ID ||
	"vy77QZUKDpumVO9KT6ll";

const supabase = getSupabaseAny();

const { data: states, error } = await supabase
	.from("account_autoposter_state")
	.select("*")
	.eq("workspace_id", workspaceId);

if (error) {
	throw new Error(`Failed to load account_autoposter_state: ${error.message}`);
}

const report = await syncAccountScheduleStatuses({
	workspaceId,
	states: states ?? [],
	dryRun: !apply,
});

console.log(
	JSON.stringify(
		{
			workspaceId,
			mode: apply ? "apply" : "dry_run",
			checked: report.checked,
			mismatches: report.mismatches,
			repaired: report.repaired,
			skippedPaused: report.skippedPaused,
			remainingBlocked: report.remainingBlocked,
			sample: report.rows.slice(0, 50),
		},
		null,
		2,
	),
);
