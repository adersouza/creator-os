import { useCallback, useRef, useState } from "react";
import { apiUrl } from "@/lib/apiUrl";
import { supabase } from "@/services/supabase";

export interface AltTextResult {
	altText: string;
	confidence?: number | undefined;
	suggestions?: string[] | undefined;
	cached?: boolean | undefined;
}

async function authedPost(
	url: string,
	body: Record<string, unknown>,
): Promise<AltTextResult> {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	if (!session?.access_token) throw new Error("Not authenticated");
	const response = await fetch(url, {
		method: "POST",
		headers: {
			Authorization: `Bearer ${session.access_token}`,
			"Content-Type": "application/json",
		},
		body: JSON.stringify(body),
	});
	const json = await response.json().catch(() => null);
	if (!response.ok) throw new Error(json?.error || `Request failed: ${response.status}`);
	return (json?.data || json) as AltTextResult;
}

export function useAltTextGenerator() {
	const [loading, setLoading] = useState<Record<string, boolean>>({});
	const cacheRef = useRef<Record<string, AltTextResult>>({});

	const generateAltText = useCallback(
		async ({
			imageUrl,
			platform,
			postType,
		}: {
			imageUrl: string;
			platform: "instagram" | "threads";
			postType: string;
		}): Promise<AltTextResult | null> => {
			const key = `${imageUrl}:${platform}:${postType}`;
			const cached = cacheRef.current[key];
			if (cached) return cached;
			setLoading((prev) => ({ ...prev, [imageUrl]: true }));
			try {
				const result = await authedPost(apiUrl("/api/ai/alt-text"), {
					imageUrl,
					platform,
					postType,
				});
				cacheRef.current = { ...cacheRef.current, [key]: result };
				return result;
			} catch {
				return null;
			} finally {
				setLoading((prev) => ({ ...prev, [imageUrl]: false }));
			}
		},
		[],
	);

	return { loading, generateAltText };
}
