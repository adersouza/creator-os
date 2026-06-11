import { supabase } from "@/services/supabase";

export async function getCrossPostSettings(workspaceId: string) {
	const { data, error } = await supabase
		.from("cross_post_settings")
		.select("*")
		.eq("workspace_id", workspaceId)
		.maybeSingle();
	if (error) throw error;
	return data;
}

export async function upsertCrossPostSettings(
	workspaceId: string,
	config: Record<string, unknown>,
) {
	const { error } = await supabase.from("cross_post_settings").upsert(
		{
			workspace_id: workspaceId,
			...config,
			updated_at: new Date().toISOString(),
		},
		{ onConflict: "workspace_id" },
	);
	if (error) throw error;
}
