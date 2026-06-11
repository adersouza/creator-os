/**
 * Push Subscription Service (Frontend)
 *
 * Manages browser push notification permission and subscription lifecycle.
 * Communicates with /api/push/subscribe and /api/push/vapid-key endpoints.
 */

import { supabase } from "@/services/supabase.js";

/** Check if the browser supports push notifications */
export function isPushSupported(): boolean {
	return (
		"serviceWorker" in navigator &&
		"PushManager" in window &&
		"Notification" in window
	);
}

/** Get current notification permission state */
export function getPermissionState(): NotificationPermission {
	if (!("Notification" in window)) return "denied";
	return Notification.permission;
}

/** Check if user currently has an active push subscription */
export async function isCurrentlySubscribed(): Promise<boolean> {
	try {
		const registration = await navigator.serviceWorker.ready;
		const subscription = await registration.pushManager.getSubscription();
		return subscription !== null;
	} catch {
		return false;
	}
}

/** Fetch VAPID public key from backend */
async function getVapidKey(): Promise<string | null> {
	try {
		const response = await fetch("/api/push/vapid-key");
		if (!response.ok) return null;
		const data = await response.json();
		return data.key || null;
	} catch {
		return null;
	}
}

/** Get auth header for API calls */
async function getAuthHeaders(): Promise<Record<string, string>> {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	if (!session?.access_token) throw new Error("Not authenticated");
	return {
		Authorization: `Bearer ${session.access_token}`,
		"Content-Type": "application/json",
	};
}

/**
 * Subscribe to push notifications.
 * 1. Requests browser permission
 * 2. Creates a push subscription via PushManager
 * 3. Sends the subscription to the backend
 */
export async function subscribeToPush(): Promise<boolean> {
	if (!isPushSupported()) return false;

	try {
		// Get VAPID key
		const vapidKey = await getVapidKey();
		if (!vapidKey) return false;

		// Request permission (triggers browser dialog if state is 'default')
		const permission = await Notification.requestPermission();
		if (permission !== "granted") return false;

		// Get service worker registration
		const registration = await navigator.serviceWorker.ready;

		// Convert VAPID key from base64url to Uint8Array
		const applicationServerKey = urlBase64ToUint8Array(vapidKey);

		// Subscribe via PushManager
		const subscription = await registration.pushManager.subscribe({
			userVisibleOnly: true,
			applicationServerKey,
		});

		// Send to backend
		const headers = await getAuthHeaders();
		const response = await fetch("/api/push/subscribe", {
			method: "POST",
			headers,
			body: JSON.stringify({ subscription: subscription.toJSON() }),
		});

		return response.ok;
	} catch (_err) {
		return false;
	}
}

/**
 * Unsubscribe from push notifications.
 */
export async function unsubscribeFromPush(): Promise<boolean> {
	try {
		const registration = await navigator.serviceWorker.ready;
		const subscription = await registration.pushManager.getSubscription();

		if (subscription) {
			const endpoint = subscription.endpoint;
			await subscription.unsubscribe();

			// Notify backend
			try {
				const headers = await getAuthHeaders();
				await fetch("/api/push/subscribe", {
					method: "DELETE",
					headers,
					body: JSON.stringify({ endpoint }),
				});
			} catch {
				// Backend cleanup failed — subscription still removed locally
			}
		}

		return true;
	} catch (_err) {
		return false;
	}
}

/** Convert a base64url-encoded string to a Uint8Array (for applicationServerKey) */
function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
	const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
	const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
	const rawData = atob(base64);
	const buffer = new ArrayBuffer(rawData.length);
	const outputArray = new Uint8Array(buffer);
	for (let i = 0; i < rawData.length; ++i) {
		outputArray[i] = rawData.charCodeAt(i);
	}
	return outputArray;
}
