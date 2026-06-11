import { supabase } from "@/services/supabase.js";
import type { Json } from "../types/supabase.js";

function isJsonValue(value: unknown): value is Json {
	if (
		value === null ||
		typeof value === "string" ||
		typeof value === "number" ||
		typeof value === "boolean"
	) {
		return true;
	}

	if (Array.isArray(value)) {
		return value.every((item) => isJsonValue(item));
	}

	if (typeof value !== "object") {
		return false;
	}

	return Object.values(value).every(
		(item) => item === undefined || isJsonValue(item),
	);
}

/**
 * upsertUserSetting — persist a user setting to the user_settings table.
 *
 * Uses upsert with (user_id, setting_key) conflict resolution.
 * Previously copy-pasted across AIConfigSection, GrowthPreferencesSection,
 * and NotificationsSection.
 */
export async function upsertUserSetting(
	userId: string,
	settingKey: string,
	settingValue: unknown,
): Promise<void> {
	if (!isJsonValue(settingValue)) {
		throw new Error("Setting value must be JSON-serializable");
	}

	const { error } = await supabase.from("user_settings").upsert(
		{
			user_id: userId,
			setting_key: settingKey,
			setting_value: settingValue,
			updated_at: new Date().toISOString(),
		},
		{ onConflict: "user_id,setting_key" },
	);
	if (error) throw error;
}

export async function getUserSetting(
	userId: string,
	settingKey: string,
): Promise<unknown | null> {
	const { data, error } = await supabase
		.from("user_settings")
		.select("setting_value")
		.eq("user_id", userId)
		.eq("setting_key", settingKey)
		.maybeSingle();
	if (error) throw error;
	return data?.setting_value ?? null;
}
