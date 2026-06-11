import { Loader2, Plus, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Input } from "@/components/ui/Input";
import { Modal } from "@/components/ui/Modal";
import { Textarea } from "@/components/ui/Textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/ToggleGroup";
import type { AccountPlatform } from "@/hooks/useFleetAccounts";
import { appToast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { AiNotConfiguredError, AiRateLimitedError } from "@/services/ai";
import {
	extractStyleBible,
	fetchVoiceProfile,
	StyleBibleTierLockedError,
	saveVoiceProfile,
	toExtractedStyle,
} from "@/services/voiceProfileService";
import type { VoiceProfile } from "@/types/voice";

interface Props {
	open: boolean;
	onClose: () => void;
	accountId: string;
	platform: AccountPlatform;
	handle: string;
	/** Called after a successful save so the parent list can refresh. */
	onSaved?: () => void;
}

type EmojiUsage = NonNullable<VoiceProfile["emoji_usage"]>;
type CtaStyle = NonNullable<VoiceProfile["cta_style"]>;

const EMOJI_OPTIONS: EmojiUsage[] = ["none", "minimal", "moderate", "heavy"];
const CTA_OPTIONS: { id: CtaStyle; label: string }[] = [
	{ id: "none", label: "None" },
	{ id: "link_in_bio", label: "Link in bio" },
	{ id: "dm_me", label: "DM me" },
	{ id: "subscribe", label: "Subscribe" },
];

const MIN_CAPTIONS = 3;
const MAX_CAPTIONS = 20;

function splitCaptions(raw: string): string[] {
	return raw
		.split(/\n\s*\n+|^---+\s*$/m)
		.map((c) => c.trim())
		.filter((c) => c.length > 0);
}

export function VoiceProfileEditor({
	open,
	onClose,
	accountId,
	platform,
	handle,
	onSaved,
}: Props) {
	const [loading, setLoading] = useState(true);
	const [saving, setSaving] = useState(false);
	const [extracting, setExtracting] = useState(false);
	const [profile, setProfile] = useState<VoiceProfile>({});
	const [samples, setSamples] = useState("");
	const [newFocusTopic, setNewFocusTopic] = useState("");
	const [newAvoidTopic, setNewAvoidTopic] = useState("");
	const [newAvoidWord, setNewAvoidWord] = useState("");

	useEffect(() => {
		if (!open) return;
		let cancelled = false;
		setLoading(true);
		setSamples("");
		fetchVoiceProfile(accountId, platform)
			.then((p) => {
				if (!cancelled) setProfile(p);
			})
			.catch((err) => {
				if (!cancelled) {
					appToast.error("Could not load voice profile", {
						description: err instanceof Error ? err.message : undefined,
					});
				}
			})
			.finally(() => {
				if (!cancelled) setLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, [open, accountId, platform]);

	const captionList = useMemo(() => splitCaptions(samples), [samples]);
	const canExtract =
		captionList.length >= MIN_CAPTIONS && captionList.length <= MAX_CAPTIONS;

	const addChip = (
		key: "focus_topics" | "avoid_topics" | "avoid_words",
		value: string,
	) => {
		const trimmed = value.trim();
		if (!trimmed) return;
		const existing = profile[key] ?? [];
		if (existing.includes(trimmed)) return;
		setProfile({ ...profile, [key]: [...existing, trimmed] });
	};

	const removeChip = (
		key: "focus_topics" | "avoid_topics" | "avoid_words",
		value: string,
	) => {
		const existing = profile[key] ?? [];
		setProfile({ ...profile, [key]: existing.filter((v) => v !== value) });
	};

	const runExtract = async () => {
		if (!canExtract || extracting) return;
		setExtracting(true);
		try {
			const extracted = await extractStyleBible(captionList, accountId);
			setProfile((prev) => ({
				...prev,
				tone: prev.tone || extracted.personality,
				emoji_usage: prev.emoji_usage || extracted.emojiUsage,
				voice_profile: prev.voice_profile || extracted.personality,
				extracted_style: toExtractedStyle(extracted),
			}));
			appToast.success("Voice extracted", {
				description: "Review the fields below and save when it feels right.",
			});
		} catch (err) {
			if (err instanceof StyleBibleTierLockedError) {
				appToast.info("Style extraction is a Pro feature", {
					description: "Upgrade to auto-extract voice from sample captions.",
				});
			} else if (err instanceof AiNotConfiguredError) {
				appToast.error("AI is not configured", {
					description: "Add an API key in Settings to enable extraction.",
				});
			} else if (err instanceof AiRateLimitedError) {
				appToast.info("Rate limit reached — try again in a moment.");
			} else {
				appToast.error("Could not extract voice", {
					description: err instanceof Error ? err.message : undefined,
				});
			}
		} finally {
			setExtracting(false);
		}
	};

	const save = async () => {
		if (saving) return;
		setSaving(true);
		try {
			await saveVoiceProfile(accountId, platform, profile);
			appToast.success("Voice profile saved");
			onSaved?.();
			onClose();
		} catch (err) {
			appToast.error("Could not save voice profile", {
				description: err instanceof Error ? err.message : undefined,
			});
		} finally {
			setSaving(false);
		}
	};

	const hasExtracted = !!profile.extracted_style?.extracted_at;

	return (
		<Modal
			open={open}
			onClose={onClose}
			maxWidthClass="max-w-2xl"
			title={`Voice profile · @${handle.replace(/^@/, "")}`}
			description={
				platform === "threads"
					? "Threads — this account will inherit these rules for every AI-generated post."
					: "Instagram — this account will inherit these rules for every AI-generated caption."
			}
			footer={
				<>
					<Button variant="outline" onClick={onClose} disabled={saving}>
						Cancel
					</Button>
					<Button onClick={save} disabled={saving || loading}>
						{saving ? "Saving…" : "Save voice profile"}
					</Button>
				</>
			}
		>
			{loading ? (
				<div className="py-8 flex items-center justify-center text-muted-foreground">
					<Loader2 className="w-4 h-4 animate-spin mr-2" />
					<span className="text-[0.8125rem]">Loading profile…</span>
				</div>
			) : (
				<div className="flex flex-col gap-5">
					<FieldBlock
						label="Voice description"
						hint="One or two sentences describing this account's voice. Grounds every AI rewrite."
					>
						<Textarea
							value={profile.voice_profile ?? ""}
							onChange={(e) =>
								setProfile({ ...profile, voice_profile: e.target.value })
							}
							placeholder="e.g. Casual, direct, lightly deadpan. Talks to the audience like a friend. No corporate-speak."
							rows={3}
							className="min-h-[72px]"
						/>
					</FieldBlock>

					<div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
						<FieldBlock label="Tone">
							<Input
								type="text"
								value={profile.tone ?? ""}
								onChange={(e) =>
									setProfile({ ...profile, tone: e.target.value })
								}
								placeholder="casual · edgy · warm · authoritative"
							/>
						</FieldBlock>

						<FieldBlock label="Emoji usage">
							<SegmentedRow
								value={profile.emoji_usage}
								options={EMOJI_OPTIONS.map((id) => ({ id, label: id }))}
								onChange={(v) =>
									setProfile({ ...profile, emoji_usage: v as EmojiUsage })
								}
							/>
						</FieldBlock>
					</div>

					<FieldBlock label="Call-to-action style">
						<SegmentedRow
							value={profile.cta_style}
							options={CTA_OPTIONS}
							onChange={(v) =>
								setProfile({ ...profile, cta_style: v as CtaStyle })
							}
						/>
					</FieldBlock>

					<ChipField
						label="Focus topics"
						hint="Subjects to lean into when generating."
						chips={profile.focus_topics ?? []}
						value={newFocusTopic}
						onValueChange={setNewFocusTopic}
						onAdd={() => {
							addChip("focus_topics", newFocusTopic);
							setNewFocusTopic("");
						}}
						onRemove={(chip) => removeChip("focus_topics", chip)}
					/>

					<ChipField
						label="Avoid topics"
						hint="Subjects the AI should steer away from."
						chips={profile.avoid_topics ?? []}
						value={newAvoidTopic}
						onValueChange={setNewAvoidTopic}
						onAdd={() => {
							addChip("avoid_topics", newAvoidTopic);
							setNewAvoidTopic("");
						}}
						onRemove={(chip) => removeChip("avoid_topics", chip)}
					/>

					<ChipField
						label="Banned words"
						hint="Exact strings to never output — casing-insensitive."
						chips={profile.avoid_words ?? []}
						value={newAvoidWord}
						onValueChange={setNewAvoidWord}
						onAdd={() => {
							addChip("avoid_words", newAvoidWord);
							setNewAvoidWord("");
						}}
						onRemove={(chip) => removeChip("avoid_words", chip)}
					/>

					<NovaCard variant="panel" contentClassName="flex flex-col gap-3">
						<div className="flex items-center gap-2">
							<Sparkles className="w-3.5 h-3.5 text-[color:var(--color-oxblood)]" />
							<span className="text-[0.78125rem] font-medium text-foreground">
								Auto-extract from sample captions
							</span>
						</div>
						<p className="text-[0.71875rem] text-muted-foreground leading-relaxed">
							Paste {MIN_CAPTIONS}–{MAX_CAPTIONS} of this account's best
							captions, separated by blank lines. The extractor merges a
							quantitative pass (length, emoji, hashtags) with a Gemini pass
							(tone words, personality) and fills in the fields above.
						</p>
						<Textarea
							value={samples}
							onChange={(e) => setSamples(e.target.value)}
							placeholder={`Caption one…\n\nCaption two…\n\nCaption three…`}
							rows={5}
							className="min-h-[96px] bg-background font-[family-name:inherit] md:text-[0.78125rem]"
						/>
						<div className="flex items-center justify-between gap-3">
							<span
								className={cn(
									"text-[0.6875rem] tabular-nums",
									canExtract ? "text-muted-foreground" : "text-muted-foreground",
								)}
							>
								{captionList.length}/{MAX_CAPTIONS} captions detected
								{captionList.length > 0 &&
									captionList.length < MIN_CAPTIONS &&
									` — need ${MIN_CAPTIONS - captionList.length} more`}
							</span>
							<Button
								variant="outline"
								onClick={runExtract}
								disabled={!canExtract || extracting}
								className="h-8 text-[0.75rem]"
							>
								{extracting ? (
									<>
										<Loader2 data-icon="inline-start" className="animate-spin" />{" "}
										Extracting…
									</>
								) : (
									<>
										<Sparkles data-icon="inline-start" /> Extract voice
									</>
								)}
							</Button>
						</div>
						{hasExtracted && (
							<div className="text-[0.6875rem] text-muted-foreground">
								Style DNA extracted · the AI will now inherit signature words
								and length preference in every generate call.
							</div>
						)}
					</NovaCard>
				</div>
			)}
		</Modal>
	);
}

function FieldBlock({
	label,
	hint,
	children,
}: {
	label: string;
	hint?: React.ReactNode | undefined;
	children: React.ReactNode;
}) {
	return (
		<div>
			{/* biome-ignore lint/a11y/noLabelWithoutControl: {children} is the associated control rendered in the same container */}
			<label className="block text-[0.75rem] font-medium text-muted-foreground mb-1.5">
				{label}
			</label>
			{children}
			{hint && (
				<div className="mt-1.5 text-[0.6875rem] text-muted-foreground">
					{hint}
				</div>
			)}
		</div>
	);
}

function SegmentedRow<T extends string>({
	value,
	options,
	onChange,
}: {
	value: T | undefined;
	options: { id: T; label: string }[];
	onChange: (v: T) => void;
}) {
	return (
		<ToggleGroup
			type="single"
			value={value ?? ""}
			onValueChange={(next) => {
				if (next) onChange(next as T);
			}}
			className="w-full rounded-md"
		>
			{options.map((opt) => (
				<ToggleGroupItem
					key={opt.id}
					value={opt.id}
					sizeVariant="sm"
					className="flex-1 capitalize"
				>
					{opt.label}
				</ToggleGroupItem>
			))}
		</ToggleGroup>
	);
}

function ChipField({
	label,
	hint,
	chips,
	value,
	onValueChange,
	onAdd,
	onRemove,
}: {
	label: string;
	hint?: string | undefined;
	chips: string[];
	value: string;
	onValueChange: (v: string) => void;
	onAdd: () => void;
	onRemove: (chip: string) => void;
}) {
	return (
		<FieldBlock label={label} hint={hint}>
			<div className="flex items-center gap-2">
				<Input
					type="text"
					value={value}
					onChange={(e) => onValueChange(e.target.value)}
					onKeyDown={(e) => {
						if (e.key === "Enter") {
							e.preventDefault();
							onAdd();
						}
					}}
					placeholder="Type and press Enter"
					className="flex-1"
				/>
				<Button
					variant="outline"
					onClick={onAdd}
					disabled={!value.trim()}
					className="h-9 px-3 text-[0.75rem]"
					aria-label={`Add ${label.toLowerCase()}`}
				>
					<Plus data-icon aria-hidden="true" />
				</Button>
			</div>
			{chips.length > 0 && (
				<div className="mt-2 flex flex-wrap gap-1.5">
					{chips.map((chip) => (
						<span
							key={chip}
							className={cn(
								"inline-flex items-center gap-1 h-[22px] pl-2 pr-1 rounded-full",
								"text-[0.6875rem] font-medium",
								"bg-muted text-foreground border border-border",
							)}
						>
							{chip}
							<Button
								type="button"
								onClick={() => onRemove(chip)}
								aria-label={`Remove ${chip}`}
								variant="ghost"
								size="icon"
								className="h-[14px] w-[14px] rounded-full"
							>
								<X data-icon aria-hidden="true" />
							</Button>
						</span>
					))}
				</div>
			)}
		</FieldBlock>
	);
}
