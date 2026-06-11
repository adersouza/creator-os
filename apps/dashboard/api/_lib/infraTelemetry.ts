import { logger } from "./logger.js";

function currentHourKey(): string {
	return new Date().toISOString().slice(0, 13);
}

export async function recordInfraEvent(
	event: string,
	fields?: Record<string, unknown>,
): Promise<void> {
	try {
		const { getRedis } = await import("./redis.js");
		const redis = getRedis();
		const key = `infra:${event}:${currentHourKey()}`;
		const count = await redis.incr(key);
		if (count === 1) {
			await redis.expire(key, 2 * 24 * 60 * 60);
		}
	} catch (error) {
		logger.debug("[infra-telemetry] Redis counter failed", {
			event,
			error: error instanceof Error ? error.message : String(error),
		});
	}

	logger.info("[infra-telemetry] Event", {
		event,
		...(fields || {}),
	});
}
