import {
	AtSign,
	BarChart2,
	EyeOff,
	FileText,
	Ghost,
	Globe,
	Hash,
	Image as ImageIcon,
	Layers,
	Link2,
	MapPin,
	MessageCircle,
	Moon,
	Plus,
	Quote,
	Share2,
	ShieldCheck,
	X,
} from "lucide-react";
import { useEffect } from "react";
import {
	CollapsibleSection,
	Field,
	SelectInput,
	TextInput,
	Toggle,
} from "@/components/composer/ComposerFormControls";
import type { ReplyControl } from "@/components/composer/PreviewSection";
import type { ConnectedAccount } from "@/hooks/useConnectedAccounts";
import { Button } from "@/components/ui/Button";
import { IconTooltipButton } from "@/components/ui/IconTooltipButton";
import { Input } from "@/components/ui/Input";
import { cn } from "@/lib/utils";

const REPLY_LABEL: Record<ReplyControl, string> = {
	anyone: "Anyone can reply",
	followed: "Profiles you follow",
	mentioned: "Profiles you mention",
	none: "No one",
};

export interface ThreadsOptions {
	replyControl: ReplyControl;
	topicTag: string;
	location: string;
	quoteUrl: string;
	linkAttach: string;
	textSpoilerTerms: string;
	gifId: string;
	gifProvider: "GIPHY" | "TENOR";
	textAttachment: string;
	textAttachmentUrl: string;
	textAttachmentStyles: string;
	geoGate: string;
	replyApprovalMode: "none" | "manual_approval";
	threadChain: boolean;
	spoiler: boolean;
	ghostPost: boolean;
	ghostDuration: "24h" | "48h" | "7d";
	pollEnabled: boolean;
	pollOptions: string[];
	crossFb: boolean;
	crossIgDarkMode: boolean;
}

interface Props {
	targets: ConnectedAccount[];
	open: boolean;
	onToggle: () => void;
	options: ThreadsOptions;
	onChange: (patch: Partial<ThreadsOptions>) => void;
}

export function ThreadsOptionsPanel({
	targets,
	open,
	onToggle,
	options,
	onChange,
}: Props) {
	const {
		replyControl,
		topicTag,
		location,
		quoteUrl,
		linkAttach,
		textSpoilerTerms,
		gifId,
		gifProvider,
		textAttachment,
		textAttachmentUrl,
		textAttachmentStyles,
		geoGate,
		replyApprovalMode,
		threadChain,
		spoiler,
		ghostPost,
		ghostDuration,
		pollEnabled,
		pollOptions,
		crossFb,
		crossIgDarkMode,
	} = options;

	const threadsCount = targets.filter((a) => a.platform === "threads").length;
	const threadsTargets = targets.filter((a) => a.platform === "threads");
	const canGeoGate =
		threadsTargets.length > 0 &&
		threadsTargets.every((account) => account.isEligibleForGeoGating === true);
	const scopeHint =
		threadsCount === 0
			? { tone: "muted" as const, text: "Add a Threads account to apply" }
			: {
					tone: "active" as const,
					text: `Applies to ${threadsCount} Threads ${threadsCount === 1 ? "account" : "accounts"}`,
				};

	useEffect(() => {
		if (!canGeoGate && geoGate) {
			onChange({ geoGate: "" });
		}
	}, [canGeoGate, geoGate, onChange]);

	useEffect(() => {
		if (ghostDuration !== "24h") {
			onChange({ ghostDuration: "24h" });
		}
	}, [ghostDuration, onChange]);

	return (
		<CollapsibleSection
			title="Threads options"
			icon={
				<AtSign
					className="w-3.5 h-3.5"
					style={{ color: "var(--color-oxblood)" }}
					aria-hidden="true"
				/>
			}
			scopeHint={scopeHint}
			open={open}
			onToggle={onToggle}
		>
			<div className="grid grid-cols-1 md:grid-cols-2 gap-3">
				<Field label="Who can reply">
					<SelectInput
						value={replyControl}
						onChange={(v) => onChange({ replyControl: v as ReplyControl })}
						options={(Object.keys(REPLY_LABEL) as ReplyControl[]).map((k) => ({
							value: k,
							label: REPLY_LABEL[k],
						}))}
						icon={<MessageCircle className="w-3.5 h-3.5" />}
					/>
				</Field>

				<Field label="Reply approval">
					<SelectInput
						value={replyApprovalMode}
						onChange={(v) =>
							onChange({
								replyApprovalMode: v as ThreadsOptions["replyApprovalMode"],
							})
						}
						options={[
							{ value: "none", label: "Auto-approve replies" },
							{ value: "manual_approval", label: "Manual approval" },
						]}
						icon={<ShieldCheck className="w-3.5 h-3.5" />}
					/>
				</Field>

				<Field label="Topic tag">
					<TextInput
						value={topicTag}
						onChange={(v) => onChange({ topicTag: v })}
						placeholder="e.g. founder-tips"
						icon={<Hash className="w-3.5 h-3.5" />}
					/>
				</Field>

				<Field label="Location">
					<TextInput
						value={location}
						onChange={(v) => onChange({ location: v })}
						placeholder="e.g. New York, NY"
						icon={<MapPin className="w-3.5 h-3.5" />}
					/>
				</Field>

				<Field label="Quote post URL">
					<TextInput
						value={quoteUrl}
						onChange={(v) => onChange({ quoteUrl: v })}
						placeholder="threads.net/@handle/post/…"
						icon={<Quote className="w-3.5 h-3.5" />}
					/>
				</Field>

				<Field label="Link attachment">
					<TextInput
						value={linkAttach}
						onChange={(v) => onChange({ linkAttach: v })}
						placeholder="https://"
						icon={<Link2 className="w-3.5 h-3.5" />}
					/>
				</Field>

				<Field label="Text spoilers">
					<TextInput
						value={textSpoilerTerms}
						onChange={(v) => onChange({ textSpoilerTerms: v })}
						placeholder="comma-separated phrases in caption"
						icon={<EyeOff className="w-3.5 h-3.5" />}
					/>
				</Field>

				{canGeoGate && (
					<Field label="Geo-gate (country codes)">
						<TextInput
							value={geoGate}
							onChange={(v) => onChange({ geoGate: v })}
							placeholder="US, CA, GB"
							icon={<Globe className="w-3.5 h-3.5" />}
						/>
					</Field>
				)}

				<Field label="GIF attachment ID">
					<TextInput
						value={gifId}
						onChange={(v) => onChange({ gifId: v })}
						placeholder="Tenor/GIPHY media id"
						icon={<ImageIcon className="w-3.5 h-3.5" />}
					/>
				</Field>

				<Field label="GIF provider">
					<SelectInput
						value={gifProvider}
						onChange={(v) => onChange({ gifProvider: v })}
						options={[
							{ value: "GIPHY", label: "GIPHY" },
							{ value: "TENOR", label: "Tenor" },
						]}
						icon={<ImageIcon className="w-3.5 h-3.5" />}
					/>
				</Field>

				<Field label="Text attachment">
					<TextInput
						value={textAttachment}
						onChange={(v) => onChange({ textAttachment: v })}
						placeholder="Long-form attachment text"
						icon={<FileText className="w-3.5 h-3.5" />}
					/>
				</Field>

				<Field label="Attachment link">
					<TextInput
						value={textAttachmentUrl}
						onChange={(v) => onChange({ textAttachmentUrl: v })}
						placeholder="https://"
						icon={<Link2 className="w-3.5 h-3.5" />}
					/>
				</Field>

				<Field label="Attachment styling">
					<TextInput
						value={textAttachmentStyles}
						onChange={(v) => onChange({ textAttachmentStyles: v })}
						placeholder="phrase:bold+italic, note:highlight"
						icon={<FileText className="w-3.5 h-3.5" />}
					/>
				</Field>
			</div>

			<Toggle
				label="Thread chain"
				detail="Split on paragraph breaks and publish as consecutive posts."
				checked={threadChain}
				onChange={(v) => onChange({ threadChain: v })}
				icon={<Layers className="w-3.5 h-3.5" />}
			/>

			<Toggle
				label="Spoiler content"
				detail="Hide media and text behind a spoiler cover. Viewers tap to reveal."
				checked={spoiler}
				onChange={(v) => onChange({ spoiler: v })}
				icon={<EyeOff className="w-3.5 h-3.5" />}
			/>

			<Toggle
				label="Ghost post (24h)"
				detail="Threads ghost posts expire after 24 hours."
				checked={ghostPost}
				onChange={(v) => onChange({ ghostPost: v, ghostDuration: "24h" })}
				icon={<Ghost className="w-3.5 h-3.5" />}
			/>

			{ghostPost && (
				<Field label="Ghost duration">
					<div
						className="flex items-center gap-1.5"
						role="radiogroup"
						aria-label="Ghost duration"
					>
						{[{ v: "24h" as const, label: "24 hours" }].map(({ v, label }) => {
							const active = ghostDuration === v;
							return (
								<Button
									key={v}
									type="button"
									variant={active ? "secondary" : "outline"}
									role="radio"
									aria-checked={active}
									onClick={() => onChange({ ghostDuration: v })}
									className={cn(
										"h-9 text-[0.78125rem]",
										active && "border-input",
									)}
								>
									{label}
								</Button>
							);
						})}
					</div>
				</Field>
			)}

			<Toggle
				label="Poll"
				detail="Attach a 2–4 option poll to this post. Each option 1–25 characters."
				checked={pollEnabled}
				onChange={(v) => {
					if (v && pollOptions.length < 2) {
						onChange({ pollEnabled: v, pollOptions: ["", ""] });
					} else {
						onChange({ pollEnabled: v });
					}
				}}
				icon={<BarChart2 className="w-3.5 h-3.5" />}
			/>

			{pollEnabled && (
				<div className="flex flex-col gap-2">
					{pollOptions.map((opt, i) => (
						<div key={i} className="flex items-center gap-2">
							<span className="w-5 h-5 rounded-full bg-muted border border-border inline-flex items-center justify-center text-[0.65625rem] font-semibold text-muted-foreground tabular-nums shrink-0">
								{String.fromCharCode(65 + i)}
							</span>
							<Input
								type="text"
								value={opt}
								maxLength={25}
								onChange={(e) => {
									const next = [...pollOptions];
									next[i] = e.target.value;
									onChange({ pollOptions: next });
								}}
								placeholder={`Option ${String.fromCharCode(65 + i)}`}
								className="flex-1"
							/>
							<span className="text-[0.65625rem] tabular-nums text-muted-foreground w-8 text-right">
								{opt.length}/25
							</span>
							{pollOptions.length > 2 && (
								<IconTooltipButton
									label={`Remove option ${String.fromCharCode(65 + i)}`}
									onClick={() =>
										onChange({
											pollOptions: pollOptions.filter((_, idx) => idx !== i),
										})
									}
								>
									<span className="w-6 h-6 inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-[color:var(--color-oxblood)] hover:bg-[color-mix(in_srgb,var(--color-oxblood)_8%,transparent)] active:bg-[color-mix(in_srgb,var(--color-oxblood)_14%,transparent)] transition-colors">
										<X className="w-3 h-3" aria-hidden="true" />
									</span>
								</IconTooltipButton>
							)}
						</div>
					))}
					{pollOptions.length < 4 && (
						<Button
							type="button"
							variant="ghost"
							size="sm"
							onClick={() => onChange({ pollOptions: [...pollOptions, ""] })}
							className="self-start gap-1"
						>
							<Plus className="w-3 h-3" aria-hidden="true" />
							Add option
						</Button>
					)}
				</div>
			)}
			<Toggle
				label="Share to Instagram Story"
				detail="Use Threads cross-reshare to mirror this post into Instagram Stories when the connected account supports it."
				checked={crossFb}
				onChange={(v) => onChange({ crossFb: v })}
				icon={<Share2 className="w-3.5 h-3.5" />}
			/>

			{crossFb && (
				<Toggle
					label="Story dark mode"
					detail="Request the dark-mode Instagram Story rendering for Threads cross-reshare."
					checked={crossIgDarkMode}
					onChange={(v) => onChange({ crossIgDarkMode: v })}
					icon={<Moon className="w-3.5 h-3.5" />}
				/>
			)}
		</CollapsibleSection>
	);
}
