/**
 * useVisionScore — hook for scoring images via Vision AI
 */

import { useCallback, useRef, useState } from "react";
import { supabase } from "@/services/supabase";

export interface VisionScore {
	score: number;
	breakdown: {
		composition: number;
		lighting: number;
		color: number;
		clarity: number;
		engagement_potential: number;
	};
	suggestions: string[];
	captionAngle: string;
	cached: boolean;
}

async function authedPost(
	url: string,
	body: Record<string, unknown>,
): Promise<unknown> {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	if (!session?.access_token) throw new Error("Not authenticated");
	const res = await fetch(url, {
		method: "POST",
		headers: {
			Authorization: `Bearer ${session.access_token}`,
			"Content-Type": "application/json",
		},
		body: JSON.stringify(body),
	});
	if (!res.ok) throw new Error(`Request failed: ${res.status}`);
	const json = await res.json();
	return json.data || json;
}

export function useVisionScore() {
	const [scores, setScores] = useState<Record<string, VisionScore>>({});
	const [loading, setLoading] = useState<Record<string, boolean>>({});
	const scoresRef = useRef<Record<string, VisionScore>>({});

	const scoreImage = useCallback(
		async (imageUrl: string, platform: string): Promise<VisionScore | null> => {
			// Check cache via ref to avoid stale closure
			const cached = scoresRef.current[imageUrl];
			if (cached) return cached;

			setLoading((prev) => ({ ...prev, [imageUrl]: true }));
			try {
				const data = await authedPost("/api/ai/vision-score", {
					imageUrl,
					platform,
				});
				const result = data as VisionScore;
				setScores((prev) => {
					const next = { ...prev, [imageUrl]: result };
					scoresRef.current = next;
					return next;
				});
				return result;
			} catch (_err) {
				return null;
			} finally {
				setLoading((prev) => ({ ...prev, [imageUrl]: false }));
			}
		},
		[],
	);

	const clearScore = useCallback((imageUrl: string) => {
		setScores((prev) => {
			const next = { ...prev };
			delete next[imageUrl];
			scoresRef.current = next;
			return next;
		});
	}, []);

	return { scores, loading, scoreImage, clearScore };
}
