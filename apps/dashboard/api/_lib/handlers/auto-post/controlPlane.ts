export type AutoposterRuntimeMode =
	| "running"
	| "paused"
	| "fill_disabled"
	| "group_mode_disabled"
	| "hard_disabled";

export interface AutoposterSwitchState {
	is_enabled: boolean;
	group_mode_enabled: boolean;
	enable_ai_queue_fill: boolean;
	hard_disabled: boolean;
}

interface WorkspaceConfigRow {
	is_enabled?: boolean | null;
	group_mode_enabled?: boolean | null;
	enable_ai_queue_fill?: boolean | null;
}

export function deriveAutoposterRuntimeMode(
	switches: AutoposterSwitchState,
): AutoposterRuntimeMode {
	if (switches.hard_disabled) return "hard_disabled";
	if (!switches.is_enabled) return "paused";
	if (!switches.group_mode_enabled) return "group_mode_disabled";
	if (!switches.enable_ai_queue_fill) return "fill_disabled";
	return "running";
}

export function deriveAutoposterRuntimeModeFromConfig(
	config: WorkspaceConfigRow | null | undefined,
	hardDisabled: boolean,
): AutoposterRuntimeMode {
	return deriveAutoposterRuntimeMode({
		is_enabled: Boolean(config?.is_enabled),
		group_mode_enabled: Boolean(config?.group_mode_enabled),
		enable_ai_queue_fill: Boolean(config?.enable_ai_queue_fill),
		hard_disabled: hardDisabled,
	});
}
