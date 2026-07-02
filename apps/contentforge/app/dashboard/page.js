"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

var REFRESH_MS = 30000;

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

export default function Dashboard() {
  var [data, setData] = useState(null);
  var [error, setError] = useState("");

  useEffect(function () {
    var alive = true;
    async function load() {
      try {
        var res = await fetch("/api/dashboard");
        var body = await res.json();
        if (!res.ok) throw new Error(body.error || "load failed");
        if (alive) {
          setData(body);
          setError("");
        }
      } catch (err) {
        if (alive) setError(err.message || "load failed");
      }
    }
    load();
    var timer = setInterval(load, REFRESH_MS);
    return function () {
      alive = false;
      clearInterval(timer);
    };
  }, []);

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
          {error
            ? "error: " + error
            : data
              ? "updated " + timeAgo(data.generatedAt) + " · refreshes 30s"
              : "loading…"}
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <Stat
          label="In-flight gens"
          value={data ? (cc ? cc.in_flight_generations : "offline") : "…"}
          tone={cc ? undefined : "bad"}
        />
        <Stat label="Failed gens" value={data ? failedCount : "…"} tone={failedCount > 0 ? "bad" : "good"} />
        <Stat label="Render queue" value={data ? queued : "…"} />
        <Stat
          label="Spend today"
          value={data ? usd(spend?.todayUsd) + (spend?.budgetUsd ? " / " + usd(spend.budgetUsd) : "") : "…"}
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
          {!data ? (
            <Empty>Loading…</Empty>
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
          {!data ? (
            <Empty>Loading…</Empty>
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
          {!data ? (
            <Empty>Loading…</Empty>
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
          {!data ? (
            <Empty>Loading…</Empty>
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
    </div>
  );
}
