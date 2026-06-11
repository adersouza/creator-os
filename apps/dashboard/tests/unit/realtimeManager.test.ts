import type { RealtimeChannel } from "@supabase/supabase-js";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ── Mock Supabase before imports ─────────────────────────────────────────────

const mockRemoveChannel = vi.fn();
const mockSubscribe = vi.fn().mockReturnThis();
const mockOn = vi.fn().mockReturnThis();

function createMockChannel(name: string) {
	return {
		name,
		on: mockOn,
		subscribe: mockSubscribe,
		unsubscribe: vi.fn(),
		_isMockChannel: true,
	} as unknown as RealtimeChannel;
}

const mockChannelFn = vi.fn((name: string) => createMockChannel(name));

vi.mock("@/services/supabase", () => ({
	supabase: {
		channel: (name: string) => mockChannelFn(name),
		removeChannel: (ch: any) => mockRemoveChannel(ch),
		auth: {
			getSession: vi.fn().mockResolvedValue({
				data: { session: { user: { id: "user-1" } } },
			}),
		},
	},
}));

import {
	subscribe,
	unsubscribeAll,
	getActiveCount,
	getActiveKeys,
	_resetWakeTimestamp,
} from "@/services/realtimeManager";

// ── Helpers ──────────────────────────────────────────────────────────────────

beforeEach(() => {
	vi.useFakeTimers();
	vi.clearAllMocks();
	unsubscribeAll();
	_resetWakeTimestamp();
	vi.clearAllMocks(); // clear the removeChannel calls from unsubscribeAll
});

afterEach(() => {
	vi.useRealTimers();
	unsubscribeAll();
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("realtimeManager", () => {
	describe("subscribe / unsubscribe lifecycle", () => {
		it("registers a channel from a sync factory", () => {
			const channel = createMockChannel("test-1");
			const unsub = subscribe("test-1", () => channel);

			expect(getActiveCount()).toBe(1);
			expect(getActiveKeys()).toContain("test-1");

			unsub();
			expect(getActiveCount()).toBe(0);
			expect(mockRemoveChannel).toHaveBeenCalledWith(channel);
		});

		it("calls removeChannel (not unsubscribe) on cleanup", () => {
			const channel = createMockChannel("test-rc");
			const unsub = subscribe("test-rc", () => channel);
			unsub();

			expect(mockRemoveChannel).toHaveBeenCalledTimes(1);
			expect(mockRemoveChannel).toHaveBeenCalledWith(channel);
			// Must NOT use .unsubscribe()
			expect(channel.unsubscribe).not.toHaveBeenCalled();
		});

		it("handles null factory return gracefully", () => {
			const unsub = subscribe("null-chan", () => null);

			expect(getActiveCount()).toBe(1);
			unsub();
			expect(getActiveCount()).toBe(0);
			// removeChannel should NOT be called for null channel
			expect(mockRemoveChannel).not.toHaveBeenCalled();
		});
	});

	describe("async factory with abort signal", () => {
		it("cleans up channel created after unmount (async race)", async () => {
			const channel = createMockChannel("async-race");
			let resolveFactory!: (ch: any) => void;
			const factoryPromise = new Promise<any>((r) => {
				resolveFactory = r;
			});

			const unsub = subscribe("async-race", (_signal) => factoryPromise);

			// Unmount BEFORE factory resolves
			unsub();
			expect(getActiveCount()).toBe(0);

			// Factory resolves with a channel AFTER cleanup ran
			resolveFactory(channel);
			await factoryPromise;

			// The manager must have torn it down immediately
			// Advance timers so the .then() handler runs
			await vi.advanceTimersByTimeAsync(0);
			expect(mockRemoveChannel).toHaveBeenCalledWith(channel);
		});

		it("keeps channel alive when factory resolves before unmount", async () => {
			const channel = createMockChannel("async-ok");
			const unsub = subscribe(
				"async-ok",
				async (_signal) => {
					// Simulate brief async work
					await new Promise((r) => setTimeout(r, 10));
					return channel;
				},
			);

			// Advance timers so the factory resolves
			await vi.advanceTimersByTimeAsync(20);
			expect(getActiveCount()).toBe(1);

			// Now unmount — should call removeChannel
			unsub();
			expect(mockRemoveChannel).toHaveBeenCalledWith(channel);
			expect(getActiveCount()).toBe(0);
		});

		it("handles async factory returning null", async () => {
			const unsub = subscribe("async-null", async () => null);
			await vi.advanceTimersByTimeAsync(10);

			unsub();
			expect(getActiveCount()).toBe(0);
			expect(mockRemoveChannel).not.toHaveBeenCalled();
		});
	});

	describe("deduplication via refCount", () => {
		it("does not open a second channel for the same key", () => {
			const channel = createMockChannel("shared");
			let factoryCallCount = 0;
			const factory = () => {
				factoryCallCount++;
				return channel;
			};

			const unsub1 = subscribe("shared", factory);
			const unsub2 = subscribe("shared", factory);

			expect(factoryCallCount).toBe(1); // factory called only once
			expect(getActiveCount()).toBe(1);

			// First unsubscribe decrements refCount but keeps channel
			unsub1();
			expect(getActiveCount()).toBe(1);
			expect(mockRemoveChannel).not.toHaveBeenCalled();

			// Second unsubscribe drops refCount to 0 — removes channel
			unsub2();
			expect(getActiveCount()).toBe(0);
			expect(mockRemoveChannel).toHaveBeenCalledWith(channel);
		});

		it("survives 20 rapid mount/unmount cycles without leaking", () => {
			const channel = createMockChannel("rapid");
			const unsubs: (() => void)[] = [];

			for (let i = 0; i < 20; i++) {
				unsubs.push(subscribe("rapid", () => channel));
			}

			expect(getActiveCount()).toBe(1); // deduplicated to 1

			// Unmount all 20
			for (const u of unsubs) u();
			expect(getActiveCount()).toBe(0);
			expect(mockRemoveChannel).toHaveBeenCalledTimes(1);
		});
	});

	describe("unsubscribe idempotency", () => {
		it("calling unsubscribe twice does not double-remove", () => {
			const channel = createMockChannel("idem");
			const unsub = subscribe("idem", () => channel);

			unsub();
			unsub(); // second call — should be a no-op

			expect(mockRemoveChannel).toHaveBeenCalledTimes(1);
		});
	});

	describe("unsubscribeAll", () => {
		it("removes every channel on logout", () => {
			const ch1 = createMockChannel("ch-1");
			const ch2 = createMockChannel("ch-2");
			const ch3 = createMockChannel("ch-3");

			subscribe("ch-1", () => ch1);
			subscribe("ch-2", () => ch2);
			subscribe("ch-3", () => ch3);

			expect(getActiveCount()).toBe(3);

			unsubscribeAll();
			expect(getActiveCount()).toBe(0);
			expect(mockRemoveChannel).toHaveBeenCalledWith(ch1);
			expect(mockRemoveChannel).toHaveBeenCalledWith(ch2);
			expect(mockRemoveChannel).toHaveBeenCalledWith(ch3);
		});
	});

	describe("wake reconnect callbacks", () => {
		it("fires onReconnect for all active channels on visibilitychange", () => {
			const reconnect1 = vi.fn();
			const reconnect2 = vi.fn();

			subscribe("wake-1", () => createMockChannel("wake-1"), reconnect1);
			subscribe("wake-2", () => createMockChannel("wake-2"), reconnect2);

			// Simulate tab becoming visible
			Object.defineProperty(document, "visibilityState", {
				value: "visible",
				writable: true,
				configurable: true,
			});
			document.dispatchEvent(new Event("visibilitychange"));

			expect(reconnect1).toHaveBeenCalledTimes(1);
			expect(reconnect2).toHaveBeenCalledTimes(1);
		});

		it("debounces rapid visibility toggles to 1 call per 2s", async () => {
			const reconnect = vi.fn();
			subscribe("debounce", () => createMockChannel("debounce"), reconnect);

			Object.defineProperty(document, "visibilityState", {
				value: "visible",
				writable: true,
				configurable: true,
			});

			// Fire 5 times rapidly
			for (let i = 0; i < 5; i++) {
				document.dispatchEvent(new Event("visibilitychange"));
			}

			// Only 1 call due to debounce (the first one fires, rest are within 2s)
			expect(reconnect).toHaveBeenCalledTimes(1);
		});

		it("does not fire reconnect when tab goes hidden", () => {
			const reconnect = vi.fn();
			subscribe("hidden", () => createMockChannel("hidden"), reconnect);

			Object.defineProperty(document, "visibilityState", {
				value: "hidden",
				writable: true,
				configurable: true,
			});
			document.dispatchEvent(new Event("visibilitychange"));

			expect(reconnect).not.toHaveBeenCalled();
		});

		it("does not call reconnect for channels without it", () => {
			// No onReconnect provided
			subscribe("no-reconnect", () => createMockChannel("no-reconnect"));

			Object.defineProperty(document, "visibilityState", {
				value: "visible",
				writable: true,
				configurable: true,
			});

			// Should not throw
			expect(() => {
				document.dispatchEvent(new Event("visibilitychange"));
			}).not.toThrow();
		});
	});

	describe("signal propagation", () => {
		it("passes AbortSignal to factory", () => {
			let receivedSignal: AbortSignal | null = null;
			subscribe("signal-test", (signal) => {
				receivedSignal = signal;
				return createMockChannel("signal-test");
			});

			expect(receivedSignal).toBeInstanceOf(AbortSignal);
			expect(receivedSignal!.aborted).toBe(false);
		});

		it("aborts signal on unsubscribe", () => {
			let receivedSignal: AbortSignal | null = null;
			const unsub = subscribe("signal-abort", (signal) => {
				receivedSignal = signal;
				return createMockChannel("signal-abort");
			});

			unsub();
			expect(receivedSignal!.aborted).toBe(true);
		});
	});
});
