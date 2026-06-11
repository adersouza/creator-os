import { useEffect, useState } from "react";
import { RotateCcw, Save, Sparkles } from "lucide-react";
import { useAccountGroups, type AccountGroup } from "@/hooks/useAccountGroups";
import { appToast } from "@/lib/toast";
import { supabase } from "@/services/supabase";
import {
	fetchVoiceContextFile,
	saveVoiceContextFile,
} from "@/services/api/composer";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Textarea } from "@/components/ui/Textarea";
import { Panel, SectionHeader } from "./shared";

interface VoiceFileState {
	content: string;
	lastEditedAt: string | null;
	loading: boolean;
	saving: boolean;
}

function formatDate(value: string | null) {
	return value ? new Date(value).toLocaleString() : "Not saved yet";
}

async function defaultVoiceContent(groupId: string): Promise<string> {
	const { data } = await supabase
		.from("account_groups")
		.select("voice_profile")
		.eq("id", groupId)
		.maybeSingle();
	return data?.voice_profile ? JSON.stringify(data.voice_profile, null, 2) : "";
}

function VoiceGroupEditor({
	group,
	state,
	onChange,
	onSave,
	onReset,
}: {
	group: AccountGroup;
	state: VoiceFileState;
	onChange: (value: string) => void;
	onSave: () => void;
	onReset: () => void;
}) {
	return (
		<Panel className="flex flex-col gap-3">
			<div className="flex items-start justify-between gap-3">
				<div className="min-w-0">
					<div className="flex items-center gap-2">
						<span
							className="w-2.5 h-2.5 rounded-full"
							style={{ backgroundColor: group.color }}
						/>
						<h2 className="text-[0.9375rem] font-semibold text-foreground">
							{group.name}
						</h2>
					</div>
					<div className="mt-1 text-[0.71875rem] text-muted-foreground">
						{state.loading
							? "Loading..."
							: `Last edited ${formatDate(state.lastEditedAt)}`}
					</div>
				</div>
				<div className="flex gap-2">
					<Button
						type="button"
						onClick={onReset}
						disabled={state.saving || state.loading}
						variant="outline"
						size="sm"
						className="gap-1.5"
					>
						<RotateCcw data-icon="inline-start" aria-hidden="true" />
						Reset
					</Button>
					<Button
						type="button"
						onClick={onSave}
						disabled={state.saving || state.loading}
						size="sm"
						className="gap-1.5"
					>
						<Save data-icon="inline-start" aria-hidden="true" />
						{state.saving ? "Saving..." : "Save"}
					</Button>
				</div>
			</div>
			<Textarea
				value={state.content}
				onChange={(event) => onChange(event.target.value)}
				onBlur={onSave}
				rows={10}
				disabled={state.loading}
				className="min-h-[240px] font-mono"
				placeholder="Write voice rules, banned phrases, examples, audience notes, and top patterns..."
			/>
		</Panel>
	);
}

export function VoiceProfilesEditorTab() {
	const { groups, isLoading } = useAccountGroups();
	const [files, setFiles] = useState<Record<string, VoiceFileState>>({});

	useEffect(() => {
		let cancelled = false;
		groups.forEach((group) => {
			setFiles((prev) => ({
				...prev,
				[group.id]: prev[group.id] ?? {
					content: "",
					lastEditedAt: null,
					loading: true,
					saving: false,
				},
			}));
			fetchVoiceContextFile(group.id)
				.then((file) => {
					if (cancelled) return;
					setFiles((prev) => ({
						...prev,
						[group.id]: {
							content: file.content ?? "",
							lastEditedAt:
								typeof file.last_edited_at === "string"
									? file.last_edited_at
									: null,
							loading: false,
							saving: false,
						},
					}));
				})
				.catch(() => {
					if (cancelled) return;
					setFiles((prev) => ({
						...prev,
						[group.id]: {
							content: "",
							lastEditedAt: null,
							loading: false,
							saving: false,
						},
					}));
				});
		});
		return () => {
			cancelled = true;
		};
	}, [groups]);

	const updateContent = (groupId: string, content: string) => {
		setFiles((prev) => ({
			...prev,
			[groupId]: {
				...(prev[groupId] ?? {
					loading: false,
					saving: false,
					lastEditedAt: null,
				}),
				content,
			},
		}));
	};

	const save = async (groupId: string) => {
		const current = files[groupId];
		if (!current || current.loading || current.saving) return;
		setFiles((prev) => ({ ...prev, [groupId]: { ...current, saving: true } }));
		try {
			const saved = await saveVoiceContextFile(groupId, current.content);
			setFiles((prev) => ({
				...prev,
				[groupId]: {
					content: saved.content ?? current.content,
					lastEditedAt:
						typeof saved.last_edited_at === "string"
							? saved.last_edited_at
							: new Date().toISOString(),
					loading: false,
					saving: false,
				},
			}));
		} catch (err) {
			setFiles((prev) => ({
				...prev,
				[groupId]: { ...current, saving: false },
			}));
			appToast.error("Could not save voice profile", {
				description:
					err instanceof Error ? err.message : "Try again in a moment.",
			});
		}
	};

	const reset = async (groupId: string) => {
		try {
			const content = await defaultVoiceContent(groupId);
			updateContent(groupId, content);
			const saved = await saveVoiceContextFile(groupId, content);
			setFiles((prev) => ({
				...prev,
				[groupId]: {
					content: saved.content ?? content,
					lastEditedAt:
						typeof saved.last_edited_at === "string"
							? saved.last_edited_at
							: new Date().toISOString(),
					loading: false,
					saving: false,
				},
			}));
		} catch (err) {
			appToast.error("Could not reset voice profile", {
				description:
					err instanceof Error ? err.message : "Try again in a moment.",
			});
		}
	};

	return (
		<div className="flex flex-col gap-6">
			<SectionHeader
				title="Voice profiles"
				description="Edit the markdown voice context Composer and AI generation use for each account group."
			/>

			<NovaCard
				variant="panel"
				title="Group-level voice files"
				description={
					<>
						These files live in{" "}
						<span className="font-mono">voice_context_files</span>. Blur saves
						changes; reset rebuilds from the legacy account group voice profile.
					</>
				}
				action={
					<Sparkles className="size-4 text-muted-foreground" aria-hidden="true" />
				}
			/>

			{isLoading ? (
				<Panel>
					<div className="text-[0.8125rem] text-muted-foreground">
						Loading voice profiles...
					</div>
				</Panel>
			) : groups.length === 0 ? (
				<Panel>
					<div className="text-[0.8125rem] text-muted-foreground">
						Create an account group to edit a voice file.
					</div>
				</Panel>
			) : (
				groups.map((group) => (
					<VoiceGroupEditor
						key={group.id}
						group={group}
						state={
							files[group.id] ?? {
								content: "",
								lastEditedAt: null,
								loading: true,
								saving: false,
							}
						}
						onChange={(value) => updateContent(group.id, value)}
						onSave={() => void save(group.id)}
						onReset={() => void reset(group.id)}
					/>
				))
			)}
		</div>
	);
}
