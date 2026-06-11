import {
	AtSign,
	Camera,
	Film,
	FlaskConical,
	Handshake,
	Image as ImageIcon,
	Layers,
	Loader2,
	MapPin,
	MessageCircle,
	Music,
	Play,
	Search,
	X,
} from "lucide-react";
import { useState } from "react";
import {
	CollapsibleSection,
	Field,
	TextInput,
	Toggle,
} from "@/components/composer/ComposerFormControls";
import type { IGPostType } from "@/components/composer/PreviewSection";
import type { ConnectedAccount } from "@/hooks/useConnectedAccounts";
import { IconTooltipButton } from "@/components/ui/IconTooltipButton";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Slider } from "@/components/ui/Slider";
import { cn } from "@/lib/utils";
import {
	type InstagramAudioAsset,
	type InstagramAudioType,
	instagramService,
} from "@/services/instagramService";

export interface InstagramOptions {
	igType: IGPostType;
	firstComment: string;
	location: string;
	collaborators: string[];
	collaboratorDraft: string;
	userTags: string;
	productTags: string;
	reelCover: number;
	coverUrl: string;
	audioName: string;
	igAudioId: string;
	igAudioTitle: string;
	igAudioArtist: string;
	igAudioType: InstagramAudioType;
	shareToFeed: boolean;
	trialReel: boolean;
	graduation: "MANUAL" | "SS_PERFORMANCE";
	commentEnabled: boolean;
	isPaidPartnership: boolean;
	brandedContentSponsorIds: string;
}

interface Props {
	targets: ConnectedAccount[];
	open: boolean;
	onToggle: () => void;
	options: InstagramOptions;
	onChange: (patch: Partial<InstagramOptions>) => void;
	showPostType?: boolean;
}

export function InstagramOptionsPanel({
	targets,
	open,
	onToggle,
	options,
	onChange,
	showPostType = true,
}: Props) {
	const {
		igType,
		firstComment,
		location,
		collaborators,
		collaboratorDraft,
		userTags,
		reelCover,
		coverUrl,
		audioName,
		igAudioId,
		igAudioTitle,
		igAudioArtist,
		igAudioType,
		shareToFeed,
		trialReel,
		graduation,
		commentEnabled,
		isPaidPartnership,
		brandedContentSponsorIds,
	} = options;

	const igCount = targets.filter((a) => a.platform === "instagram").length;
	const firstInstagramTarget = targets.find((a) => a.platform === "instagram");
	const [audioQuery, setAudioQuery] = useState("");
	const [audioType, setAudioType] = useState<InstagramAudioType>(
		igAudioType || "music",
	);
	const [audioResults, setAudioResults] = useState<InstagramAudioAsset[]>([]);
	const [audioLoading, setAudioLoading] = useState(false);
	const [audioError, setAudioError] = useState<string | null>(null);

	const searchAudio = async () => {
		if (!firstInstagramTarget?.id) return;
		setAudioLoading(true);
		setAudioError(null);
		try {
			const result = await instagramService.searchAudio(
				firstInstagramTarget.id,
				{
					audioType,
					query: audioQuery.trim() || undefined,
					limit: 8,
				},
			);
			setAudioResults(result?.audio ?? []);
			if (!result?.audio?.length) setAudioError("No audio found.");
		} catch (error) {
			setAudioResults([]);
			setAudioError(
				error instanceof Error
					? error.message
					: "Instagram audio search failed.",
			);
		} finally {
			setAudioLoading(false);
		}
	};

	const selectAudio = (audio: InstagramAudioAsset) => {
		onChange({
			igAudioId: audio.id,
			igAudioTitle: audio.title || audio.id,
			igAudioArtist: audio.artistName || "",
			igAudioType:
				audio.audioType === "original_sound" ? "original_sound" : audioType,
		});
	};

	const scopeHint =
		igCount === 0
			? { tone: "muted" as const, text: "Add an Instagram account to apply" }
			: {
					tone: "active" as const,
					text: `Applies to ${igCount} Instagram ${igCount === 1 ? "account" : "accounts"}`,
				};

	return (
		<CollapsibleSection
			title="Instagram options"
			icon={
				<Camera
					className="w-3.5 h-3.5"
					style={{ color: "var(--color-oxblood)" }}
					aria-hidden="true"
				/>
			}
			scopeHint={scopeHint}
			open={open}
			onToggle={onToggle}
		>
			{showPostType && (
				<Field label="Post type">
					<div
						className="flex items-center gap-1.5"
						role="radiogroup"
						aria-label="Instagram post type"
					>
						{[
							{ v: "feed" as IGPostType, label: "Feed", Icon: ImageIcon },
							{ v: "reels" as IGPostType, label: "Reels", Icon: Film },
							{ v: "story" as IGPostType, label: "Story", Icon: Play },
						].map(({ v, label, Icon }) => {
							const active = igType === v;
							return (
								<Button
									key={v}
									type="button"
									variant={active ? "secondary" : "outline"}
									role="radio"
									aria-checked={active}
									onClick={() => onChange({ igType: v })}
									className={cn(
										"h-9 gap-1.5 text-[0.78125rem]",
										active && "border-input",
									)}
								>
									<Icon className="w-3.5 h-3.5" aria-hidden="true" />
									{label}
								</Button>
							);
						})}
					</div>
				</Field>
			)}

			<div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
				{igType !== "story" && (
					<Field label="First comment">
						<TextInput
							value={firstComment}
							onChange={(v) => onChange({ firstComment: v })}
							placeholder="First comment (posted unpinned - Instagram API has no pin endpoint)"
							icon={<MessageCircle className="w-3.5 h-3.5" />}
						/>
					</Field>
				)}

				<Field label="Location">
					<TextInput
						value={location}
						onChange={(v) => onChange({ location: v })}
						placeholder="Facebook Place ID"
						icon={<MapPin className="w-3.5 h-3.5" />}
					/>
				</Field>

				{igType !== "story" && (
					<div className="md:col-span-2">
						<Field label="Collaborators (up to 3)">
							<div className="flex items-center gap-1.5 flex-wrap">
								{collaborators.map((c) => (
									<span
										key={c}
										className="inline-flex items-center gap-1 h-7 pl-2.5 pr-1 rounded-full bg-[color-mix(in_srgb,var(--color-foreground)_4%,transparent)] dark:bg-[color-mix(in_srgb,var(--color-foreground)_5%,transparent)] border border-border text-[0.71875rem] font-medium text-foreground"
									>
										@{c}
										<IconTooltipButton
											label={`Remove collaborator @${c}`}
											onClick={() =>
												onChange({
													collaborators: collaborators.filter((x) => x !== c),
												})
											}
											className="min-w-0 min-h-0 w-4 h-4 rounded-full text-muted-foreground hover:text-[color:var(--color-oxblood)] hover:bg-[color-mix(in_srgb,var(--color-oxblood)_10%,transparent)] active:bg-[color-mix(in_srgb,var(--color-oxblood)_18%,transparent)] transition-colors"
										>
											<X className="w-2.5 h-2.5" aria-hidden="true" />
										</IconTooltipButton>
									</span>
								))}
								{collaborators.length < 3 && (
									<div className="flex items-center gap-1.5 flex-1 min-w-[180px]">
										<TextInput
											value={collaboratorDraft}
											onChange={(v) => onChange({ collaboratorDraft: v })}
											placeholder="handle"
											icon={<AtSign className="w-3.5 h-3.5" />}
										/>
										<Button
											type="button"
											variant="outline"
											onClick={() => {
												const v = collaboratorDraft.trim().replace(/^@/, "");
												if (!v || collaborators.includes(v)) return;
												onChange({
													collaborators: [...collaborators, v],
													collaboratorDraft: "",
												});
											}}
											disabled={!collaboratorDraft.trim()}
											className="h-9 text-[0.78125rem]"
										>
											Add
										</Button>
									</div>
								)}
							</div>
						</Field>
					</div>
				)}

				<Field label="User tags (handles)">
					<TextInput
						value={userTags}
						onChange={(v) => onChange({ userTags: v })}
						placeholder="natgeo@0.5:0.5, creator_studio"
						icon={<AtSign className="w-3.5 h-3.5" />}
					/>
				</Field>

				{igType !== "story" && (
					<div className="md:col-span-2">
						<Toggle
							label="Paid partnership"
							detail="Adds the paid partnership disclosure when Instagram publishes the post."
							checked={isPaidPartnership}
							onChange={(v) => onChange({ isPaidPartnership: v })}
							icon={<Handshake className="w-3.5 h-3.5" />}
						/>
						{isPaidPartnership && (
							<Field label="Brand partner IDs (up to 2)">
								<TextInput
									value={brandedContentSponsorIds}
									onChange={(v) => onChange({ brandedContentSponsorIds: v })}
									placeholder="17841400000000000, 17841411111111111"
									icon={<Handshake className="w-3.5 h-3.5" />}
								/>
							</Field>
						)}
					</div>
				)}

				{igType === "reels" && (
					<>
						<Field label={`Cover frame — ${reelCover.toFixed(1)}s`}>
							<Slider
								min={0}
								max={15}
								step={0.5}
								value={[reelCover]}
								onValueChange={([next]) =>
									onChange({
										reelCover: typeof next === "number" ? next : reelCover,
									})
								}
							/>
						</Field>

						<Field label="Cover image URL (override)">
							<TextInput
								value={coverUrl}
								onChange={(v) => onChange({ coverUrl: v })}
								placeholder="https://cdn.…/cover.jpg"
								icon={<ImageIcon className="w-3.5 h-3.5" />}
							/>
						</Field>

						<Field label="Audio name (rename original)">
							<TextInput
								value={audioName}
								onChange={(v) => onChange({ audioName: v })}
								placeholder="Morning routine — original"
								icon={<Music className="w-3.5 h-3.5" />}
							/>
						</Field>

						<div className="md:col-span-2">
							<Field label="Instagram audio">
								<div className="rounded-lg border border-border bg-card/50 p-3">
									<div className="flex flex-col gap-2 sm:flex-row">
										<div
											className="flex items-center gap-1.5"
											role="radiogroup"
											aria-label="Instagram audio type"
										>
											{[
												{ value: "music" as const, label: "Music" },
												{ value: "original_sound" as const, label: "Original" },
											].map((item) => {
												const active = audioType === item.value;
												return (
													<Button
														key={item.value}
														type="button"
														variant={active ? "secondary" : "outline"}
														role="radio"
														aria-checked={active}
														onClick={() => {
															setAudioType(item.value);
															onChange({ igAudioType: item.value });
														}}
														className="h-9 text-[0.78125rem]"
													>
														{item.label}
													</Button>
												);
											})}
										</div>
										<div className="flex min-w-0 flex-1 items-center gap-2">
											<div className="relative min-w-0 flex-1">
												<Search
													className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
													aria-hidden="true"
												/>
												<Input
													value={audioQuery}
													onChange={(event) =>
														setAudioQuery(event.target.value)
													}
													onKeyDown={(event) => {
														if (event.key === "Enter") {
															event.preventDefault();
															void searchAudio();
														}
													}}
													placeholder="Search Meta audio"
													className="h-9 pl-8 text-[0.8125rem]"
													disabled={!firstInstagramTarget || audioLoading}
												/>
											</div>
											<Button
												type="button"
												variant="outline"
												onClick={() => void searchAudio()}
												disabled={!firstInstagramTarget || audioLoading}
												className="h-9 text-[0.78125rem]"
											>
												{audioLoading ? (
													<Loader2
														className="size-3.5 animate-spin"
														aria-hidden="true"
													/>
												) : (
													"Search"
												)}
											</Button>
										</div>
									</div>

									{igAudioId ? (
										<div className="mt-3 flex items-center justify-between gap-3 rounded-md bg-muted px-3 py-2">
											<div className="min-w-0">
												<div className="truncate text-[0.8125rem] font-medium text-foreground">
													{igAudioTitle || igAudioId}
												</div>
												<div className="truncate text-[0.71875rem] text-muted-foreground">
													{igAudioArtist || "Selected Instagram audio"}
												</div>
											</div>
											<Button
												type="button"
												variant="ghost"
												size="sm"
												onClick={() =>
													onChange({
														igAudioId: "",
														igAudioTitle: "",
														igAudioArtist: "",
													})
												}
											>
												Clear
											</Button>
										</div>
									) : null}

									{audioResults.length > 0 ? (
										<div className="mt-3 grid gap-2">
											{audioResults.map((audio) => (
												<Button
													key={audio.id}
													type="button"
													variant="outline"
													onClick={() => selectAudio(audio)}
													className="h-auto min-h-12 w-full justify-between gap-3 px-3 py-2 text-left"
												>
													<span className="min-w-0">
														<span className="block truncate text-[0.8125rem] font-medium text-foreground">
															{audio.title || audio.id}
														</span>
														<span className="block truncate text-[0.71875rem] text-muted-foreground">
															{audio.artistName ||
																audio.audioType ||
																"Instagram audio"}
														</span>
													</span>
													<span className="shrink-0 text-[0.71875rem] font-medium text-muted-foreground">
														Select
													</span>
												</Button>
											))}
										</div>
									) : null}

									{audioError ? (
										<p className="mt-2 text-[0.75rem] text-muted-foreground">
											{audioError}
										</p>
									) : null}
								</div>
							</Field>
						</div>
					</>
				)}
			</div>

			{igType === "reels" && (
				<>
					<Toggle
						label="Share to Feed"
						detail="Reel also appears in the Feed tab (not just Reels-only)."
						checked={shareToFeed}
						onChange={(v) => onChange({ shareToFeed: v })}
						icon={<Layers className="w-3.5 h-3.5" />}
					/>

					<Toggle
						label="Trial Reel"
						detail="Publish to non-followers only. Track performance before graduating to followers."
						checked={trialReel}
						onChange={(v) => onChange({ trialReel: v })}
						icon={<FlaskConical className="w-3.5 h-3.5" />}
					/>

					{trialReel && (
						<Field label="Graduation strategy">
							<div
								className="flex items-center gap-1.5"
								role="radiogroup"
								aria-label="Trial reel graduation"
							>
								{[
									{
										v: "SS_PERFORMANCE" as const,
										label: "Auto — by performance",
									},
									{ v: "MANUAL" as const, label: "Manual — graduate in app" },
								].map(({ v, label }) => {
									const active = graduation === v;
									return (
										<Button
											key={v}
											type="button"
											variant={active ? "secondary" : "outline"}
											role="radio"
											aria-checked={active}
											onClick={() => onChange({ graduation: v })}
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
				</>
			)}

			{igType !== "story" && (
				<Toggle
					label="Comments"
					detail="Allow comments on the Instagram post after publish."
					checked={commentEnabled}
					onChange={(v) => onChange({ commentEnabled: v })}
					icon={<MessageCircle className="w-3.5 h-3.5" />}
				/>
			)}
		</CollapsibleSection>
	);
}
