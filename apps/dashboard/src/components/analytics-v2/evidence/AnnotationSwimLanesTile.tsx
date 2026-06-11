// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useChartAnnotations } from "@/hooks/useChartAnnotations";
import type { ConnectedAccount } from "@/hooks/useConnectedAccounts";
import type { ScopedAccountLite } from "@/components/analytics/analyticsShared";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";

interface Props {
  days: number;
  scopedAccount?: ScopedAccountLite | null | undefined;
  accounts: ConnectedAccount[];
}

const LANES = [
  { key: "algorithm", label: "Algorithm", color: "var(--color-chart-4)" },
  { key: "campaign", label: "Campaign", color: "var(--color-chart-1)" },
  { key: "holiday", label: "Holiday", color: "var(--color-chart-warning)" },
  { key: "incident", label: "Incident", color: "var(--color-chart-danger)" },
  { key: "launch", label: "Launch", color: "var(--color-chart-5)" },
] as const;

type LaneKey = (typeof LANES)[number]["key"];
interface SwimEvent {
  id: string;
  lane: LaneKey;
  label: string;
  left: number;
  width: number;
}

export function AnnotationSwimLanesTile({
  days,
  scopedAccount,
  accounts,
}: Props) {
  const accountId = scopedAccount?.id ?? accounts[0]?.id ?? null;
  const { annotations, isLoading, hasError } = useChartAnnotations(
    accountId,
    days,
  );

  if (isLoading) {
    return (
      <EvidenceCard
        state="loading"
        eyebrow="Annotations"
        title="Annotation swim-lanes"
        description="Chart annotations"
        contentClassName="flex min-h-[220px] flex-col gap-3"
      >
        <Skeleton className="h-5 w-44" />
        <div className="flex flex-col gap-2">
          {LANES.map((lane) => (
            <div
              key={lane.key}
              className="grid min-h-9 grid-cols-[minmax(76px,0.34fr)_minmax(0,1fr)] gap-3"
            >
              <Skeleton className="h-8 rounded-md" />
              <Skeleton className="h-8 rounded-md" />
            </div>
          ))}
        </div>
      </EvidenceCard>
    );
  }

  if (annotations.length === 0) {
    return (
      <EvidenceCard
        state="empty"
        eyebrow="Annotations"
        title="Annotation swim-lanes"
        description="Backed by chart_annotations"
      >
        <NovaEmpty
          className="min-h-[220px]"
          title={hasError ? "Annotation data unavailable" : "No saved annotations"}
          description={
            hasError
              ? "The annotation endpoint is unavailable, so no swim-lane events are shown."
              : "No saved annotations exist for this account and date window yet."
          }
        />
      </EvidenceCard>
    );
  }

  const events: SwimEvent[] = annotations.map<SwimEvent>(
    (annotation, index) => ({
      id: annotation.id,
      lane: laneFor(annotation.annotation_type, index),
      label: annotation.label,
      left: leftForDate(annotation.annotation_date, days),
      width: annotation.annotation_type === "range" ? 12 : 5,
    }),
  );

  return (
    <EvidenceCard
      eyebrow="Annotations"
      title="Annotation swim-lanes"
      description={
        hasError
          ? "Annotation endpoint unavailable"
          : "Backed by chart_annotations"
      }
      contentClassName="flex min-h-[250px] flex-col gap-3"
      footer={
        <p className="text-[0.72rem] leading-relaxed text-muted-foreground">
          {annotations.length} saved annotations in this window.
        </p>
      }
    >
      <div className="overflow-hidden rounded-xl border border-border bg-muted/30">
        {LANES.map((lane) => (
          <div
            key={lane.key}
            className="grid min-h-[38px] grid-cols-[minmax(76px,0.34fr)_minmax(0,1fr)] border-border border-b last:border-b-0"
          >
            <div className="flex min-w-0 items-center truncate border-border border-r px-3 py-2 text-[0.68rem] font-medium tracking-wide text-muted-foreground uppercase">
              {lane.label}
            </div>
            <div className="relative min-h-9">
              <div className="absolute inset-x-3 top-1/2 h-px bg-border" />
              {events
                .filter((event) => event.lane === lane.key)
                .map((event) => {
                  const width = Math.max(5, Math.min(24, event.width));
                  const left = Math.max(3, Math.min(96 - width, event.left));
                  return (
                    <div
                      key={event.id}
                      className="absolute top-2 flex h-5 items-center truncate rounded px-2 text-[0.62rem] font-medium text-background"
                      title={event.label}
                      style={{
                        left: `${left}%`,
                        width: `${width}%`,
                        background: lane.color,
                      }}
                    >
                      {event.label}
                    </div>
                  );
                })}
            </div>
          </div>
        ))}
      </div>
    </EvidenceCard>
  );
}

function laneFor(type: string | null, index: number): LaneKey {
  const normalized = (type ?? "").toLowerCase();
  if (normalized.includes("algo")) return "algorithm";
  if (normalized.includes("campaign")) return "campaign";
  if (normalized.includes("holiday")) return "holiday";
  if (normalized.includes("incident") || normalized.includes("bug"))
    return "incident";
  if (normalized.includes("launch") || normalized.includes("feature"))
    return "launch";
  return LANES[index % LANES.length]!.key;
}

function leftForDate(date: string, days: number) {
  const end = Date.now();
  const start = end - days * 86_400_000;
  const t = Date.parse(date);
  if (!Number.isFinite(t)) return 8;
  return Math.max(
    3,
    Math.min(92, ((t - start) / Math.max(1, end - start)) * 100),
  );
}
