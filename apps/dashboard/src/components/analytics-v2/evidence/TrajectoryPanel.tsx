import { useMemo } from "react";
import type {
  Platform,
  ScopedAccountLite,
} from "@/components/analytics/analyticsShared";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { useChartAnnotations } from "@/hooks/useChartAnnotations";
import type { ConnectedAccount } from "@/hooks/useConnectedAccounts";
import type { FleetMetricsState } from "@/hooks/useFleetMetrics";
import { useNonFollowerReach } from "@/hooks/useNonFollowerReach";
import { useScopedEqsTrend } from "@/hooks/useScopedEqsTrend";
import { computeForecast } from "@/lib/forecast";
import { TrendingUp } from "lucide-react";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { NovaEmpty, NovaMiniStat } from "@/components/ui/NovaPrimitives";

interface Props {
  platform: Platform;
  days: number;
  scopedAccount?: ScopedAccountLite | null | undefined;
  live: FleetMetricsState;
  accounts: ConnectedAccount[];
}

const LANES = [
  { key: "algorithm", label: "Algo", color: "var(--color-chart-4)" },
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

export function TrajectoryPanel({
  platform,
  days,
  scopedAccount,
  live,
  accounts,
}: Props) {
  const scopedTrend = useScopedEqsTrend(
    scopedAccount?.id
      ? {
          accountId: scopedAccount.id,
          accountPlatform: scopedAccount.platform,
        }
      : null,
    days,
  );
  const accountId = scopedAccount?.id ?? accounts[0]?.id ?? null;
  const { annotations, hasError: annotationError } = useChartAnnotations(
    accountId,
    days,
  );

  const series = scopedAccount ? scopedTrend.series : live?.series;
  const delta = scopedAccount ? scopedTrend.eqsDelta : live.eqsDelta;
  const history = (series ?? []).map((point) => point.eqs);
  const usableHistory = history.filter(
    (point) => Number.isFinite(point) && point > 0,
  );
  const horizon = Math.max(7, Math.min(14, Math.round(days * 0.22)));
  const forecast = useMemo(
    () =>
      usableHistory.length >= 3
        ? computeForecast(usableHistory, horizon)
        : null,
    [usableHistory, horizon],
  );
  const latest = usableHistory[usableHistory.length - 1] ?? null;
  const projected = forecast?.points[forecast.points.length - 1]?.value ?? null;
  const projectedDelta =
    latest != null && projected != null ? projected - latest : null;
  const status = trajectoryStatus(projected ?? latest, projectedDelta);
  const events = annotations.length
    ? annotations.map<SwimEvent>((annotation, index) => ({
        id: annotation.id,
        lane: laneFor(annotation.annotation_type, index),
        label: annotation.label,
        left: leftForDate(annotation.annotation_date, days),
        width: annotation.annotation_type === "range" ? 13 : 5,
      }))
    : [];

  return (
    <EvidenceCard
      eyebrow="Trajectory"
      title="Performance trajectory"
      description={`${platformLabel(platform)} · ${days}d history · ${horizon}d projection`}
      action={
        <InvestigateButton
          accountId={scopedAccount?.id ?? null}
          metric="engagement"
          metricLabel="Performance trajectory"
          periodDays={days}
        />
      }
    >
      <div className="analytics-trajectory-body">
        <div className="analytics-trajectory-lead">
          <div className="analytics-trajectory-summary">
            <NovaMiniStat
              label="Current EQS"
              value={latest == null ? "—" : latest.toFixed(1)}
              description={
                delta == null
                  ? "No prior comparison"
                  : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)} vs prior`
              }
              tone={delta == null || delta >= 0 ? "success" : "danger"}
            />
            <NovaMiniStat
              label="Projected"
              value={projected == null ? "—" : projected.toFixed(1)}
              description={
                projectedDelta == null
                  ? "Needs more posts"
                  : `${projectedDelta >= 0 ? "+" : ""}${projectedDelta.toFixed(1)} next`
              }
              tone={
                projectedDelta == null || projectedDelta >= 0
                  ? "success"
                  : "danger"
              }
            />
            <NovaMiniStat
              label="Risk"
              value={status.label}
              description={status.caption}
              tone={trajectoryMiniStatTone(status.tone)}
            />
          </div>

          <ForecastBandChart
            history={usableHistory}
            forecast={forecast}
            statusColor={status.color}
          />
        </div>

        <aside className="analytics-trajectory-rail">
          {platform !== "threads" ? (
            <DiscoveryCard days={days} scopedAccount={scopedAccount} />
          ) : null}
          <AnnotationCard
            days={days}
            events={events}
            count={annotations.length}
            hasError={annotationError}
          />
        </aside>
      </div>
    </EvidenceCard>
  );
}

function DiscoveryCard({
  days,
  scopedAccount,
}: {
  days: number;
  scopedAccount?: ScopedAccountLite | null | undefined;
}) {
  const live = useNonFollowerReach(
    { days },
    scopedAccount?.id
      ? {
          accountId: scopedAccount.id,
          accountPlatform: scopedAccount.platform,
          accountHandle: scopedAccount.handle,
        }
      : null,
  );
  const pct = clamp(
    Number.isFinite(live.nonFollowerPct) ? live.nonFollowerPct : 0,
    0,
    100,
  );
  const status =
    pct < 10
      ? { label: "Alarm", tone: "bad" as const }
      : pct <= 60
        ? { label: "Healthy", tone: "good" as const }
        : { label: "Wide", tone: "warn" as const };

  return (
    <div className="analytics-trajectory-card">
      <div className="analytics-trajectory-card-head">
        <span>Discovery split</span>
        <strong className={`is-${status.tone}`}>{status.label}</strong>
      </div>
      <div className="analytics-discovery-band" aria-hidden="true">
        <span style={{ width: "10%" }} data-tone="bad" />
        <span style={{ width: "20%" }} data-tone="warn" />
        <span style={{ width: "30%" }} data-tone="good" />
        <span style={{ width: "40%" }} data-tone="warn" />
        <i style={{ left: `${pct}%` }} />
      </div>
      <div className="analytics-trajectory-card-foot">
        <span>
          {live.hasRealData
            ? `${pct.toFixed(1)}% non-follower`
            : "Split unavailable"}
        </span>
        <span>{live.delta ?? `${live.followerPct}% follower`}</span>
      </div>
    </div>
  );
}

function AnnotationCard({
  days,
  events,
  count,
  hasError,
}: {
  days: number;
  events: SwimEvent[];
  count: number;
  hasError: boolean;
}) {
  return (
    <div className="analytics-trajectory-card analytics-trajectory-card-lanes">
      <div className="analytics-trajectory-card-head">
        <span>Why it moved</span>
        <strong>
          {hasError ? "Offline" : count ? `${count} saved` : `${days}d ready`}
        </strong>
      </div>
      <div className="analytics-trajectory-lanes">
        {LANES.map((lane) => (
          <div key={lane.key} className="analytics-trajectory-lane">
            <span>{lane.label}</span>
            <div>
              {events
                .filter((event) => event.lane === lane.key)
                .slice(0, 2)
                .map((event) => {
                  const width = Math.max(5, Math.min(24, event.width));
                  const left = Math.max(2, Math.min(98 - width, event.left));
                  return (
                    <i
                      key={event.id}
                      title={event.label}
                      style={{
                        left: `${left}%`,
                        width: `${width}%`,
                        background: lane.color,
                      }}
                    />
                  );
                })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ForecastBandChart({
  history,
  forecast,
  statusColor,
}: {
  history: number[];
  forecast: ReturnType<typeof computeForecast>;
  statusColor: string;
}) {
  const w = 920;
  const h = 250;
  const pad = 22;
  const splitX = Math.round(w * 0.72);
  const forecastEndX = w - pad;
  const allValues = [
    ...history,
    ...(forecast?.points.flatMap((point) => [
      point.value,
      point.upper,
      point.lower,
    ]) ?? []),
  ].filter(Number.isFinite);
  const min = Math.max(0, Math.min(...allValues, 0) - 4);
  const max = Math.min(100, Math.max(...allValues, 18) + 4);
  const mapY = (value: number) =>
    h - pad - ((value - min) / (max - min || 1)) * (h - pad * 2);
  const mapHistoryX = (index: number) =>
    history.length <= 1
      ? pad
      : pad + (index / (history.length - 1)) * (splitX - pad);
  const mapForecastX = (index: number) =>
    forecast && forecast.points.length > 1
      ? splitX +
        ((index + 1) / forecast.points.length) * (forecastEndX - splitX)
      : forecastEndX;
  const actual = history.map((value, index) => ({
    x: mapHistoryX(index),
    y: mapY(value),
    value,
  }));
  const forecastCoords =
    forecast?.points.map((point, index) => ({
      x: mapForecastX(index),
      y: mapY(point.value),
      yUpper: mapY(point.upper),
      yLower: mapY(point.lower),
    })) ?? [];
  const actualPath = pathFor(actual);
  const anchor = actual[actual.length - 1];
  const forecastPath = anchor
    ? pathFor([{ x: anchor.x, y: anchor.y }, ...forecastCoords])
    : "";
  const bandPath =
    anchor && forecastCoords.length
      ? [
          `M ${anchor.x.toFixed(1)} ${anchor.y.toFixed(1)}`,
          ...forecastCoords.map(
            (point) => `L ${point.x.toFixed(1)} ${point.yUpper.toFixed(1)}`,
          ),
          ...[...forecastCoords]
            .reverse()
            .map(
              (point) => `L ${point.x.toFixed(1)} ${point.yLower.toFixed(1)}`,
            ),
          "Z",
        ].join(" ")
      : "";

  if (history.length < 3) {
    return (
      <NovaEmpty
        className="analytics-trajectory-empty"
        icon={<TrendingUp data-icon aria-hidden="true" />}
        title="Forecast unavailable"
        description="Publish at least three posts in this window to unlock projection. The panel is holding the forecast empty until it has a real trend line."
      />
    );
  }

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      width="100%"
      height="100%"
      preserveAspectRatio="none"
      className="analytics-trajectory-chart"
      role="img"
      aria-label="EQS trajectory with projection band"
    >
      <defs>
        <linearGradient id="trajectoryActualFill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={statusColor} stopOpacity="0.17" />
          <stop offset="100%" stopColor={statusColor} stopOpacity="0" />
        </linearGradient>
        <linearGradient id="trajectoryBandFill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="var(--color-info)" stopOpacity="0.22" />
          <stop
            offset="100%"
            stopColor="var(--color-info)"
            stopOpacity="0.04"
          />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((tick) => (
        <line
          key={tick}
          x1={pad}
          x2={w - pad}
          y1={pad + tick * (h - pad * 2)}
          y2={pad + tick * (h - pad * 2)}
          stroke="var(--color-border)"
          strokeWidth="0.75"
          opacity="0.65"
        />
      ))}
      <rect
        x={splitX}
        y={pad}
        width={forecastEndX - splitX}
        height={h - pad * 2}
        fill="var(--color-info)"
        opacity="0.04"
      />
      {actualPath ? (
        <>
          <path
            d={`${actualPath} L ${splitX} ${h - pad} L ${pad} ${h - pad} Z`}
            fill="url(#trajectoryActualFill)"
          />
          <path
            d={actualPath}
            fill="none"
            stroke={statusColor}
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="2.6"
          />
        </>
      ) : null}
      {bandPath ? <path d={bandPath} fill="url(#trajectoryBandFill)" /> : null}
      {forecastPath ? (
        <path
          d={forecastPath}
          fill="none"
          stroke="var(--color-info)"
          strokeDasharray="6 5"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2"
        />
      ) : null}
      {actual.map((point, index) => (
        <circle
          key={`${index}-${point.value}`}
          cx={point.x}
          cy={point.y}
          r="3.2"
          fill={statusColor}
          opacity="0.78"
        />
      ))}
    </svg>
  );
}

function trajectoryStatus(
  value: number | null,
  delta: number | null,
): {
  label: string;
  caption: string;
  tone: "good" | "bad" | "warn" | "neutral";
  color: string;
} {
  if (value == null) {
    return {
      label: "—",
      caption: "Need sample",
      tone: "neutral",
      color: "var(--color-muted-foreground)",
    };
  }
  if (value < 35 || (delta != null && delta < -8)) {
    return {
      label: "At risk",
      caption: "Downside skew",
      tone: "bad",
      color: "var(--color-oxblood)",
    };
  }
  if (value < 60 || (delta != null && delta < 0)) {
    return {
      label: "Watch",
      caption: "Needs lift",
      tone: "warn",
      color: "var(--color-gold)",
    };
  }
  return {
    label: "Stable",
    caption: "Quality intact",
    tone: "good",
    color: "var(--color-health-good)",
  };
}

function trajectoryMiniStatTone(tone: "good" | "bad" | "warn" | "neutral") {
  if (tone === "good") return "success";
  if (tone === "bad") return "danger";
  if (tone === "warn") return "warning";
  return "default";
}

function platformLabel(platform: Platform) {
  if (platform === "ig") return "Instagram";
  if (platform === "threads") return "Threads";
  return "All platforms";
}

function pathFor(points: Array<{ x: number; y: number }>) {
  if (points.length < 2) return "";
  return points
    .map(
      (point, index) =>
        `${index === 0 ? "M" : "L"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`,
    )
    .join(" ");
}

function laneFor(type: string | null, index: number): LaneKey {
  const normalized = (type ?? "").toLowerCase();
  if (normalized.includes("algo")) return "algorithm";
  if (normalized.includes("campaign")) return "campaign";
  if (normalized.includes("holiday")) return "holiday";
  if (normalized.includes("incident") || normalized.includes("bug")) {
    return "incident";
  }
  if (normalized.includes("launch") || normalized.includes("feature")) {
    return "launch";
  }
  return LANES[index % LANES.length]?.key ?? "algorithm";
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

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}
