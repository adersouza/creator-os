// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useMemo, useState } from "react";
import { Info } from "lucide-react";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { Slider } from "@/components/ui/Slider";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/Tooltip";
import type { FleetMetricsState } from "@/hooks/useFleetMetrics";
import { useScopedEqsTrend } from "@/hooks/useScopedEqsTrend";
import { computeForecast } from "@/lib/forecast";
import type {
  Platform,
  ScopedAccountLite,
} from "@/components/analytics/analyticsShared";
import { EvidenceTile } from "../EvidenceTile";

interface Props {
  platform: Platform;
  days: number;
  scopedAccount?: ScopedAccountLite | undefined;
  live: FleetMetricsState;
}

const CONFIDENCE_OPTIONS = [80, 90, 95, 99] as const;
type ConfidenceLevel = (typeof CONFIDENCE_OPTIONS)[number];

const BAND_SCALE: Record<ConfidenceLevel, number> = {
  80: 0.65,
  90: 0.84,
  95: 1,
  99: 1.31,
};

/**
 * §7 / §14 / §37 EQS forecast with adjustable confidence interval.
 * Uses the same live EQS history as the existing chart, then renders the
 * visual pattern requested in the analytics brief: blue CI band, dashed
 * expected line, and orange outlier dots.
 */
export function EqsForecastCiTile({
  platform,
  days,
  scopedAccount,
  live,
}: Props) {
  const [confidence, setConfidence] = useState<ConfidenceLevel>(95);
  const scopedTrend = useScopedEqsTrend(
    scopedAccount?.id
      ? {
          accountId: scopedAccount.id,
          accountPlatform: scopedAccount.platform,
        }
      : null,
    days,
  );

  const series = scopedAccount ? scopedTrend.series : live.series;
  const delta = scopedAccount ? scopedTrend.eqsDelta : live.eqsDelta;
  const isLoading = scopedAccount ? scopedTrend.loading : live.isLoading;
  const history = (series ?? []).map((point) => point.eqs);
  const observedHistory = history.filter(
    (point) => Number.isFinite(point) && point > 0,
  );
  const hasLiveSeries = observedHistory.length >= 3;
  const horizon = Math.max(7, Math.min(14, Math.round(days * 0.22)));
  const forecast = useMemo(
    () => (hasLiveSeries ? computeForecast(observedHistory, horizon) : null),
    [hasLiveSeries, observedHistory, horizon],
  );

  const residuals = useMemo(() => {
    if (!forecast || observedHistory.length < 3) return [];
    const values = observedHistory.map((value, index) => {
      const expected = forecast.intercept + forecast.slope * index;
      return { index, value, expected, residual: value - expected };
    });
    const meanAbs =
      values.reduce((sum, point) => sum + Math.abs(point.residual), 0) /
      values.length;
    const threshold = Math.max(2, meanAbs * 2.25);
    return values
      .filter((point) => Math.abs(point.residual) >= threshold)
      .map((point) => point.index);
  }, [forecast, observedHistory]);

  if (!hasLiveSeries && !isLoading) {
    return (
      <EvidenceTile
        state="empty"
        label="Forecast"
        title="EQS forecast"
        note="Publish at least three non-zero EQS days in this window to unlock the forecast, confidence band, and outlier markers."
      />
    );
  }

  const latest = observedHistory[observedHistory.length - 1] ?? null;
  const projected = forecast?.points[forecast.points.length - 1]?.value ?? null;
  const projectedDelta =
    latest != null && projected != null ? projected - latest : null;

  return (
    <EvidenceCard
      eyebrow="Forecast"
      title="EQS forecast"
      description={`${platformLabel(platform)} · ${days}d history · ${horizon}d projection`}
      action={
        <InvestigateButton
          accountId={scopedAccount?.id ?? null}
          metric="engagement"
          metricLabel="EQS forecast"
          periodDays={days}
        />
      }
      contentClassName="flex h-full flex-col gap-5"
    >
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="text-4xl font-semibold tracking-[-0.045em] text-foreground tabular-nums">
            {latest == null ? "—" : latest.toFixed(1)}
          </div>
          <div className="mt-1 flex items-center gap-1.5 text-[0.75rem] text-muted-foreground">
            Latest observed Engagement Quality Score
            <EqsTooltip />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 text-right">
          <Summary
            label="Projected"
            value={projected == null ? "—" : projected.toFixed(1)}
            tone={
              projectedDelta == null || projectedDelta >= 0 ? "good" : "bad"
            }
          />
          <Summary
            label="Vs now"
            value={
              projectedDelta == null
                ? "—"
                : `${projectedDelta >= 0 ? "+" : ""}${projectedDelta.toFixed(1)}`
            }
            tone={
              projectedDelta == null || projectedDelta >= 0 ? "good" : "bad"
            }
          />
        </div>
      </div>

      <ForecastChart
        history={observedHistory}
        confidence={confidence}
        forecast={forecast}
        outlierIndexes={residuals}
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <Legend color="var(--color-chart-ink)" label="Actual" />
          <Legend color="var(--color-info)" label="Expected" dashed />
          <Legend color="var(--color-gold)" label="Outlier" />
        </div>
        <div className="flex w-full items-center justify-between gap-2 text-[0.6875rem] text-muted-foreground sm:w-auto sm:justify-start">
          <span className="font-mono tabular-nums">{confidence}% CI</span>
          <Slider
            min={0}
            max={CONFIDENCE_OPTIONS.length - 1}
            step={1}
            value={[CONFIDENCE_OPTIONS.indexOf(confidence)]}
            onValueChange={(value) => {
              const next = CONFIDENCE_OPTIONS[value[0] ?? 0];
              setConfidence(next!);
            }}
            className="w-24 max-w-[46vw]"
            aria-label="Forecast confidence interval"
          />
        </div>
      </div>

      {delta != null ? (
        <p className="text-[0.75rem] leading-relaxed text-muted-foreground">
          Current EQS is {delta >= 0 ? "up" : "down"}{" "}
          {Math.abs(delta).toFixed(1)} vs the prior period. The forecast band is
          a statistical projection from recent EQS history and widens when
          points are volatile.
        </p>
      ) : null}
      <div className="text-[0.6875rem] uppercase tracking-[0.08em] text-muted-foreground">
        SOURCE · Non-zero EQS history from synced analytics. Forecast uses
        linear trend + residual spread, not a guaranteed outcome.
      </div>
    </EvidenceCard>
  );
}

function platformLabel(platform: Platform) {
  if (platform === "ig") return "Instagram";
  if (platform === "threads") return "Threads";
  return "All platforms";
}

function ForecastChart({
  history,
  confidence,
  forecast,
  outlierIndexes,
}: {
  history: number[];
  confidence: ConfidenceLevel;
  forecast: ReturnType<typeof computeForecast>;
  outlierIndexes: number[];
}) {
  const w = 720;
  const h = 210;
  const pad = 18;
  const forecastStartX = Math.round(w * 0.72);
  const forecastEndX = w - pad;
  const historyEndX = forecastStartX;

  const scaledForecast = forecast
    ? forecast.points.map((point) => {
        const scale = BAND_SCALE[confidence];
        return {
          ...point,
          upper: point.value + (point.upper - point.value) * scale,
          lower: point.value - (point.value - point.lower) * scale,
        };
      })
    : [];

  const allValues = [
    ...history,
    ...scaledForecast.flatMap((point) => [
      point.value,
      point.upper,
      point.lower,
    ]),
  ].filter(Number.isFinite);
  const min = Math.max(0, Math.min(...allValues, 0) - 3);
  const max = Math.min(100, Math.max(...allValues, 12) + 3);
  const mapY = (value: number) =>
    h - pad - ((value - min) / (max - min || 1)) * (h - pad * 2);
  const mapHistoryX = (index: number) => {
    if (history.length <= 1) return pad;
    return pad + (index / (history.length - 1)) * (historyEndX - pad);
  };
  const mapForecastX = (index: number) => {
    if (scaledForecast.length <= 1) return forecastEndX;
    return (
      forecastStartX +
      ((index + 1) / scaledForecast.length) * (forecastEndX - forecastStartX)
    );
  };

  const historyCoords = history.map((value, index) => ({
    x: mapHistoryX(index),
    y: mapY(value),
    value,
  }));
  const actualPath = toPath(historyCoords);

  const forecastCoords = scaledForecast.map((point, index) => ({
    x: mapForecastX(index),
    y: mapY(point.value),
    yUpper: mapY(point.upper),
    yLower: mapY(point.lower),
  }));
  const anchor = historyCoords[historyCoords.length - 1];
  const expectedPath = anchor
    ? toPath([{ x: anchor.x, y: anchor.y }, ...forecastCoords])
    : "";
  const bandPath =
    anchor && forecastCoords.length > 0
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
          `L ${anchor.x.toFixed(1)} ${anchor.y.toFixed(1)}`,
          "Z",
        ].join(" ")
      : "";

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      width="100%"
      height={h}
      preserveAspectRatio="none"
      role="img"
      aria-label={`EQS forecast with ${confidence}% confidence interval.`}
      className="rounded-md border border-border/70 bg-muted/20"
    >
      <defs>
        <linearGradient id="eqsForecastBand" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="var(--color-info)" stopOpacity="0.22" />
          <stop
            offset="100%"
            stopColor="var(--color-info)"
            stopOpacity="0.04"
          />
        </linearGradient>
        <linearGradient id="eqsForecastArea" x1="0" x2="0" y1="0" y2="1">
          <stop
            offset="0%"
            stopColor="var(--color-chart-ink)"
            stopOpacity="0.12"
          />
          <stop
            offset="100%"
            stopColor="var(--color-chart-ink)"
            stopOpacity="0"
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
          strokeWidth="0.7"
          opacity="0.6"
        />
      ))}
      <rect
        x={forecastStartX}
        y={pad}
        width={forecastEndX - forecastStartX}
        height={h - pad * 2}
        fill="var(--color-info)"
        opacity="0.035"
      />
      {bandPath ? <path d={bandPath} fill="url(#eqsForecastBand)" /> : null}
      {actualPath ? (
        <>
          <path
            d={`${actualPath} L ${historyEndX} ${h - pad} L ${pad} ${h - pad} Z`}
            fill="url(#eqsForecastArea)"
          />
          <path
            d={actualPath}
            fill="none"
            stroke="var(--color-chart-ink)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </>
      ) : null}
      {expectedPath ? (
        <path
          d={expectedPath}
          fill="none"
          stroke="var(--color-info)"
          strokeWidth="1.6"
          strokeDasharray="5 4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ) : null}
      {historyCoords.map((point, index) => {
        const isOutlier = outlierIndexes.includes(index);
        return (
          <circle
            key={`${index}-${point.value}`}
            cx={point.x}
            cy={point.y}
            r={isOutlier ? 4 : 2.5}
            fill={isOutlier ? "var(--color-gold)" : "var(--color-chart-ink)"}
            opacity={isOutlier ? 0.95 : 0.6}
          />
        );
      })}
    </svg>
  );
}

function toPath(points: Array<{ x: number; y: number }>) {
  if (points.length < 2) return "";
  return points
    .map(
      (point, index) =>
        `${index === 0 ? "M" : "L"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`,
    )
    .join(" ");
}

function Summary({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "good" | "bad";
}) {
  return (
    <div>
      <div className="text-[0.625rem] uppercase tracking-[0.1em] text-muted-foreground">
        {label}
      </div>
      <div
        className="mt-1 font-mono text-[0.8125rem] tabular-nums"
        style={{
          color:
            tone === "good"
              ? "var(--color-health-good)"
              : "var(--color-oxblood)",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function Legend({
  color,
  label,
  dashed = false,
}: {
  color: string;
  label: string;
  dashed?: boolean | undefined;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[0.625rem] uppercase tracking-[0.08em] text-muted-foreground">
      <span
        className="h-px w-5"
        style={{
          background: dashed
            ? `repeating-linear-gradient(to right, ${color}, ${color} 4px, transparent 4px, transparent 7px)`
            : color,
        }}
      />
      {label}
    </span>
  );
}

function EqsTooltip() {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex cursor-help text-muted-foreground">
            <Info data-icon="inline-start" />
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-[260px] text-left leading-relaxed">
          EQS weights sends, saves, comments, and likes toward content quality
          instead of raw vanity engagement.
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
