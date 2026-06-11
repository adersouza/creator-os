import type React from "react";
import {
  BarChart2,
  Check,
  Copy,
  ExternalLink,
  Link2,
  MoreHorizontal,
  Pencil,
  Trash2,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ListRow } from "@/components/ui/ListRow";
import {
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuRoot,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/ContextMenu";
import {
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRoot,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/DropdownMenu";
import { cn } from "@/lib/utils";
import type { SmartLink } from "./types";
import { formatClicks } from "./utils";

/* =========================================================================
   LINK ROW
   ========================================================================= */
export function LinkRow({
  link,
  active,
  copied,
  onClick,
  onCopy,
  onOpen,
  onViewStats,
  onDelete,
}: {
  link: SmartLink;
  active: boolean;
  copied: boolean;
  onClick: () => void;
  onCopy: () => void;
  onOpen: () => void;
  onViewStats: () => void;
  onDelete: () => void;
}) {
  const destinationLabel = formatDestination(link.targetUrl);
  return (
    <ContextMenuRoot>
      <ContextMenuTrigger asChild>
        <ListRow onClick={onClick} selected={active} density="comfortable">
          <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(220px,1.35fr)_minmax(180px,1fr)_96px_112px_auto] lg:items-center">
            <div className="flex min-w-0 items-center gap-3">
              <div
                className={cn(
                  "inline-flex size-9 flex-shrink-0 items-center justify-center rounded-md border",
                  active
                    ? "border-primary/30 bg-primary/10 text-primary"
                    : "border-border bg-muted text-muted-foreground",
                )}
                aria-hidden="true"
              >
                <Link2 />
              </div>

              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate text-[0.875rem] font-semibold tracking-[-0.01em] text-foreground">
                    {link.title}
                  </span>
                  {!link.isActive && (
                    <Badge tone="outline" className="h-[18px] px-1.5 text-xs">
                      Inactive
                    </Badge>
                  )}
                </div>
                <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="app-data max-w-full truncate text-xs font-medium text-muted-foreground sm:max-w-[min(28vw,18rem)]">
                    juno33.link{link.slug}
                  </span>
                  <span
                    className="size-1 shrink-0 rounded-full bg-muted-foreground/40"
                    aria-hidden="true"
                  />
                  <span className="text-xs text-muted-foreground lg:hidden">
                    {link.items.length} destinations
                  </span>
                </div>
              </div>
            </div>

            <div className="hidden min-w-0 lg:block">
              <div className="truncate text-[0.78125rem] font-medium text-foreground">
                {destinationLabel}
              </div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                {link.items.length}{" "}
                {link.items.length === 1 ? "destination" : "destinations"}
              </div>
            </div>

            <div className="hidden text-right lg:block">
              <div className="app-kpi-value text-[0.9375rem] font-bold text-foreground tabular-nums">
                {formatClicks(link.totalClicks)}
              </div>
              <div className="mt-0.5 text-[0.68rem] font-medium uppercase tracking-wide text-muted-foreground">
                clicks
              </div>
            </div>

            <div className="hidden text-sm text-muted-foreground lg:block">
              {link.lastEdited}
            </div>

            <div className="flex shrink-0 items-center gap-1.5 justify-self-start lg:justify-self-end">
              <RowIcon
                onClick={(e) => {
                  e.stopPropagation();
                  onOpen();
                }}
                label="Open public link"
              >
                <ExternalLink className="w-3.5 h-3.5" />
              </RowIcon>
              <RowIcon
                onClick={(e) => {
                  e.stopPropagation();
                  onCopy();
                }}
                label={copied ? "Copied" : "Copy URL"}
                active={copied}
              >
                {copied ? (
                  <Check className="w-3.5 h-3.5" />
                ) : (
                  <Copy className="w-3.5 h-3.5" />
                )}
              </RowIcon>
              <DropdownMenuRoot>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={(event) => event.stopPropagation()}
                    aria-label="Link actions"
                    title="Link actions"
                    className="text-muted-foreground hover:text-foreground"
                  >
                    <MoreHorizontal
                      data-icon="inline-start"
                      aria-hidden="true"
                    />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={onClick}>
                    <Pencil aria-hidden="true" />
                    Edit details
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={onOpen}>
                    <ExternalLink aria-hidden="true" />
                    Open public link
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={onViewStats}>
                    <BarChart2 aria-hidden="true" />
                    View stats
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={onCopy}>
                    <Copy aria-hidden="true" />
                    Copy URL
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem destructive onSelect={onDelete}>
                    <Trash2 aria-hidden="true" />
                    Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenuRoot>
            </div>
          </div>
        </ListRow>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onSelect={onClick}>Edit</ContextMenuItem>
        <ContextMenuItem onSelect={onOpen}>Open public link</ContextMenuItem>
        <ContextMenuItem onSelect={onViewStats}>View stats</ContextMenuItem>
        <ContextMenuItem onSelect={onCopy}>Copy URL</ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem destructive onSelect={onDelete}>
          Delete
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenuRoot>
  );
}

function formatDestination(url: string): string {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    return host || "No destination";
  } catch {
    return url
      ? url.replace(/^https?:\/\//, "").slice(0, 42)
      : "No destination";
  }
}

function RowIcon({
  children,
  onClick,
  label,
  active,
  destructive,
}: {
  children: React.ReactNode;
  onClick: (e: React.MouseEvent) => void;
  label: string;
  active?: boolean | undefined;
  destructive?: boolean | undefined;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={cn(
        "size-8 min-w-8 rounded-md",
        destructive
          ? "text-primary hover:bg-primary/10"
          : active
            ? "bg-primary/10 text-primary"
            : "text-muted-foreground hover:bg-muted hover:text-foreground active:bg-muted",
      )}
    >
      {children}
    </Button>
  );
}
