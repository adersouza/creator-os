/**
 * Global hard-stop switch for the autoposter.
 *
 * This is intentionally environment-based so operators can stop the entire
 * system even if queue rows or per-workspace config are already in flight.
 */

const TRUE_VALUES = new Set(["1", "true", "yes", "on"]);

export function isAutoposterHardDisabled(): boolean {
	const raw = process.env.AUTOPOSTER_HARD_DISABLED?.trim().toLowerCase();
	return raw ? TRUE_VALUES.has(raw) : false;
}
