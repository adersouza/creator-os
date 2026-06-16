// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useCallback } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Search, Plus, Link2 } from "lucide-react";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import {
  NovaCard,
  NovaDataPanel,
  NovaEmpty,
  NovaHeader,
  NovaMiniStat,
  NovaSection,
} from "@/components/ui/NovaPrimitives";
import { Progress } from "@/components/ui/Progress";
import { useSmartLinks, type SmartLinkRow } from "@/hooks/useSmartLinks";
import {
  useSmartLinkClickGoal,
  useSmartLinkClickSummary,
} from "@/hooks/useSmartLinkClickGoal";
import { EmptyDetail } from "@/components/links/EmptyDetail";
import { LinkDetail } from "@/components/links/LinkDetailPane";
import { LinkRow } from "@/components/links/LinkRow";
import { MobileLinkPreviewOverlay } from "@/components/links/LinkPagePreview";
import {
  NEW_LINK_PLACEHOLDER_URL,
  type DetailTab,
  type SmartLink,
  type Theme,
} from "@/components/links/types";
import { formatClicks } from "@/components/links/utils";
import { SmartLinksSkeleton } from "@/components/skeletons/PageSkeletons";
import { appToast } from "@/lib/toast";
import {
  getSmartLinkTopPerformer,
  smartLinkTopPerformerCaption,
} from "@/lib/smartLinksSampleGate";

/* =========================================================================
   Smart Links — tracked bio-link manager
   Two-pane operator surface. Matches Inbox / Analytics register (eyebrow,
   solid .card, tabular-nums, signature motion).
   Keyboard: J/K navigate list · Enter focus title · Esc deselect.
   ========================================================================= */

/* =========================================================================
   COMPONENT
   ========================================================================= */

// items/utm/theme now persist to smart_links columns (see migration
// 20260418200100_smart_links_ui_persistence). last30 is the only remaining
// UI-only field — derived per-session.
type UiOverlay = Pick<
  SmartLink,
  "items" | "utm" | "theme" | "last30" | "metadata"
>;

const DEFAULT_THEME: Theme = "ink";
const DEFAULT_UTM = {
  source: "threads",
  medium: "bio",
  campaign: "default",
} as const;

function buildUiOverlay(row: SmartLinkRow): UiOverlay {
  const hasItems = Array.isArray(row.items) && row.items.length > 0;
  const items = hasItems
    ? row.items
    : [
        {
          id: `${row.id}-primary`,
          title: row.title || "Primary destination",
          url: row.targetUrl,
          clicks: row.clickCount,
        },
      ];
  const utm = row.utm
    ? {
        source: row.utm.source ?? DEFAULT_UTM.source,
        medium: row.utm.medium ?? DEFAULT_UTM.medium,
        campaign: row.utm.campaign ?? DEFAULT_UTM.campaign,
      }
    : { ...DEFAULT_UTM };
  const theme: Theme =
    row.theme === "ink" ||
    row.theme === "cream" ||
    row.theme === "oxblood" ||
    row.theme === "vale"
      ? row.theme
      : DEFAULT_THEME;
  return {
    items,
    utm,
    theme,
    metadata: row.metadata ?? undefined,
    last30: Array.from({ length: 30 }, () => 0),
  };
}

function syncOverlayWithRow(row: SmartLinkRow, overlay: UiOverlay): UiOverlay {
  const rest = overlay.items.filter((item) => item.id !== `${row.id}-primary`);
  return {
    ...overlay,
    items: [
      {
        id: `${row.id}-primary`,
        title: row.title || "Primary destination",
        url: row.targetUrl,
        clicks: row.clickCount,
      },
      ...rest,
    ],
  };
}

function relLastEdited(iso: string | null): string {
  if (!iso) return "just now";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "just now";
  const diff = Date.now() - t;
  const min = Math.round(diff / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  if (day < 7) return `${day}d ago`;
  return `${Math.round(day / 7)}w ago`;
}

function mergeRowToUi(row: SmartLinkRow, overlay: UiOverlay): SmartLink {
  const syncedOverlay = syncOverlayWithRow(row, overlay);
  return {
    id: row.id,
    slug: row.code.startsWith("/") ? row.code : `/${row.code}`,
    title: row.title ?? "Untitled link",
    targetUrl: row.targetUrl,
    isActive: row.isActive,
    totalClicks: row.clickCount,
    lastEdited: relLastEdited(row.updatedAt ?? row.createdAt),
    metadata: row.metadata ?? undefined,
    ...syncedOverlay,
  };
}

function uiSlugToCode(slug: string): string {
  return slug.startsWith("/") ? slug.slice(1) : slug;
}

function generateSlug(): string {
  const rand = Math.random().toString(36).slice(2, 7);
  return `link-${rand}`;
}

export function Links() {
  const [searchParams, setSearchParams] = useSearchParams();
  const {
    links: dbLinks,
    isLoading: linksLoading,
    createLink: dbCreateLink,
    updateLink: dbUpdateLink,
    deleteLink: dbDeleteLink,
  } = useSmartLinks();
  const { goal: clickGoal, saveGoal: saveClickGoalSetting } =
    useSmartLinkClickGoal();
  const clickGoalProgress = useSmartLinkClickSummary(clickGoal.periodDays);
  const [clickGoalTargetDraft, setClickGoalTargetDraft] = useState(
    String(clickGoal.targetClicks),
  );
  const [clickGoalDaysDraft, setClickGoalDaysDraft] = useState(
    String(clickGoal.periodDays),
  );
  // Per-id overlay for UI-only fields (linktree items, UTM, theme, etc).
  // Lives for the session; lost on reload — persistence needs schema work.
  const [overlays, setOverlays] = useState<Map<string, UiOverlay>>(
    () => new Map(),
  );
  const [undoableDeleteIds, setUndoableDeleteIds] = useState<Set<string>>(
    () => new Set(),
  );
  const allLinks = useMemo<SmartLink[]>(() => {
    return dbLinks.map((row) => {
      const overlay = overlays.get(row.id) ?? buildUiOverlay(row);
      return mergeRowToUi(row, overlay);
    });
  }, [dbLinks, overlays]);
  const links = useMemo(
    () => allLinks.filter((link) => !undoableDeleteIds.has(link.id)),
    [allLinks, undoableDeleteIds],
  );
  const [activeId, setActiveId] = useState<string | null>(null);

  // Auto-select first link once data hydrates
  useEffect(() => {
    if (!activeId && links.length > 0) setActiveId(links[0]!.id);
  }, [links, activeId]);
  const [search, setSearch] = useState("");
  const [copiedUrl, setCopiedUrl] = useState<string | null>(null);
  const [copiedUtm, setCopiedUtm] = useState(false);
  const [detailTab, setDetailTab] = useState<DetailTab>("editor");
  const [focusTitleOnNextFrame, setFocusTitleOnNextFrame] = useState(false);
  const [mobilePreviewOpen, setMobilePreviewOpen] = useState(false);
  const [pendingDeleteLink, setPendingDeleteLink] = useState<SmartLink | null>(
    null,
  );
  const [deleteBusy, setDeleteBusy] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const copiedUrlTimerRef = useRef<number | null>(null);
  const copiedUtmTimerRef = useRef<number | null>(null);

  useEffect(() => {
    setClickGoalTargetDraft(String(clickGoal.targetClicks));
    setClickGoalDaysDraft(String(clickGoal.periodDays));
  }, [clickGoal.periodDays, clickGoal.targetClicks]);

  useEffect(() => {
    const focusLinksSearch = () => {
      setSearch("");
      window.requestAnimationFrame(() => searchInputRef.current?.focus());
    };

    window.addEventListener("juno33:links-search", focusLinksSearch);
    return () => {
      window.removeEventListener("juno33:links-search", focusLinksSearch);
      if (copiedUrlTimerRef.current != null) {
        window.clearTimeout(copiedUrlTimerRef.current);
      }
      if (copiedUtmTimerRef.current != null) {
        window.clearTimeout(copiedUtmTimerRef.current);
      }
    };
  }, []);

  /* Filter */
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return links.filter((l) => {
      if (q) {
        const hay = `${l.title} ${l.slug}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [links, search]);

  const active = useMemo(
    () => filtered.find((l) => l.id === activeId) ?? filtered[0] ?? null,
    [filtered, activeId],
  );

  useEffect(() => {
    if (active && activeId !== active.id) setActiveId(active.id);
    if (!active && activeId !== null) setActiveId(null);
  }, [active, activeId]);

  useEffect(() => {
    if (!focusTitleOnNextFrame || !active) return;
    const id = window.requestAnimationFrame(() => {
      titleRef.current?.focus();
      titleRef.current?.select();
    });
    setFocusTitleOnNextFrame(false);
    return () => window.cancelAnimationFrame(id);
  }, [focusTitleOnNextFrame, active]);

  /* Actions */
  const copyUrl = async (slug: string) => {
    const url = `juno33.link${slug}`;
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      appToast.error("Could not copy to clipboard");
      return;
    }
    setCopiedUrl(slug);
    appToast.success("Smart link copied");
    if (copiedUrlTimerRef.current != null) {
      window.clearTimeout(copiedUrlTimerRef.current);
    }
    copiedUrlTimerRef.current = window.setTimeout(() => {
      setCopiedUrl((s) => (s === slug ? null : s));
      copiedUrlTimerRef.current = null;
    }, 1600);
  };

  const openPublicLink = (slug: string) => {
    window.open(`https://juno33.link${slug}`, "_blank", "noopener,noreferrer");
  };

  const synthesizeRow = (link: SmartLink): SmartLinkRow => ({
    id: link.id,
    code: uiSlugToCode(link.slug),
    title: link.title,
    targetUrl: link.targetUrl,
    clickCount: link.totalClicks,
    isActive: link.isActive,
    postId: null,
    createdAt: null,
    updatedAt: null,
    utm: null,
    theme: null,
    items: [],
    blocks: [],
    metadata: link.metadata ?? null,
  });

  const updateActive = (patch: Partial<SmartLink>) => {
    if (!active) return;
    // DB-backed fields — persist via the hook.
    if (
      patch.title !== undefined ||
      patch.slug !== undefined ||
      patch.targetUrl !== undefined ||
      patch.isActive !== undefined ||
      patch.items !== undefined ||
      patch.theme !== undefined ||
      patch.metadata !== undefined
    ) {
      void dbUpdateLink(active.id, {
        ...(patch.title !== undefined ? { title: patch.title } : {}),
        ...(patch.slug !== undefined ? { code: uiSlugToCode(patch.slug) } : {}),
        ...(patch.targetUrl !== undefined
          ? { targetUrl: patch.targetUrl }
          : {}),
        ...(patch.isActive !== undefined ? { isActive: patch.isActive } : {}),
        ...(patch.items !== undefined ? { items: patch.items } : {}),
        ...(patch.theme !== undefined ? { theme: patch.theme } : {}),
        ...(patch.metadata !== undefined ? { metadata: patch.metadata } : {}),
      });
    }
    // UI-only overlay carries last30 + an optimistic copy of items/theme so the
    // edit shows immediately while the DB round-trip lands.
    const uiOnly: Partial<UiOverlay> = {};
    if (patch.items !== undefined) uiOnly.items = patch.items;
    if (patch.theme !== undefined) uiOnly.theme = patch.theme;
    if (patch.metadata !== undefined) uiOnly.metadata = patch.metadata;
    if (patch.last30 !== undefined) uiOnly.last30 = patch.last30;
    if (Object.keys(uiOnly).length > 0) {
      setOverlays((prev) => {
        const next = new Map(prev);
        const prior =
          next.get(active.id) ??
          buildUiOverlay(
            dbLinks.find((r) => r.id === active.id) ?? synthesizeRow(active),
          );
        next.set(active.id, { ...prior, ...uiOnly });
        return next;
      });
    }
  };

  const updateUtm = (patch: Partial<SmartLink["utm"]>) => {
    if (!active) return;
    const nextUtm = { ...active.utm, ...patch };
    void dbUpdateLink(active.id, { utm: nextUtm });
    setOverlays((prev) => {
      const next = new Map(prev);
      const prior =
        next.get(active.id) ??
        buildUiOverlay(
          dbLinks.find((r) => r.id === active.id) ?? synthesizeRow(active),
        );
      next.set(active.id, { ...prior, utm: nextUtm });
      return next;
    });
  };

  const applyUtmToAll = () => {
    if (!active) return;
    const sourceUtm = { ...active.utm };
    // Persist the active link's UTM to every other smart link in the workspace
    // so creators don't have to re-tag campaigns one-by-one.
    for (const row of dbLinks) {
      if (row.id === active.id) continue;
      void dbUpdateLink(row.id, { utm: sourceUtm });
    }
  };

  const requestDeleteLink = useCallback((link: SmartLink) => {
    setPendingDeleteLink(link);
  }, []);

  const confirmDeleteLink = useCallback(() => {
    if (!pendingDeleteLink) return;
    const link = pendingDeleteLink;
    const id = link.id;
    let settled = false;
    let toastId: string | number | undefined;

    const restoreLink = () => {
      if (settled) return;
      settled = true;
      setUndoableDeleteIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      setActiveId(id);
      if (toastId !== undefined) appToast.dismiss(toastId);
    };

    const commitDelete = async () => {
      if (settled) return;
      settled = true;
      try {
        await dbDeleteLink(id);
        setOverlays((prev) => {
          const next = new Map(prev);
          next.delete(id);
          return next;
        });
      } catch {
        setUndoableDeleteIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
        setActiveId(id);
        appToast.error("Could not delete Smart Link", {
          description: "The link was restored because the delete failed.",
        });
      }
    };

    setDeleteBusy(true);
    try {
      setUndoableDeleteIds((prev) => {
        const next = new Set(prev);
        next.add(id);
        return next;
      });
      setActiveId((current) => (current === id ? null : current));
      setPendingDeleteLink(null);
      toastId = appToast.info("Smart Link deleted", {
        description: `${link.title || link.slug} was removed. Undo keeps the same URL and click history.`,
        duration: 8000,
        action: {
          label: "Undo",
          onClick: restoreLink,
        },
        onDismiss: () => void commitDelete(),
        onAutoClose: () => void commitDelete(),
      });
    } finally {
      setDeleteBusy(false);
    }
  }, [dbDeleteLink, pendingDeleteLink]);

  const deleteActive = useCallback(() => {
    if (!active) return;
    requestDeleteLink(active);
  }, [active, requestDeleteLink]);

  const copyUtmUrl = async () => {
    if (!active) return;
    // Strip empty UTM values so we don't emit malformed params like
    // ?utm_source=&utm_medium=bio — analytics tools treat empty params as
    // "present with no value", which looks intentional in reports.
    const params = new URLSearchParams();
    if (active.utm.source?.trim())
      params.set("utm_source", active.utm.source.trim());
    if (active.utm.medium?.trim())
      params.set("utm_medium", active.utm.medium.trim());
    if (active.utm.campaign?.trim())
      params.set("utm_campaign", active.utm.campaign.trim());
    const qs = params.toString();
    const url = `juno33.link${active.slug}${qs ? `?${qs}` : ""}`;
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      appToast.error("Could not copy to clipboard");
      return;
    }
    setCopiedUtm(true);
    if (copiedUtmTimerRef.current != null) {
      window.clearTimeout(copiedUtmTimerRef.current);
    }
    copiedUtmTimerRef.current = window.setTimeout(() => {
      setCopiedUtm(false);
      copiedUtmTimerRef.current = null;
    }, 1600);
  };

  const createNewLink = useCallback(async () => {
    const code = generateSlug();
    const created = await dbCreateLink({
      title: "Finish setup",
      code,
      targetUrl: NEW_LINK_PLACEHOLDER_URL,
      isActive: false,
    });
    if (!created) return;
    // Seed the session-only overlay for theme/UTM/items.
    setOverlays((prev) => {
      const next = new Map(prev);
      next.set(created.id, buildUiOverlay(created));
      return next;
    });
    setActiveId(created.id);
    setDetailTab("editor");
    setFocusTitleOnNextFrame(true);
  }, [dbCreateLink]);

  useEffect(() => {
    if (searchParams.get("new") !== "1") return;
    void createNewLink().then(() => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete("new");
          return next;
        },
        { replace: true },
      );
    });
  }, [createNewLink, searchParams, setSearchParams]);

  /* Keyboard */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable);

      if (typing) {
        if (e.key === "Escape") (target as HTMLElement).blur();
        return;
      }

      if (!filtered.length) return;
      const idx = filtered.findIndex((l) => l.id === activeId);

      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        const next = Math.min(filtered.length - 1, idx < 0 ? 0 : idx + 1);
        setActiveId(filtered[next]!.id);
        return;
      }
      if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        const next = Math.max(0, idx < 0 ? 0 : idx - 1);
        setActiveId(filtered[next]!.id);
        return;
      }
      if (e.key === "Enter" && active) {
        e.preventDefault();
        titleRef.current?.focus();
        titleRef.current?.select();
        return;
      }
      if (e.key === "Escape" && activeId) {
        e.preventDefault();
        setActiveId(null);
      }
      // Backspace/Delete while a link is selected (and nothing is focused)
      // removes the row. Holds the modifier to prevent accidental deletes.
      if (
        (e.key === "Backspace" || e.key === "Delete") &&
        (e.metaKey || e.ctrlKey) &&
        active
      ) {
        e.preventDefault();
        deleteActive();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [filtered, activeId, active, deleteActive]);

  const activeCount = links.filter((link) => link.isActive).length;
  const totalClicks = links.reduce((s, l) => s + l.totalClicks, 0);
  const topLink = useMemo(() => getSmartLinkTopPerformer(links), [links]);
  const avgClicks =
    links.length === 0 ? 0 : Math.round(totalClicks / links.length);
  const smartLinkKpis = [
    {
      label: "Active links",
      value: String(activeCount),
      caption: `of ${links.length} total`,
      trend: activeCount > 0 ? "good" : "neutral",
      active: true,
      empty: links.length === 0,
    },
    {
      label: "Clicks all-time",
      value: formatClicks(totalClicks),
      caption: "across active + paused",
      trend: totalClicks > 0 ? "good" : "neutral",
      active: false,
      empty: totalClicks === 0,
    },
    {
      label: "Top performer",
      value: topLink ? topLink.slug : "—",
      caption: topLink
        ? `${formatClicks(topLink.totalClicks)} clicks`
        : smartLinkTopPerformerCaption(),
      trend: topLink ? "good" : "neutral",
      active: false,
      empty: !topLink,
    },
    {
      label: "Avg per link",
      value: formatClicks(avgClicks),
      caption: links.length === 0 ? "—" : `mean across ${links.length}`,
      trend: avgClicks > 0 ? "good" : "neutral",
      active: false,
      empty: avgClicks === 0,
    },
  ] as const;
  const clickGoalProgressPct =
    clickGoal.targetClicks > 0
      ? Math.min(
          100,
          Math.round(
            (clickGoalProgress.totalClicks / clickGoal.targetClicks) * 100,
          ),
        )
      : 0;
  const saveClickGoal = async () => {
    const targetClicks = Number.parseInt(clickGoalTargetDraft, 10);
    const periodDays = Number.parseInt(clickGoalDaysDraft, 10);
    if (!Number.isFinite(targetClicks) || targetClicks < 1) {
      appToast.error("Enter a click goal above 0");
      return;
    }
    if (!Number.isFinite(periodDays) || periodDays < 1 || periodDays > 90) {
      appToast.error("Goal window must be 1-90 days");
      return;
    }
    try {
      await saveClickGoalSetting({ targetClicks, periodDays, enabled: true });
      appToast.success("Smart Links goal saved");
    } catch {
      appToast.error("Could not save click goal");
    }
  };

  if (linksLoading && dbLinks.length === 0) return <SmartLinksSkeleton />;

  return (
    <NovaScreen width="full" density="compact">
      {/* Signature pulse for live dot */}
      <style>{`
        @keyframes links-live-pulse {
          0%, 100% { box-shadow: 0 0 0 0 var(--color-ring-oxblood-strong); }
          70% { box-shadow: 0 0 0 6px transparent; }
        }
        .links-live-dot { animation: links-live-pulse 2s ease-out infinite; }
        @media (prefers-reduced-motion: reduce) {
          .links-live-dot { animation: none; }
        }
      `}</style>

      <NovaSection>
        <NovaHeader
          eyebrow="Links"
          title="Smart links"
          meta="Links · live"
          description="Manage tracked redirects, click goals, UTMs, and live destination health."
          actions={
            <Button type="button" onClick={createNewLink}>
              <Plus data-icon="inline-start" aria-hidden="true" />
              Create new link
            </Button>
          }
        />
      </NovaSection>

      {/* Filter row */}
      <div className="links-filter-row flex flex-col items-stretch gap-2 mb-4 sm:flex-row sm:items-center">
        <Field
          label={<span className="sr-only">Search links</span>}
          className="flex-1 max-w-none sm:max-w-[320px]"
        >
          <Input
            id="links-search"
            ref={searchInputRef}
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search links"
            leadingIcon={<Search className="h-3.5 w-3.5" />}
            className="md:text-[0.78125rem]"
          />
        </Field>

        {search.trim() ? (
          <div className="text-xs text-muted-foreground tabular-nums sm:ml-auto">
            {filtered.length} of {links.length}
          </div>
        ) : null}
      </div>

      {links.length === 0 && !linksLoading ? (
        <NovaEmpty
          title="Create your first smart link"
          description="Wrap any URL with tracking, UTMs, and analytics. Perfect for bio links, campaign tracking, and seeing which posts drive clicks."
          icon={<Link2 data-icon="inline-start" aria-hidden="true" />}
          action={
            <Button type="button" onClick={createNewLink}>
              <Plus data-icon="inline-start" aria-hidden="true" />
              Create new link
            </Button>
          }
        />
      ) : (
        <>
          <NovaSection className="mb-6 grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
            <NovaCard
              eyebrow="Click goal"
              title={
                <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  <span className="app-kpi-value text-2xl font-bold tabular-nums text-foreground">
                    {clickGoalProgress.isLoading
                      ? "--"
                      : formatClicks(clickGoalProgress.totalClicks)}
                  </span>
                  <span className="text-sm text-muted-foreground">
                    of {formatClicks(clickGoal.targetClicks)} clicks in{" "}
                    {clickGoal.periodDays}d
                  </span>
                </span>
              }
              description="Dashboard progress uses real Smart Link click events, not Meta account-click estimates."
            >
              <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-end">
                <div className="min-w-0">
                  <Progress
                    value={clickGoalProgressPct}
                    aria-label="Smart Link click goal progress"
                    className="h-2"
                  />
                </div>
                <div className="links-goal-controls flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-end xl:justify-end [&_button]:max-sm:min-h-11 [&_input]:max-sm:min-h-11">
                  <Field
                    label="Goal"
                    className="min-w-0 flex-1 sm:flex-none"
                  >
                    <Input
                      id="links-click-goal-target"
                      type="number"
                      min={1}
                      value={clickGoalTargetDraft}
                      onChange={(event) =>
                        setClickGoalTargetDraft(event.target.value)
                      }
                      className="sm:w-28"
                    />
                  </Field>
                  <Field
                    label="Days"
                    className="min-w-0 flex-1 sm:flex-none"
                  >
                    <Input
                      id="links-click-goal-days"
                      type="number"
                      min={1}
                      max={90}
                      value={clickGoalDaysDraft}
                      onChange={(event) =>
                        setClickGoalDaysDraft(event.target.value)
                      }
                      className="sm:w-24"
                    />
                  </Field>
                  <Button
                    type="button"
                    onClick={() => void saveClickGoal()}
                    variant="secondary"
                    className="sm:w-auto"
                  >
                    Save goal
                  </Button>
                </div>
              </div>
            </NovaCard>
            <NovaCard
              eyebrow="Link health"
              description="Outbound click surface"
              action={<Badge tone="secondary">{links.length} total</Badge>}
            >
              <div className="grid grid-cols-2 gap-x-5 gap-y-4">
                {smartLinkKpis.slice(0, 4).map((kpi) => (
                  <NovaMiniStat
                    key={kpi.label}
                    label={kpi.label}
                    value={kpi.value}
                    description={kpi.caption}
                    className="min-w-0"
                    tone={
                      kpi.trend === "good"
                        ? "success"
                        : kpi.active
                          ? "primary"
                          : "default"
                    }
                  />
                ))}
              </div>
            </NovaCard>
          </NovaSection>

          {/* Two-pane */}
          <NovaSection className="links-editor-grid grid grid-cols-1 items-start gap-3 sm:gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(360px,0.65fr)] xl:gap-5 2xl:grid-cols-[minmax(0,1.45fr)_minmax(420px,0.55fr)] 2xl:gap-6 [&>*]:min-w-0">
            {/* LEFT — link list */}
            <NovaDataPanel
              title="Links"
              description="Tracked redirects and campaign destinations."
              contentClassName="p-0"
              className="overflow-hidden"
            >
              <div className="hidden border-b border-border px-5 py-3 text-xs font-medium text-muted-foreground lg:grid lg:grid-cols-[minmax(220px,1.35fr)_minmax(180px,1fr)_96px_112px_auto] lg:items-center lg:gap-4">
                <span>Link</span>
                <span>Destination</span>
                <span className="text-right">Clicks</span>
                <span>Updated</span>
                <span className="sr-only">Actions</span>
              </div>
              <div className="flex flex-col">
                {filtered.map((l) => (
                  <LinkRow
                    key={l.id}
                    link={l}
                    active={active?.id === l.id}
                    copied={copiedUrl === l.slug}
                    onClick={() => setActiveId(l.id)}
                    onCopy={() => copyUrl(l.slug)}
                    onOpen={() => openPublicLink(l.slug)}
                    onViewStats={() => {
                      setActiveId(l.id);
                      setDetailTab("analytics");
                    }}
                    onDelete={() => {
                      requestDeleteLink(l);
                    }}
                  />
                ))}

                {filtered.length === 0 && (
                  <NovaEmpty
                    className="m-5"
                    title="No links match"
                    description="Try clearing filters or search."
                    icon={<Link2 data-icon="inline-start" aria-hidden="true" />}
                  />
                )}
              </div>
            </NovaDataPanel>

            {/* RIGHT — detail / editor */}
            <div className="flex flex-col">
              {active ? (
                <LinkDetail
                  link={active}
                  titleRef={titleRef}
                  copiedUtm={copiedUtm}
                  detailTab={detailTab}
                  onTabChange={setDetailTab}
                  onPatch={updateActive}
                  onPatchUtm={updateUtm}
                  onCopyUtm={copyUtmUrl}
                  onApplyUtmToAll={links.length > 1 ? applyUtmToAll : undefined}
                  onOpenMobilePreview={() => setMobilePreviewOpen(true)}
                />
              ) : (
                <EmptyDetail />
              )}
            </div>
          </NovaSection>

          <NovaCard
            variant="panel"
            contentClassName="hidden flex-wrap items-center gap-2 text-sm text-muted-foreground md:flex"
            className="mt-4"
          >
            <Badge tone="outline">J / K</Badge>
            <span>navigate</span>
            <Badge tone="outline">Enter</Badge>
            <span>edit title</span>
            <Badge tone="outline">Esc</Badge>
            <span>deselect</span>
          </NovaCard>
        </>
      )}

      {/* Mobile preview overlay */}
      <MobileLinkPreviewOverlay
        open={mobilePreviewOpen && !!active}
        link={active}
        onClose={() => setMobilePreviewOpen(false)}
      />
      <ConfirmDialog
        open={pendingDeleteLink !== null}
        onClose={() => {
          if (!deleteBusy) setPendingDeleteLink(null);
        }}
        onConfirm={confirmDeleteLink}
        title={`Delete ${pendingDeleteLink?.title || pendingDeleteLink?.slug || "smart link"}?`}
        description="This removes the Smart Link from this workspace. You can undo briefly from the toast before the delete is finalized."
        confirmLabel="Delete link"
        cancelLabel="Keep link"
        destructive
        busy={deleteBusy}
      />
    </NovaScreen>
  );
}
