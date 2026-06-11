import type React from "react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
	ArrowLeft,
	Mail,
	FileText,
	Shield,
	Scale,
	Database,
	ExternalLink,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { cn } from "@/lib/utils";

type LegalType = "privacy" | "terms" | "gdpr";

interface Section {
	id: string;
	title: string;
	body: React.ReactNode;
}

interface LegalDoc {
	title: string;
	lead: string;
	updated: string;
	Icon: typeof Shield;
	sections: Section[];
}

const EFFECTIVE_DATE = "April 15, 2026";
const CONTACT_EMAIL = "privacy@juno33.com";
const LEGAL_CONTACT_EMAIL = "legal@juno33.com";

/* ============================================================================
   Privacy
   ========================================================================= */

const PRIVACY: LegalDoc = {
	title: "Privacy policy",
	lead: "How Juno33 collects, uses, stores, and protects data for operators managing brand accounts on Meta platforms.",
	updated: EFFECTIVE_DATE,
	Icon: Shield,
	sections: [
		{
			id: "overview",
			title: "Overview",
			body: (
				<>
					<p>
						Juno33 is a scheduling and analytics tool for operators managing
						Threads and Instagram accounts. This policy describes what we
						collect, why, how long we keep it, and your rights over it.
					</p>
					<p>
						We are the data controller for your account information and the data
						processor for the social content you publish through the platform.
					</p>
				</>
			),
		},
		{
			id: "what-we-collect",
			title: "What we collect",
			body: (
				<>
					<ul>
						<li>
							<strong>Account details</strong> — name, email, and authentication
							identifier from your signup provider.
						</li>
						<li>
							<strong>Connected platforms</strong> — OAuth tokens issued by Meta
							(Threads, Instagram) and Stripe. Tokens are stored with envelope
							encryption and never exposed to clients.
						</li>
						<li>
							<strong>Post content</strong> — captions, media, scheduling
							metadata you create inside the Composer and Scheduler.
						</li>
						<li>
							<strong>Performance metrics</strong> — engagement, reach,
							impressions, and delivery logs returned by Meta's Graph API for
							accounts you own.
						</li>
						<li>
							<strong>Product analytics</strong> — anonymized feature usage
							(which pages you visit, which buttons you click) for product
							improvement.
						</li>
					</ul>
				</>
			),
		},
		{
			id: "how-we-use",
			title: "How we use it",
			body: (
				<>
					<p>We use the data above to:</p>
					<ul>
						<li>Authenticate you and keep you signed in.</li>
						<li>
							Publish the posts you schedule, to the accounts you've connected.
						</li>
						<li>Show you accurate analytics for those accounts.</li>
						<li>
							Detect abusive patterns (rate-limit violations, spam,
							impersonation).
						</li>
						<li>
							Send you operational emails — digest, failures, security alerts.
						</li>
					</ul>
					<p>
						We do not sell your data, do not train public ML models on your
						content, and do not share identifying data with advertisers.
					</p>
				</>
			),
		},
		{
			id: "retention",
			title: "Data retention",
			body: (
				<>
					<p>
						Active-account data is retained for the life of your subscription.
						On account deletion, personally-identifiable data is purged within
						30 days; aggregated anonymous metrics may be retained indefinitely
						for product analytics.
					</p>
					<p>
						Meta Platform data (posts, engagement) is deleted immediately on
						disconnect, in compliance with Meta's Platform Terms and our Meta
						Deletion Callback integration.
					</p>
				</>
			),
		},
		{
			id: "security",
			title: "Security",
			body: (
				<>
					<ul>
						<li>All traffic is encrypted in transit (TLS 1.3).</li>
						<li>
							OAuth tokens and secrets are encrypted at rest using envelope
							encryption with AWS KMS-managed data keys.
						</li>
						<li>
							Access to production infrastructure is restricted to authorized
							engineers and logged.
						</li>
						<li>
							Row-level security is enforced at the database layer, so workspace
							data can only be read by users belonging to that workspace.
						</li>
					</ul>
				</>
			),
		},
		{
			id: "rights",
			title: "Your rights",
			body: (
				<>
					<p>You can, at any time:</p>
					<ul>
						<li>
							Download a full export of your workspace data (Settings → Data &
							privacy).
						</li>
						<li>Disconnect any platform — tokens are destroyed immediately.</li>
						<li>
							Delete your workspace, triggering the 30-day purge pipeline.
						</li>
						<li>
							Contact us at{" "}
							<a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a> with
							questions about how your data is processed.
						</li>
					</ul>
					<p>
						EU residents have additional rights under GDPR — see the{" "}
						<Link
							to="/gdpr-deletion"
							className="text-primary underline underline-offset-4"
						>
							GDPR addendum
						</Link>
						.
					</p>
				</>
			),
		},
		{
			id: "contact",
			title: "Contact",
			body: (
				<p>
					Questions or requests related to privacy:{" "}
					<a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. We respond
					within 5 business days.
				</p>
			),
		},
	],
};

/* ============================================================================
   Terms
   ========================================================================= */

const TERMS: LegalDoc = {
	title: "Terms of service",
	lead: "The contract between you and Juno33 when you use the product.",
	updated: EFFECTIVE_DATE,
	Icon: Scale,
	sections: [
		{
			id: "acceptance",
			title: "Acceptance",
			body: (
				<p>
					By creating an account or using Juno33, you agree to these terms. If
					you're using Juno33 on behalf of an organization, you represent that
					you have authority to bind that organization.
				</p>
			),
		},
		{
			id: "the-service",
			title: "The service",
			body: (
				<p>
					Juno33 provides a web application for scheduling, publishing, and
					analyzing content across Meta-owned platforms (Threads, Instagram) and
					other integrations we may add. Access is governed by the plan you've
					subscribed to, documented in Settings → Billing.
				</p>
			),
		},
		{
			id: "your-content",
			title: "Your content",
			body: (
				<>
					<p>
						You retain full ownership of the content you publish through Juno33.
						You grant us a limited, non-exclusive license to store, process,
						transmit, and display your content only as necessary to operate the
						service on your behalf.
					</p>
					<p>
						You are responsible for the accounts you connect and the content you
						publish. You represent that you have the rights to those accounts
						and that your content complies with the terms of each underlying
						platform (Meta, Stripe, etc.).
					</p>
				</>
			),
		},
		{
			id: "acceptable-use",
			title: "Acceptable use",
			body: (
				<>
					<p>You agree not to:</p>
					<ul>
						<li>
							Use Juno33 to impersonate a person or entity without
							authorization.
						</li>
						<li>
							Publish content that is illegal, that targets minors sexually, or
							that contains material you do not have the right to distribute.
						</li>
						<li>
							Attempt to circumvent platform rate limits or detection systems.
						</li>
						<li>
							Reverse-engineer, resell, or redistribute the Juno33 service
							except where permitted by your subscription tier.
						</li>
						<li>
							Use Juno33 to operate schemes that violate Meta's Platform Terms
							or Community Guidelines.
						</li>
					</ul>
					<p>
						We reserve the right to suspend accounts that violate these rules,
						with or without notice, depending on severity.
					</p>
				</>
			),
		},
		{
			id: "payment",
			title: "Payment and trials",
			body: (
				<>
					<p>
						Paid plans are billed monthly or annually through Stripe. Trials
						auto-convert to paid at the end of the trial period unless canceled.
						Refunds are issued at our discretion for service outages we're
						responsible for.
					</p>
					<p>
						Price changes require 30 days' written notice sent to your account
						email.
					</p>
				</>
			),
		},
		{
			id: "termination",
			title: "Termination",
			body: (
				<>
					<p>
						You may cancel at any time from Settings → Billing. On cancellation,
						your workspace remains read-only until the end of the paid period,
						after which the 30-day deletion pipeline begins.
					</p>
					<p>
						We may terminate accounts for non-payment (after notice), for
						violation of these terms, or when required by law or a connected
						platform's policies.
					</p>
				</>
			),
		},
		{
			id: "warranty",
			title: "Warranty and liability",
			body: (
				<>
					<p>
						Juno33 is provided "as is." We aim for 99.9% uptime but do not
						guarantee uninterrupted access, and we're not liable for
						content-delivery outages at third-party platforms (Meta, Stripe)
						that affect publishing.
					</p>
					<p>
						Our aggregate liability for any claim is capped at the fees you paid
						to us in the twelve months preceding the claim.
					</p>
				</>
			),
		},
		{
			id: "changes",
			title: "Changes to these terms",
			body: (
				<p>
					We may update these terms as the product evolves. Material changes
					will be announced in the app and by email at least 30 days before they
					take effect. Continued use after that period constitutes acceptance.
				</p>
			),
		},
		{
			id: "contact",
			title: "Contact",
			body: (
				<p>
					Questions about these terms:{" "}
					<a href={`mailto:${LEGAL_CONTACT_EMAIL}`}>{LEGAL_CONTACT_EMAIL}</a>.
				</p>
			),
		},
	],
};

/* ============================================================================
   GDPR
   ========================================================================= */

const GDPR: LegalDoc = {
	title: "GDPR & data rights",
	lead: "Your rights over your data under GDPR and how to exercise them.",
	updated: EFFECTIVE_DATE,
	Icon: Database,
	sections: [
		{
			id: "scope",
			title: "Who this applies to",
			body: (
				<p>
					This addendum applies to anyone in the European Economic Area, the
					United Kingdom, or Switzerland. It supplements — not replaces — our{" "}
					<Link
						to="/privacy"
						className="text-primary underline underline-offset-4"
					>
						Privacy Policy
					</Link>
					. If you're outside these regions you still have access rights under
					our Privacy Policy; this document describes your additional statutory
					rights.
				</p>
			),
		},
		{
			id: "your-rights",
			title: "Your rights",
			body: (
				<>
					<ul>
						<li>
							<strong>Access</strong> — request a copy of the personal data we
							hold about you.
						</li>
						<li>
							<strong>Rectification</strong> — correct inaccurate data.
						</li>
						<li>
							<strong>Erasure</strong> — request deletion, subject to our legal
							retention obligations.
						</li>
						<li>
							<strong>Restriction</strong> — ask us to stop processing while a
							dispute is resolved.
						</li>
						<li>
							<strong>Portability</strong> — receive your data in a
							machine-readable format.
						</li>
						<li>
							<strong>Objection</strong> — object to processing based on
							legitimate interest.
						</li>
						<li>
							<strong>Withdrawal of consent</strong> — where processing is
							consent-based.
						</li>
					</ul>
				</>
			),
		},
		{
			id: "exercise",
			title: "How to exercise them",
			body: (
				<>
					<p>The fastest route is in-app:</p>
					<ul>
						<li>
							<strong>Export</strong> — Settings → Data & privacy → Export
							workspace.
						</li>
						<li>
							<strong>Delete</strong> — Settings → Danger zone → Delete
							workspace.
						</li>
						<li>
							<strong>Disconnect</strong> — Settings → Connections → Configure →
							Disconnect.
						</li>
					</ul>
					<p>
						For requests you can't complete in-app, email{" "}
						<a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a> from the
						address on file. We respond within 30 days per GDPR Article 12.
					</p>
				</>
			),
		},
		{
			id: "processors",
			title: "Sub-processors",
			body: (
				<>
					<p>We rely on these sub-processors to deliver Juno33:</p>
					<ul>
						<li>
							<strong>Supabase</strong> — database, authentication, file storage
							(EU region).
						</li>
						<li>
							<strong>Vercel</strong> — application hosting and CDN.
						</li>
						<li>
							<strong>Stripe</strong> — payment processing; see Stripe's own
							DPA.
						</li>
						<li>
							<strong>AWS KMS</strong> — key management for envelope encryption.
						</li>
						<li>
							<strong>Meta</strong> — Threads and Instagram Graph APIs;
							publishing and metrics.
						</li>
					</ul>
				</>
			),
		},
		{
			id: "meta-deletion",
			title: "Meta Platform deletion",
			body: (
				<p>
					When a user requests deletion through Meta's Platform Deletion
					Callback, we purge their associated data within the required 30-day
					window and return a confirmation code. This endpoint is publicly
					documented at{" "}
					<a
						href="https://juno33.com/api/meta/data-deletion"
						className="text-primary underline underline-offset-4"
					>
						juno33.com/api/meta/data-deletion
					</a>
					.
				</p>
			),
		},
		{
			id: "complaints",
			title: "Complaints",
			body: (
				<p>
					If you believe we've mishandled your data, please reach out to us
					first at <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. You
					also have the right to lodge a complaint with your local
					data-protection authority.
				</p>
			),
		},
	],
};

const DOCS: Record<LegalType, LegalDoc> = {
	privacy: PRIVACY,
	terms: TERMS,
	gdpr: GDPR,
};

/* ============================================================================
   Shared shell
   ========================================================================= */

const DOC_NAV: {
	type: LegalType;
	label: string;
	to: string;
	Icon: typeof Shield;
}[] = [
	{ type: "privacy", label: "Privacy", to: "/privacy", Icon: Shield },
	{ type: "terms", label: "Terms", to: "/terms", Icon: Scale },
	{ type: "gdpr", label: "GDPR", to: "/gdpr-deletion", Icon: Database },
];

export function LegalPage({ type }: { type: LegalType }) {
	const doc = DOCS[type];
	const [activeId, setActiveId] = useState(doc.sections[0]?.id ?? "");
	const observerRef = useRef<IntersectionObserver | null>(null);

	useEffect(() => {
		setActiveId(doc.sections[0]?.id ?? "");
		window.scrollTo({ top: 0, behavior: "instant" });
	}, [doc.sections]);

	useEffect(() => {
		if (observerRef.current) observerRef.current.disconnect();
		const observer = new IntersectionObserver(
			(entries) => {
				const visible = entries
					.filter((e) => e.isIntersecting)
					.sort(
						(a, b) => a.boundingClientRect.top - b.boundingClientRect.top,
					)[0];
				if (visible) setActiveId(visible.target.id);
			},
			{ rootMargin: "-96px 0px -70% 0px", threshold: [0, 1] },
		);
		observerRef.current = observer;
		doc.sections.forEach((s) => {
			const el = document.getElementById(`sec-${s.id}`);
			if (el) observer.observe(el);
		});
		return () => observer.disconnect();
	}, [doc.sections]);

	const scrollTo = (id: string) => {
		const el = document.getElementById(`sec-${id}`);
		if (el) {
			const y = el.getBoundingClientRect().top + window.scrollY - 80;
			window.scrollTo({ top: y, behavior: "smooth" });
		}
	};

	return (
		<div className=" min-h-[100dvh] bg-background text-foreground">
			{/* Top bar — subtle, persistent doc switcher */}
			<header className="sticky top-0 z-30 h-12 border-b border-border bg-background/90 backdrop-blur-[16px] saturate-150">
				<div className="mx-auto flex h-full max-w-6xl items-center justify-between gap-4 px-4 md:px-6">
					<Link
						to="/"
						className="inline-flex items-center gap-1.5 text-[0.78125rem] text-muted-foreground hover:text-foreground transition-colors"
					>
						<ArrowLeft className="w-3.5 h-3.5" />
						Back to Juno33
					</Link>
					<nav className="flex items-center gap-1 overflow-x-auto hide-scrollbar">
						{DOC_NAV.map((d) => {
							const active = d.type === type;
							return (
								<Link
									key={d.type}
									to={d.to}
									aria-current={active ? "page" : undefined}
									className={cn(
										"inline-flex shrink-0 items-center gap-1.5 h-8 px-2.5 rounded-md text-[0.71875rem] font-medium transition-colors",
										"outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]",
										active
											? "bg-muted text-foreground"
											: "text-muted-foreground hover:text-foreground hover:bg-muted",
									)}
								>
									<d.Icon className="w-3 h-3" aria-hidden="true" />
									{d.label}
								</Link>
							);
						})}
					</nav>
				</div>
			</header>

			<div className="mx-auto grid max-w-6xl grid-cols-1 gap-10 px-4 py-10 md:px-6 md:py-14 lg:grid-cols-[220px_1fr] lg:gap-14">
				{/* TOC (desktop, sticky) */}
				<aside className="hidden lg:block">
					<div className="sticky top-20">
						<div className="text-[0.625rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground mb-3">
							On this page
						</div>
						<nav className="flex flex-col gap-0.5">
							{doc.sections.map((s) => {
								const active = activeId === s.id;
								return (
									<Button
										key={s.id}
										type="button"
										variant="ghost"
										size="sm"
										onClick={() => scrollTo(s.id)}
										className={cn(
											"relative h-auto justify-start text-left text-[0.75rem] leading-[1.5] pl-3 pr-2 py-1.5 rounded-sm transition-colors",
											"outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]",
											active
												? "text-foreground font-medium"
												: "text-muted-foreground hover:text-muted-foreground",
										)}
									>
										{active && (
											<span
												className="absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-r-full"
												style={{ backgroundColor: "var(--color-oxblood)" }}
											/>
										)}
										{s.title}
									</Button>
								);
							})}
						</nav>

						<div className="mt-8 pt-6 border-t border-border">
							<a
								href={`mailto:${CONTACT_EMAIL}`}
								className="inline-flex items-center gap-1.5 text-[0.71875rem] font-medium text-muted-foreground hover:text-foreground transition-colors"
							>
								<Mail className="w-3 h-3" />
								{CONTACT_EMAIL}
							</a>
						</div>
					</div>
				</aside>

				{/* Main content */}
				<main>
					<NovaCard contentClassName="px-5 py-6 md:px-8 md:py-8">
						{/* Hero */}
						<div className="mb-10">
							<div className="flex items-center gap-2 text-[0.6875rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground mb-3">
								<span
									className="w-1.5 h-1.5 rounded-full"
									style={{ backgroundColor: "var(--color-oxblood)" }}
								/>
								Legal · Last updated {doc.updated}
							</div>
							<h1
								className="text-[2.375rem] md:text-[2.75rem] font-medium leading-[1.05] tracking-[-0.035em] text-foreground"
								style={{
									textWrap: "balance" as React.CSSProperties["textWrap"],
								}}
							>
								{doc.title}
							</h1>
							<p className="mt-3 text-[0.9375rem] text-muted-foreground leading-[1.55] max-w-[60ch]">
								{doc.lead}
							</p>

							{/* Mobile TOC + quick actions */}
							<div className="lg:hidden mt-6">
								<MobileTOC
									sections={doc.sections}
									activeId={activeId}
									onSelect={scrollTo}
								/>
							</div>
						</div>

						{/* Sections */}
						<article className="flex flex-col gap-10 [&_a]:text-primary [&_a]:underline [&_a]:underline-offset-4 [&_a:hover]:decoration-2 [&_strong]:font-medium [&_strong]:text-foreground [&_ul]:m-0 [&_ul]:flex [&_ul]:list-none [&_ul]:flex-col [&_ul]:gap-2.5 [&_ul]:p-0 [&_li]:relative [&_li]:pl-5 [&_li]:before:absolute [&_li]:before:left-1 [&_li]:before:top-3 [&_li]:before:h-px [&_li]:before:w-1.5 [&_li]:before:bg-muted-foreground">
							{doc.sections.map((s, i) => (
								<section key={s.id} id={`sec-${s.id}`} className="scroll-mt-24">
									<h2 className="flex items-baseline gap-3 text-[1.1875rem] font-medium text-foreground tracking-[-0.015em] mb-3">
										<span className="font-mono text-[0.71875rem] text-muted-foreground pt-[5px] tabular-nums">
											{String(i + 1).padStart(2, "0")}
										</span>
										{s.title}
									</h2>
									<div className="flex max-w-[65ch] flex-col gap-3 text-[0.875rem] text-muted-foreground leading-[1.65]">
										{s.body}
									</div>
								</section>
							))}
						</article>

						{/* Footer — cross-doc links + contact */}
						<footer className="mt-16 pt-8 border-t border-border flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
							<div className="flex flex-wrap items-center gap-3 text-[0.75rem] text-muted-foreground">
								<FileText className="w-3.5 h-3.5" />
								<span>Related:</span>
								{DOC_NAV.filter((d) => d.type !== type).map((d) => (
									<Link
										key={d.type}
										to={d.to}
										className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors"
									>
										{d.label}
										<ExternalLink className="w-2.5 h-2.5" />
									</Link>
								))}
							</div>
							<a
								href={`mailto:${CONTACT_EMAIL}`}
								className="inline-flex items-center gap-1.5 text-[0.75rem] font-medium"
								style={{ color: "var(--color-oxblood)" }}
							>
								<Mail className="w-3.5 h-3.5" />
								{CONTACT_EMAIL}
							</a>
						</footer>
					</NovaCard>
				</main>
			</div>
		</div>
	);
}

/* ---------- Mobile TOC (<lg>) ---------- */

function MobileTOC({
	sections,
	activeId,
	onSelect,
}: {
	sections: Section[];
	activeId: string;
	onSelect: (id: string) => void;
}) {
	const [open, setOpen] = useState(false);
	return (
		<NovaCard contentClassName="p-3">
			<Button
				type="button"
				variant="ghost"
				size="sm"
				onClick={() => setOpen((v) => !v)}
				className={cn(
					"w-full flex items-center justify-between min-h-[44px] text-[0.6875rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground",
					"outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)] rounded-sm",
				)}
				aria-expanded={open}
				aria-controls="legal-mobile-toc"
			>
				On this page · {sections.length} sections
				<span
					className={cn(
						"transition-transform duration-200",
						open ? "rotate-180" : "",
					)}
					aria-hidden="true"
				>
					▾
				</span>
			</Button>
			{open && (
				<nav
					id="legal-mobile-toc"
					className="flex flex-col gap-0.5 mt-3 pt-3 border-t border-border"
				>
					{sections.map((s, i) => {
						const active = activeId === s.id;
						return (
							<Button
								key={s.id}
								type="button"
								variant="ghost"
								size="sm"
								onClick={() => {
									onSelect(s.id);
									setOpen(false);
								}}
								className={cn(
									"h-auto flex items-baseline justify-start gap-2 text-left text-[0.8125rem] min-h-[44px] py-2 px-2.5 rounded-md transition-colors",
									"outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]",
									active
										? "bg-muted text-foreground font-medium"
										: "text-muted-foreground hover:text-foreground hover:bg-muted/50",
								)}
							>
								<span className="font-mono text-[0.625rem] text-muted-foreground tabular-nums shrink-0 pt-[3px]">
									{String(i + 1).padStart(2, "0")}
								</span>
								{s.title}
							</Button>
						);
					})}
				</nav>
			)}
		</NovaCard>
	);
}
