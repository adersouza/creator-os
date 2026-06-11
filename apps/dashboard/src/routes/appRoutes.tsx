import type { ReactNode } from "react";
import {
	AuthCallback,
	Billing,
	Dashboard,
	InviteAccept,
	Landing,
	Layout,
	LegalPage,
	Login,
	OAuthCallback,
	ResetPassword,
	SharedReport,
	Signup,
	Welcome,
	protectedRedirectElements,
	protectedRouteElements,
	routeFallbackForPathname,
} from "@/routes/routeRegistry";

export {
	AuthCallback,
	Billing,
	Dashboard,
	InviteAccept,
	Landing,
	Layout,
	LegalPage,
	Login,
	OAuthCallback,
	ResetPassword,
	SharedReport,
	Signup,
	Welcome,
	routeFallbackForPathname,
};

export type AppRoute = {
	path: string;
	element: ReactNode;
};

export const protectedRoutes: AppRoute[] = protectedRouteElements();
export const protectedRedirects: AppRoute[] = protectedRedirectElements();
