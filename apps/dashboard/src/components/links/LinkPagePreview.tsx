import { useEffect, useMemo } from "react";
import { Button } from "@/components/ui/Button";
import {
  LINK_BLOCK_LIBRARY,
  type LinkItem,
  type SmartLink,
  type Theme,
} from "./types";

/* =========================================================================
   PHONE MOCKUP — live bio-page preview
   ========================================================================= */
export function MobileLinkPreviewOverlay({
  open,
  link,
  onClose,
}: {
  open: boolean;
  link: SmartLink | null;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open || typeof document === "undefined" || !link) return null;

  return (
    <div
      className="fixed inset-0 z-[80] lg:hidden"
      role="dialog"
      aria-modal="true"
      aria-label="Link page preview"
    >
      <div
        onClick={onClose}
        className="absolute inset-0 bg-[color-mix(in_srgb,var(--color-foreground)_55%,transparent)] backdrop-blur-sm"
      />
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <div className="pointer-events-auto flex flex-col items-center gap-4">
          <LinkPagePreview link={link} />
          <Button
            type="button"
            onClick={onClose}
            variant="secondary"
            size="lg"
            className="rounded-full"
          >
            Close
          </Button>
        </div>
      </div>
    </div>
  );
}

export function LinkPagePreview({ link }: { link: SmartLink }) {
  const themeMeta: Record<
    Theme,
    { bg: string; fg: string; button: string; buttonFg: string; border: string }
  > = {
    ink: {
      bg: "#121214",
      fg: "#FAFAFA",
      button: "color-mix(in_srgb,var(--color-card)_8%,transparent)",
      buttonFg: "#FAFAFA",
      border: "color-mix(in_srgb,var(--color-card)_12%,transparent)",
    },
    cream: {
      bg: "#F4F1E8",
      fg: "#0A0A0B",
      button: "#FFFFFF",
      buttonFg: "#0A0A0B",
      border: "color-mix(in_srgb,var(--color-foreground)_10%,transparent)",
    },
    oxblood: {
      bg: "#2A1018",
      fg: "#FAFAFA",
      button: "color-mix(in srgb, #D4818A 14%, transparent)",
      buttonFg: "#FAFAFA",
      border: "color-mix(in srgb, #D4818A 28%, transparent)",
    },
    vale: {
      bg: "#1F1B2E",
      fg: "#FAFAFA",
      button: "color-mix(in srgb, #B5A6D6 14%, transparent)",
      buttonFg: "#FAFAFA",
      border: "color-mix(in srgb, #B5A6D6 28%, transparent)",
    },
  };
  const t = themeMeta[link.theme];
  const accentColor = "var(--color-oxblood)";
  const handle = link.slug.replace(/^\//, "");
  const initial = (link.title[0] || "?").toUpperCase();

  return (
    <div className="sticky top-6">
      <div className="mb-2 text-center text-xs font-medium text-muted-foreground lg:text-left">
        Live preview
      </div>
      {/* Phone frame */}
      <div
        className="relative w-[220px] h-[440px] rounded-[34px] p-[6px] shadow-[0_12px_32px_color-mix(in_srgb,var(--color-foreground)_18%,transparent),0_2px_8px_color-mix(in_srgb,var(--color-foreground)_8%,transparent)]"
        style={{ background: "#0A0A0B" }}
        aria-hidden="true"
      >
        {/* Notch */}
        <div
          className="absolute top-[6px] left-1/2 -translate-x-1/2 w-[72px] h-[18px] rounded-b-xl z-10"
          style={{ background: 'var(--color-ink)' }}
        />
        {/* Screen */}
        <div
          className="w-full h-full rounded-[28px] overflow-hidden flex flex-col items-center px-4 pt-10 pb-4 text-center"
          style={{ background: t.bg, color: t.fg }}
        >
          {/* Avatar */}
          <div
            className="w-[52px] h-[52px] rounded-full flex items-center justify-center text-[1.25rem] font-semibold shrink-0 mb-3"
            style={{
              background: `linear-gradient(135deg, ${accentColor}, color-mix(in srgb, var(--color-oxblood) 70%, var(--color-background)))`,
              color: 'var(--color-primary-foreground)',
            }}
          >
            {initial}
          </div>
          {/* Handle */}
          <div className="text-[0.625rem] font-mono opacity-60 mb-1">
            juno33.link/{handle}
          </div>
          {/* Title */}
          <div className="text-[0.875rem] font-semibold tracking-[-0.01em] leading-[1.2] mb-4 line-clamp-2">
            {link.title}
          </div>
          {/* Link buttons */}
          <div className="w-full flex flex-col gap-2 flex-1 overflow-hidden">
            {link.items.slice(0, 5).map((it) => (
              <PreviewBlock key={it.id} item={it} theme={t} />
            ))}
            {link.items.length > 5 && (
              <div className="text-[0.59375rem] opacity-40 mt-1">
                +{link.items.length - 5} more
              </div>
            )}
          </div>
          {/* Footer */}
          <div className="mt-3 text-[0.53125rem] uppercase tracking-[0.12em] opacity-30">
            Powered by Juno33
          </div>
        </div>
      </div>
    </div>
  );
}

function blockIcon(item: LinkItem) {
  return (
    LINK_BLOCK_LIBRARY.find((entry) => entry.type === item.blockType)?.icon ??
    "↗"
  );
}

function isScheduledActive(item: LinkItem) {
  if (item.blockType !== "scheduled_window") return true;
  const activeFrom =
    typeof item.metadata?.activeFrom === "string"
      ? item.metadata.activeFrom
      : "";
  const activeTo =
    typeof item.metadata?.activeTo === "string" ? item.metadata.activeTo : "";
  const now = Date.now();
  if (activeFrom && Date.parse(activeFrom) > now) return false;
  if (activeTo && Date.parse(activeTo) < now) return false;
  return true;
}

function metadataString(item: LinkItem, key: string) {
  const value = item.metadata?.[key];
  return typeof value === "string" ? value : "";
}

function metadataLines(item: LinkItem, key: string) {
  return metadataString(item, key)
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function PreviewBlock({
  item,
  theme,
}: {
  item: LinkItem;
  theme: { button: string; buttonFg: string; border: string };
}) {
  if (item.blockType === "bento_media_grid") {
    const mediaUrls = metadataLines(item, "mediaUrls").slice(0, 4);
    return (
      <div className="grid grid-cols-2 gap-1 w-full">
        {Array.from({ length: 4 }).map((_, index) => {
          const url = mediaUrls[index];
          return (
            <div
              key={`${item.id}-${index}`}
              className="aspect-square rounded-[5px] overflow-hidden"
              style={{
                background:
                  index % 2 === 0
                    ? "color-mix(in_srgb,var(--color-card)_18%,transparent)"
                    : "color-mix(in_srgb,var(--color-card)_10%,transparent)",
                border: `0.5px solid ${theme.border}`,
              }}
            >
              {url && (
                <img
                  src={url}
                  alt=""
                  className="w-full h-full object-cover"
                  loading="lazy"
                  decoding="async"
                />
              )}
            </div>
          );
        })}
      </div>
    );
  }

  const active = isScheduledActive(item);
  const suffix =
    item.blockType === "email_capture"
      ? metadataString(item, "ctaText") || "email"
      : item.blockType === "tip_jar"
        ? metadataString(item, "presets") || "$"
        : item.blockType === "digital_product"
          ? metadataString(item, "price") || "product"
          : item.blockType === "affiliate_catalog"
            ? "catalog"
            : "";
  return (
    <div
      className="w-full min-h-8 rounded-md flex items-center gap-1.5 justify-center text-[0.6875rem] font-medium truncate px-2"
      style={{
        background: active ? theme.button : "transparent",
        color: active ? theme.buttonFg : "color-mix(in srgb, var(--color-muted-foreground) 70%, transparent)",
        border: `0.5px solid ${theme.border}`,
        opacity: active ? 1 : 0.52,
      }}
    >
      <span aria-hidden="true">{blockIcon(item)}</span>
      <span className="truncate">{item.title}</span>
      {suffix && <span className="opacity-60">· {suffix}</span>}
    </div>
  );
}

export function FullSparkline({
  data,
  color,
}: {
  data: number[];
  color: string;
}) {
  const width = 320;
  const height = 64;
  const { path, area } = useMemo(() => {
    if (!data.length) return { path: "", area: "" };
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;
    const stepX = width / (data.length - 1);
    const pts = data.map((v, i) => ({
      x: i * stepX,
      y: height - ((v - min) / range) * (height - 4) - 2,
    }));
    const d = pts
      .map(
        (p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`,
      )
      .join(" ");
    const a = `${d} L ${width.toFixed(2)} ${height} L 0 ${height} Z`;
    return { path: d, area: a };
  }, [data]);

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-full"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="spark-area" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.14" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#spark-area)" />
      <path
        d={path}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
