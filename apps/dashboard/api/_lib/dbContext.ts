import type { SupabaseClient } from "@supabase/supabase-js";
import type { VercelRequest } from "@vercel/node";
import {
	createUserClient,
	getSupabase,
	getSupabaseAny,
	type TypedSupabaseClient,
} from "./supabase.js";

export type ApiAuthUser = {
	id: string;
	email?: string | undefined;
};

export type DbContext = {
	user: ApiAuthUser;
	userDb: TypedSupabaseClient;
	adminDb: TypedSupabaseClient;
	// biome-ignore lint/suspicious/noExplicitAny: explicit service-role escape hatch for deep Supabase typing
	adminDbAny: SupabaseClient<any>;
};

function bearerTokenFromRequest(req: VercelRequest): string {
	const authHeader = req.headers.authorization;
	if (!authHeader?.startsWith("Bearer ")) {
		throw new Error("Authenticated request is missing Bearer token");
	}
	return authHeader.slice(7);
}

export function createDbContext(
	req: VercelRequest,
	user: ApiAuthUser,
): DbContext {
	const accessToken = bearerTokenFromRequest(req);
	return {
		user,
		userDb: createUserClient(accessToken),
		adminDb: getSupabase(),
		adminDbAny: getSupabaseAny(),
	};
}
