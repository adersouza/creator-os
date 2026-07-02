"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

var REFRESH_MS = 30000;
var RETRY_HINT = "The dashboard will retry every 30 seconds and recover when the API responds.";

function apiErrorHint(status) {
  if (status === 401) return "Start the server with ALLOW_INSECURE_LOCAL=1 npm run dev or set CREATOR_OS_API_TOKEN.";
  return RETRY_HINT;
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
        hint: RETRY_HINT,
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
  if (!iso) return "—";
  var ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return iso.slice(0, 10);
  var mins = Math.floor(ms / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return mins + "m ago";
  var hours = Math.floor(mins / 60);
  if (hours < 24) return hours + "h ago";
  return Math.floor(hours / 24) + "d ago";
}

function Label({ children }) {
  return (
    <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium">
      {children}
    </span>
  );
}

function Card({ title, right, children }) {
  return (
    <div className="bg-card rounded-card border border-border p-5">
      <div className="flex items-center justify-between mb-4">
        <Label>{title}</Label>
        {right}
      </div>
      {children}
    </div>
  );
}

function Stat({ label, value, tone }) {
  var toneClass =
    tone === "bad" ? "text-amber" : tone === "good" ? "text-green" : "text-purple";
  return (
    <div className="bg-card rounded-card border border-border px-5 py-4">
      <Label>{label}</Label>
      <div className={"font-mono text-2xl mt-1 " + toneClass}>{value}</div>
    </div>
  );
}

function Row({ left, right, dim }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border/60 last:border-0 gap-3">
      <span className={"text-xs truncate " + (dim ? "text-muted" : "text-[#c8c8d0]")}>{left}</span>
      <span className="text-xs font-mono text-muted shrink-0">{right}</span>
    </div>
  );
}

function Empty({ children }) {
  return <div className="text-xs text-muted py-4 text-center">{children}</div>;
}

function PanelIssue({ children }) {
  if (!children) return null;
  return <div className="text-xs text-amber py-2">{children}</div>;
}

function LoadingSkeleton() {
  return (
    <div className="space-y-6" aria-label="Loading dashboard">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Array.from({ length: 4 }, function (_, i) {
          return (
            <div key={i} className="bg-card rounded-card border border-border px-5 py-4 space-y-3">
              <div className="h-3 w-20 bg-border rounded" />
              <div className="h-8 bg-border/80 rounded" />
            </div>
          );
        })}
      </div>
      <div className="grid md:grid-cols-2 gap-3">
        {Array.from({ length: 4 }, function (_, i) {
          return (
            <div key={i} className="bg-card rounded-card border border-border p-5 space-y-4">
              <div className="h-3 w-28 bg-border rounded" />
              <div className="h-16 bg-border/80 rounded" />
              <div className="h-3 bg-border rounded" />
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
    <div className="bg-card rounded-card border border-amber p-5">
      <Label>Dashboard unavailable</Label>
      <div className="mt-3 font-mono text-2xl text-amber">{title}</div>
      <div className="mt-2 text-sm text-[#c8c8d0]">{error?.reason || "The API did not respond."}</div>
      <div className="mt-4 text-xs font-mono text-purple">{error?.hint || RETRY_HINT}</div>
    </div>
  );
}

export default function Dashboard() {
  var [state, setState] = useState({
    status: "loading",
    data: null,
    error: null,
    stale: false,
  });

  useEffect(function () {
    var alive = true;
    async function load() {
      var result = await readApiJson("/api/dashboard");
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
  var cc = data?.reelGui?.commandCenter;
  var spend = data?.spend;
  var overBudget = spend?.budgetUsd != null && spend.todayUsd >= spend.budgetUsd;
  var failedCount =
    (data?.failedGenerations?.count || 0) + (cc ? Number(cc.failed_generations || 0) : 0);
  var queued = data?.renderQueue?.counts?.queued || 0;

  return (
    <div className="min-h-screen px-6 py-8 max-w-6xl mx-auto">
      <div className="flex items-baseline justify-between mb-6">
        <div className="flex items-baseline gap-3">
          <h1 className="font-serif text-2xl text-[#e4e4ec]">Dashboard</h1>
          <Link href="/" className="text-xs text-purple hover:underline">
            ← ContentForge
          </Link>
        </div>
        <span className="text-[10px] font-mono text-muted-dark">
          {state.stale
            ? "stale: " + (error?.message || "refresh failed") + " · retrying"
            : error && !data
              ? "error: " + (error.message || error.reason)
              : data
              ? "updated " + timeAgo(data.generatedAt) + " · refreshes 30s"
              : "loading…"}
        </span>
      </div>

      {state.status === "loading" ? (
        <LoadingSkeleton />
      ) : state.status === "error" ? (
        <ErrorPanel error={error} />
      ) : (
        <>
          {state.stale && (
            <div className="bg-amber/10 border border-amber rounded-card px-4 py-3 mb-4 text-xs text-amber">
              Showing last-good data. Latest refresh failed: {error?.message || error?.reason}
            </div>
          )}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <Stat
              label="In-flight gens"
              value={cc ? cc.in_flight_generations : "offline"}
              tone={cc ? undefined : "bad"}
            />
            <Stat label="Failed gens" value={failedCount} tone={failedCount > 0 ? "bad" : "good"} />
            <Stat label="Render queue" value={queued} />
            <Stat
              label="Spend today"
              value={usd(spend?.todayUsd) + (spend?.budgetUsd ? " / " + usd(spend.budgetUsd) : "")}
              tone={overBudget ? "bad" : "good"}
            />
          </div>

          <div className="grid md:grid-cols-2 gap-3">
        <Card
          title="Pipeline health"
          right={
            <span className={"text-[10px] font-mono " + (data?.reelGui?.online ? "text-green" : "text-amber")}>
              {data?.reelGui?.online ? "reel factory online" : "reel factory offline"}
            </span>
          }
        >
          {data.renderQueue?.error || data.failedGenerations?.error ? (
            <>
              <PanelIssue>{data.renderQueue?.error}</PanelIssue>
              <PanelIssue>{data.failedGenerations?.error}</PanelIssue>
            </>
          ) : (
            <>
              {Object.entries(data.renderQueue?.counts || {}).map(function ([status, n]) {
                return <Row key={status} left={"render " + status} right={n} />;
              })}
              {cc && <Row left="needs review (reel gui)" right={cc.needs_review} />}
              {cc && <Row left="ready to post" right={cc.ready_to_post} />}
              {(data.failedGenerations?.recent || []).map(function (item, i) {
                return (
                  <Row
                    key={i}
                    dim
                    left={"✕ " + (item.reason || item.stage || item.filename || "failed generation")}
                    right={item.timestamp ? timeAgo(item.timestamp) : ""}
                  />
                );
              })}
              {!data.renderQueue?.available && data.failedGenerations?.count === 0 && !cc && (
                <Empty>No pipeline data yet — run the reel factory to populate.</Empty>
              )}
            </>
          )}
        </Card>

        <Card
          title="Spend vs budget"
          right={spend?.budgetUsd == null ? <span className="text-[10px] font-mono text-muted">no daily cap set</span> : null}
        >
          {spend?.error ? (
            <PanelIssue>{spend.error}</PanelIssue>
          ) : !spend?.available ? (
            <Empty>Cost ledger not found.</Empty>
          ) : (
            <>
              {spend.budgetUsd != null && (
                <div className="h-1.5 rounded bg-border mb-4 overflow-hidden">
                  <div
                    className={"h-full rounded " + (overBudget ? "bg-amber" : "bg-purple")}
                    style={{ width: Math.min(100, (spend.todayUsd / spend.budgetUsd) * 100) + "%" }}
                  />
                </div>
              )}
              <Row left={"today · " + spend.todayEvents + " events"} right={usd(spend.todayUsd)} />
              {spend.recent.map(function (event, i) {
                return (
                  <Row
                    key={i}
                    dim
                    left={event.provider + " · " + event.operation}
                    right={usd(event.estimated_cost_usd) + " · " + timeAgo(event.created_at)}
                  />
                );
              })}
              {spend.recent.length === 0 && <Empty>No cost events yet.</Empty>}
            </>
          )}
        </Card>

        <Card
          title="Approval queue"
          right={
            <span className="text-[10px] font-mono text-muted">
              {data ? data.approvals.approved + " approved · " + data.approvals.rejected + " rejected" : ""}
            </span>
          }
        >
          {data.approvals?.error ? (
            <PanelIssue>{data.approvals.error}</PanelIssue>
          ) : (
            <>
              <div className={"font-mono text-2xl mb-3 " + (data.approvals.pending > 0 ? "text-amber" : "text-green")}>
                {data.approvals.pending}
                <span className="text-xs text-muted ml-2">awaiting review</span>
              </div>
              {data.approvals.runs.map(function (run) {
                return (
                  <a key={run.runId} href={"/?runId=" + encodeURIComponent(run.runId)} className="block hover:bg-card-hover rounded px-1 -mx-1">
                    <Row
                      left={run.runId}
                      right={run.pending + " pending / " + run.media + " files"}
                    />
                  </a>
                );
              })}
              {data.approvals.skipped > 0 && (
                <div className="text-[10px] text-muted mt-2">
                  scanned newest {data.approvals.scanned} · skipped {data.approvals.skipped}
                </div>
              )}
              {data.approvals.runs.length === 0 && <Empty>No runs with media found.</Empty>}
            </>
          )}
        </Card>

        <Card
          title="Posted + engagement"
          right={
            data?.outcomes?.available ? (
              <span className="text-[10px] font-mono text-muted">
                {compact(data.outcomes.totals.views)} views · {compact(data.outcomes.totals.likes)} likes
              </span>
            ) : null
          }
        >
          {data.outcomes?.error ? (
            <PanelIssue>{data.outcomes.error}</PanelIssue>
          ) : !data.outcomes?.available || data.outcomes.count === 0 ? (
            <Empty>No outcomes yet — the learning loop is waiting for real posts.</Empty>
          ) : (
            <>
              {Object.entries(data.outcomes.slots).map(function ([status, n]) {
                return <Row key={status} dim left={"slot " + status} right={n} />;
              })}
              {data.outcomes.recent.map(function (row, i) {
                return (
                  <Row
                    key={i}
                    left={(row.account || row.platform || "?") + " · " + (row.filename || "")}
                    right={compact(row.views) + "v · " + compact(row.likes) + "l · " + timeAgo(row.posted_at)}
                  />
                );
              })}
            </>
          )}
        </Card>
          </div>
        </>
      )}
    </div>
  );
}
