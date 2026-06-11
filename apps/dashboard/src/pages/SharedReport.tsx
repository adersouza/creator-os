import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, ExternalLink, FileText, LockKeyhole } from "lucide-react";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
	NovaCard,
	NovaEmpty,
	NovaSection,
	NovaStat,
} from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { Sigil33 } from "@/components/ui/Sigil33";
import { supabase } from "@/services/supabase";

interface SharedReportRow {
	share_token: string;
	expires_at: string | null;
	view_count: number;
	report_data: unknown;
}

type State =
	| { kind: "loading" }
	| { kind: "not_found" }
	| { kind: "expired" }
	| { kind: "ready"; report: SharedReportRow };

/**
 * Public read-only view of a shared report. No auth — gated entirely by
 * knowledge of the token. Tokens are opaque, single-purpose, and revocable.
 *
 * Backend contract in this repo:
 *   - shared_reports.share_token TEXT
 *   - shared_reports.report_data JSON snapshot payload
 *   - shared_reports.expires_at TIMESTAMP
 *   - shared_reports.view_count INTEGER
 */
export function SharedReport() {
	const { token } = useParams<{ token: string }>();
	const [state, setState] = useState<State>({ kind: "loading" });

	useEffect(() => {
		if (!token) {
			setState({ kind: "not_found" });
			return;
		}

		(async () => {
			try {
				const { data, error } = await supabase
					.from("shared_reports")
					.select("share_token, expires_at, view_count, report_data")
					.eq("share_token", token)
					.maybeSingle();

				if (error || !data) {
					setState({ kind: "not_found" });
					return;
				}

				if (
					data.expires_at &&
					new Date(data.expires_at).getTime() < Date.now()
				) {
					setState({ kind: "expired" });
					return;
				}

				// Best-effort view count bump — RLS on the table should allow anon updates
				// only on this specific column; if it fails, the view still renders.
				void supabase
					.from("shared_reports")
					.update({ view_count: (data.view_count ?? 0) + 1 })
					.eq("share_token", token);

				setState({ kind: "ready", report: data as SharedReportRow });
			} catch {
				setState({ kind: "not_found" });
			}
		})();
	}, [token]);

	return (
		<div className="min-h-[100dvh] w-full bg-background text-foreground">
			<header className="border-b border-border">
				<div className="mx-auto flex h-14 w-full max-w-[1200px] items-center justify-between gap-4 px-4 sm:px-6 md:px-10">
					<Link
						to="/"
						className="inline-flex min-h-10 items-center gap-2.5 rounded-md text-foreground outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]"
					>
						<Sigil33 size={22} />
						<span className="text-[0.9375rem] font-medium tracking-[-0.01em]">
							Juno33
						</span>
					</Link>
					<Badge tone="outline" className="hidden sm:inline-flex">
						Shared report · read-only
					</Badge>
				</div>
			</header>

			<main>
				{state.kind === "loading" && <LoadingState />}
				{state.kind === "not_found" && (
					<MessageState
						title="Link not found"
						description="This share link doesn't exist or was never created."
					/>
				)}
				{state.kind === "expired" && (
					<MessageState
						title="Link expired"
						description="The share window for this report has passed. Ask the sender for a fresh link."
					/>
				)}
				{state.kind === "ready" && <ReadyReport report={state.report} />}
			</main>

			<footer className="mx-auto w-full max-w-[1200px] px-4 pb-10 text-sm text-muted-foreground sm:px-6 md:px-10">
				Powered by Juno33 ·{" "}
				<Link
					className="underline decoration-dotted underline-offset-4 hover:text-foreground"
					to="/"
				>
					juno33.com
				</Link>
			</footer>
		</div>
	);
}

function LoadingState() {
	return (
		<NovaScreen width="narrow">
			<NovaCard
				title="Loading report"
				description="Preparing the shared snapshot."
			>
				<div className="flex flex-col gap-3">
					<Skeleton className="h-8 w-2/3" />
					<Skeleton className="h-4 w-full" />
					<Skeleton className="h-4 w-4/5" />
					<div className="grid gap-3 pt-3 sm:grid-cols-4">
						{Array.from({ length: 4 }).map((_, index) => (
							<Skeleton key={index} className="h-24" />
						))}
					</div>
				</div>
			</NovaCard>
		</NovaScreen>
	);
}

function MessageState({
	title,
	description,
}: {
	title: string;
	description: string;
}) {
	return (
		<NovaScreen width="narrow">
			<NovaEmpty
				className="min-h-[22rem]"
				icon={<LockKeyhole data-icon aria-hidden="true" />}
				title={title}
				description={description}
			>
				<div className="flex flex-col items-center gap-3">
					<Badge tone="oxblood">Juno33 Share</Badge>
					<Button asChild>
						<Link to="/">
							<ArrowLeft data-icon="inline-start" aria-hidden="true" />
							Back to juno33.com
						</Link>
					</Button>
				</div>
			</NovaEmpty>
		</NovaScreen>
	);
}

function ReadyReport({ report }: { report: SharedReportRow }) {
	const snapshot = report.report_data as {
		name?: string | undefined;
		headline?: string | undefined;
		description?: string | undefined;
		stats?: { label: string; value: string }[] | undefined;
	} | null;

	return (
		<NovaScreen width="narrow">
			<article className="flex flex-col gap-6">
				<NovaCard
					variant="hero"
					eyebrow="Shared report"
					title={snapshot?.name || snapshot?.headline || "Untitled report"}
					description={snapshot?.description}
					action={<Badge tone="outline">Read-only snapshot</Badge>}
				>
					<div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
						<FileText aria-hidden="true" />
						<span>Numbers reflect the moment this report was generated.</span>
					</div>
				</NovaCard>

				{snapshot?.stats && snapshot.stats.length > 0 && (
					<NovaSection className="grid grid-cols-2 md:grid-cols-4 gap-3">
						{snapshot.stats.map((s) => (
							<NovaStat
								key={s.label}
								label={s.label}
								value={s.value}
								variant="compact"
							/>
						))}
					</NovaSection>
				)}

				<NovaCard
					title="Snapshot details"
					description="Contact the sender for a live workspace view."
					action={
						<Button variant="outline" size="sm" asChild>
							<Link to="/">
								Visit Juno33
								<ExternalLink data-icon="inline-end" aria-hidden="true" />
							</Link>
						</Button>
					}
				>
					<p className="text-sm leading-relaxed text-muted-foreground">
						Viewed {report.view_count + 1}{" "}
						{report.view_count + 1 === 1 ? "time" : "times"}
						{report.expires_at
							? ` · Expires ${new Date(report.expires_at).toLocaleDateString()}`
							: ""}
					</p>
				</NovaCard>
			</article>
		</NovaScreen>
	);
}
