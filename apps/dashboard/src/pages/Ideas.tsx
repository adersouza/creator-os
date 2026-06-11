import {
	type RefObject,
	useCallback,
	useEffect,
	useMemo,
	useRef,
	useState,
} from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
	Archive,
	CheckCircle2,
	CircleGauge,
	ClipboardList,
	FileText,
	Image,
	InspectionPanel,
	Layers,
	Lightbulb,
	Link2,
	Mic,
	Plus,
	Send,
	Sparkles,
	Square,
	Target,
	Trash2,
	Upload,
} from "lucide-react";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
	NovaCard,
	NovaDataPanel,
	NovaEmpty,
	NovaHeader,
	NovaSection,
	NovaToolbar,
} from "@/components/ui/NovaPrimitives";
import { Input } from "@/components/ui/Input";
import { Progress } from "@/components/ui/Progress";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { useAccountGroups } from "@/hooks/useAccountGroups";
import { useAuthUser } from "@/hooks/useAuthUser";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import { appToast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { randomUUID } from "@/lib/uuid";
import { generateComposerVariants } from "@/services/api/composer";
import {
	getUserSetting,
	upsertUserSetting,
} from "@/services/userSettingsService";

type IdeaStatus = "inbox" | "shaping" | "ready" | "used";
type IdeaSource = "rough" | "link" | "screenshot" | "voice";

interface IdeaItem {
	id: string;
	title: string;
	body: string;
	linkUrl: string | null;
	imageUrl: string | null;
	audioUrl: string | null;
	transcript: string | null;
	status: IdeaStatus;
	accountId: string | null;
	groupId: string | null;
	source: IdeaSource;
	variants: string[];
	createdAt: string;
	updatedAt: string;
}

interface IdeaHandoff {
	id: string;
	content: string;
	accountId: string | null;
	groupId: string | null;
	linkUrl: string | null;
	imageUrl: string | null;
	imageName: string | null;
	label: string;
}

type IdeaDisplayInput = Pick<
	IdeaItem,
	| "body"
	| "source"
	| "status"
	| "variants"
	| "linkUrl"
	| "imageUrl"
	| "audioUrl"
	| "transcript"
	| "accountId"
	| "groupId"
>;

type DraftSummaryInput = Pick<IdeaItem, "status" | "variants">;

const STORAGE_PREFIX = "juno33:ideas-board";
const REMOTE_SETTING_KEY = "ideas_board_v1";
const MAX_DATA_URL_BYTES = 1_200_000;

const STATUS_COLUMNS: Array<{
	id: IdeaStatus;
	label: string;
	icon: typeof Lightbulb;
}> = [
	{ id: "inbox", label: "Inbox", icon: Lightbulb },
	{ id: "shaping", label: "Shaping", icon: FileText },
	{ id: "ready", label: "Ready", icon: CheckCircle2 },
	{ id: "used", label: "Used", icon: Archive },
];

const SOURCE_OPTIONS: Array<{
	id: IdeaSource;
	label: string;
	icon: typeof Lightbulb;
}> = [
	{ id: "rough", label: "Thought", icon: Lightbulb },
	{ id: "voice", label: "Voice", icon: Mic },
	{ id: "link", label: "Link", icon: Link2 },
	{ id: "screenshot", label: "Shot", icon: Image },
];

export function getIdeaSignalScore(idea: IdeaDisplayInput): number {
	let score = 58;
	if (idea.body.trim().length >= 32) score += 8;
	if (idea.source === "voice") score += 6;
	if (idea.source === "screenshot") score += 5;
	if (idea.source === "link") score += 4;
	if (idea.status === "ready") score += 10;
	if (idea.status === "shaping") score += 6;
	if (idea.status === "used") score += 4;
	score += Math.min(idea.variants.length * 4, 10);
	if (idea.linkUrl) score += 4;
	if (idea.imageUrl) score += 4;
	if (idea.audioUrl || idea.transcript) score += 4;
	if (idea.accountId) score += 4;
	if (idea.groupId) score += 3;
	return Math.min(96, Math.max(50, score));
}

export function getIdeaDraftSummary(ideas: DraftSummaryInput[]) {
	return {
		inbox: ideas.filter((idea) => idea.status === "inbox").length,
		shaping: ideas.filter((idea) => idea.status === "shaping").length,
		ready: ideas.filter((idea) => idea.status === "ready").length,
		used: ideas.filter((idea) => idea.status === "used").length,
		variants: ideas.reduce((total, idea) => total + idea.variants.length, 0),
	};
}

function ideasStorageKey(userId: string | null): string {
	return `${STORAGE_PREFIX}:${userId ?? "anon"}`;
}

function normalizeIdea(row: unknown): IdeaItem | null {
	if (!row || typeof row !== "object") return null;
	const candidate = row as Partial<IdeaItem>;
	if (typeof candidate.id !== "string") return null;
	if (typeof candidate.body !== "string") return null;
	const now = new Date().toISOString();
	const status: IdeaStatus = STATUS_COLUMNS.some(
		(s) => s.id === candidate.status,
	)
		? (candidate.status as IdeaStatus)
		: "inbox";
	const source: IdeaSource = SOURCE_OPTIONS.some(
		(s) => s.id === candidate.source,
	)
		? (candidate.source as IdeaSource)
		: "rough";
	return {
		id: candidate.id,
		title:
			typeof candidate.title === "string" && candidate.title.trim()
				? candidate.title
				: titleFromIdea(candidate.body, candidate.linkUrl ?? null),
		body: candidate.body,
		linkUrl: typeof candidate.linkUrl === "string" ? candidate.linkUrl : null,
		imageUrl:
			typeof candidate.imageUrl === "string" ? candidate.imageUrl : null,
		audioUrl:
			typeof candidate.audioUrl === "string" ? candidate.audioUrl : null,
		transcript:
			typeof candidate.transcript === "string" ? candidate.transcript : null,
		status,
		accountId:
			typeof candidate.accountId === "string" ? candidate.accountId : null,
		groupId: typeof candidate.groupId === "string" ? candidate.groupId : null,
		source,
		variants: Array.isArray(candidate.variants)
			? candidate.variants.filter((v): v is string => typeof v === "string")
			: [],
		createdAt:
			typeof candidate.createdAt === "string" ? candidate.createdAt : now,
		updatedAt:
			typeof candidate.updatedAt === "string" ? candidate.updatedAt : now,
	};
}

function titleFromIdea(body: string, linkUrl: string | null): string {
	const firstLine = body
		.split("\n")
		.map((line) => line.trim())
		.find(Boolean);
	if (firstLine) return firstLine.slice(0, 72);
	if (linkUrl) {
		try {
			return new URL(linkUrl).hostname.replace(/^www\./, "");
		} catch {
			return "Link idea";
		}
	}
	return "Untitled idea";
}

function buildIdeaCaption(idea: IdeaItem, variant?: string): string {
	const parts = [variant ?? idea.body, idea.transcript, idea.linkUrl]
		.map((part) => part?.trim())
		.filter(Boolean);
	return parts.join("\n\n");
}

function remoteSafeIdea(idea: IdeaItem): IdeaItem {
	return {
		...idea,
		// Browser-captured data URLs can exceed practical settings payload size.
		// Keep them local; URL-backed media still roams across devices.
		imageUrl: idea.imageUrl?.startsWith("data:") ? null : idea.imageUrl,
		audioUrl: idea.audioUrl?.startsWith("data:") ? null : idea.audioUrl,
	};
}

function parseIdeasSetting(value: unknown): IdeaItem[] {
	if (!value || typeof value !== "object") return [];
	const ideas = (value as { ideas?: unknown }).ideas;
	if (!Array.isArray(ideas)) return [];
	return ideas.map(normalizeIdea).filter((item): item is IdeaItem => !!item);
}

function mergeIdeas(local: IdeaItem[], remote: IdeaItem[]): IdeaItem[] {
	const byId = new Map<string, IdeaItem>();
	for (const idea of [...remote, ...local]) {
		const existing = byId.get(idea.id);
		if (!existing) {
			byId.set(idea.id, idea);
			continue;
		}
		const ideaTime = Date.parse(idea.updatedAt);
		const existingTime = Date.parse(existing.updatedAt);
		if (
			Number.isFinite(ideaTime) &&
			(!Number.isFinite(existingTime) || ideaTime >= existingTime)
		) {
			byId.set(idea.id, idea);
		}
	}
	return Array.from(byId.values()).sort(
		(a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt),
	);
}

function dataUrlBytes(dataUrl: string): number {
	const comma = dataUrl.indexOf(",");
	const payload = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
	return Math.ceil((payload.length * 3) / 4);
}

function readFileAsDataUrl(file: File): Promise<string> {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () =>
			typeof reader.result === "string"
				? resolve(reader.result)
				: reject(new Error("Could not read file"));
		reader.onerror = () =>
			reject(reader.error ?? new Error("Could not read file"));
		reader.readAsDataURL(file);
	});
}

function formatRelativeDate(value: string): string {
	const time = new Date(value).getTime();
	if (!Number.isFinite(time)) return "Recently";
	const diff = Date.now() - time;
	const minutes = Math.max(1, Math.round(diff / 60_000));
	if (minutes < 60) return `${minutes}m ago`;
	const hours = Math.round(minutes / 60);
	if (hours < 24) return `${hours}h ago`;
	const days = Math.round(hours / 24);
	return `${days}d ago`;
}

function captionsDataUrl(text: string | null | undefined): string {
	const caption = (text?.trim() || "Voice note audio").replace(/\r/g, "");
	return `data:text/vtt;charset=utf-8,${encodeURIComponent(`WEBVTT\n\n00:00:00.000 --> 99:59:59.000\n${caption}\n`)}`;
}

export function Ideas() {
	const navigate = useNavigate();
	const [searchParams, setSearchParams] = useSearchParams();
	const authUser = useAuthUser();
	const { accounts } = useConnectedAccounts();
	const { groups } = useAccountGroups();
	const storageKey = ideasStorageKey(authUser?.id ?? null);
	const [ideas, setIdeas] = useState<IdeaItem[]>([]);
	const [loadedKey, setLoadedKey] = useState<string | null>(null);
	const [source, setSource] = useState<IdeaSource>("rough");
	const [body, setBody] = useState("");
	const [linkUrl, setLinkUrl] = useState("");
	const [imageUrl, setImageUrl] = useState("");
	const [audioUrl, setAudioUrl] = useState<string | null>(null);
	const [transcript, setTranscript] = useState("");
	const [accountId, setAccountId] = useState("");
	const [groupId, setGroupId] = useState("");
	const [variantBusyId, setVariantBusyId] = useState<string | null>(null);
	const [recording, setRecording] = useState(false);
	const [remoteReady, setRemoteReady] = useState(false);
	const [selectedIdeaId, setSelectedIdeaId] = useState<string | null>(null);
	const quickCaptureRef = useRef<HTMLInputElement | null>(null);
	const recorderRef = useRef<MediaRecorder | null>(null);
	const chunksRef = useRef<Blob[]>([]);
	const hydratedRouteContextRef = useRef<string | null>(null);

	useEffect(() => {
		let cancelled = false;
		setRemoteReady(false);
		try {
			const raw = window.localStorage.getItem(storageKey);
			const parsed = raw ? JSON.parse(raw) : [];
			const local = Array.isArray(parsed)
				? parsed.map(normalizeIdea).filter((item): item is IdeaItem => !!item)
				: [];
			setIdeas(local);
			if (!authUser) {
				setRemoteReady(true);
			} else {
				void getUserSetting(authUser.id, REMOTE_SETTING_KEY)
					.then((setting) => {
						if (cancelled) return;
						const remote = parseIdeasSetting(setting);
						const next = mergeIdeas(local, remote);
						setIdeas(next);
						window.localStorage.setItem(storageKey, JSON.stringify(next));
					})
					.catch(() => {
						/* local board stays authoritative until remote is reachable */
					})
					.finally(() => {
						if (!cancelled) setRemoteReady(true);
					});
			}
		} catch {
			setIdeas([]);
			setRemoteReady(true);
		}
		setLoadedKey(storageKey);
		return () => {
			cancelled = true;
		};
	}, [storageKey, authUser]);

	useEffect(() => {
		if (loadedKey !== storageKey) return;
		try {
			window.localStorage.setItem(storageKey, JSON.stringify(ideas));
		} catch {
			appToast.warn("Ideas saved for this session only", {
				description:
					"Browser storage is full. Remove large attachments to persist.",
			});
		}
	}, [ideas, loadedKey, storageKey]);

	useEffect(() => {
		if (!authUser || loadedKey !== storageKey || !remoteReady) return;
		const timer = window.setTimeout(() => {
			void upsertUserSetting(authUser.id, REMOTE_SETTING_KEY, {
				ideas: ideas.map(remoteSafeIdea),
				updatedAt: new Date().toISOString(),
			}).catch(() => {
				/* localStorage remains the fast-path/offline copy */
			});
		}, 800);
		return () => window.clearTimeout(timer);
	}, [authUser, ideas, loadedKey, remoteReady, storageKey]);

	useEffect(() => {
		const raw = searchParams.toString();
		if (!raw || hydratedRouteContextRef.current === raw) return;
		hydratedRouteContextRef.current = raw;

		const nextAccountId = searchParams.get("accountId");
		const nextGroupId = searchParams.get("group");
		const nextBody = searchParams.get("body");
		const nextSource = searchParams.get("source");
		if (nextAccountId) setAccountId(nextAccountId);
		if (nextGroupId) setGroupId(nextGroupId);
		if (nextBody) setBody((current) => current || nextBody);
		if (
			nextSource === "rough" ||
			nextSource === "link" ||
			nextSource === "screenshot" ||
			nextSource === "voice"
		) {
			setSource(nextSource);
		}

		if (nextAccountId || nextGroupId || nextBody || nextSource) {
			const cleaned = new URLSearchParams(searchParams);
			cleaned.delete("accountId");
			cleaned.delete("account");
			cleaned.delete("platform");
			cleaned.delete("group");
			cleaned.delete("accounts");
			cleaned.delete("body");
			cleaned.delete("source");
			setSearchParams(cleaned, { replace: true });
		}
	}, [searchParams, setSearchParams]);

	const accountsById = useMemo(
		() => new Map(accounts.map((account) => [account.id, account])),
		[accounts],
	);
	const groupsById = useMemo(
		() => new Map(groups.map((group) => [group.id, group])),
		[groups],
	);
	const stats = useMemo(() => getIdeaDraftSummary(ideas), [ideas]);
	const rankedIdeas = useMemo(
		() =>
			[...ideas].sort((a, b) => {
				const scoreDelta = getIdeaSignalScore(b) - getIdeaSignalScore(a);
				if (scoreDelta !== 0) return scoreDelta;
				return Date.parse(b.updatedAt) - Date.parse(a.updatedAt);
			}),
		[ideas],
	);
	const selectedIdea = useMemo(
		() =>
			rankedIdeas.find((idea) => idea.id === selectedIdeaId) ??
			rankedIdeas[0] ??
			null,
		[rankedIdeas, selectedIdeaId],
	);

	useEffect(() => {
		if (!selectedIdeaId) return;
		if (!ideas.some((idea) => idea.id === selectedIdeaId)) {
			setSelectedIdeaId(null);
		}
	}, [ideas, selectedIdeaId]);

	const canSave =
		body.trim().length > 0 ||
		linkUrl.trim().length > 0 ||
		imageUrl.trim().length > 0 ||
		audioUrl !== null ||
		transcript.trim().length > 0;

	const resetForm = () => {
		setBody("");
		setLinkUrl("");
		setImageUrl("");
		setAudioUrl(null);
		setTranscript("");
		setAccountId("");
		setGroupId("");
		setSource("rough");
	};

	const saveIdea = () => {
		if (!canSave) {
			appToast.info("Add a thought, link, screenshot, or voice note first.");
			return;
		}
		const now = new Date().toISOString();
		const idea: IdeaItem = {
			id: randomUUID(),
			title: titleFromIdea(body, linkUrl.trim() || null),
			body: body.trim(),
			linkUrl: linkUrl.trim() || null,
			imageUrl: imageUrl.trim() || null,
			audioUrl,
			transcript: transcript.trim() || null,
			status: "inbox",
			accountId: accountId || null,
			groupId: groupId || null,
			source,
			variants: [],
			createdAt: now,
			updatedAt: now,
		};
		setIdeas((prev) => [idea, ...prev]);
		resetForm();
		appToast.success("Idea captured");
	};

	const updateIdea = useCallback((id: string, patch: Partial<IdeaItem>) => {
		setIdeas((prev) =>
			prev.map((idea) =>
				idea.id === id
					? { ...idea, ...patch, updatedAt: new Date().toISOString() }
					: idea,
			),
		);
	}, []);

	const deleteIdea = useCallback((id: string) => {
		setIdeas((prev) => prev.filter((idea) => idea.id !== id));
	}, []);

	const onImageFile = async (file: File | undefined) => {
		if (!file) return;
		if (!file.type.startsWith("image/")) {
			appToast.error("Choose an image file");
			return;
		}
		const dataUrl = await readFileAsDataUrl(file);
		if (dataUrlBytes(dataUrl) > MAX_DATA_URL_BYTES) {
			appToast.error("Screenshot is too large", {
				description: "Use an image under 1.2 MB or paste a hosted URL.",
			});
			return;
		}
		setImageUrl(dataUrl);
		setSource("screenshot");
	};

	const toggleRecording = async () => {
		if (recording) {
			recorderRef.current?.stop();
			return;
		}
		if (
			!navigator.mediaDevices?.getUserMedia ||
			typeof MediaRecorder === "undefined"
		) {
			appToast.warn("Voice recording is not available in this browser.");
			return;
		}
		try {
			const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
			const recorder = new MediaRecorder(stream);
			chunksRef.current = [];
			recorder.ondataavailable = (event) => {
				if (event.data.size > 0) chunksRef.current.push(event.data);
			};
			recorder.onstop = async () => {
				for (const track of stream.getTracks()) track.stop();
				setRecording(false);
				const blob = new Blob(chunksRef.current, { type: recorder.mimeType });
				const dataUrl = await readFileAsDataUrl(
					new File([blob], "voice-note.webm", { type: recorder.mimeType }),
				);
				if (dataUrlBytes(dataUrl) > MAX_DATA_URL_BYTES) {
					appToast.error("Voice note is too large", {
						description:
							"Keep captures short or add the transcript text instead.",
					});
					return;
				}
				setAudioUrl(dataUrl);
				setSource("voice");
			};
			recorderRef.current = recorder;
			recorder.start();
			setRecording(true);
		} catch (err) {
			appToast.error("Could not start voice recording", {
				description: err instanceof Error ? err.message : undefined,
			});
		}
	};

	const expandIdea = async (idea: IdeaItem) => {
		if (variantBusyId) return;
		setVariantBusyId(idea.id);
		try {
			const variants = await generateComposerVariants({
				caption: buildIdeaCaption(idea),
				accountId: idea.accountId,
				draftId: null,
			});
			updateIdea(idea.id, {
				status: "shaping",
				variants: variants.map((variant) => variant.content).filter(Boolean),
			});
			appToast.success("Variants generated");
		} catch (err) {
			appToast.error("Could not expand idea", {
				description: err instanceof Error ? err.message : undefined,
			});
		} finally {
			setVariantBusyId(null);
		}
	};

	const composeIdea = (idea: IdeaItem, variant?: string) => {
		const handoff: IdeaHandoff = {
			id: idea.id,
			content: buildIdeaCaption(idea, variant),
			accountId: idea.accountId,
			groupId: idea.groupId,
			linkUrl: idea.linkUrl,
			imageUrl: idea.imageUrl,
			imageName: idea.imageUrl
				? `${idea.title || "Idea screenshot"}.png`
				: null,
			label: "Idea loaded",
		};
		window.sessionStorage.setItem(
			"juno33:composer-idea",
			JSON.stringify(handoff),
		);
		updateIdea(idea.id, { status: "used" });
		navigate("/composer", { state: { ideaHandoff: handoff } });
	};

	const groupedIdeas = useMemo(
		() =>
			STATUS_COLUMNS.map((column) => ({
				...column,
				ideas: ideas.filter((idea) => idea.status === column.id),
			})),
		[ideas],
	);

	return (
		<NovaScreen width="wide" density="compact">
			<NovaHeader
				eyebrow="Ideas"
				title="Idea Lab"
				meta={`${ideas.length} drafts · ${stats.variants} variants`}
				description="Generate, refine, and save content angles that match your voice."
				actions={
					<NovaToolbar>
						<Button
							type="button"
							onClick={() =>
								void (rankedIdeas[0] ? expandIdea(rankedIdeas[0]) : saveIdea())
							}
							disabled={variantBusyId !== null || (!rankedIdeas[0] && !canSave)}
							variant="outline"
							size="sm"
						>
							<Sparkles data-icon="inline-start" aria-hidden="true" />
							Generate ideas
						</Button>
						<Button type="button" onClick={saveIdea} disabled={!canSave} size="sm">
							<Plus data-icon="inline-start" aria-hidden="true" />
							Capture
						</Button>
					</NovaToolbar>
				}
			/>

			<NovaSection className="grid items-start gap-4 xl:grid-cols-[20rem_minmax(0,1fr)_20rem]">
				<IdeaCapturePanel
					source={source}
					quickInputRef={quickCaptureRef}
					onSourceChange={setSource}
					body={body}
					onBodyChange={setBody}
					linkUrl={linkUrl}
					onLinkUrlChange={(value) => {
						setLinkUrl(value);
						if (value.trim()) setSource("link");
					}}
					imageUrl={imageUrl}
					onImageUrlChange={(value) => {
						setImageUrl(value);
						if (value.trim()) setSource("screenshot");
					}}
					onImageFile={onImageFile}
					transcript={transcript}
					onTranscriptChange={(value) => {
						setTranscript(value);
						if (value.trim()) setSource("voice");
					}}
					audioUrl={audioUrl}
					recording={recording}
					onToggleRecording={() => void toggleRecording()}
					accountId={accountId}
					onAccountIdChange={setAccountId}
					groupId={groupId}
					onGroupIdChange={setGroupId}
					accounts={accounts}
					groups={groups}
					stats={stats}
					canSave={canSave}
					onSave={saveIdea}
				/>

				<NovaSection>
					<IdeaAnglesList
						ideas={rankedIdeas}
						accountsById={accountsById}
						groupsById={groupsById}
						selectedId={selectedIdea?.id ?? null}
						onSelect={setSelectedIdeaId}
						onStatus={(idea, status) => updateIdea(idea.id, { status })}
						onDelete={(idea) => deleteIdea(idea.id)}
						onExpand={(idea) => void expandIdea(idea)}
						onCompose={(idea, variant) => composeIdea(idea, variant)}
						variantBusyId={variantBusyId}
					/>
					<IdeaDraftBuckets
						groupedIdeas={groupedIdeas}
						onStatus={(idea, status) => updateIdea(idea.id, { status })}
						onDelete={(idea) => deleteIdea(idea.id)}
						onExpand={(idea) => void expandIdea(idea)}
						onCompose={(idea, variant) => composeIdea(idea, variant)}
						variantBusyId={variantBusyId}
						onNewBrief={() => {
							quickCaptureRef.current?.scrollIntoView({
								behavior: "smooth",
								block: "center",
							});
							quickCaptureRef.current?.focus();
						}}
					/>
				</NovaSection>

				<IdeaInspector
					idea={selectedIdea}
					accountLabel={
						selectedIdea?.accountId
							? (accountsById.get(selectedIdea.accountId)?.handle ?? "Account")
							: null
					}
					groupLabel={
						selectedIdea?.groupId
							? (groupsById.get(selectedIdea.groupId)?.name ?? "Group")
							: null
					}
					onExpand={
						selectedIdea ? () => void expandIdea(selectedIdea) : undefined
					}
					onCompose={selectedIdea ? () => composeIdea(selectedIdea) : undefined}
					expanding={selectedIdea ? variantBusyId === selectedIdea.id : false}
				/>
			</NovaSection>
		</NovaScreen>
	);
}

type DraftSummary = ReturnType<typeof getIdeaDraftSummary>;
type AccountOption = { id: string; handle: string; platform: string };
type GroupOption = { id: string; name: string };

function IdeaCapturePanel({
	source,
	quickInputRef,
	onSourceChange,
	body,
	onBodyChange,
	linkUrl,
	onLinkUrlChange,
	imageUrl,
	onImageUrlChange,
	onImageFile,
	transcript,
	onTranscriptChange,
	audioUrl,
	recording,
	onToggleRecording,
	accountId,
	onAccountIdChange,
	groupId,
	onGroupIdChange,
	accounts,
	groups,
	stats,
	canSave,
	onSave,
}: {
	source: IdeaSource;
	quickInputRef: RefObject<HTMLInputElement | null>;
	onSourceChange: (source: IdeaSource) => void;
	body: string;
	onBodyChange: (value: string) => void;
	linkUrl: string;
	onLinkUrlChange: (value: string) => void;
	imageUrl: string;
	onImageUrlChange: (value: string) => void;
	onImageFile: (file: File | undefined) => Promise<void>;
	transcript: string;
	onTranscriptChange: (value: string) => void;
	audioUrl: string | null;
	recording: boolean;
	onToggleRecording: () => void;
	accountId: string;
	onAccountIdChange: (value: string) => void;
	groupId: string;
	onGroupIdChange: (value: string) => void;
	accounts: AccountOption[];
	groups: GroupOption[];
	stats: DraftSummary;
	canSave: boolean;
	onSave: () => void;
}) {
	return (
		<NovaCard
			title="Capture brief"
			description="Save rough thoughts, links, screenshots, and voice notes."
			contentClassName="p-0"
		>
			<div className="flex flex-col gap-2 border-b border-border p-4 sm:flex-row">
				<div className="relative min-w-0 flex-1">
					<ClipboardList
						className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
						aria-hidden="true"
					/>
					<Input
						ref={quickInputRef}
						value={body}
						onChange={(event) => onBodyChange(event.target.value)}
						placeholder="Quick capture... e.g. product update, holiday, campaign"
						className="pl-9"
					/>
				</div>
				<Button
					type="button"
					onClick={onSave}
					disabled={!canSave}
					variant="outline"
					size="sm"
					className="shrink-0"
				>
					<Plus data-icon="inline-start" aria-hidden="true" />
					Capture
				</Button>
			</div>

			<NovaToolbar className="border-b border-border p-4">
				{SOURCE_OPTIONS.map((option) => (
					<Button
						key={option.id}
						type="button"
						variant={source === option.id ? "default" : "outline"}
						size="sm"
						onClick={() => onSourceChange(option.id)}
						aria-pressed={source === option.id}
						className="min-h-10 justify-center gap-1.5 px-2 text-[0.75rem]"
					>
						<option.icon data-icon="inline-start" aria-hidden="true" />
						{option.label}
					</Button>
				))}
			</NovaToolbar>

			<div className="flex flex-col gap-4 p-4">
				<div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
					<label htmlFor="ideas-account-filter" className="block">
						<span className="mb-1.5 block text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
							Account
						</span>
						<Select
							id="ideas-account-filter"
							value={accountId}
							onChange={(event) => onAccountIdChange(event.target.value)}
						>
							<option value="">Any account</option>
							{accounts.map((account) => (
								<option key={account.id} value={account.id}>
									{account.handle} · {account.platform}
								</option>
							))}
						</Select>
					</label>
					<label htmlFor="ideas-group-filter" className="block">
						<span className="mb-1.5 block text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
							Group
						</span>
						<Select
							id="ideas-group-filter"
							value={groupId}
							onChange={(event) => onGroupIdChange(event.target.value)}
						>
							<option value="">No group</option>
							{groups.map((group) => (
								<option key={group.id} value={group.id}>
									{group.name}
								</option>
							))}
						</Select>
					</label>
				</div>

				<label htmlFor="ideas-reference-link" className="block">
					<span className="mb-1.5 block text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
						Reference link
					</span>
					<div className="relative">
						<Link2 className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
						<Input
							id="ideas-reference-link"
							type="url"
							value={linkUrl}
							onChange={(event) => onLinkUrlChange(event.target.value)}
							placeholder="https://"
							className="pl-8"
						/>
					</div>
				</label>

				<label className="block">
					<span className="mb-1.5 block text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
						Screenshot
					</span>
					<div className="flex gap-2">
						<div className="relative flex-1">
							<Image className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
							<Input
								type="url"
								value={imageUrl}
								onChange={(event) => onImageUrlChange(event.target.value)}
								placeholder="Image URL"
								className="pl-8"
							/>
						</div>
						<label className="flex h-9 w-9 cursor-pointer items-center justify-center rounded-md border border-border bg-background hover:bg-muted">
							<Upload
								className="h-3.5 w-3.5 text-muted-foreground"
								aria-hidden="true"
							/>
							<input
								type="file"
								accept="image/*"
								className="sr-only"
								onChange={(event) => void onImageFile(event.target.files?.[0])}
							/>
						</label>
					</div>
					{imageUrl ? (
						<div className="mt-2 aspect-video overflow-hidden rounded-md border border-border bg-muted">
							<img
								src={imageUrl}
								alt=""
								className="h-full w-full object-cover"
							/>
						</div>
					) : null}
				</label>

				<div>
					<div className="mb-1.5 flex items-center justify-between">
						<span className="text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
							Voice note
						</span>
						<Button
							type="button"
							onClick={onToggleRecording}
							variant={recording ? "default" : "outline"}
							size="sm"
							className="h-7"
						>
							{recording ? (
								<Square data-icon="inline-start" aria-hidden="true" />
							) : (
								<Mic data-icon="inline-start" aria-hidden="true" />
							)}
							{recording ? "Stop" : "Record"}
						</Button>
					</div>
					<Textarea
						value={transcript}
						onChange={(event) => onTranscriptChange(event.target.value)}
						placeholder="Transcript, customer phrase, or takeaway"
						rows={1}
					/>
					{audioUrl ? (
						<audio controls src={audioUrl} className="mt-2 h-8 w-full">
							<track
								kind="captions"
								src={captionsDataUrl(transcript)}
								srcLang="en"
								label="Voice note transcript"
							/>
						</audio>
					) : null}
				</div>
			</div>
			<div className="flex flex-wrap gap-2 border-t border-border bg-muted/35 p-4 text-xs text-muted-foreground">
				<span>{stats.inbox} inbox</span>
				<span>{stats.ready} ready</span>
				<span>{stats.variants} generated</span>
			</div>
		</NovaCard>
	);
}

function IdeaAnglesList({
	ideas,
	accountsById,
	groupsById,
	selectedId,
	onSelect,
	onStatus,
	onDelete,
	onExpand,
	onCompose,
	variantBusyId,
}: {
	ideas: IdeaItem[];
	accountsById: Map<string, AccountOption>;
	groupsById: Map<string, GroupOption>;
	selectedId: string | null;
	onSelect: (id: string) => void;
	onStatus: (idea: IdeaItem, status: IdeaStatus) => void;
	onDelete: (idea: IdeaItem) => void;
	onExpand: (idea: IdeaItem) => void;
	onCompose: (idea: IdeaItem, variant?: string) => void;
	variantBusyId: string | null;
}) {
	return (
		<NovaDataPanel
			title="Best match queue"
			description="Generated angles ranked by context, source, and readiness."
			toolbar={
				<Badge tone="oxblood">
					{ideas.length} {ideas.length === 1 ? "angle" : "angles"}
				</Badge>
			}
			className="overflow-hidden"
			contentClassName="p-0"
		>
			<div className="flex items-center gap-2 border-b border-border px-4 py-3 text-sm text-muted-foreground">
				<CircleGauge className="h-3.5 w-3.5" aria-hidden="true" />
				<span>Context quality, source strength, and publish readiness</span>
			</div>
			<div className="flex flex-col gap-2 p-2.5">
				{ideas.length === 0 ? (
					<IdeaEmpty
						icon={Layers}
						title="No angles captured yet"
						description="Add a thought, reference, screenshot, or voice note to populate the lab."
					/>
				) : (
					ideas.map((idea) => (
						<IdeaAngleRow
							key={idea.id}
							idea={idea}
							accountLabel={
								idea.accountId
									? (accountsById.get(idea.accountId)?.handle ?? "Account")
									: null
							}
							groupLabel={
								idea.groupId
									? (groupsById.get(idea.groupId)?.name ?? "Group")
									: null
							}
							selected={selectedId === idea.id}
							onSelect={() => onSelect(idea.id)}
							onStatus={(status) => onStatus(idea, status)}
							onDelete={() => onDelete(idea)}
							onExpand={() => onExpand(idea)}
							onCompose={(variant) => onCompose(idea, variant)}
							expanding={variantBusyId === idea.id}
						/>
					))
				)}
			</div>
		</NovaDataPanel>
	);
}

function IdeaAngleRow({
	idea,
	accountLabel,
	groupLabel,
	selected,
	onSelect,
	onStatus,
	onDelete,
	onExpand,
	onCompose,
	expanding,
}: {
	idea: IdeaItem;
	accountLabel: string | null;
	groupLabel: string | null;
	selected: boolean;
	onSelect: () => void;
	onStatus: (status: IdeaStatus) => void;
	onDelete: () => void;
	onExpand: () => void;
	onCompose: (variant?: string) => void;
	expanding: boolean;
}) {
	const SourceIcon =
		SOURCE_OPTIONS.find((option) => option.id === idea.source)?.icon ??
		Lightbulb;
	const score = getIdeaSignalScore(idea);
	return (
		<article
			className={cn(
				"rounded-md border bg-background transition-colors",
				selected
					? "border-[color-mix(in_srgb,var(--color-oxblood)_52%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-oxblood)_7%,var(--color-card))]"
					: "border-border hover:border-input",
			)}
		>
			<div className="flex flex-col gap-3 px-3 py-2.5 lg:flex-row lg:items-center">
				<Button
					type="button"
					variant="ghost"
					size="sm"
					onClick={onSelect}
					className="h-auto min-w-0 flex-1 justify-start gap-3 p-0 text-left"
				>
					<div className="flex size-12 shrink-0 items-center justify-center rounded-md border border-border bg-muted text-sm font-semibold tabular-nums text-foreground">
						{score}
					</div>
					<div className="min-w-0 flex-1">
						<div className="mb-1.5 flex flex-wrap items-center gap-1.5">
							<Badge tone="outline">{idea.status}</Badge>
							<Badge tone="outline">{idea.source}</Badge>
							{accountLabel ? (
								<Badge tone="outline">{accountLabel}</Badge>
							) : null}
							{groupLabel ? <Badge tone="outline">{groupLabel}</Badge> : null}
						</div>
						<h3 className="break-words text-[0.9375rem] font-semibold leading-snug text-foreground">
							{idea.title}
						</h3>
						<p className="mt-1 line-clamp-1 text-[0.75rem] leading-5 text-muted-foreground">
							{idea.body ||
								idea.transcript ||
								idea.linkUrl ||
								"Ready for context."}
						</p>
					</div>
				</Button>

				<div className="grid grid-cols-[minmax(120px,1fr)_auto_auto_auto] gap-1.5 lg:w-[21rem]">
					<Select
						value={idea.status}
						onChange={(event) => onStatus(event.target.value as IdeaStatus)}
						aria-label="Idea status"
						sizeVariant="sm"
					>
						{STATUS_COLUMNS.map((status) => (
							<option key={status.id} value={status.id}>
								{status.label}
							</option>
						))}
					</Select>
					<Button
						type="button"
						variant="secondary"
						size="icon"
						onClick={onExpand}
						disabled={expanding}
						className="size-8 disabled:opacity-50"
						aria-label="Expand into variants"
					>
						<Sparkles aria-hidden="true" />
					</Button>
					<Button
						type="button"
						variant="secondary"
						size="icon"
						onClick={() => onCompose()}
						className="size-8"
						aria-label="Convert to post"
					>
						<Send aria-hidden="true" />
					</Button>
					<Button
						type="button"
						variant="secondary"
						size="icon"
						onClick={onDelete}
						className="size-8"
						aria-label="Delete idea"
					>
						<Trash2 aria-hidden="true" />
					</Button>
				</div>
			</div>

			{idea.variants.length > 0 ? (
				<div className="mt-3 grid gap-2 md:grid-cols-2">
					{idea.variants.slice(0, 2).map((variant, index) => (
						<Button
							key={`${idea.id}-angle-${index}-${variant.slice(0, 12)}`}
							type="button"
							variant="outline"
							size="sm"
							onClick={() => onCompose(variant)}
							className="h-auto justify-start px-2.5 py-2 text-left text-[0.75rem] leading-5"
						>
							<span className="mb-1 block text-[0.6875rem] font-semibold text-muted-foreground">
								Variant {index + 1}
							</span>
							<span className="line-clamp-2">{variant}</span>
						</Button>
					))}
				</div>
			) : null}
			<div className="border-t border-border/70 px-3 py-2 text-[0.6875rem] uppercase tracking-[0.12em] text-muted-foreground">
				<span className="inline-flex items-center gap-2">
					<SourceIcon className="size-3.5" aria-hidden="true" />
					Updated {formatRelativeDate(idea.updatedAt)}
				</span>
			</div>
		</article>
	);
}

function IdeaInspector({
	idea,
	accountLabel,
	groupLabel,
	onExpand,
	onCompose,
	expanding,
}: {
	idea: IdeaItem | null;
	accountLabel: string | null;
	groupLabel: string | null;
	onExpand: (() => void) | undefined;
	onCompose: (() => void) | undefined;
	expanding: boolean;
}) {
	return (
		<aside className="flex flex-col gap-4 xl:sticky xl:top-4 xl:h-fit">
			<NovaDataPanel
				title="Voice profile"
				description="Signal score, source context, and next actions."
				toolbar={
					<Badge tone="oxblood">
						<InspectionPanel data-icon="inline-start" aria-hidden="true" />
						Inspector
					</Badge>
				}
				contentClassName="p-4"
			>
				{idea ? (
					<div className="flex flex-col gap-3">
						<div className="rounded-md border border-border bg-background/70 p-3">
							<div className="mb-2 flex items-center justify-between gap-3">
								<span className="text-[0.75rem] font-semibold text-muted-foreground">
									Signal score
								</span>
								<span className="text-[1.5rem] font-semibold tabular-nums text-foreground">
									{getIdeaSignalScore(idea)}
								</span>
							</div>
							<Progress value={getIdeaSignalScore(idea)} />
						</div>
						<InspectorLine
							label="Account"
							value={accountLabel ?? "Any account"}
						/>
						<InspectorLine label="Group" value={groupLabel ?? "No group"} />
						<InspectorLine label="Source" value={idea.source} />
						<InspectorLine label="Variants" value={`${idea.variants.length}`} />
						<div className="grid grid-cols-2 gap-2 pt-1">
							<Button
								type="button"
								onClick={onExpand}
								disabled={expanding}
								variant="outline"
								size="sm"
								className="justify-center"
							>
								<Sparkles data-icon="inline-start" aria-hidden="true" />
								Expand
							</Button>
							<Button
								type="button"
								onClick={onCompose}
								size="sm"
								className="justify-center"
							>
								<Send data-icon="inline-start" aria-hidden="true" />
								Compose
							</Button>
						</div>
					</div>
				) : (
					<IdeaEmpty
						icon={Target}
						title="Select an angle"
						description="Captured ideas will show account context, source quality, and next actions here."
					/>
				)}
			</NovaDataPanel>
		</aside>
	);
}

function IdeaDraftBuckets({
	groupedIdeas,
	onStatus,
	onDelete,
	onExpand,
	onCompose,
	variantBusyId,
	onNewBrief,
}: {
	groupedIdeas: Array<(typeof STATUS_COLUMNS)[number] & { ideas: IdeaItem[] }>;
	onStatus: (idea: IdeaItem, status: IdeaStatus) => void;
	onDelete: (idea: IdeaItem) => void;
	onExpand: (idea: IdeaItem) => void;
	onCompose: (idea: IdeaItem, variant?: string) => void;
	variantBusyId: string | null;
	onNewBrief: () => void;
}) {
	return (
		<NovaDataPanel
			title="Status shelves"
			description="Move captured ideas from inbox through shaping, ready, and used."
			toolbar={
				<Button
					type="button"
					onClick={onNewBrief}
					variant="outline"
					size="sm"
					aria-label="New brief"
				>
					<Plus data-icon="inline-start" aria-hidden="true" />
					New brief
				</Button>
			}
			className="overflow-hidden"
			contentClassName="p-0"
		>
			<div className="grid gap-3 p-3 md:grid-cols-2 2xl:grid-cols-4">
				{groupedIdeas.map((column) => {
					const primaryIdea = column.ideas[0] ?? null;
					return (
						<article
							key={column.id}
							className="rounded-md border border-border bg-muted/35 p-3"
						>
							<div className="flex items-center justify-between gap-2">
								<div className="flex min-w-0 items-center gap-2">
									<column.icon
										className="size-3.5 shrink-0 text-muted-foreground"
										aria-hidden="true"
									/>
									<h3 className="truncate text-[0.75rem] font-semibold text-foreground">
										{primaryIdea?.title ?? column.label}
									</h3>
								</div>
								<span className="text-[0.75rem] tabular-nums text-muted-foreground">
									{column.ideas.length}
								</span>
							</div>
							<p className="mt-2 line-clamp-2 min-h-10 text-[0.75rem] leading-5 text-muted-foreground">
								{primaryIdea?.body ||
									primaryIdea?.transcript ||
									(primaryIdea ? "Ready for the next pass." : "No ideas")}
							</p>
							<div className="mt-3 flex items-center justify-between gap-2">
								<Badge tone="outline">{column.label}</Badge>
								{primaryIdea ? (
									<div className="flex items-center gap-1">
										<Button
											type="button"
											variant="secondary"
											size="icon"
											onClick={() => onExpand(primaryIdea)}
											disabled={variantBusyId === primaryIdea.id}
											className="size-8"
											aria-label="Expand into variants"
										>
											<Sparkles aria-hidden="true" />
										</Button>
										<Button
											type="button"
											variant="secondary"
											size="icon"
											onClick={() => onCompose(primaryIdea)}
											className="size-8"
											aria-label="Convert to post"
										>
											<Send aria-hidden="true" />
										</Button>
										<Button
											type="button"
											variant="secondary"
											size="icon"
											onClick={() => onDelete(primaryIdea)}
											className="size-8"
											aria-label="Delete idea"
										>
											<Trash2 aria-hidden="true" />
										</Button>
									</div>
								) : null}
							</div>
							{primaryIdea ? (
								<Select
									value={primaryIdea.status}
									onChange={(event) =>
										onStatus(primaryIdea, event.target.value as IdeaStatus)
									}
									aria-label="Idea status"
									sizeVariant="sm"
									className="mt-3"
								>
									{STATUS_COLUMNS.map((status) => (
										<option key={status.id} value={status.id}>
											{status.label}
										</option>
									))}
								</Select>
							) : null}
						</article>
					);
				})}
			</div>
		</NovaDataPanel>
	);
}

function InspectorLine({ label, value }: { label: string; value: string }) {
	return (
		<div className="flex items-center justify-between gap-3 border-b border-border/70 pb-2 text-[0.75rem]">
			<span className="text-muted-foreground">{label}</span>
			<span className="truncate text-right font-medium text-muted-foreground">
				{value}
			</span>
		</div>
	);
}

function IdeaEmpty({
	icon: Icon,
	title,
	description,
}: {
	icon: typeof Lightbulb;
	title: string;
	description: string;
}) {
	return (
		<NovaEmpty
			className="border-0 bg-transparent"
			icon={<Icon aria-hidden="true" />}
			title={title}
			description={description}
		/>
	);
}
