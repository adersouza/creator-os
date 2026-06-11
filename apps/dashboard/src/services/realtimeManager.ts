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

import type { AuthChangeEvent, RealtimeChannel } from "@supabase/supabase-js";
import { supabase } from "./supabase.js";

// -- Types --------------------------------------------------------------------

export type ChannelFactory = (
	signal: AbortSignal,
) => RealtimeChannel | Promise<RealtimeChannel | null> | null;

interface ChannelEntry {
	channel: RealtimeChannel | null;
	/** Called on tab wake to re-fetch data missed while socket was dead */
	onReconnect?: () => void;
	/** Number of active consumers sharing this key */
	refCount: number;
	/** Abort controller for in-flight async setup */
	abort: AbortController;
}

// -- State --------------------------------------------------------------------

const channels = new Map<string, ChannelEntry>();
let wakeFiredAt = 0;

/** Reset internal debounce state (for tests only) */
export function _resetWakeTimestamp(): void {
	wakeFiredAt = 0;
}

// -- Core API -----------------------------------------------------------------

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
		// Update reconnect callback to the latest consumer's version
		if (onReconnect) {
			existing.onReconnect = onReconnect;
		}
		return createUnsubscribe(key);
	}

	const abort = new AbortController();
	const entry: ChannelEntry = {
		channel: null,
		refCount: 1,
		abort,
	};
	if (onReconnect) entry.onReconnect = onReconnect;
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
			entry.channel = ch;
		});
	} else {
		// Sync factory — result is RealtimeChannel | null (Promise narrowed out above)
		entry.channel = result as RealtimeChannel | null;
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

// Keep realtime teardown colocated with the channel registry so sign-out
// can clear both the Supabase socket subscriptions and our ref-count map
// without creating a supabase -> realtimeManager import edge.
if (typeof supabase.auth.onAuthStateChange === "function") {
	supabase.auth.onAuthStateChange((event: AuthChangeEvent) => {
		if (event === "SIGNED_OUT") {
			unsubscribeAll();
		}
	});
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

// -- Internals ----------------------------------------------------------------

function createUnsubscribe(key: string): () => void {
	let called = false;
	return () => {
		if (called) return; // idempotent
		called = true;

		const entry = channels.get(key);
		if (!entry) return;

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

// -- Wake handler -------------------------------------------------------------

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

	for (const entry of channels.values()) {
		try {
			entry.onReconnect?.();
		} catch {
			// Swallow — individual reconnect failures must not block others
		}
	}
}

// Only register in browser (not during SSR/tests)
if (typeof document !== "undefined") {
	document.addEventListener("visibilitychange", handleWake);
}

// -- Dev leak detector --------------------------------------------------------

if (typeof window !== "undefined" && import.meta.env?.DEV) {
	setInterval(() => {
		const count = channels.size;
		if (count > 15) {
		}
	}, 10_000);
}
