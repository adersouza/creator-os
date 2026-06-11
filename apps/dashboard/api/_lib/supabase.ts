/**
 * Supabase Server Client for Vercel API Routes
 *
 * Uses service role key for admin operations.
 * Lazy initialization to avoid crashes at module load time.
 */

import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import "./envCheck.js"; // Validate required env vars on cold start
import type { Database } from "../../types/supabase.js";

export type TypedSupabaseClient = SupabaseClient<Database>;

let _supabaseAdmin: TypedSupabaseClient | null = null;

/**
 * Get the shared Supabase admin client (service role).
 * Lazily initialized on first call.
 * All API routes should use this instead of inline createClient().
 */
export function getSupabase(): TypedSupabaseClient {
	if (!_supabaseAdmin) {
		const supabaseUrl = process.env.SUPABASE_URL || "";
		const supabaseServiceKey =
			process.env.SUPABASE_SERVICE_ROLE_KEY ||
			process.env.SUPABASE_SERVICE_KEY ||
			"";

		_supabaseAdmin = createClient<Database>(supabaseUrl, supabaseServiceKey, {
			auth: {
				autoRefreshToken: false,
				persistSession: false,
			},
		});
	}
	return _supabaseAdmin;
}

/**
 * Get the shared Supabase admin client with loosened typing.
 * Used for extremely large files where the full Database type causes
 * 'Type instantiation is excessively deep' errors.
 */
// biome-ignore lint/suspicious/noExplicitAny: intentional escape hatch for deeply typed Supabase queries
export function getSupabaseAny(): SupabaseClient<any> {
	// biome-ignore lint/suspicious/noExplicitAny: intentional escape hatch for deeply typed Supabase queries
	return getSupabase() as any;
}

/**
 * Create a Supabase client for a specific user session
 */
export function createUserClient(accessToken: string): TypedSupabaseClient {
	const supabaseUrl = process.env.SUPABASE_URL || "";
	return createClient<Database>(
		supabaseUrl,
		process.env.SUPABASE_ANON_KEY || "",
		{
			global: {
				headers: {
					Authorization: `Bearer ${accessToken}`,
				},
			},
		},
	);
}
