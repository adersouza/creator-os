// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useMemo, useState } from "react";
import { ChevronDown, ChevronUp, ExternalLink, GripVertical, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Checkbox } from "@/components/ui/Checkbox";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Field, FieldLabel } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { cn } from "@/lib/utils";
import { randomUUID } from "@/lib/uuid";
import { LINK_BLOCK_LIBRARY, type LinkBlockType, type LinkItem } from "./types";
import { formatClicks } from "./utils";

const FEATURED_BLOCKS: LinkBlockType[] = [
	"link",
	"animated",
	"scheduled_window",
	"email_capture",
	"tip_jar",
	"affiliate_catalog",
	"bento_media_grid",
];

const ALL_BLOCK_TYPES = LINK_BLOCK_LIBRARY.map((block) => block.type);

function blockMeta(type: LinkBlockType | string | undefined) {
	return (
		LINK_BLOCK_LIBRARY.find((block) => block.type === type) ??
		LINK_BLOCK_LIBRARY[0]
	);
}

export function BlockListEditor({
	items,
	onChange,
}: {
	items: LinkItem[];
	onChange: (items: LinkItem[]) => void;
}) {
	const [selectedId, setSelectedId] = useState<string | null>(null);
	const selected = useMemo(
		() => items.find((item) => item.id === selectedId) ?? items[0] ?? null,
		[items, selectedId],
	);

	const patchItem = (id: string, patch: Partial<LinkItem>) => {
		onChange(
			items.map((item) => (item.id === id ? { ...item, ...patch } : item)),
		);
	};

	const patchMetadata = (
		id: string,
		patch: Record<string, string | boolean | number | null>,
	) => {
		onChange(
			items.map((item) =>
				item.id === id
					? { ...item, metadata: { ...(item.metadata ?? {}), ...patch } }
					: item,
			),
		);
	};

	const removeBlock = (id: string) => {
		onChange(items.filter((item) => item.id !== id));
		setSelectedId((current) => (current === id ? null : current));
	};

	const moveBlock = (id: string, direction: -1 | 1) => {
		const index = items.findIndex((item) => item.id === id);
		const nextIndex = index + direction;
		if (index < 0 || nextIndex < 0 || nextIndex >= items.length) return;
		const next = [...items];
		const [item] = next.splice(index, 1);
		if (!item) return;
		next.splice(nextIndex, 0, item);
		onChange(next);
		setSelectedId(id);
	};

	const addBlock = (type: LinkBlockType) => {
		const meta = blockMeta(type);
		const next: LinkItem = {
			id: randomUUID(),
			title: meta!.defaultTitle,
			url: "",
			clicks: 0,
			blockType: type,
			subtitle: meta!.description,
			metadata: defaultMetadata(type),
		};
		onChange([...items, next]);
		setSelectedId(next.id);
	};

	return (
		<div className="mt-5">
			<div className="flex items-center justify-between mb-2">
				<span className="text-xs font-medium text-muted-foreground">
					Blocks
				</span>
				<Badge tone="outline" className="tabular-nums">
					{items.length} total
				</Badge>
			</div>

			<div className="overflow-hidden rounded-md border border-border bg-card">
				{items.map((item, idx) => {
					const meta = blockMeta(item.blockType);
					return (
						<div
							key={item.id}
							className={cn(
								"group relative flex items-center gap-2 bg-card px-3 py-2.5 transition-colors hover:bg-muted",
								selected?.id === item.id &&
									"bg-[color-mix(in_srgb,var(--color-oxblood)_5%,transparent)]",
								idx !== items.length - 1 && "border-b border-border",
							)}
							onClick={() => setSelectedId(item.id)}
						>
							<span
								aria-hidden="true"
								className="shrink-0 text-muted-foreground transition-colors group-hover:text-foreground"
							>
								<GripVertical />
							</span>
							<span
								aria-hidden="true"
								className="inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-muted text-sm font-medium text-muted-foreground"
							>
								{meta!.icon}
							</span>
							<div className="min-w-0 flex-1">
								<div className="flex items-center gap-2">
									<span className="text-[0.78125rem] font-medium text-foreground truncate">
										{item.title}
									</span>
									<Badge tone="outline" className="hidden sm:inline-flex">
										{meta!.label}
									</Badge>
								</div>
								<div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
									<ExternalLink className="shrink-0" aria-hidden="true" />
									<span className="font-mono truncate">
										{item.url || item.subtitle || meta!.description}
									</span>
								</div>
							</div>
							<span className="shrink-0 text-xs tabular-nums text-muted-foreground">
								{formatClicks(item.clicks)}
							</span>
							<div className="flex shrink-0 items-center gap-0.5">
								<Button
									type="button"
									aria-label={`Move ${item.title} up`}
									variant="ghost"
									size="icon"
									disabled={idx === 0}
									onClick={(event) => {
										event.stopPropagation();
										moveBlock(item.id, -1);
									}}
									className="size-6 text-muted-foreground"
								>
									<ChevronUp aria-hidden="true" />
								</Button>
								<Button
									type="button"
									aria-label={`Move ${item.title} down`}
									variant="ghost"
									size="icon"
									disabled={idx === items.length - 1}
									onClick={(event) => {
										event.stopPropagation();
										moveBlock(item.id, 1);
									}}
									className="size-6 text-muted-foreground"
								>
									<ChevronDown aria-hidden="true" />
								</Button>
							</div>
							<Button
								type="button"
								aria-label={`Remove ${item.title}`}
								variant="ghost"
								size="icon"
								onPointerDown={(event) => event.stopPropagation()}
								onClick={(event) => {
									event.stopPropagation();
									removeBlock(item.id);
								}}
								className="absolute top-1.5 right-1.5 size-5 opacity-0 focus-visible:opacity-100 group-hover:opacity-100"
							>
								<X aria-hidden="true" />
							</Button>
						</div>
					);
				})}
			</div>

			{selected && (
				<BlockSettingsPanel
					item={selected}
					onPatch={(patch) => patchItem(selected.id, patch)}
					onPatchMetadata={(patch) => patchMetadata(selected.id, patch)}
				/>
			)}

			<NovaCard
				variant="panel"
				className="mt-3"
				contentClassName="p-3"
				title="Add block"
				action={<Badge tone="outline">2026 bio-link library</Badge>}
			>
				<div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
					{FEATURED_BLOCKS.map((type) => {
						const meta = blockMeta(type);
						return (
							<Button
								key={type}
								type="button"
								variant="outline"
								size="sm"
								onClick={() => addBlock(type)}
								className="justify-start gap-2 px-2 text-left"
							>
								<span
									aria-hidden="true"
									className="inline-flex size-5 items-center justify-center rounded bg-muted text-xs font-medium text-muted-foreground"
								>
									{meta!.icon}
								</span>
								<span className="min-w-0 truncate text-[0.71875rem] font-medium text-foreground">
									{meta!.label}
								</span>
							</Button>
						);
					})}
				</div>
				<Button
					type="button"
					variant="outline"
					size="sm"
					onClick={() => addBlock("link")}
					className="mt-2 gap-1.5"
				>
					<Plus data-icon="inline-start" aria-hidden="true" />
					Add standard link
				</Button>
			</NovaCard>
		</div>
	);
}

function defaultMetadata(type: LinkBlockType): Record<string, unknown> {
	switch (type) {
		case "scheduled_window":
			return { activeFrom: "", activeTo: "", autoHide: true, eventName: "" };
		case "email_capture":
			return { ctaText: "Join list", provider: "beehiiv", doubleOptIn: true };
		case "tip_jar":
			return {
				paymentUrl: "",
				presets: "3,5,10",
				currency: "USD",
				eventName: "tip_jar_click",
			};
		case "digital_product":
			return {
				fileUrl: "",
				price: "",
				paymentUrl: "",
				eventName: "digital_product_click",
			};
		case "code_gate":
			return { accessCode: "", revealLabel: "Unlock" };
		case "affiliate_catalog":
			return { entries: "", commission: "", boost: false };
		case "bento_media_grid":
			return { mediaUrls: "", source: "manual", layout: "bento" };
		default:
			return {};
	}
}

function metadataString(
	metadata: Record<string, unknown> | undefined,
	key: string,
) {
	const value = metadata?.[key];
	return typeof value === "string" ? value : "";
}

function metadataBoolean(
	metadata: Record<string, unknown> | undefined,
	key: string,
) {
	return metadata?.[key] === true;
}

function BlockSettingsPanel({
	item,
	onPatch,
	onPatchMetadata,
}: {
	item: LinkItem;
	onPatch: (patch: Partial<LinkItem>) => void;
	onPatchMetadata: (
		patch: Record<string, string | boolean | number | null>,
	) => void;
}) {
	const meta = blockMeta(item.blockType);
	const metadata = item.metadata ?? {};

	return (
		<NovaCard
			variant="panel"
			className="mt-3"
			contentClassName="p-3"
			title="Block settings"
			description={`${meta!.label} · ${meta!.description}`}
			action={
				<span className="inline-flex size-8 items-center justify-center rounded-md border border-border bg-muted text-sm font-medium text-muted-foreground">
					{meta!.icon}
				</span>
			}
		>
			<div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
				<Field label="Type">
					<Select
						value={String(item.blockType ?? "link")}
						onChange={(event) =>
							onPatch({
								blockType: event.target.value as LinkBlockType,
								metadata: defaultMetadata(event.target.value as LinkBlockType),
							})
						}
					>
						{ALL_BLOCK_TYPES.map((type) => (
							<option key={type} value={type}>
								{blockMeta(type)!.label}
							</option>
						))}
					</Select>
				</Field>

				<Field label="Label">
					<Input
						value={item.title}
						onChange={(event) => onPatch({ title: event.target.value })}
					/>
				</Field>

				<Field label="Destination">
					<Input
						value={item.url}
						onChange={(event) => onPatch({ url: event.target.value })}
						placeholder="https://..."
						className="font-mono"
					/>
				</Field>

				<Field label="Supporting text">
					<Input
						value={item.subtitle ?? ""}
						onChange={(event) => onPatch({ subtitle: event.target.value })}
						placeholder="Short context shown in editor"
					/>
				</Field>
			</div>

			<BlockSpecificFields
				type={String(item.blockType ?? "link")}
				metadata={metadata}
				onPatchMetadata={onPatchMetadata}
			/>
			<div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3 pt-3 border-t border-border">
				<Field label="Event name">
					<Input
						value={metadataString(metadata, "eventName")}
						onChange={(event) =>
							onPatchMetadata({ eventName: event.target.value })
						}
						placeholder="lead_click"
						className="font-mono"
					/>
				</Field>
				<Field orientation="horizontal" className="min-h-8 items-center gap-2 pb-1">
					<Checkbox
						id="link-block-escape-in-app"
						checked={metadataBoolean(metadata, "escapeInApp")}
						onCheckedChange={(checked) =>
							onPatchMetadata({ escapeInApp: checked === true })
						}
					/>
					<FieldLabel htmlFor="link-block-escape-in-app">
						Escape in-app browser
					</FieldLabel>
				</Field>
			</div>
		</NovaCard>
	);
}

function BlockSpecificFields({
	type,
	metadata,
	onPatchMetadata,
}: {
	type: string;
	metadata: Record<string, unknown>;
	onPatchMetadata: (
		patch: Record<string, string | boolean | number | null>,
	) => void;
}) {
	if (type === "scheduled_window") {
		return (
			<div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-3">
				<Field label="Starts">
					<Input
						type="datetime-local"
						value={metadataString(metadata, "activeFrom")}
						onChange={(event) =>
							onPatchMetadata({ activeFrom: event.target.value })
						}
					/>
				</Field>
				<Field label="Ends">
					<Input
						type="datetime-local"
						value={metadataString(metadata, "activeTo")}
						onChange={(event) =>
							onPatchMetadata({ activeTo: event.target.value })
						}
					/>
				</Field>
				<Field orientation="horizontal" className="min-h-8 items-center gap-2 pb-1">
					<Checkbox
						id="link-block-auto-hide"
						checked={metadataBoolean(metadata, "autoHide")}
						onCheckedChange={(checked) =>
							onPatchMetadata({ autoHide: checked === true })
						}
					/>
					<FieldLabel htmlFor="link-block-auto-hide">
						Auto-hide outside window
					</FieldLabel>
				</Field>
			</div>
		);
	}

	if (type === "email_capture") {
		return (
			<div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
				<Field label="CTA text">
					<Input
						value={metadataString(metadata, "ctaText") || "Join list"}
						onChange={(event) =>
							onPatchMetadata({ ctaText: event.target.value })
						}
					/>
				</Field>
				<Field label="ESP">
					<Select
						value={metadataString(metadata, "provider") || "beehiiv"}
						onChange={(event) =>
							onPatchMetadata({ provider: event.target.value })
						}
					>
						<option value="beehiiv">Beehiiv</option>
						<option value="convertkit">ConvertKit</option>
						<option value="mailchimp">Mailchimp</option>
						<option value="custom">Custom webhook</option>
					</Select>
				</Field>
				<Field orientation="horizontal" className="min-h-8 items-center gap-2 pb-1">
					<Checkbox
						id="link-block-double-opt-in"
						checked={metadataBoolean(metadata, "doubleOptIn")}
						onCheckedChange={(checked) =>
							onPatchMetadata({ doubleOptIn: checked === true })
						}
					/>
					<FieldLabel htmlFor="link-block-double-opt-in">
						Double opt-in
					</FieldLabel>
				</Field>
			</div>
		);
	}

	if (type === "tip_jar") {
		return (
			<div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
				<Field label="Payment URL">
					<Input
						value={metadataString(metadata, "paymentUrl")}
						onChange={(event) =>
							onPatchMetadata({ paymentUrl: event.target.value })
						}
						placeholder="https://buy.stripe.com/..."
						className="font-mono"
					/>
				</Field>
				<Field label="Presets">
					<Input
						value={metadataString(metadata, "presets")}
						onChange={(event) =>
							onPatchMetadata({ presets: event.target.value })
						}
						placeholder="3,5,10"
						className="font-mono"
					/>
				</Field>
				<Field label="Currency">
					<Input
						value={metadataString(metadata, "currency") || "USD"}
						onChange={(event) =>
							onPatchMetadata({ currency: event.target.value })
						}
						className="font-mono"
					/>
				</Field>
			</div>
		);
	}

	if (type === "digital_product") {
		return (
			<div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
				<Field label="File URL">
					<Input
						value={metadataString(metadata, "fileUrl")}
						onChange={(event) =>
							onPatchMetadata({ fileUrl: event.target.value })
						}
						placeholder="https://..."
						className="font-mono"
					/>
				</Field>
				<Field label="Price">
					<Input
						value={metadataString(metadata, "price")}
						onChange={(event) => onPatchMetadata({ price: event.target.value })}
						placeholder="$19"
					/>
				</Field>
				<Field label="Payment URL">
					<Input
						value={metadataString(metadata, "paymentUrl")}
						onChange={(event) =>
							onPatchMetadata({ paymentUrl: event.target.value })
						}
						placeholder="https://..."
						className="font-mono"
					/>
				</Field>
			</div>
		);
	}

	if (type === "code_gate") {
		return (
			<div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
				<Field label="Access code">
					<Input
						value={metadataString(metadata, "accessCode")}
						onChange={(event) =>
							onPatchMetadata({ accessCode: event.target.value })
						}
						className="font-mono"
					/>
				</Field>
				<Field label="Button copy">
					<Input
						value={metadataString(metadata, "revealLabel") || "Unlock"}
						onChange={(event) =>
							onPatchMetadata({ revealLabel: event.target.value })
						}
					/>
				</Field>
			</div>
		);
	}

	if (type === "affiliate_catalog") {
		return (
			<div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
				<Field label="Affiliate entries">
					<Textarea
						value={metadataString(metadata, "entries")}
						onChange={(event) =>
							onPatchMetadata({ entries: event.target.value })
						}
						placeholder="Logo | Name | URL, one per line"
						rows={3}
						className="min-h-20 resize-none"
					/>
				</Field>
				<Field label="Commission">
					<Input
						value={metadataString(metadata, "commission")}
						onChange={(event) =>
							onPatchMetadata({ commission: event.target.value })
						}
						placeholder="10%"
					/>
				</Field>
				<Field orientation="horizontal" className="min-h-8 items-center gap-2 pb-1">
					<Checkbox
						id="link-block-boost-commission"
						checked={metadataBoolean(metadata, "boost")}
						onCheckedChange={(checked) =>
							onPatchMetadata({ boost: checked === true })
						}
					/>
					<FieldLabel htmlFor="link-block-boost-commission">
						Boost commission active
					</FieldLabel>
				</Field>
			</div>
		);
	}

	if (type === "bento_media_grid") {
		return (
			<div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
				<Field label="Media URLs">
					<Textarea
						value={metadataString(metadata, "mediaUrls")}
						onChange={(event) =>
							onPatchMetadata({ mediaUrls: event.target.value })
						}
						placeholder="One image or video URL per line"
						rows={3}
						className="min-h-20 resize-none font-mono"
					/>
				</Field>
				<Field label="Source">
					<Select
						value={metadataString(metadata, "source") || "manual"}
						onChange={(event) =>
							onPatchMetadata({ source: event.target.value })
						}
					>
						<option value="manual">Manual</option>
						<option value="instagram">Instagram</option>
						<option value="tiktok">TikTok</option>
					</Select>
				</Field>
				<Field label="Layout">
					<Select
						value={metadataString(metadata, "layout") || "bento"}
						onChange={(event) =>
							onPatchMetadata({ layout: event.target.value })
						}
					>
						<option value="bento">Bento</option>
						<option value="grid">Grid</option>
						<option value="strip">Strip</option>
					</Select>
				</Field>
			</div>
		);
	}

	return null;
}
