import { supabase } from "@/services/supabase";

export async function fetchAllAccountIds(): Promise<string[]> {
	const { data: wsAccounts } = await supabase.from("accounts").select("id");
	const { data: wsIgAccounts } = await supabase
		.from("instagram_accounts")
		.select("id");
	return [
		...(wsAccounts || []).map((a: { id: string }) => a.id),
		...(wsIgAccounts || []).map((a: { id: string }) => a.id),
	];
}

export async function fetchPendingPostsByAccountIds(accountIds: string[]) {
	const { data, error } = await supabase
		.from("posts")
		.select(
			"id, content, media_urls, status, approval_status, scheduled_for, account_id, created_at, approval_notes",
		)
		.eq("approval_status", "pending")
		.in("account_id", accountIds)
		.order("created_at", { ascending: false });
	if (error) throw error;
	return data || [];
}
