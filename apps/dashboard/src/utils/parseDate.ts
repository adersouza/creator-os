/**
 * parseDate — safely converts various date representations to a Date object.
 * Handles: Date objects, ISO strings, Firestore timestamps ({seconds, toDate()}),
 * numeric timestamps, null/undefined.
 */
export function parseDate(value: unknown): Date {
	if (!value) return new Date();
	if (value instanceof Date) return value;
	if (typeof value === "string" || typeof value === "number") {
		const d = new Date(value);
		return Number.isNaN(d.getTime()) ? new Date() : d;
	}
	// Firestore Timestamp with toDate()
	if (typeof value === "object" && value !== null) {
		if (
			"toDate" in value &&
			typeof (value as { toDate: unknown }).toDate === "function"
		) {
			return (value as { toDate: () => Date }).toDate();
		}
		// Firestore-style {seconds: number}
		if (
			"seconds" in value &&
			typeof (value as { seconds: unknown }).seconds === "number"
		) {
			return new Date((value as { seconds: number }).seconds * 1000);
		}
	}
	return new Date();
}
