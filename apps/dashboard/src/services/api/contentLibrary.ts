import { apiUrl } from "@/lib/apiUrl";
import { supabase } from "@/services/supabase";

async function authHeaders(): Promise<HeadersInit | null> {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	if (!session?.access_token) return null;
	return {
		"Content-Type": "application/json",
		Authorization: `Bearer ${session.access_token}`,
	};
}

export async function registerUploadedMedia(input: {
	fileName: string;
	fileUrl: string;
	storagePath: string;
	mimeType: string;
	fileSize: number;
	groupId?: string | null | undefined;
	accountId?: string | null | undefined;
	accountPlatform?: "threads" | "instagram" | null | undefined;
}) {
	const headers = await authHeaders();
	if (!headers) throw new Error("Not authenticated");
	const response = await fetch(apiUrl("/api/media?action=upload"), {
		method: "POST",
		headers,
		body: JSON.stringify(input),
	});
	if (!response.ok) {
		throw new Error(`Media registration failed: ${response.status}`);
	}
	return response.json();
}
