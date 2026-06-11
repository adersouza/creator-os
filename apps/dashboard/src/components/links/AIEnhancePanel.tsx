import { useEffect, useMemo, useState } from "react";
import { Check, Sparkles, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { MatrixLoader } from "@/components/ui/MatrixLoader";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import {
	enhanceLinkBlocks,
	type LinksEnhanceVariant,
} from "@/services/api/links";
import type { LinkItem } from "./types";

function smartLabel(item: LinkItem): string {
	const base = item.title.trim() || "Untitled block";
	if (/limited|drop|sale|launch/i.test(base)) return `Limited drop · ${base}`;
	if (/newsletter|email|subscribe/i.test(base)) return "Get the newsletter";
	if (/tip|coffee|support/i.test(base)) return "Tip jar · support the work";
	if (/book|call|session|calendar/i.test(base)) return "Book a session";
	if (/essay|post|article|read/i.test(base)) return `New essay · ${base}`;
	return base.length > 32 ? base : `${base} · open now`;
}

function localVariants(blocks: LinkItem[]): LinksEnhanceVariant[] {
	const relabeled = blocks.map((item) => ({
		...item,
		title: smartLabel(item),
	}));
	const reordered = [...blocks].sort((a, b) => b.clicks - a.clicks);
	const revenueFirst = [...blocks].sort((a, b) => {
		const score = (item: LinkItem) =>
			["tip_jar", "digital_product", "affiliate_catalog"].includes(
				String(item.blockType ?? ""),
			)
				? 1
				: 0;
		return score(b) - score(a);
	});
	return [
		{
			blocks: relabeled,
			reasoning:
				"Sharper labels improve scan speed and make each click intent explicit.",
		},
		{
			blocks: reordered,
			reasoning: "Highest observed click blocks move closer to the top.",
		},
		{
			blocks: revenueFirst,
			reasoning:
				"Monetization blocks are prioritized while keeping the existing page shape.",
		},
	];
}

export function AIEnhancePanel({
	open,
	linkId,
	blocks,
	onAccept,
	onClose,
}: {
	open: boolean;
	linkId: string;
	blocks: LinkItem[];
	onAccept: (blocks: LinkItem[]) => void;
	onClose: () => void;
}) {
	const fallbackVariants = useMemo(() => localVariants(blocks), [blocks]);
	const [variants, setVariants] =
		useState<LinksEnhanceVariant[]>(fallbackVariants);
	const [isLoading, setIsLoading] = useState(false);
	const [status, setStatus] = useState("Review suggested arrangements.");

	useEffect(() => {
		if (!open) return;
		let cancelled = false;
		setVariants(fallbackVariants);
		setStatus("Review suggested arrangements.");
		setIsLoading(true);
		enhanceLinkBlocks({ linkId, blocks })
			.then((result) => {
				if (cancelled) return;
				if (result?.variants?.length) {
					setVariants(result.variants.slice(0, 3));
					setStatus("Live AI suggestions are ready.");
				}
			})
			.catch((error) => {
				if (cancelled) return;
				setStatus(
					error instanceof Error
						? `Using local fallback: ${error.message}`
						: "Using local fallback.",
				);
			})
			.finally(() => {
				if (!cancelled) setIsLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, [blocks, fallbackVariants, linkId, open]);

	useEffect(() => {
		if (!open) return;
		const onKey = (event: KeyboardEvent) => {
			if (event.key === "Escape") onClose();
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [onClose, open]);

	if (!open) return null;

	return (
		<div
			className="fixed inset-0 z-[90]"
			role="dialog"
			aria-modal="true"
			aria-label="AI enhance link blocks"
		>
			<div
				aria-hidden="true"
				className="absolute inset-0 bg-[color-mix(in_srgb,var(--color-foreground)_38%,transparent)]"
				onClick={onClose}
			/>
			<aside className="absolute right-0 top-0 flex h-full w-full max-w-[420px] flex-col border-l border-border bg-card shadow-2xl">
						<header className="px-4 py-3 border-b border-border flex items-center justify-between gap-3">
							<div className="min-w-0">
								<div className="flex items-center gap-2 text-[0.875rem] font-semibold text-foreground">
									<Sparkles className="text-primary" aria-hidden="true" />
									AI Enhance
									{isLoading ? (
										<MatrixLoader
											label="Generating link variants"
											size="sm"
											className="ml-1"
										/>
									) : null}
								</div>
								<p className="mt-0.5 text-sm text-muted-foreground">
									{isLoading ? "Generating variants..." : status}
								</p>
							</div>
							<Button
								type="button"
								onClick={onClose}
								variant="outline"
								size="icon"
								aria-label="Close AI Enhance"
							>
								<X aria-hidden="true" />
							</Button>
						</header>

						<div className="flex flex-1 flex-col gap-3 overflow-auto p-4">
							{variants.slice(0, 3).map((variant, index) => (
								<NovaCard
									key={`variant-${index}`}
									variant="panel"
									contentClassName="p-3"
									title={`Variant ${index + 1}`}
									description={variant.reasoning}
									action={
										<Button
											type="button"
											size="sm"
											onClick={() => {
												onAccept(variant.blocks);
												onClose();
											}}
											className="gap-1.5"
										>
											<Check data-icon="inline-start" aria-hidden="true" />
											Accept
										</Button>
									}
								>
									<div className="flex flex-col gap-1.5">
										{variant.blocks.slice(0, 4).map((block, blockIndex) => (
											<div
												key={block.id}
												className="grid grid-cols-[22px_1fr] gap-2 text-[0.71875rem]"
											>
												<span className="text-muted-foreground tabular-nums">
													{blockIndex + 1}
												</span>
												<span className="truncate text-foreground">
													{block.title || "Untitled block"}
												</span>
											</div>
										))}
									</div>
								</NovaCard>
							))}
						</div>
			</aside>
		</div>
	);
}
