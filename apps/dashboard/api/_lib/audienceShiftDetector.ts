// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Audience Shift Detector
 *
 * Compares current demographics snapshot to 30-day-ago snapshot.
 * If any bucket shifts >15%, creates an anomaly_alert of type 'audience_shift'.
 */

import { createNotification } from "./createNotification.js";
import { logger } from "./logger.js";
import type { Platform } from "./platform.js";
import { getSupabase } from "./supabase.js";

const db = () => getSupabase();

interface DemoBucket {
	[key: string]: number;
}

interface ShiftResult {
	bucket: string;
	category: string;
	oldPct: number;
	newPct: number;
	shiftPct: number;
}

/**
 * Detect audience shifts by comparing current demographics to stored snapshot.
 * Stores current demographics as a snapshot, then compares to 30-day-old snapshot.
 */
export async function detectAudienceShifts(
	userId: string,
	accountId: string,
	platform: Platform,
	currentDemographics: {
		age?: DemoBucket | undefined;
		gender?: DemoBucket | undefined;
	},
): Promise<ShiftResult[]> {
	if (!currentDemographics.age && !currentDemographics.gender) return [];

	const accountIdCol =
		platform === "instagram" ? "instagram_account_id" : "account_id";
	const today = new Date().toISOString().split("T")[0]!;

	// Store current snapshot
	// biome-ignore lint/suspicious/noExplicitAny: demographics_snapshots not in generated types
	await (db() as any).from("demographics_snapshots").upsert(
		{
			[accountIdCol]: accountId,
			user_id: userId,
			platform,
			date: today,
			demographics_data: currentDemographics,
		},
		{ onConflict: `${accountIdCol},date` },
	);

	// Fetch 30-day-old snapshot
	const thirtyDaysAgo = new Date();
	thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
	const targetDate = thirtyDaysAgo.toISOString().split("T")[0]!;

	// biome-ignore lint/suspicious/noExplicitAny: demographics_snapshots not in generated types
	const { data: oldSnapshot } = await (db() as any)
		.from("demographics_snapshots")
		.select("demographics_data")
		.eq(accountIdCol, accountId)
		.lte("date", targetDate)
		.order("date", { ascending: false })
		.limit(1)
		.maybeSingle();

	if (!oldSnapshot?.demographics_data) return [];

	const oldDemo = oldSnapshot.demographics_data as typeof currentDemographics;
	const shifts: ShiftResult[] = [];

	// Compare each category (age, gender)
	for (const category of ["age", "gender"] as const) {
		const oldBuckets = oldDemo[category];
		const newBuckets = currentDemographics[category];
		if (!oldBuckets || !newBuckets) continue;

		const oldTotal = Object.values(oldBuckets).reduce((s, v) => s + v, 0);
		const newTotal = Object.values(newBuckets).reduce((s, v) => s + v, 0);
		// #604: Skip comparison when totals are too small (new accounts)
		if (oldTotal < 10 || newTotal < 10) continue;

		const allKeys = new Set([
			...Object.keys(oldBuckets),
			...Object.keys(newBuckets),
		]);
		for (const key of allKeys) {
			const oldPct = ((oldBuckets[key] ?? 0) / oldTotal) * 100;
			const newPct = ((newBuckets[key] ?? 0) / newTotal) * 100;
			const shiftPct = Math.abs(newPct - oldPct);

			if (shiftPct > 15) {
				shifts.push({ bucket: key, category, oldPct, newPct, shiftPct });
			}
		}
	}

	// Create anomaly alerts for significant shifts
	for (const shift of shifts) {
		const direction = shift.newPct > shift.oldPct ? "increased" : "decreased";
		const title = `Audience shift: ${shift.category} "${shift.bucket}" ${direction}`;
		const description = `The "${shift.bucket}" ${shift.category} segment shifted from ${shift.oldPct.toFixed(1)}% to ${shift.newPct.toFixed(1)}% (${shift.shiftPct.toFixed(1)}pp change over 30 days).`;

		// biome-ignore lint/suspicious/noExplicitAny: anomaly_alerts not in generated types
		await (db() as any).from("anomaly_alerts").insert({
			user_id: userId,
			[accountIdCol]: accountId,
			platform,
			alert_type: "audience_shift",
			severity: shift.shiftPct > 25 ? "high" : "medium",
			title,
			description,
			data: shift,
		});

		await createNotification({
			userId,
			type: "anomaly_audience_shift",
			title,
			message: description,
		}).catch(() => {});
	}

	if (shifts.length > 0) {
		logger.info("Audience shifts detected", {
			userId,
			accountId,
			platform,
			shifts: shifts.length,
		});
	}

	return shifts;
}
