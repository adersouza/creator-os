"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

var REFRESH_MS = 30000;
var AUTH_HINT =
  "Start the server with ALLOW_INSECURE_LOCAL=1 npm run dev or set CREATOR_OS_API_TOKEN.";

function apiErrorHint(status) {
  if (status === 401) return AUTH_HINT;
  return "The dashboard will retry every 30 seconds and recover when the API responds.";
}

async function readApiJson(path) {
  try {
    var res = await fetch(path, { signal: AbortSignal.timeout(10000) });
    var body = await res.json().catch(function () {
      return {};
    });
    if (!res.ok) {
      var reason = body.reason || body.error || body.message || res.statusText || "request failed";
      return {
        ok: false,
        error: {
          status: res.status,
          reason,
          message: "HTTP " + res.status + ": " + reason,
          hint: apiErrorHint(res.status),
        },
      };
    }
    return { ok: true, data: body };
  } catch (err) {
    var timedOut = err && (err.name === "TimeoutError" || err.name === "AbortError");
    var reason = timedOut ? "request timed out after 10s" : err.message || "load failed";
    return {
      ok: false,
      error: {
        status: timedOut ? "timeout" : "network",
        reason,
        message: reason,
        hint: "The dashboard will retry every 30 seconds and recover when the API responds.",
      },
    };
  }
}

function usd(value) {
  if (value == null) return "—";
  return "$" + Number(value).toFixed(2);
}

function compact(value) {
  if (value == null) return "—";
  var n = Number(value);
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(n);
}

function timeAgo(iso) {
  if (!iso) return "";
  var ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms)) return String(iso).slice(0, 10);
  if (ms < 0) return String(iso).slice(11, 16) || String(iso).slice(0, 10);
  var mins = Math.floor(ms / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return mins + "m";
  var hours = Math.floor(mins / 60);
  if (hours < 24) return hours + "h";
  return Math.floor(hours / 24) + "d";
}

function Eyebrow({ children }) {
  return (
    <div className="font-display font-semibold text-[10px] uppercase tracking-[0.22em] text-faint">
      {children}
    </div>
  );
}

function Panel({ title, right, children, className = "" }) {
  return (
    <section className={"bg-panel/90 border border-seam rounded-panel p-5 " + className}>
      <div className="flex items-center justify-between mb-4">
        <Eyebrow>{title}</Eyebrow>
        {right}
      </div>
      {children}
    </section>
  );
}

function Tally({ tone }) {
  var cls =
    tone === "live"
      ? "tally-live"
      : tone === "signal"
        ? "tally-signal"
        : tone === "alert"
          ? "tally-alert"
          : "tally-off";
  return <span className={"tally " + cls} aria-hidden="true" />;
}

function Idle({ children }) {
  return <div className="text-xs text-faint py-3">{children}</div>;
}

function PanelIssue({ children }) {
  if (!children) return null;
  return <div className="text-xs text-alert py-2">{children}</div>;
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4" aria-label="Loading dashboard">
      <div className="border border-seam rounded-panel bg-panel/90 p-5">
        <div className="h-4 w-32 bg-seam rounded mb-5" />
        <div className="grid grid-cols-6 gap-3">
          {Array.from({ length: 6 }, function (_, i) {
            return (
              <div key={i} className="space-y-3">
                <div className="h-3 bg-seam rounded" />
                <div className="h-8 bg-seam-bright/60 rounded" />
                <div className="h-2 bg-seam rounded" />
              </div>
            );
          })}
        </div>
      </div>
      <div className="grid md:grid-cols-3 gap-4">
        {Array.from({ length: 3 }, function (_, i) {
          return (
            <div key={i} className="border border-seam rounded-panel bg-panel/90 p-5 space-y-4">
              <div className="h-3 w-24 bg-seam rounded" />
              <div className="h-8 bg-seam-bright/60 rounded" />
              <div className="h-3 bg-seam rounded" />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ErrorPanel({ error }) {
  var title =
    typeof error?.status === "number"
      ? "HTTP " + error.status
      : error?.status === "timeout"
        ? "Request timed out"
        : "Request failed";
  return (
    <section className="border border-alert/50 bg-alert/10 rounded-panel p-5">
      <Eyebrow>Dashboard unavailable</Eyebrow>
      <div className="mt-3 font-display font-bold text-alert text-lg">{title}</div>
      <div className="mt-2 text-sm text-dim">{error?.reason || "The API did not respond."}</div>
      <div className="mt-4 text-xs font-mono text-phosphor">{error?.hint || apiErrorHint()}</div>
    </section>
  );
}

/* The signature: the production line. */
function ProductionLine({ line, failedTotal }) {
  return (
    <div className="border border-seam rounded-panel bg-panel/90 px-2 py-5 overflow-x-auto">
      <div className="flex items-stretch min-w-[720px]">
        {line.map(function (stage, i) {
          return (
            <div key={stage.key} className="flex-1 flex items-center">
              {i > 0 && <div className="h-px w-full max-w-[48px] bg-seam-bright mx-1 shrink" />}
              <div className="px-3 min-w-[100px]">
                <div className="flex items-center gap-2 mb-2">
                  <Tally tone={stage.tone} />
                  <Eyebrow>{stage.label}</Eyebrow>
                </div>
                <div
                  className={
                    "font-mono text-3xl leading-none " +
                    (stage.value === null
                      ? "text-faint"
                      : stage.tone === "signal"
                        ? "text-signal"
                        : stage.tone === "live"
                          ? "text-phosphor"
                          : "text-dim")
                  }
                >
                  {stage.value === null ? "–" : stage.value}
                </div>
                <div className="text-[10px] text-faint mt-1.5">{stage.detail}</div>
              </div>
            </div>
          );
        })}
        <div className="flex items-center">
          <div className="h-px w-full max-w-[48px] bg-seam-bright mx-1" />
          <div className="px-3 min-w-[90px]">
            <div className="flex items-center gap-2 mb-2">
              <Tally tone={failedTotal > 0 ? "alert" : "idle"} />
              <Eyebrow>Failed</Eyebrow>
            </div>
            <div
              className={
                "font-mono text-3xl leading-none " + (failedTotal > 0 ? "text-alert" : "text-dim")
              }
            >
              {failedTotal}
            </div>
            <div className="text-[10px] text-faint mt-1.5">dead-letter</div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* Segmented VU meter for spend vs daily cap. */
function SpendMeter({ spend }) {
  var SEGMENTS = 24;
  var ratio = spend.budgetUsd ? Math.min(1, spend.todayUsd / spend.budgetUsd) : 0;
  var lit = Math.round(ratio * SEGMENTS);
  return (
    <div>
      <div className="flex gap-[3px] mb-3" role="img" aria-label={"Spend " + usd(spend.todayUsd) + (spend.budgetUsd ? " of " + usd(spend.budgetUsd) : "")}>
        {Array.from({ length: SEGMENTS }, function (_, i) {
          var on = i < lit;
          var zone = i / SEGMENTS;
          var color = !on
            ? "bg-seam"
            : zone < 0.6
              ? "bg-live"
              : zone < 0.85
                ? "bg-signal"
                : "bg-alert";
          return <span key={i} className={"h-4 flex-1 rounded-[2px] " + color} />;
        })}
      </div>
      <div className="flex items-baseline justify-between">
        <span className="font-mono text-2xl text-phosphor">{usd(spend.todayUsd)}</span>
        <span className="text-[10px] text-faint font-mono">
          {spend.budgetUsd
            ? "cap " + usd(spend.budgetUsd)
            : "no daily cap — set HIGGSFIELD_DAILY_BUDGET_USD"}
        </span>
      </div>
    </div>
  );
}

function SoulSplit({ souls }) {
  var items = Array.isArray(souls) ? souls : souls?.items || [];
  if (souls && souls.available === false) {
    return <PanelIssue>{souls.error || "Soul metrics unavailable."}</PanelIssue>;
  }
  var named = items.filter(function (soul) {
    return soul.soulId !== "unattributed";
  });
  if (named.length === 0) {
    return <Idle>No attributed posts yet. The A/B lights up when Stacey and Stacey1 start posting.</Idle>;
  }
  return (
    <div className="grid grid-cols-2 gap-3">
      {named.map(function (soul) {
        return (
          <div key={soul.soulId} className="border border-seam rounded-panel p-3 bg-panel-2">
            <div className="text-soul font-display font-bold text-sm mb-2">{soul.name}</div>
            <div className="font-mono text-xl text-phosphor">{compact(soul.views)}</div>
            <div className="text-[10px] text-faint">views · {soul.posts} posts</div>
            <div className="font-mono text-xs text-dim mt-1">
              {soul.engagementRate != null ? (soul.engagementRate * 100).toFixed(1) + "% eng" : "—"}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function CommandCenter() {
  var [state, setState] = useState({
    status: "loading",
    data: null,
    error: null,
    stale: false,
  });

  useEffect(function () {
    var alive = true;
    async function load() {
      var result = await readApiJson("/api/state");
      if (!alive) return;
      if (result.ok) {
        setState({
          status: "loaded",
          data: result.data,
          error: null,
          stale: false,
        });
      } else {
        setState(function (previous) {
          if (previous.data) {
            return { ...previous, status: "loaded", error: result.error, stale: true };
          }
          return {
            status: "error",
            data: null,
            error: result.error,
            stale: false,
          };
        });
      }
    }
    load();
    var timer = setInterval(load, REFRESH_MS);
    return function () {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  var data = state.data;
  var error = state.error;

  return (
    <main className="min-h-screen max-w-7xl mx-auto px-6 py-8">
      <header className="flex items-center justify-between mb-8">
        <div>
          <h1 className="font-display font-black text-xl tracking-[0.14em] text-phosphor uppercase">
            Creator&nbsp;OS
          </h1>
          <Eyebrow>Master control</Eyebrow>
        </div>
        <div className="flex items-center gap-4">
          <Link
            href="/inbox"
            className="font-display font-bold text-[11px] tracking-[0.18em] uppercase text-signal hover:underline"
          >
            Inbox →
          </Link>
          <span
            className={
              "flex items-center gap-2 border rounded-panel px-3 py-1.5 font-display font-bold text-[11px] tracking-[0.18em] uppercase " +
              (data?.onAir
                ? "border-live/40 text-live"
                : "border-seam text-faint")
            }
          >
            <Tally tone={data?.onAir ? "live" : "off"} />
            {data ? (data.onAir ? "On air" : "Line idle") : "…"}
          </span>
          <span className="text-[10px] font-mono text-faint">
            {state.stale
              ? "stale: " + (error?.message || "refresh failed") + " · retrying"
              : error && !data
                ? "error: " + (error.message || error.reason)
                : data
                  ? "updated " + timeAgo(data.generatedAt) + " ago · 30s"
                  : "loading"}
          </span>
        </div>
      </header>

      {state.status === "loading" ? (
        <LoadingSkeleton />
      ) : state.status === "error" ? (
        <ErrorPanel error={error} />
      ) : (
        <>
          {state.stale && (
            <div className="border border-signal/40 bg-signal/10 rounded-panel px-4 py-3 mb-4 text-xs text-signal">
              Showing last-good data. Latest refresh failed: {error?.message || error?.reason}
            </div>
          )}
          <div className="mb-4">
            <ProductionLine line={data.line} failedTotal={data.failedTotal} />
          </div>

          <div className="grid md:grid-cols-3 gap-4 mb-4">
            <Panel
              title="Spend today"
              right={
                <span className="text-[10px] font-mono text-faint">
                  {data.spend.todayEvents} events
                </span>
              }
            >
              {data.spend.error ? (
                <PanelIssue>{data.spend.error}</PanelIssue>
              ) : data.spend.available ? (
                <SpendMeter spend={data.spend} />
              ) : (
                <Idle>Cost ledger not found. Paid runs write it automatically.</Idle>
              )}
            </Panel>

            <Panel
              title="Approval queue"
              right={
                <Link
                  className="text-[10px] font-mono text-signal hover:underline"
                  href="/inbox"
                >
                  open review →
                </Link>
              }
            >
              {data.approvals.error ? (
                <PanelIssue>{data.approvals.error}</PanelIssue>
              ) : (
                <>
                  <div className="flex items-baseline gap-2 mb-3">
                    <span
                      className={
                        "font-mono text-2xl " + (data.approvals.pending > 0 ? "text-signal" : "text-phosphor")
                      }
                    >
                      {data.approvals.pending}
                    </span>
                    <span className="text-[10px] text-faint">
                      pending · {data.approvals.approved} approved · {data.approvals.rejected} rejected
                    </span>
                  </div>
                  {data.approvals.skipped > 0 && (
                    <div className="text-[10px] text-faint mb-2">
                      scanned newest {data.approvals.scanned} · skipped {data.approvals.skipped}
                    </div>
                  )}
                  {data.approvals.runs.slice(0, 4).map(function (run) {
                    return (
                      <div key={run.runId} className="flex justify-between py-1 border-t border-seam/60">
                        <span className="text-xs text-dim truncate">{run.runId}</span>
                        <span className="text-xs font-mono text-faint shrink-0">
                          {run.pending}/{run.media}
                        </span>
                      </div>
                    );
                  })}
                  {data.approvals.runs.length === 0 && (
                    <Idle>Nothing staged. Forge a batch in ContentForge to fill the queue.</Idle>
                  )}
                </>
              )}
            </Panel>

            <Panel title="Souls · A/B">
              <SoulSplit souls={data.souls} />
            </Panel>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <Panel
              title="Event log"
              right={<span className="text-[10px] font-mono text-faint">latest {data.events.length}</span>}
            >
              {data.failedGenerations.error || data.outcomes.error ? (
                <>
                  <PanelIssue>{data.failedGenerations.error}</PanelIssue>
                  <PanelIssue>{data.outcomes.error}</PanelIssue>
                </>
              ) : data.events.length === 0 ? (
                <Idle>Quiet floor. Events appear as the pipeline generates, fails, spends, and posts.</Idle>
              ) : (
                <div className="font-mono text-xs">
                  {data.events.map(function (event, i) {
                    return (
                      <div key={i} className="flex items-center gap-2 py-1.5 border-b border-seam/60 last:border-0">
                        <Tally tone={event.kind === "failure" ? "alert" : event.kind === "post" ? "live" : "idle"} />
                        <span className="text-dim truncate flex-1">{event.text}</span>
                        <span className="text-faint shrink-0">{event.value}</span>
                        <span className="text-faint/70 shrink-0 w-8 text-right">{timeAgo(event.at)}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </Panel>

            <Panel
              title="Engagement"
              right={
                data.outcomes.available && data.outcomes.count > 0 ? (
                  <span className="text-[10px] font-mono text-faint">
                    {compact(data.outcomes.totals.views)} views · {compact(data.outcomes.totals.likes)} likes
                  </span>
                ) : null
              }
            >
              {data.outcomes.error ? (
                <PanelIssue>{data.outcomes.error}</PanelIssue>
              ) : !data.outcomes.available || data.outcomes.count === 0 ? (
                <Idle>
                  No posted outcomes yet. This panel becomes the scoreboard once reels go live and
                  metrics sync back.
                </Idle>
              ) : (
                data.outcomes.recent.map(function (row, i) {
                  return (
                    <div key={i} className="flex items-center gap-2 py-1.5 border-b border-seam/60 last:border-0 text-xs">
                      <span className="text-dim truncate flex-1">
                        {(row.account || row.platform || "?") + " · " + (row.filename || "")}
                      </span>
                      <span className="font-mono text-phosphor shrink-0">{compact(row.views)}v</span>
                      <span className="font-mono text-faint shrink-0">{compact(row.likes)}l</span>
                      <span className="text-faint/70 font-mono shrink-0 w-8 text-right">
                        {timeAgo(row.posted_at)}
                      </span>
                    </div>
                  );
                })
              )}
            </Panel>
          </div>
        </>
      )}
    </main>
  );
}
