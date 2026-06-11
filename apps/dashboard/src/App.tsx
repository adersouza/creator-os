import type React from "react";
import { useEffect, Suspense } from "react";
import {
	BrowserRouter,
	Routes,
	Route,
	Navigate,
	useLocation,
	Outlet,
} from "react-router-dom";
import { Toaster } from "sonner";
import { useWorkspaceInit } from "@/stores/useWorkspaceStore";
import { AuthCheckingFallback } from "@/components/skeletons/PageSkeletons";
import { GlobalErrorSurface } from "@/components/ui/GlobalErrorSurface";
import { SessionExpiryWatcher } from "@/components/ui/SessionExpiryWatcher";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import { useOnboardingState } from "@/hooks/useOnboardingState";
import { useLastRoute } from "@/hooks/useLastRoute";
import { useRoutePerformanceTelemetry } from "@/hooks/useRoutePerformanceTelemetry";
import { ErrorBoundary } from "./components/ui/ErrorBoundary";
import { warmHotRoutes } from "@/lib/warmRoutes";

import { AuthLayout } from "./components/layout/AuthLayout";
import {
	AuthCallback,
	InviteAccept,
	Landing,
	Layout,
	LegalPage,
	Login,
	OAuthCallback,
	protectedRedirects,
	protectedRoutes,
	ResetPassword,
	routeFallbackForPathname,
	SharedReport,
	Signup,
	Welcome,
} from "@/routes/appRoutes";
// Picks the skeleton that matches the page being lazy-loaded, so first-paint
// reflects the real layout instead of a generic Dashboard shape. Used both
// as the Suspense fallback for route chunk-loading AND as the placeholder
// while the protected-route auth check resolves — so the brief auth-check
// flash already shows the destination's shape.
function RouteAwareFallback() {
	const { pathname } = useLocation();
	return <>{routeFallbackForPathname(pathname)}</>;
}

/** Thin wrapper kept for the legal/auth-callback Suspense boundaries that
 *  sit inside AuthLayout's centered chrome — a full page skeleton looks
 *  out of place there, so they get the minimal shape. */
function PageLoader() {
	return <AuthCheckingFallback />;
}

function RouteBoundary({
	scope,
	children,
}: {
	scope: string;
	children: React.ReactNode;
}) {
	const location = useLocation();
	return (
		<ErrorBoundary key={`${scope}:${location.pathname}`} scope={scope}>
			{children}
		</ErrorBoundary>
	);
}

/**
 * Guards the app chrome behind a live Supabase session.
 * Unauthed visitors bounce to /login with the attempted path preserved
 * in location state so Login can send them back after sign-in.
 */
function ProtectedLayout() {
	const status = useAuthStatus({ checkMfa: true });
	const location = useLocation();
	useLastRoute();

	useEffect(() => {
		if (status !== "authed") return;
		// Idle-warm protected route chunks only after auth is known. Doing this
		// from main.tsx made unauthenticated /login redirects download operator
		// routes they could not render.
		warmHotRoutes();
	}, [status]);

	if (status === "checking") return <RouteAwareFallback />;
	if (status === "unauthed" || status === "mfa-pending") {
		return <Navigate to="/login" state={{ from: location }} replace />;
	}
	return (
		<Suspense fallback={<RouteAwareFallback />}>
			<Layout>
				<AuthGate>
					{/* Route-scoped ErrorBoundary — a crash on one page renders the
              fallback inside the chrome instead of nuking Sidebar + topbar.
              Keyed by pathname so navigating away auto-resets. */}
					<ErrorBoundary key={location.pathname}>
						<Outlet />
					</ErrorBoundary>
				</AuthGate>
			</Layout>
		</Suspense>
	);
}

/**
 * Soft-wall inside the protected shell.
 * 1. Onboarding incomplete + 0 accounts → /welcome (matches Dashboard's own redirect but covers every protected route)
 * 2. Trial expired + no paid subscription → /billing (except /billing itself and /settings/* where they can manage)
 */
function AuthGate({ children }: { children: React.ReactNode }) {
	const location = useLocation();
	// Delegated to `useOnboardingState` — a TanStack Query hook keyed on
	// `authUser.id` with 60s staleTime + auth-state invalidation. Previously
	// this component refetched user + two account-count queries on every
	// `location.pathname` change; switching to the shared hook deduplicates
	// with the Dashboard's own `useOnboardingState()` and eliminates 3
	// Supabase round-trips per in-app navigation.
	const onboarding = useOnboardingState();

	if (!onboarding.ready) return <RouteAwareFallback />;

	const onWelcome = location.pathname.startsWith("/welcome");
	const onBilling = location.pathname.startsWith("/billing");
	const onSettings = location.pathname.startsWith("/settings");
	const onLegal = location.pathname.startsWith("/legal");

	// Only force the wizard when the user has NEITHER a completion flag NOR any
	// connected accounts. Having accounts implies they walked the flow at least
	// once — we shouldn't re-prompt them even if the metadata write dropped.
	if (
		!onboarding.isOnboardingComplete &&
		!onboarding.hasConnectedAccounts &&
		!onWelcome
	) {
		return <Navigate to="/welcome" state={{ from: location }} replace />;
	}

	// Subscription gate is advisory: trial banner already warns (see Dashboard). We
	// only hard-wall when the user disconnected everything AND is past trial — the
	// banner handles the in-trial state without a forced redirect.
	void onBilling;
	void onSettings;
	void onLegal;

	return <>{children}</>;
}

function SessionRoute() {
	const status = useAuthStatus();
	const location = useLocation();

	if (status === "checking") return <RouteAwareFallback />;
	if (status === "unauthed") {
		return <Navigate to="/login" state={{ from: location }} replace />;
	}
	return <Outlet />;
}

/**
 * Inverse of ProtectedLayout: sends already-authed visitors straight to
 * the dashboard (or their pre-auth target) so they don't hit the
 * "sign in again after sign-up" footgun when revisiting /login or /signup.
 */
function PublicOnlyRoute() {
	const status = useAuthStatus({ checkMfa: true, mfaPendingStatus: "unauthed" });

	if (status === "checking") return <RouteAwareFallback />;
	if (status === "authed") {
		return <Navigate to="/dashboard" replace />;
	}
	return <Outlet />;
}

function NotFound() {
	const location = useLocation();
	return (
		<div className="flex flex-col items-center justify-center min-h-[60vh] text-center px-6">
			<h2 className="text-2xl font-medium tracking-[-0.02em] text-foreground mb-2">
				Page not found
			</h2>
			<p className="text-[0.8125rem] text-label-secondary mb-6 max-w-md">
				<code className="font-mono text-label-tertiary">
					{location.pathname}
				</code>{" "}
				doesn't exist.
			</p>
			<a
				href="/dashboard"
				className="h-9 px-4 rounded-md bg-primary text-primary-foreground text-[0.8125rem] font-semibold inline-flex items-center"
			>
				Back to Dashboard
			</a>
		</div>
	);
}

function AppContent() {
	useWorkspaceInit();
	useRoutePerformanceTelemetry();

	return (
		<>
			<Routes>
				{/* Marketing landing — no Layout chrome, own CSS + scripts */}
				<Route
					path="/"
					element={
						<Suspense fallback={null}>
							<Landing />
						</Suspense>
					}
				/>

				{/* Public shared reports — token-gated, no auth. Route-level so it's bookmarkable
            by anyone the sender shares the link with. */}
				<Route
					path="/share/:token"
					element={
						<RouteBoundary scope="shared-report">
							<Suspense fallback={<PageLoader />}>
								<SharedReport />
							</Suspense>
						</RouteBoundary>
					}
				/>

				<Route element={<AuthLayout />}>
					{/* Auth-callback and reset-password are exempt from PublicOnlyRoute:
              they must run even for authed sessions (OAuth exchange, password update). */}
					<Route
						path="/auth/callback"
						element={
							<Suspense fallback={<PageLoader />}>
								<AuthCallback />
							</Suspense>
						}
					/>
					<Route
						path="/auth/reset-password"
						element={
							<Suspense fallback={<PageLoader />}>
								<ResetPassword />
							</Suspense>
						}
					/>
					{/* Invite acceptance is exempt from PublicOnlyRoute so signed-in
              operators can click a colleague's invite link and add the
              workspace without signing out first. */}
					<Route
						path="/invite/:code"
						element={
							<Suspense fallback={<PageLoader />}>
								<InviteAccept />
							</Suspense>
						}
					/>
					<Route element={<PublicOnlyRoute />}>
						<Route
							path="/login"
							element={
								<Suspense fallback={<PageLoader />}>
									<Login />
								</Suspense>
							}
						/>
						<Route
							path="/signup"
							element={
								<Suspense fallback={<PageLoader />}>
									<Signup />
								</Suspense>
							}
						/>
					</Route>
				</Route>

				<Route element={<SessionRoute />}>
					<Route element={<AuthLayout />}>
						<Route
							path="/welcome"
							element={
								<Suspense fallback={<PageLoader />}>
									<Welcome />
								</Suspense>
							}
						/>
						<Route
							path="/auth/threads/callback"
							element={
								<Suspense fallback={<PageLoader />}>
									<OAuthCallback platform="threads" />
								</Suspense>
							}
						/>
						<Route
							path="/auth/instagram/callback"
							element={
								<Suspense fallback={<PageLoader />}>
									<OAuthCallback platform="instagram" />
								</Suspense>
							}
						/>
						<Route
							path="/auth/facebook/callback"
							element={
								<Suspense fallback={<PageLoader />}>
									<OAuthCallback platform="facebook" />
								</Suspense>
							}
						/>
					</Route>
				</Route>

				{/* Legal pages are public (no auth required) */}
				<Route
					element={
						<Suspense fallback={<PageLoader />}>
							<Outlet />
						</Suspense>
					}
				>
					<Route
						path="/privacy"
						element={
							<RouteBoundary scope="legal-privacy">
								<LegalPage type="privacy" />
							</RouteBoundary>
						}
					/>
					<Route
						path="/terms"
						element={
							<RouteBoundary scope="legal-terms">
								<LegalPage type="terms" />
							</RouteBoundary>
						}
					/>
					<Route
						path="/gdpr-deletion"
						element={
							<RouteBoundary scope="legal-gdpr-deletion">
								<LegalPage type="gdpr" />
							</RouteBoundary>
						}
					/>
				</Route>

				<Route element={<ProtectedLayout />}>
					{protectedRoutes.map((route) => (
						<Route key={route.path} path={route.path} element={route.element} />
					))}
					{protectedRedirects.map((route) => (
						<Route key={route.path} path={route.path} element={route.element} />
					))}
					<Route path="*" element={<NotFound />} />
				</Route>
			</Routes>
			<Toaster
				theme="system"
				position={
					typeof window !== "undefined" &&
					window.matchMedia("(max-width: 767px)").matches
						? "top-center"
						: "bottom-right"
				}
				expand
				mobileOffset={12}
				{...(typeof window !== "undefined" &&
				window.matchMedia("(max-width: 767px)").matches
					? { offset: 12 }
					: {})}
				toastOptions={{
					duration: 5000,
					style: {
						background: "var(--color-card)",
						color: "var(--color-foreground)",
						border: "1px solid var(--color-border)",
						boxShadow:
							"0 18px 56px color-mix(in_srgb,var(--color-foreground)_46%,transparent), inset 0 1px 0 color-mix(in_srgb,var(--color-card-elevated)_8%,transparent)",
						fontFamily: "var(--font-sans)",
					},
					classNames: {
						toast:
							"border border-border text-foreground flex gap-3 backdrop-blur-[20px]",
						error: "border-[var(--color-ring-oxblood-strong)]",
						success: "border-[rgba(63,107,82,0.28)]",
						warning: "border-[rgba(142,111,46,0.28)]",
						info: "border-border",
					},
				}}
			/>
			<GlobalErrorSurface />
			<SessionExpiryWatcher />
		</>
	);
}

export default function App() {
	return (
		<BrowserRouter>
			<AppContent />
		</BrowserRouter>
	);
}
