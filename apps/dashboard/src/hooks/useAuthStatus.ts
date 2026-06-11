import { useEffect, useState } from "react";
import { supabase, supabaseAuth } from "@/services/supabase";

export type AuthStatus = "checking" | "authed" | "unauthed" | "mfa-pending";

type UseAuthStatusOptions = {
	checkMfa?: boolean | undefined;
	mfaPendingStatus?: AuthStatus | undefined;
};

export function useAuthStatus({
	checkMfa = false,
	mfaPendingStatus = "mfa-pending",
}: UseAuthStatusOptions = {}): AuthStatus {
	const [status, setStatus] = useState<AuthStatus>("checking");

	useEffect(() => {
		let cancelled = false;
		const resolve = async (session: unknown) => {
			if (cancelled) return;
			if (!session) {
				setStatus("unauthed");
				return;
			}
			if (!checkMfa) {
				setStatus("authed");
				return;
			}
			const mfa = await supabaseAuth.getMfaStatus();
			if (cancelled) return;
			setStatus(mfa.needsMfa ? mfaPendingStatus : "authed");
		};

		supabaseAuth
			.getSession()
			.then(resolve)
			.catch(() => {
				if (!cancelled) setStatus("unauthed");
			});
		const {
			data: { subscription },
		} = supabase.auth.onAuthStateChange((_event, session) => resolve(session));

		return () => {
			cancelled = true;
			subscription.unsubscribe();
		};
	}, [checkMfa, mfaPendingStatus]);

	return status;
}
