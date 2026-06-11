import { Check, MoreHorizontal } from "lucide-react";
import type React from "react";
import { memo, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { PostStatusDot } from "@/components/ui/PostStatusDot";
import { cn } from "@/lib/utils";
import {
	formatCampaignFactoryAuditStatus,
	formatCampaignFactoryAudioStatus,
	formatCampaignFactoryScheduleMode,
	formatCampaignFactorySurface,
	campaignFactoryAudioAllowsLive,
} from "@/lib/campaignFactory";
import { badgeLabelFor, labelFor } from "@/lib/socialPlatform";
import {
	DAY_NAMES_LONG,
	DRAG_THRESHOLD,
	formatHour,
	HOLD_JITTER_TOLERANCE,
	HOVER_PREVIEW_DELAY_MS,
	LONG_PRESS_MS,
	type Post,
	STATUS_STYLE,
} from "./shared";

interface PostCardProps {
	post: Post;
	selected: boolean;
	onClick: (e: React.MouseEvent) => void;
	onDragMove: (x: number, y: number) => void;
	onDragEnd: (postId: string, moved: boolean) => void;
	onQuickMove?:
		| ((
				post: Post,
				action: "minus-hour" | "plus-hour" | "tomorrow" | "next-peak",
		  ) => void)
		| undefined;
	riskLabels?: string[] | undefined;
}

/* =========================================================================
   POST CARD — extracted from src/pages/Calendar.tsx verbatim.
   ========================================================================= */
function PostCardInner({
	post,
	selected,
	onClick,
	onDragMove,
	onDragEnd,
	onQuickMove,
	riskLabels = [],
}: PostCardProps) {
	const platformLabel = badgeLabelFor(post.platform);
	const campaignFactory = post.campaignFactory;
	const campaignFactorySurface = campaignFactory
		? formatCampaignFactorySurface(campaignFactory)
		: null;
	const campaignFactoryScheduleMode = campaignFactory
		? formatCampaignFactoryScheduleMode(campaignFactory)
		: null;
	const campaignFactoryAudioStatus = campaignFactory
		? formatCampaignFactoryAudioStatus(campaignFactory)
		: null;
	const campaignFactoryAudioReady = campaignFactory
		? campaignFactoryAudioAllowsLive(campaignFactory)
		: true;
	const [dragging, setDragging] = useState(false);
	const [lifted, setLifted] = useState(false);
	const [offset, setOffset] = useState({ x: 0, y: 0 });
	const [previewRect, setPreviewRect] = useState<DOMRect | null>(null);
	const [moveMenuRect, setMoveMenuRect] = useState<DOMRect | null>(null);

	const buttonRef = useRef<HTMLButtonElement | null>(null);
	const pointerRef = useRef<{
		startX: number;
		startY: number;
		pointerId: number;
		moved: boolean;
	} | null>(null);
	const holdTimerRef = useRef<number | null>(null);
	const hoverTimerRef = useRef<number | null>(null);
	const clickBlockTimerRef = useRef<number | null>(null);
	// Persists past pointerup to block the subsequent click event
	const wasDragRef = useRef(false);

	// Clear any dangling timers on unmount — drag/hover timers can outlive
	// fast unmounts during scheduler virtualization.
	useEffect(() => {
		return () => {
			if (holdTimerRef.current !== null)
				window.clearTimeout(holdTimerRef.current);
			if (hoverTimerRef.current !== null)
				window.clearTimeout(hoverTimerRef.current);
			if (clickBlockTimerRef.current !== null)
				window.clearTimeout(clickBlockTimerRef.current);
		};
	}, []);

	const closePreview = () => {
		if (hoverTimerRef.current !== null) {
			window.clearTimeout(hoverTimerRef.current);
			hoverTimerRef.current = null;
		}
		setPreviewRect(null);
	};

	const closeMoveMenu = () => setMoveMenuRect(null);

	const clearHoldTimer = () => {
		if (holdTimerRef.current !== null) {
			window.clearTimeout(holdTimerRef.current);
			holdTimerRef.current = null;
		}
	};

	const handlePointerDown = (e: React.PointerEvent<HTMLButtonElement>) => {
		// Skip secondary buttons (right-click, middle-click)
		if (e.button !== 0) return;
		e.currentTarget.setPointerCapture(e.pointerId);
		pointerRef.current = {
			startX: e.clientX,
			startY: e.clientY,
			pointerId: e.pointerId,
			moved: false,
		};
		// Close hover preview if open — it'd compete with drag visuals
		closePreview();
		// Start long-press timer — if user holds without moving, enter "lift" mode
		holdTimerRef.current = window.setTimeout(() => {
			setLifted(true);
			holdTimerRef.current = null;
		}, LONG_PRESS_MS);
	};

	const handleMouseEnter = () => {
		if (hoverTimerRef.current !== null)
			window.clearTimeout(hoverTimerRef.current);
		hoverTimerRef.current = window.setTimeout(() => {
			if (buttonRef.current && !dragging) {
				setPreviewRect(buttonRef.current.getBoundingClientRect());
			}
			hoverTimerRef.current = null;
		}, HOVER_PREVIEW_DELAY_MS);
	};

	const handleMouseLeave = () => {
		closePreview();
	};

	const handlePointerMove = (e: React.PointerEvent<HTMLButtonElement>) => {
		const p = pointerRef.current;
		if (!p || p.pointerId !== e.pointerId) return;
		const dx = e.clientX - p.startX;
		const dy = e.clientY - p.startY;
		const distance = Math.hypot(dx, dy);
		// Only cancel the hold timer on meaningful movement. Small jitter during
		// a still "hold" shouldn't kill the long-press intent.
		if (holdTimerRef.current !== null && distance > HOLD_JITTER_TOLERANCE) {
			clearHoldTimer();
		}
		if (!p.moved && distance > DRAG_THRESHOLD) {
			p.moved = true;
			setDragging(true);
		}
		if (p.moved) {
			setOffset({ x: dx, y: dy });
			onDragMove(e.clientX, e.clientY);
		}
	};

	const handlePointerUp = (e: React.PointerEvent<HTMLButtonElement>) => {
		const p = pointerRef.current;
		if (!p || p.pointerId !== e.pointerId) return;
		e.currentTarget.releasePointerCapture(e.pointerId);
		const wasDrag = p.moved;
		pointerRef.current = null;
		clearHoldTimer();
		if (wasDrag) {
			// Tell parent to commit the drop BEFORE we reset visual state,
			// so the parent reads the latest drop target while still relevant.
			wasDragRef.current = true;
			onDragEnd(post.id, true);
			// Keep the click-block flag set briefly — the click event will
			// fire right after pointerup and we need wasDragRef truthy then.
			if (clickBlockTimerRef.current !== null)
				window.clearTimeout(clickBlockTimerRef.current);
			clickBlockTimerRef.current = window.setTimeout(() => {
				wasDragRef.current = false;
				clickBlockTimerRef.current = null;
			}, 0);
		}
		setDragging(false);
		setLifted(false);
		setOffset({ x: 0, y: 0 });
	};

	const handlePointerCancel = (_e: React.PointerEvent<HTMLButtonElement>) => {
		pointerRef.current = null;
		clearHoldTimer();
		setDragging(false);
		setLifted(false);
		setOffset({ x: 0, y: 0 });
		onDragEnd(post.id, false);
	};

	const handleClick = (e: React.MouseEvent) => {
		if (wasDragRef.current) {
			// Drag just finished — suppress the click that would otherwise open the slide-over.
			e.preventDefault();
			e.stopPropagation();
			return;
		}
		onClick(e);
	};

	const openMoveMenu = (e: React.MouseEvent | React.KeyboardEvent) => {
		if (!buttonRef.current || !onQuickMove) return;
		e.preventDefault();
		e.stopPropagation();
		closePreview();
		setMoveMenuRect(buttonRef.current.getBoundingClientRect());
	};

	return (
		<>
			<Button
				ref={buttonRef}
				type="button"
				variant="ghost"
				data-post-id={post.id}
				onClick={handleClick}
				onPointerDown={handlePointerDown}
				onPointerMove={handlePointerMove}
				onPointerUp={handlePointerUp}
				onPointerCancel={handlePointerCancel}
				onMouseEnter={handleMouseEnter}
				onMouseLeave={handleMouseLeave}
				onContextMenu={openMoveMenu}
				onKeyDown={(e) => {
					if (e.key.toLowerCase() === "m") openMoveMenu(e);
				}}
				aria-describedby={`post-card-help-${post.id}`}
				style={{
					transform: dragging
						? `translate(${offset.x}px, ${offset.y}px) scale(1.06)`
						: lifted
							? "scale(1.06)"
							: undefined,
					zIndex: dragging || lifted ? 20 : undefined,
					transition: dragging
						? "none"
						: "transform 200ms cubic-bezier(0.23, 1, 0.32, 1)",
					touchAction: "none",
					// Hide this element from hit-testing while dragging so elementFromPoint
					// returns the column/card underneath. setPointerCapture ensures we keep
					// receiving pointer events even with pointer-events:none.
					pointerEvents: dragging ? "none" : undefined,
				}}
				className={cn(
					"relative h-full w-full justify-start overflow-hidden rounded-md border bg-card py-1.5 pl-2.5 pr-2 text-left transition-[background-color,border-color,box-shadow] duration-200",
					selected
						? "cursor-grab border-primary bg-primary/5 shadow-[0_0_0_2px_color-mix(in_srgb,var(--color-oxblood)_20%,transparent)] active:cursor-grabbing"
						: dragging
							? "cursor-grabbing border-input shadow-xl"
							: lifted
								? "cursor-grab border-primary bg-primary/5 shadow-lg"
								: "cursor-grab border-border shadow-sm hover:border-input hover:bg-muted/45 hover:shadow-md active:cursor-grabbing",
				)}
			>
				{/* 2px group rail — matches landing blueprint .dash-nextup-row.accent pattern */}
				<span
					className="absolute left-0 top-1 bottom-1 w-[2px] rounded-full"
					style={{ backgroundColor: post.groupColor }}
					aria-hidden="true"
				/>
				{/* Top row: time + platform/status micro-indicators */}
				<div className="mb-0.5 flex items-center justify-between gap-1">
					<span
						className="font-mono text-[0.65625rem] font-medium tabular-nums leading-none"
						style={{ color: "var(--color-oxblood)" }}
					>
						{post.isUnscheduledDraft ? "Draft" : formatHour(post.hour, post.minute)}
					</span>
					<div className="flex items-center gap-1 flex-shrink-0">
						<span className="text-[0.5625rem] font-semibold text-muted-foreground tabular-nums uppercase tracking-[0.1em]">
							{platformLabel}
						</span>
						{campaignFactorySurface && (
							<Badge tone="oxblood" className="h-4 rounded px-1 py-0 text-[0.5rem]">
								{campaignFactorySurface}
							</Badge>
						)}
						{campaignFactoryScheduleMode && (
							<Badge tone="outline" className="h-4 rounded px-1 py-0 text-[0.5rem]">
								{campaignFactoryScheduleMode}
							</Badge>
						)}
						{campaignFactoryAudioStatus && (
							<Badge
								tone={campaignFactoryAudioReady ? "secondary" : "danger"}
								className="h-4 rounded px-1 py-0 text-[0.5rem]"
							>
								{campaignFactoryAudioStatus}
							</Badge>
						)}
						<PostStatusDot status={post.status} />
						{selected && (
							<span
								className="ml-0.5 inline-flex size-3 items-center justify-center rounded-full"
								style={{ backgroundColor: "var(--color-oxblood)" }}
								aria-hidden="true"
							>
								<Check className="size-2 text-white" strokeWidth={3} />
							</span>
						)}
					</div>
				</div>
				<span id={`post-card-help-${post.id}`} className="sr-only">
					Press M or open the context menu for non-drag move actions.
				</span>
				{riskLabels.length > 0 && (
					<div className="absolute bottom-1 right-1.5 flex gap-1">
						{riskLabels.slice(0, 2).map((label) => (
							<Badge
								key={label}
								tone="oxblood"
								className="h-4 rounded px-1 py-0 text-[0.5rem]"
							>
								{label}
							</Badge>
						))}
					</div>
				)}
				{/* Title + optional thumbnail. Thumbnail is 14×14, lives inline-right of
          the caption so it doesn't compete with the top status row. */}
				<div className="flex items-center gap-1.5">
					<div className="line-clamp-1 min-w-0 flex-1 text-[0.71875rem] leading-[1.25] text-foreground">
						{post.title}
					</div>
					{post.thumbnailUrl && (
						<img
							src={post.thumbnailUrl}
							alt=""
							aria-hidden="true"
							loading="lazy"
							decoding="async"
							onError={(event) => {
								event.currentTarget.style.display = "none";
							}}
							className="size-[14px] shrink-0 rounded-sm border border-border object-cover"
						/>
					)}
				</div>
			</Button>
			{previewRect && !dragging && !lifted && (
				<PostHoverPreview post={post} anchor={previewRect} />
			)}
			{moveMenuRect && onQuickMove && (
				<QuickMoveMenu
					post={post}
					anchor={moveMenuRect}
					onClose={closeMoveMenu}
					onMove={(action) => {
						closeMoveMenu();
						onQuickMove(post, action);
					}}
				/>
			)}
		</>
	);
}

export const PostCard = memo(PostCardInner);

function QuickMoveMenu({
	post,
	anchor,
	onMove,
	onClose,
}: {
	post: Post;
	anchor: DOMRect;
	onMove: (
		action: "minus-hour" | "plus-hour" | "tomorrow" | "next-peak",
	) => void;
	onClose: () => void;
}) {
	if (typeof document === "undefined") return null;
	const width = 220;
	const left = Math.min(
		window.innerWidth - width - 8,
		Math.max(8, anchor.right - width),
	);
	const top = Math.min(window.innerHeight - 180, anchor.bottom + 8);

	return createPortal(
		<>
			<Button
				type="button"
				variant="ghost"
				className="fixed inset-0 z-[8490] cursor-default"
				aria-label="Close quick move menu"
				onClick={onClose}
			/>
			<div
				role="menu"
				aria-label={`Move ${post.title}`}
				className="fixed z-[8500] rounded-md border border-border bg-card p-1 shadow-xl"
				style={{ top, left, width }}
			>
				<div className="flex items-center gap-2 border-b border-border px-2 py-2 text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
					<MoreHorizontal className="size-3.5" />
					Move without dragging
				</div>
				{[
					["minus-hour", "Move back 1 hour"],
					["plus-hour", "Move forward 1 hour"],
					["tomorrow", "Move to tomorrow"],
					["next-peak", "Move to next peak slot"],
				].map(([id, label]) => (
					<Button
						key={id}
						type="button"
						variant="ghost"
						size="sm"
						role="menuitem"
						onClick={() =>
							onMove(
								id as "minus-hour" | "plus-hour" | "tomorrow" | "next-peak",
							)
						}
						className="h-8 w-full justify-start rounded px-2 text-left text-[0.8125rem]"
					>
						{label}
					</Button>
				))}
			</div>
		</>,
		document.body,
	);
}

/* =========================================================================
   POST HOVER PREVIEW — richer floating card on sustained mouse-hover.
   ========================================================================= */
export function PostHoverPreview({
	post,
	anchor,
}: {
	post: Post;
	anchor: DOMRect;
}) {
	if (typeof document === "undefined") return null;
	const campaignFactorySurface = post.campaignFactory
		? formatCampaignFactorySurface(post.campaignFactory)
		: null;
	const status = STATUS_STYLE[post.status];
	const width = 320;
	const margin = 12;
	// Approximate preview height — used for viewport clamp. Preview has header +
	// time + caption (variable) + meta row. 360px accommodates most captions;
	// very long captions let the preview scroll internally via max-height.
	const approxHeight = Math.min(
		420,
		260 + Math.ceil(post.title.length / 50) * 20,
	);

	// Default: open to the right of the card. Flip left if near right edge.
	const openLeft = anchor.right + margin + width > window.innerWidth;
	const left = openLeft
		? Math.max(8, anchor.left - margin - width)
		: anchor.right + margin;
	// Vertically align to card top but keep in-viewport accounting for actual height
	const top = Math.max(
		8,
		Math.min(window.innerHeight - approxHeight - 8, anchor.top),
	);

	return createPortal(
		<div
			style={{
				position: "fixed",
				top,
				left,
				width,
				maxHeight: `calc(100dvh - ${top + 16}px)`,
				overflowY: "auto",
				zIndex: 8500,
				pointerEvents: "none",
				border: "0.5px solid var(--color-border)",
				borderRadius: 14,
				boxShadow:
					"0 16px 48px color-mix(in_srgb,var(--color-foreground)_14%,transparent), 0 2px 6px color-mix(in_srgb,var(--color-foreground)_4%,transparent)",
			}}
			className="hide-scrollbar bg-card"
		>
			{/* Group + account header */}
			<div className="px-4 pt-3.5 pb-2.5 flex items-center gap-2 border-b border-border">
				<span
					className="size-1.5 rounded-full flex-shrink-0"
					style={{ backgroundColor: post.groupColor }}
				/>
				<span className="text-[0.78125rem] font-medium text-foreground truncate">
					{post.account}
				</span>
				<span className="text-[0.65625rem] text-muted-foreground tabular-nums uppercase tracking-[0.08em] ml-auto">
					{post.groupName}
				</span>
			</div>

			{/* Scheduled for */}
			<div className="px-4 pt-3">
				<div className="text-[0.59375rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1">
					{post.isUnscheduledDraft ? "Review state" : "Scheduled"}
				</div>
				<div className="flex items-baseline gap-2 tabular-nums">
					<span className="text-[1rem] font-medium text-foreground tracking-[-0.02em]">
						{post.isUnscheduledDraft ? "Unscheduled draft" : DAY_NAMES_LONG[post.day]}
					</span>
					{!post.isUnscheduledDraft && (
						<span
							className="text-[0.8125rem] font-semibold"
							style={{ color: "var(--color-oxblood)" }}
						>
							{formatHour(post.hour, post.minute)}
						</span>
					)}
				</div>
			</div>

			{post.campaignFactory && (
				<div className="px-4 pt-3">
					<div className="text-[0.59375rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
						Campaign Factory
					</div>
					<div className="flex flex-wrap gap-1">
						{[
							campaignFactorySurface,
							post.campaignFactory.campaign_id,
							post.campaignFactory.recipe,
							formatCampaignFactoryAuditStatus(post.campaignFactory.audit_status),
						]
							.filter(Boolean)
							.map((value) => (
								<span
									key={value}
									className="rounded px-1.5 py-0.5 text-[0.625rem] font-medium bg-muted text-muted-foreground"
								>
									{value}
								</span>
							))}
					</div>
				</div>
			)}

			{/* Media thumbnail (first asset only — operators mostly post carousels
          of similar media, first frame is a good preview). */}
			{post.thumbnailUrl && (
				<div className="px-4 pt-3">
					<div className="text-[0.59375rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
						Media
					</div>
					<div className="relative rounded-md overflow-hidden border border-border bg-muted">
						<img
							src={post.thumbnailUrl}
							alt=""
							aria-hidden="true"
							loading="lazy"
							decoding="async"
							className="w-full h-[140px] object-cover"
						/>
						{post.mediaCount !== undefined && post.mediaCount > 1 && (
							<span className="absolute top-1.5 right-1.5 h-5 px-1.5 rounded-full bg-[color-mix(in_srgb,var(--color-foreground)_70%,transparent)] text-white text-[0.625rem] font-medium tabular-nums inline-flex items-center">
								+{post.mediaCount - 1}
							</span>
						)}
					</div>
				</div>
			)}

			{/* Caption (full, no truncation) */}
			<div className="px-4 pt-3">
				<div className="text-[0.59375rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1">
					Caption
				</div>
				<p className="text-[0.8125rem] text-foreground leading-relaxed">
					{post.title}
				</p>
			</div>

			{/* Meta grid */}
			<div className="px-4 py-3 mt-3 border-t border-border flex items-center gap-4 text-[0.71875rem] tabular-nums">
				<div>
					<div className="text-[0.59375rem] uppercase tracking-[0.1em] text-muted-foreground mb-0.5">
						Platform
					</div>
					<div className="text-foreground">{labelFor(post.platform)}</div>
				</div>
				<div className="flex-1">
					<div className="text-[0.59375rem] uppercase tracking-[0.1em] text-muted-foreground mb-0.5">
						Status
					</div>
					<span
						className="text-[0.625rem] font-semibold uppercase tracking-[0.08em] px-1.5 h-4 rounded inline-flex items-center"
						style={{ color: status.color, backgroundColor: status.bg }}
					>
						{status.label}
					</span>
				</div>
				{post.mediaCount !== undefined && (
					<div>
						<div className="text-[0.59375rem] uppercase tracking-[0.1em] text-muted-foreground mb-0.5">
							Media
						</div>
						<div className="text-foreground">{post.mediaCount}</div>
					</div>
				)}
			</div>
		</div>,
		document.body,
	);
}
