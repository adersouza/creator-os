/**
 * QStash client for fan-out job dispatch
 *
 * Required environment variables:
 * - QSTASH_TOKEN
 * - QSTASH_CURRENT_SIGNING_KEY
 * - QSTASH_NEXT_SIGNING_KEY
 */

import { Client, Receiver } from "@upstash/qstash";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { logger } from "./logger.js";

let client: Client | null = null;
let receiver: Receiver | null = null;

export function getQStashClient(): Client {
	if (!client) {
		const token = process.env.QSTASH_TOKEN;
		if (!token) {
			throw new Error("Missing QSTASH_TOKEN environment variable");
		}
		client = new Client({ token });
	}
	return client;
}

function getReceiver(): Receiver {
	if (!receiver) {
		const currentSigningKey = process.env.QSTASH_CURRENT_SIGNING_KEY;
		const nextSigningKey = process.env.QSTASH_NEXT_SIGNING_KEY;
		if (!currentSigningKey || !nextSigningKey) {
			throw new Error(
				"Missing QSTASH_CURRENT_SIGNING_KEY or QSTASH_NEXT_SIGNING_KEY environment variables",
			);
		}
		receiver = new Receiver({ currentSigningKey, nextSigningKey });
	}
	return receiver;
}

/**
 * Verify QStash signature on incoming webhook requests.
 * Returns true if valid, sends 401 and returns false otherwise.
 *
 * Usage:
 *   if (!await verifyQStashSignature(req, res)) return;
 */
export async function verifyQStashSignature(
	req: VercelRequest,
	res: VercelResponse,
): Promise<boolean> {
	try {
		const signature = req.headers["upstash-signature"];
		if (!signature || typeof signature !== "string") {
			logger.warn("Missing upstash-signature header");
			res.status(401).json({ error: "Missing signature" });
			return false;
		}

		const body =
			typeof req.body === "string" ? req.body : JSON.stringify(req.body);

		const isValid = await getReceiver().verify({
			signature,
			body,
		});

		if (!isValid) {
			logger.warn("Invalid QStash signature");
			res.status(401).json({ error: "Invalid signature" });
			return false;
		}

		return true;
	} catch (err) {
		logger.warn("QStash signature verification failed", { error: String(err) });
		res.status(401).json({ error: "Signature verification failed" });
		return false;
	}
}
