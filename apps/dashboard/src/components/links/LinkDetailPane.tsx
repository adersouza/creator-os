// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.

import {
  ArrowUpRight,
  Check,
  Copy,
  ExternalLink,
  ImagePlus,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import type React from "react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { AspectRatio } from "@/components/ui/AspectRatio";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { useTablistKeyboardNav } from "@/hooks/useTablistKeyboardNav";
import { appToast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import {
  getAllMedia,
  type MediaAsset,
  uploadMedia,
} from "@/services/mediaService";
import { AIEnhancePanel } from "./AIEnhancePanel";
import { BlockListEditor } from "./BlockListEditor";
import { PixelExtensionsPanel } from "./PixelExtensionsPanel";
import type { DetailTab, SmartLink, Theme } from "./types";
import { NEW_LINK_PLACEHOLDER_URL, THEME_META } from "./types";
import { formatClicks } from "./utils";

type SmartLinkAppearance = {
  displayTitle: string;
  subtitle: string;
  ctaLabel: string;
  avatarUrl: string;
  avatarMediaId: string;
  imageUrls: string[];
  imageMediaIds: string[];
};

function appearanceFromMetadata(
  metadata: SmartLink["metadata"],
): SmartLinkAppearance {
  const raw =
    metadata?.appearance &&
    typeof metadata.appearance === "object" &&
    !Array.isArray(metadata.appearance)
      ? (metadata.appearance as Record<string, unknown>)
      : {};
  const imageUrls = Array.isArray(raw.imageUrls)
    ? raw.imageUrls.filter((url): url is string => typeof url === "string")
    : [];
  const imageMediaIds = Array.isArray(raw.imageMediaIds)
    ? raw.imageMediaIds.filter((id): id is string => typeof id === "string")
    : [];
  return {
    displayTitle: typeof raw.displayTitle === "string" ? raw.displayTitle : "",
    subtitle: typeof raw.subtitle === "string" ? raw.subtitle : "",
    ctaLabel: typeof raw.ctaLabel === "string" ? raw.ctaLabel : "",
    avatarUrl: typeof raw.avatarUrl === "string" ? raw.avatarUrl : "",
    avatarMediaId:
      typeof raw.avatarMediaId === "string" ? raw.avatarMediaId : "",
    imageUrls,
    imageMediaIds,
  };
}

/* =========================================================================
   DETAIL / EDITOR PANE
   ========================================================================= */
export function LinkDetail({
  link,
  titleRef,
  copiedUtm,
  detailTab,
  onTabChange,
  onPatch,
  onPatchUtm,
  onCopyUtm,
  onApplyUtmToAll,
  onOpenMobilePreview,
}: {
  link: SmartLink;
  titleRef: React.RefObject<HTMLInputElement | null>;
  copiedUtm: boolean;
  detailTab: DetailTab;
  onTabChange: (t: DetailTab) => void;
  onPatch: (patch: Partial<SmartLink>) => void;
  onPatchUtm: (patch: Partial<SmartLink["utm"]>) => void;
  onCopyUtm: () => void;
  onApplyUtmToAll?: (() => void) | undefined;
  onOpenMobilePreview?: () => void;
}) {
  const [aiEnhanceOpen, setAiEnhanceOpen] = useState(false);
  const [appliedAll, setAppliedAll] = useState(false);
  const [mediaItems, setMediaItems] = useState<MediaAsset[]>([]);
  const [mediaLoading, setMediaLoading] = useState(false);
  const [uploadingSlot, setUploadingSlot] = useState<
    "avatar" | "gallery" | null
  >(null);
  const [analyticsRange, setAnalyticsRange] = useState<7 | 14 | 30>(30);
  const avatarInputRef = useRef<HTMLInputElement | null>(null);
  const galleryInputRef = useRef<HTMLInputElement | null>(null);
  const appearance = appearanceFromMetadata(link.metadata);
  const patchAppearance = (patch: Partial<SmartLinkAppearance>) => {
    onPatch({
      metadata: {
        ...(link.metadata ?? {}),
        appearance: {
          ...appearance,
          ...patch,
        },
      },
    });
  };
  useEffect(() => {
    let cancelled = false;
    setMediaLoading(true);
    getAllMedia()
      .then((items) => {
        if (!cancelled) {
          setMediaItems(items.filter((item) => item.fileType === "image"));
        }
      })
      .catch(() => {
        if (!cancelled) setMediaItems([]);
      })
      .finally(() => {
        if (!cancelled) setMediaLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const addGalleryImage = (asset: Pick<MediaAsset, "id" | "url">) => {
    const imageUrls = [...appearance.imageUrls];
    const imageMediaIds = [...appearance.imageMediaIds];
    if (imageUrls.includes(asset.url) || imageMediaIds.includes(asset.id))
      return;
    patchAppearance({
      imageUrls: [...imageUrls, asset.url].slice(0, 3),
      imageMediaIds: [...imageMediaIds, asset.id].slice(0, 3),
    });
  };
  const removeGalleryImage = (index: number) => {
    patchAppearance({
      imageUrls: appearance.imageUrls.filter((_, i) => i !== index),
      imageMediaIds: appearance.imageMediaIds.filter((_, i) => i !== index),
    });
  };
  const handleImageUpload = async (
    slot: "avatar" | "gallery",
    file: File | undefined,
  ) => {
    if (!file?.type.startsWith("image/")) return;
    setUploadingSlot(slot);
    try {
      const result = await uploadMedia({ file });
      setMediaItems((items) => [result.asset, ...items]);
      if (slot === "avatar") {
        patchAppearance({
          avatarUrl: result.publicUrl,
          avatarMediaId: result.asset.id,
        });
        appToast.success("Avatar uploaded");
      } else {
        addGalleryImage(result.asset);
        appToast.success("Gallery photo added");
      }
    } catch {
      appToast.error("Image upload failed", {
        description: "Try another image or upload from the Media Library.",
      });
    } finally {
      setUploadingSlot(null);
    }
  };
  const accentColor = "var(--color-oxblood)";
  const topItem = useMemo(() => {
    return link.items.reduce<(typeof link.items)[number] | null>(
      (a, b) => (!a || b.clicks > a.clicks ? b : a),
      null,
    );
  }, [link.items]);
  const topPct = topItem
    ? Math.round((topItem.clicks / Math.max(1, link.totalClicks)) * 100)
    : 0;
  const rangeClicks = useMemo(
    () =>
      link.last30
        .slice(-analyticsRange)
        .reduce((total, value) => total + value, 0),
    [analyticsRange, link.last30],
  );
  const priorRangeClicks = useMemo(
    () =>
      link.last30
        .slice(-analyticsRange * 2, -analyticsRange)
        .reduce((total, value) => total + value, 0),
    [analyticsRange, link.last30],
  );
  const rangeDeltaPct =
    priorRangeClicks > 0
      ? Math.round(((rangeClicks - priorRangeClicks) / priorRangeClicks) * 100)
      : rangeClicks > 0
        ? 100
        : 0;
  const sortedItems = useMemo(
    () => [...link.items].sort((a, b) => b.clicks - a.clicks),
    [link.items],
  );

  const tabs: { id: DetailTab; label: string }[] = [
    { id: "editor", label: "Editor" },
    { id: "analytics", label: "Analytics" },
    { id: "utm", label: "UTM" },
  ];

  const onTablistKey = useTablistKeyboardNav({
    ids: tabs.map((t) => t.id),
    activeId: detailTab,
    onNavigate: (id) => onTabChange(id as DetailTab),
    orientation: "horizontal",
    scopeSelector: '[data-tablist="link-detail-tabs"]',
  });

  return (
    <NovaCard
      className="flex min-h-0 flex-col p-0"
      contentClassName="flex min-h-0 flex-1 flex-col p-0"
    >
      {/* Header — tabs + context */}
      <header className="px-4 pt-4 pb-0 flex flex-col items-stretch justify-between gap-3 border-b border-border sm:px-5 md:flex-row md:items-center md:gap-4">
        <div
          role="tablist"
          aria-label="Link detail"
          data-tablist="link-detail-tabs"
          onKeyDown={onTablistKey}
          className="flex min-w-0 items-center gap-0 overflow-x-auto"
        >
          {tabs.map((t) => {
            const active = detailTab === t.id;
            return (
              <Button
                key={t.id}
                type="button"
                variant="ghost"
                size="sm"
                role="tab"
                aria-selected={active}
                data-tab-id={t.id}
                tabIndex={active ? 0 : -1}
                onClick={() => onTabChange(t.id)}
                className={cn(
                  "relative rounded-t-md",
                  active
                    ? "text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {t.label}
                {active && (
                  <span
                    className="absolute left-2 right-2 -bottom-px h-[2px] rounded-full"
                    style={{ background: "var(--color-oxblood)" }}
                    aria-hidden="true"
                  />
                )}
              </Button>
            );
          })}
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-2 pb-2 md:justify-end">
          {detailTab === "editor" && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setAiEnhanceOpen(true)}
              className="rounded-full"
            >
              <Sparkles data-icon="inline-start" aria-hidden="true" />
              AI Enhance
            </Button>
          )}
          <span className="inline-flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
            <span
              className="size-1.5 rounded-full"
              style={{ background: accentColor }}
              aria-hidden="true"
            />
            <span className="min-w-0 truncate">
              {link.isActive
                ? "Shared across workspaces"
                : "Inactive until a real destination URL is set"}
            </span>
          </span>
        </div>
      </header>

      <div className="flex-1 min-h-0">
        {detailTab === "editor" && (
          <div className="p-4 grid grid-cols-1 gap-5 sm:p-5 2xl:grid-cols-[minmax(0,1fr)_300px] 2xl:gap-6">
            {/* Editor form */}
            <div className="min-w-0">
              {/* Mobile preview launcher — desktop shows inline phone, mobile shows a button */}
              {onOpenMobilePreview && (
                <Button
                  type="button"
                  variant="outline"
                  size="lg"
                  onClick={onOpenMobilePreview}
                  aria-label={`Open live preview for ${link.title || link.slug}`}
                  className="mb-4 w-full justify-between text-left 2xl:hidden"
                >
                  <span className="inline-flex items-center gap-2.5 min-w-0">
                    <span
                      className="flex size-7 shrink-0 items-center justify-center rounded-md text-xs font-semibold text-primary-foreground"
                      style={{
                        background: `linear-gradient(135deg, ${accentColor}, color-mix(in srgb, var(--color-oxblood) 55%, var(--color-background)))`,
                      }}
                      aria-hidden="true"
                    >
                      {(link.title[0] || "?").toUpperCase()}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-xs font-medium text-muted-foreground leading-none">
                        Live preview
                      </span>
                      <span className="block mt-0.5 text-[0.78125rem] font-medium text-foreground truncate max-w-[200px]">
                        {link.title || link.slug}
                      </span>
                    </span>
                  </span>
                  <span
                    className="text-[0.6875rem] font-medium inline-flex items-center gap-0.5 shrink-0"
                    style={{ color: "var(--color-oxblood)" }}
                  >
                    View
                    <ArrowUpRight aria-hidden="true" />
                  </span>
                </Button>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
                <Field label="Title">
                  <Input
                    ref={titleRef}
                    type="text"
                    value={link.title}
                    onChange={(e) => onPatch({ title: e.target.value })}
                  />
                </Field>
                <Field label="Slug">
                  <div className="relative">
                    <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 font-mono text-sm text-muted-foreground">
                      juno33.link
                    </span>
                    <Input
                      type="text"
                      value={link.slug}
                      onChange={(e) => {
                        const v = e.target.value.startsWith("/")
                          ? e.target.value
                          : `/${e.target.value}`;
                        onPatch({ slug: v });
                      }}
                      className="pl-[78px] font-mono"
                    />
                  </div>
                </Field>
              </div>

              <Field label="Primary URL">
                <Input
                  type="url"
                  value={link.targetUrl}
                  onChange={(e) => {
                    const targetUrl = e.target.value.trim();
                    const isReady =
                      targetUrl.length > 0 &&
                      targetUrl !== NEW_LINK_PLACEHOLDER_URL;
                    onPatch({
                      targetUrl,
                      isActive: isReady,
                    });
                  }}
                  placeholder="https://your-destination.com"
                  leadingIcon={<ExternalLink aria-hidden="true" />}
                />
                {!link.isActive && (
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    This link stays inactive until you replace the placeholder
                    URL with a real destination.
                  </p>
                )}
              </Field>

              <Field label="Theme">
                <div
                  className="flex flex-wrap items-center gap-1.5"
                  role="radiogroup"
                  aria-label="Theme"
                >
                  {(Object.keys(THEME_META) as Theme[]).map((t) => {
                    const meta = THEME_META[t];
                    const active = link.theme === t;
                    return (
                      <Button
                        key={t}
                        type="button"
                        variant={active ? "secondary" : "outline"}
                        size="sm"
                        role="radio"
                        aria-checked={active}
                        onClick={() => onPatch({ theme: t })}
                        className="gap-2"
                      >
                        <span
                          className="size-3 rounded-full border border-border"
                          style={{ background: meta.swatch }}
                          aria-hidden="true"
                        />
                        {meta.label}
                      </Button>
                    );
                  })}
                </div>
              </Field>

              <NovaCard
                className="mt-5"
                variant="panel"
                title="Smart-link preview"
                description="Shown before Instagram opens the destination."
                eyebrow={
                  <span className="inline-flex items-center gap-1.5">
                    <ImagePlus aria-hidden="true" />
                    Interstitial
                  </span>
                }
                action={
                  <Badge tone="outline" className="hidden sm:inline-flex">
                    No auto-open
                  </Badge>
                }
              >
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <Field label="Display title">
                    <Input
                      type="text"
                      value={appearance.displayTitle}
                      onChange={(e) =>
                        patchAppearance({ displayTitle: e.target.value })
                      }
                      placeholder={link.title || "Open this link"}
                    />
                  </Field>
                  <Field label="Button label">
                    <Input
                      type="text"
                      value={appearance.ctaLabel}
                      onChange={(e) =>
                        patchAppearance({ ctaLabel: e.target.value })
                      }
                      placeholder="Open Link"
                    />
                  </Field>
                </div>
                <Field label="Subtitle">
                  <Input
                    type="text"
                    value={appearance.subtitle}
                    onChange={(e) =>
                      patchAppearance({ subtitle: e.target.value })
                    }
                    placeholder="Choose how to open this link."
                  />
                </Field>
                <Field label="Profile photo URL">
                  <Input
                    type="url"
                    value={appearance.avatarUrl}
                    onChange={(e) =>
                      patchAppearance({
                        avatarUrl: e.target.value,
                        avatarMediaId: "",
                      })
                    }
                    placeholder="https://..."
                  />
                </Field>
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <input
                    ref={avatarInputRef}
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={(event) => {
                      void handleImageUpload("avatar", event.target.files?.[0]);
                      event.target.value = "";
                    }}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => avatarInputRef.current?.click()}
                    disabled={uploadingSlot === "avatar"}
                    className="gap-1.5"
                  >
                    <Upload data-icon="inline-start" aria-hidden="true" />
                    {uploadingSlot === "avatar"
                      ? "Uploading..."
                      : "Upload avatar"}
                  </Button>
                  {appearance.avatarUrl && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        patchAppearance({ avatarUrl: "", avatarMediaId: "" })
                      }
                      className="gap-1.5"
                    >
                      <X data-icon="inline-start" aria-hidden="true" />
                      Clear avatar
                    </Button>
                  )}
                </div>
                <Field label="Gallery photos">
                  <Textarea
                    value={appearance.imageUrls.join("\n")}
                    onChange={(e) =>
                      patchAppearance({
                        imageUrls: e.target.value
                          .split(/\r?\n/)
                          .map((url) => url.trim())
                          .filter(Boolean)
                          .slice(0, 3),
                        imageMediaIds: [],
                      })
                    }
                    placeholder={"https://...\nhttps://..."}
                    rows={3}
                    className="min-h-20 resize-none"
                  />
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    Use up to three HTTPS image URLs.
                  </p>
                </Field>
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <input
                    ref={galleryInputRef}
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={(event) => {
                      void handleImageUpload(
                        "gallery",
                        event.target.files?.[0],
                      );
                      event.target.value = "";
                    }}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => galleryInputRef.current?.click()}
                    disabled={
                      uploadingSlot === "gallery" ||
                      appearance.imageUrls.length >= 3
                    }
                    className="gap-1.5"
                  >
                    <Upload data-icon="inline-start" aria-hidden="true" />
                    {uploadingSlot === "gallery"
                      ? "Uploading..."
                      : "Upload gallery"}
                  </Button>
                  {appearance.imageUrls.map((url, index) => (
                    <Button
                      key={`${url}-${index}`}
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => removeGalleryImage(index)}
                      className="relative size-12 overflow-hidden rounded-md border border-border bg-muted p-0"
                      aria-label={`Remove gallery image ${index + 1}`}
                    >
                      <AspectRatio ratio={1} className="w-full">
                        <img
                          src={url}
                          alt=""
                          className="h-full w-full object-cover"
                          loading="lazy"
                        />
                      </AspectRatio>
                      <span className="absolute right-0.5 top-0.5 rounded-full bg-background/90 p-0.5">
                        <X className="h-3 w-3" aria-hidden="true" />
                      </span>
                    </Button>
                  ))}
                </div>
                <NovaCard
                  variant="panel"
                  title="Media Library"
                  contentClassName="pt-0"
                >
                  {mediaLoading ? (
                    <div
                      className="grid grid-cols-4 gap-2 sm:grid-cols-6"
                      role="status"
                      aria-label="Loading media library photos"
                    >
                      {Array.from({ length: 6 }).map((_, index) => (
                        <div key={index} className="min-w-0 space-y-1">
                          <Skeleton className="h-16 w-full rounded-md" />
                          <div className="grid grid-cols-2 gap-1">
                            <Skeleton className="h-6 rounded-md" />
                            <Skeleton className="h-6 rounded-md" />
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : mediaItems.length > 0 ? (
                    <div className="grid grid-cols-4 gap-2 sm:grid-cols-6">
                      {mediaItems.slice(0, 12).map((asset) => (
                        <div key={asset.id} className="min-w-0">
                          <AspectRatio
                            ratio={1}
                            className="overflow-hidden rounded-md border border-border bg-muted"
                          >
                            <img
                              src={asset.url}
                              alt=""
                              className="h-full w-full object-cover"
                              loading="lazy"
                            />
                          </AspectRatio>
                          <div className="mt-1 grid grid-cols-2 gap-1">
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              onClick={() =>
                                patchAppearance({
                                  avatarUrl: asset.url,
                                  avatarMediaId: asset.id,
                                })
                              }
                              className="h-6 px-2 text-[0.625rem]"
                            >
                              Avatar
                            </Button>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              onClick={() => addGalleryImage(asset)}
                              disabled={appearance.imageUrls.length >= 3}
                              className="h-6 px-2 text-[0.625rem]"
                            >
                              Add
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <NovaEmpty
                      className="min-h-24"
                      title="No image media yet"
                      description="Upload an avatar or gallery photo to reuse it here."
                    />
                  )}
                </NovaCard>
              </NovaCard>

              <BlockListEditor
                items={link.items}
                onChange={(items) => onPatch({ items })}
              />
              <PixelExtensionsPanel
                metadata={link.metadata}
                onChange={(metadata) => onPatch({ metadata })}
              />
            </div>

            {/* Smart-link interstitial preview — desktop only; mobile uses a launcher button + overlay */}
            <aside className="hidden 2xl:block justify-self-stretch">
              <div className="sticky top-5">
                <div className="mb-3 flex items-end justify-between gap-3">
                  <div>
                    <div className="text-[0.68rem] font-medium uppercase tracking-wide text-[color:var(--color-oxblood)]">
                      Interstitial
                    </div>
                    <div className="app-caption mt-1 text-muted-foreground">
                      Exact mobile handoff before destination click.
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => onOpenMobilePreview?.()}
                  >
                    Preview
                  </Button>
                </div>
                <SmartLinkInterstitialPreview
                  link={link}
                  appearance={appearance}
                />
              </div>
            </aside>
          </div>
        )}

        {detailTab === "analytics" && (
          <div className="p-5 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="text-xs font-medium text-muted-foreground">
                  Clicks
                </div>
                <div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  <span className="text-[2.25rem] font-medium tracking-[-0.025em] tabular-nums text-foreground leading-none">
                    {formatClicks(rangeClicks)}
                  </span>
                  <span className="text-sm text-muted-foreground">
                    last {analyticsRange} days
                  </span>
                </div>
                <div
                  className="mt-2 inline-flex items-center gap-1 text-[0.71875rem] font-medium tabular-nums"
                  style={{
                    color:
                      rangeDeltaPct >= 0
                        ? "var(--color-oxblood)"
                        : "var(--color-muted-foreground)",
                  }}
                >
                  <ArrowUpRight className="w-3 h-3" aria-hidden="true" />
                  <span>
                    {rangeDeltaPct >= 0 ? "+" : ""}
                    {rangeDeltaPct}%
                  </span>
                  <span className="text-muted-foreground font-normal">
                    vs prior {analyticsRange}d
                  </span>
                </div>
              </div>

              <div className="inline-flex rounded-md border border-border bg-muted p-[3px]">
                {([7, 14, 30] as const).map((range) => (
                  <Button
                    key={range}
                    type="button"
                    variant={analyticsRange === range ? "default" : "ghost"}
                    size="sm"
                    onClick={() => setAnalyticsRange(range)}
                    aria-pressed={analyticsRange === range}
                    className="h-7 px-2.5 text-[0.71875rem]"
                  >
                    {range}d
                  </Button>
                ))}
              </div>
            </div>

            <div className="mt-6 rounded-lg border border-border bg-muted/20 p-4 sm:p-5">
              <ClickTrendChart
                data={link.last30}
                range={analyticsRange}
                color={accentColor}
              />
            </div>

            <div className="mt-7 border-t border-border pt-6">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-xs font-medium text-muted-foreground">
                    Destination breakdown
                  </div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    Share of total clicks by button.
                  </div>
                </div>
                {topItem && (
                  <span
                    className="text-[0.6875rem] font-semibold tabular-nums"
                    style={{ color: "var(--color-oxblood)" }}
                  >
                    Top · {topPct}%
                  </span>
                )}
              </div>
              <DestinationBreakdownChart
                items={sortedItems}
                totalClicks={link.totalClicks}
                color={accentColor}
              />
            </div>
          </div>
        )}

        {detailTab === "utm" && (
          <div className="p-5">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
              <Field label="Source">
                <Input
                  type="text"
                  value={link.utm.source}
                  onChange={(e) => onPatchUtm({ source: e.target.value })}
                  className="font-mono"
                />
              </Field>
              <Field label="Medium">
                <Input
                  type="text"
                  value={link.utm.medium}
                  onChange={(e) => onPatchUtm({ medium: e.target.value })}
                  className="font-mono"
                />
              </Field>
              <Field label="Campaign">
                <Input
                  type="text"
                  value={link.utm.campaign}
                  onChange={(e) => onPatchUtm({ campaign: e.target.value })}
                  className="font-mono"
                />
              </Field>
            </div>

            <Field label="Generated URL">
              <div className="relative break-all rounded-md border border-border bg-muted px-3 py-2.5 font-mono text-sm leading-snug text-muted-foreground">
                juno33.link{link.slug}
                <span className="text-muted-foreground">?utm_source=</span>
                <span className="text-foreground">{link.utm.source}</span>
                <span className="text-muted-foreground">&utm_medium=</span>
                <span className="text-foreground">{link.utm.medium}</span>
                <span className="text-muted-foreground">&utm_campaign=</span>
                <span className="text-foreground">{link.utm.campaign}</span>
              </div>
            </Field>

            <div className="mt-3 flex items-center gap-2">
              <Button type="button" onClick={onCopyUtm} className="gap-1.5">
                {copiedUtm ? (
                  <>
                    <Check data-icon="inline-start" aria-hidden="true" />
                    Copied
                  </>
                ) : (
                  <>
                    <Copy data-icon="inline-start" aria-hidden="true" />
                    Copy URL
                  </>
                )}
              </Button>
              {onApplyUtmToAll && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    onApplyUtmToAll();
                    setAppliedAll(true);
                    window.setTimeout(() => setAppliedAll(false), 1600);
                  }}
                  className="gap-1.5"
                >
                  {appliedAll ? (
                    <>
                      <Check data-icon="inline-start" aria-hidden="true" />
                      Applied
                    </>
                  ) : (
                    <>
                      <Sparkles data-icon="inline-start" aria-hidden="true" />
                      Apply to all
                    </>
                  )}
                </Button>
              )}
            </div>
          </div>
        )}
      </div>
      <AIEnhancePanel
        open={aiEnhanceOpen}
        linkId={link.id}
        blocks={link.items}
        onAccept={(items) => onPatch({ items })}
        onClose={() => setAiEnhanceOpen(false)}
      />
    </NovaCard>
  );
}

function SmartLinkInterstitialPreview({
  link,
  appearance,
}: {
  link: SmartLink;
  appearance: SmartLinkAppearance;
}) {
  const destinationHost = useMemo(() => {
    try {
      return new URL(link.targetUrl).hostname.replace(/^www\./, "");
    } catch {
      return "";
    }
  }, [link.targetUrl]);
  const title = appearance.displayTitle || link.title || "Open this link";
  const subtitle =
    appearance.subtitle ||
    (destinationHost
      ? `Choose how to open ${destinationHost}.`
      : "Choose how to open this link.");
  const ctaLabel = appearance.ctaLabel || "Open Link";
  const avatarUrl = safeHttpsPreviewUrl(appearance.avatarUrl);
  const imageUrls = appearance.imageUrls
    .map(safeHttpsPreviewUrl)
    .filter(Boolean)
    .slice(0, 3);

  return (
    <div className="w-full max-w-[280px] rounded-[30px] border border-border bg-card p-3 shadow-sm">
      <div className="min-h-[430px] rounded-[22px] border border-border bg-popover px-4 py-5 text-center text-popover-foreground">
        {avatarUrl ? (
          <img
            src={avatarUrl}
            alt=""
            className="mx-auto mb-3 h-16 w-16 rounded-full border border-border object-cover"
            loading="lazy"
          />
        ) : (
          <div className="mx-auto mb-3 grid h-16 w-16 place-items-center rounded-full border border-border bg-muted text-xl font-semibold text-foreground">
            {title[0]?.toUpperCase() || "J"}
          </div>
        )}
        {imageUrls.length > 0 && (
          <div
            className="mb-4 grid gap-1.5"
            style={{
              gridTemplateColumns: `repeat(${Math.min(imageUrls.length, 3)}, minmax(0, 1fr))`,
            }}
          >
            {imageUrls.map((url, index) => (
              <img
                key={`${url}-${index}`}
                src={url}
                alt=""
                className="aspect-square w-full rounded-lg border border-border object-cover"
                loading="lazy"
              />
            ))}
          </div>
        )}
        <h3 className="mb-2 text-[1rem] font-semibold leading-tight text-popover-foreground">
          {title}
        </h3>
        <p className="mb-5 text-[0.75rem] leading-relaxed text-muted-foreground">
          {subtitle}
        </p>
        <div className="mb-2 rounded-xl bg-primary px-4 py-3 text-[0.8125rem] font-semibold text-primary-foreground">
          {ctaLabel}
        </div>
        <div className="rounded-xl border border-border bg-muted px-4 py-3 text-[0.8125rem] font-semibold text-muted-foreground">
          Copy Link
        </div>
        <p className="mt-4 text-[0.625rem] leading-relaxed text-muted-foreground">
          If Instagram keeps this inside the app, tap ... then Open in Browser.
          No hidden redirects or auto-launches.
        </p>
      </div>
    </div>
  );
}

function ClickTrendChart({
  data,
  range,
  color,
}: {
  data: number[];
  range: 7 | 14 | 30;
  color: string;
}) {
  const rawGradientId = useId();
  const gradientId = `click-trend-${rawGradientId.replace(/:/g, "")}`;
  const chart = useMemo(() => {
    const values = data.slice(-range);
    const safeValues = values.length > 0 ? values : [0];
    const width = 640;
    const height = 210;
    const pad = { top: 14, right: 14, bottom: 30, left: 42 };
    const innerWidth = width - pad.left - pad.right;
    const innerHeight = height - pad.top - pad.bottom;
    const max = Math.max(1, ...safeValues);
    const ticks = [max, Math.round(max / 2), 0];
    const points = safeValues.map((value, index) => {
      const x =
        pad.left +
        (safeValues.length <= 1
          ? 0
          : (index / (safeValues.length - 1)) * innerWidth);
      const y = pad.top + innerHeight - (value / max) * innerHeight;
      return { value, x, y };
    });
    const path = points
      .map(
        (point, index) =>
          `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`,
      )
      .join(" ");
    const area = `${path} L ${(pad.left + innerWidth).toFixed(2)} ${(pad.top + innerHeight).toFixed(2)} L ${pad.left.toFixed(2)} ${(pad.top + innerHeight).toFixed(2)} Z`;
    return {
      area,
      height,
      innerHeight,
      innerWidth,
      max,
      pad,
      path,
      points,
      ticks,
      values: safeValues,
      width,
    };
  }, [data, range]);

  const lastIndex = chart.points.length - 1;
  return (
    <div>
      <div className="mb-3 flex items-center justify-between text-xs text-muted-foreground">
        <span>Daily clicks</span>
        <span className="tabular-nums">0-{formatClicks(chart.max)}</span>
      </div>
      <svg
        viewBox={`0 0 ${chart.width} ${chart.height}`}
        className="h-[240px] w-full overflow-visible"
        role="img"
        aria-label={`Daily click trend for the last ${range} days`}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.16" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {chart.ticks.map((tick) => {
          const y =
            chart.pad.top +
            chart.innerHeight -
            (tick / Math.max(1, chart.max)) * chart.innerHeight;
          return (
            <g key={tick}>
              <line
                x1={chart.pad.left}
                x2={chart.pad.left + chart.innerWidth}
                y1={y}
                y2={y}
                stroke="color-mix(in srgb, var(--color-foreground) 10%, transparent)"
                strokeWidth="1"
              />
              <text
                x={chart.pad.left - 10}
                y={y + 4}
                textAnchor="end"
                className="fill-muted-foreground text-[11px] tabular-nums"
              >
                {formatClicks(tick)}
              </text>
            </g>
          );
        })}
        <path d={chart.area} fill={`url(#${gradientId})`} />
        <path
          d={chart.path}
          fill="none"
          stroke={color}
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {chart.points.map((point, index) => (
          <g key={`${index}-${point.value}`}>
            <title>{`Day ${index + 1}: ${formatClicks(point.value)} clicks`}</title>
            <circle
              cx={point.x}
              cy={point.y}
              r={index === lastIndex ? 4 : 2.75}
              fill={index === lastIndex ? color : "var(--color-background)"}
              stroke={color}
              strokeWidth="1.5"
              opacity={index === lastIndex || point.value > 0 ? 1 : 0.5}
            />
          </g>
        ))}
        <text
          x={chart.pad.left}
          y={chart.height - 7}
          className="fill-muted-foreground text-[11px]"
        >
          {range}d ago
        </text>
        <text
          x={chart.pad.left + chart.innerWidth}
          y={chart.height - 7}
          textAnchor="end"
          className="fill-muted-foreground text-[11px]"
        >
          Today
        </text>
      </svg>
    </div>
  );
}

function DestinationBreakdownChart({
  items,
  totalClicks,
  color,
}: {
  items: SmartLink["items"];
  totalClicks: number;
  color: string;
}) {
  if (items.length === 0) {
    return (
      <NovaEmpty
        className="min-h-28"
        title="Add destinations"
        description="Add destinations to compare click share."
      />
    );
  }

  const maxClicks = Math.max(1, ...items.map((item) => item.clicks));
  return (
    <div className="flex flex-col gap-4">
      {items.map((item, index) => {
        const pct = Math.round((item.clicks / Math.max(1, totalClicks)) * 100);
        const widthPct = Math.max(
          2,
          Math.round((item.clicks / maxClicks) * 100),
        );
        return (
          <div
            key={item.id}
            className="grid gap-3 sm:grid-cols-[minmax(0,0.8fr)_minmax(220px,1fr)_88px]"
          >
            <div className="min-w-0 flex items-center gap-2">
              <span className="w-4 shrink-0 text-right font-mono text-xs tabular-nums text-muted-foreground">
                {index + 1}
              </span>
              <span className="text-[0.78125rem] font-medium text-foreground truncate">
                {item.title}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <div className="relative h-8 flex-1 overflow-hidden rounded-md bg-muted">
                <div
                  className="absolute inset-y-0 left-0 rounded-md"
                  style={{
                    width: `${widthPct}%`,
                    background:
                      index === 0
                        ? color
                        : "color-mix(in srgb, var(--color-oxblood) 54%, transparent)",
                  }}
                />
              </div>
            </div>
            <div className="flex items-baseline justify-end gap-1.5 tabular-nums">
              <span className="text-[0.78125rem] text-foreground font-medium">
                {formatClicks(item.clicks)}
              </span>
              <span className="text-xs text-muted-foreground">{pct}%</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function safeHttpsPreviewUrl(url: string): string {
  try {
    const parsed = new URL(url.trim());
    return parsed.protocol === "https:" ? parsed.toString() : "";
  } catch {
    return "";
  }
}
