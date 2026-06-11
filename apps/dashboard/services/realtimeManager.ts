/// <reference path="../vite-env.d.ts" />
/**
 * Centralized Supabase Realtime channel manager.
 *
 * Solves three classes of bugs:
 * 1. Orphaned channels from async setup racing with component unmount
 * 2. Channel leaks from using .unsubscribe() instead of removeChannel()
 * 3. Missed events after sleep/wake (postgres_changes can't replay WAL)
 *
 * Every realtime subscription in the app goes through this module.
 */

import type { RealtimeChannel } from "@supabase/supabase-js";
import { supabase } from "./supabase.js";

// ── Types ────────────────────────────────────────────────────────────────────

export type ChannelFactory = (
	signal: AbortSignal,
) => RealtimeChannel | Promise<RealtimeChannel | null> | null;

interface ChannelEntry {
	channel: RealtimeChannel | null;
	/**
	 * Wake-callbacks for every active consumer of this key. Stored as an
	 * array (not a single callback) because two sibling components can
	 * subscribe to the same key — the second consumer's callback used to
	 * overwrite the first, silently dropping the earlier component's
	 * tab-wake refetch.
	 */
	onReconnect: Array<() => void>;
	/** Number of active consumers sharing this key */
	refCount: number;
	/** Abort controller for in-flight async setup */
	abort: AbortController;
}

// ── State ────────────────────────────────────────────────────────────────────

const channels = new Map<string, ChannelEntry>();
let wakeFiredAt = 0;

/** Reset internal debounce state (for tests only) */
export function _resetWakeTimestamp(): void {
	wakeFiredAt = 0;
}

// ── Core API ─────────────────────────────────────────────────────────────────

/**
 * Subscribe to a realtime channel.
 *
 * - Deduplicates by key: if a channel with the same key already exists,
 *   increments refCount instead of opening a second socket.
 * - Abort-safe: if cleanup runs before the async factory resolves,
 *   the channel is removed immediately — no orphan.
 *
 * Returns an unsubscribe function (safe to call multiple times).
 */
export function subscribe(
	key: string,
	factory: ChannelFactory,
	onReconnect?: () => void,
): () => void {
	const existing = channels.get(key);
	if (existing) {
		existing.refCount++;
		// Append the new consumer's reconnect callback so every subscriber
		// fires on wake — the previous "overwrite" behavior dropped older
		// consumers' callbacks silently.
		if (onReconnect) {
			existing.onReconnect.push(onReconnect);
		}
		return createUnsubscribe(key, onReconnect);
	}

	const abort = new AbortController();
	const entry: ChannelEntry = {
		channel: null,
		onReconnect: onReconnect ? [onReconnect] : [],
		refCount: 1,
		abort,
	};
	channels.set(key, entry);

	// Factory may be sync or async
	const result = factory(abort.signal);

	if (result && "then" in result) {
		// Async factory — handle the race
		(result as Promise<RealtimeChannel | null>).then((ch) => {
			if (abort.signal.aborted) {
				// Cleanup already ran while we were awaiting — tear down immediately
				if (ch) supabase.removeChannel(ch);
				return;
			}
			// Drop phantom entries — when the factory resolves to null
			// (e.g. unauthenticated callers), keep nothing in the map so the
			// dev leak detector doesn't count it.
			if (ch === null) {
				channels.delete(key);
				return;
			}
			entry.channel = ch;
		});
	} else {
		// Sync factory — result is RealtimeChannel | null (Promise narrowed out above)
		const ch = result as RealtimeChannel | null;
		if (ch === null) {
			channels.delete(key);
		} else {
			entry.channel = ch;
		}
	}

	return createUnsubscribe(key);
}

/**
 * Remove ALL channels. Call on logout.
 */
export function unsubscribeAll(): void {
	for (const [key, entry] of channels) {
		entry.abort.abort();
		if (entry.channel) {
			supabase.removeChannel(entry.channel);
		}
		channels.delete(key);
	}
}

/**
 * Get the number of active channels (for dev-mode leak detection).
 */
export function getActiveCount(): number {
	return channels.size;
}

/**
 * Get all active channel keys (for debugging).
 */
export function getActiveKeys(): string[] {
	return Array.from(channels.keys());
}

// ── Internals ────────────────────────────────────────────────────────────────

function createUnsubscribe(
	key: string,
	ownCallback?: () => void,
): () => void {
	let called = false;
	return () => {
		if (called) return; // idempotent
		called = true;

		const entry = channels.get(key);
		if (!entry) return;

		// Remove just this consumer's callback so other still-subscribed
		// components keep getting wake notifications.
		if (ownCallback) {
			const idx = entry.onReconnect.indexOf(ownCallback);
			if (idx !== -1) entry.onReconnect.splice(idx, 1);
		}

		entry.refCount--;
		if (entry.refCount <= 0) {
			entry.abort.abort();
			if (entry.channel) {
				supabase.removeChannel(entry.channel);
			}
			channels.delete(key);
		}
	};
}

// ── Wake handler ─────────────────────────────────────────────────────────────

/**
 * On tab wake, fire all registered onReconnect callbacks so subscribers
 * can REST-fetch data that arrived while the WebSocket was dead.
 *
 * Debounced to 1 call per 2 seconds to avoid storms from rapid
 * visibility toggles.
 */
function handleWake(): void {
	if (document.visibilityState !== "visible") return;

	const now = Date.now();
	if (now - wakeFiredAt < 2000) return;
	wakeFiredAt = now;

	// Fire each callback with a small random jitter so a tab wake with 10+
	// active subscribers doesn't cause a synchronous burst against Supabase
	// and the Vercel API layer (the dev leak threshold is 15, so this is a
	// real concern at scale).
	for (const entry of channels.values()) {
		for (const cb of entry.onReconnect) {
			const delay = Math.random() * 500;
			setTimeout(() => {
				try {
					cb();
				} catch {
					// Swallow — one consumer's failure must not block others.
				}
			}, delay);
		}
	}
}

// Only register in browser (not during SSR/tests)
if (typeof document !== "undefined") {
	document.addEventListener("visibilitychange", handleWake);
}

// ── Dev leak detector ────────────────────────────────────────────────────────

if (typeof window !== "undefined" && import.meta.env?.DEV) {
	setInterval(() => {
		const count = channels.size;
		if (count > 15) {
			// Empty body before — the entire leak detector was inert. Surface
			// the leak with a console warning + the active key list so the
			// developer can identify which subscription isn't unsubscribing.
			// biome-ignore lint/suspicious/noConsole: dev-only diagnostic
			console.warn(
				`[realtimeManager] ${count} active channels (>15 threshold). ` +
					"Check for missing unsubscribe() in useEffect cleanup.",
				Array.from(channels.keys()),
			);
		}
	}, 10_000);
}
