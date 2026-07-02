"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

var REFRESH_MS = 30000;
var AUTH_HINT =
  "Start the server with ALLOW_INSECURE_LOCAL=1 npm run dev or set CREATOR_OS_API_TOKEN.";

async function readApiJson(path, options) {
  try {
    var res = await fetch(path, { signal: AbortSignal.timeout(60000), ...options });
    var body = await res.json().catch(function () {
      return {};
    });
    if (!res.ok) {
      var reason = body.reason || body.error || res.statusText || "request failed";
      return {
        ok: false,
        error: {
          status: res.status,
          message: "HTTP " + res.status + ": " + reason,
          hint: res.status === 401 ? AUTH_HINT : "",
        },
      };
    }
    return { ok: true, data: body };
  } catch (err) {
    return { ok: false, error: { status: "network", message: err.message || "load failed" } };
  }
}

function epochAgo(epoch) {
  if (!epoch) return "";
  var mins = Math.floor((Date.now() / 1000 - epoch) / 60);
  if (mins < 1) return "now";
  if (mins < 60) return mins + "m";
  var hours = Math.floor(mins / 60);
  if (hours < 24) return hours + "h";
  return Math.floor(hours / 24) + "d";
}

function score(value) {
  return value == null ? "—" : Number(value).toFixed(3);
}

function Eyebrow({ children }) {
  return (
    <div className="font-display font-semibold text-[10px] uppercase tracking-[0.22em] text-faint">
      {children}
    </div>
  );
}

function DecisionBadge({ decision }) {
  var cls =
    decision === "approved"
      ? "text-live"
      : decision === "rejected"
        ? "text-alert"
        : "text-signal";
  return <span className={"text-xs font-semibold " + cls}>{decision}</span>;
}

function MediaPreview({ item }) {
  if (!item || !item.hasMedia) {
    return (
      <div className="flex items-center justify-center h-64 text-xs text-faint border border-seam rounded-panel">
        no media file on disk
      </div>
    );
  }
  var src = "/api/inbox/" + encodeURIComponent(item.assetId) + "/media";
  var isVideo = /\.(mp4|mov|webm)$/i.test(item.outputPath || "");
  if (isVideo) {
    return (
      <video
        key={item.assetId}
        src={src}
        controls
        autoPlay
        muted
        loop
        className="w-full max-h-[60vh] rounded-panel border border-seam bg-black"
      />
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      key={item.assetId}
      src={src}
      alt={item.assetId}
      className="w-full max-h-[60vh] object-contain rounded-panel border border-seam bg-black"
    />
  );
}

export default function InboxPage() {
  var [inbox, setInbox] = useState(null);
  var [history, setHistory] = useState(null);
  var [error, setError] = useState(null);
  var [cursor, setCursor] = useState(0);
  var [pendingReason, setPendingReason] = useState(null); // {decision} while reason input open
  var [reasonText, setReasonText] = useState("");
  var [busy, setBusy] = useState(false);
  var [flash, setFlash] = useState("");
  var reasonInputRef = useRef(null);

  var [refreshTick, setRefreshTick] = useState(0);
  var load = useCallback(function () {
    setRefreshTick(function (tick) {
      return tick + 1;
    });
  }, []);

  useEffect(
    function () {
      var alive = true;
      async function fetchAll() {
        var [inboxRes, historyRes] = await Promise.all([
          readApiJson("/api/inbox"),
          readApiJson("/api/inbox/history"),
        ]);
        if (!alive) return;
        if (!inboxRes.ok) {
          setError(inboxRes.error);
          return;
        }
        setError(null);
        setInbox(inboxRes.data);
        setHistory(historyRes.ok ? historyRes.data : { available: false, items: [] });
      }
      fetchAll();
      var timer = setInterval(fetchAll, REFRESH_MS);
      return function () {
        alive = false;
        clearInterval(timer);
      };
    },
    [refreshTick],
  );

  var items = (inbox && inbox.items) || [];
  var selected = items[Math.min(cursor, Math.max(0, items.length - 1))] || null;

  var submit = useCallback(
    async function (decision, reason) {
      if (!selected || busy) return;
      setBusy(true);
      var res = await readApiJson(
        "/api/inbox/" + encodeURIComponent(selected.assetId) + "/decision",
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ decision, reason: reason || undefined }),
        },
      );
      setBusy(false);
      setPendingReason(null);
      setReasonText("");
      if (!res.ok) {
        setFlash(res.error.message);
        return;
      }
      setFlash(selected.assetId + " → " + decision);
      load();
    },
    [selected, busy, load],
  );

  useEffect(
    function () {
      function onKey(event) {
        if (pendingReason) return; // reason input owns the keyboard
        if (event.target && /^(INPUT|TEXTAREA)$/.test(event.target.tagName)) return;
        if (event.key === "j") setCursor(function (c) {
          return Math.min(c + 1, Math.max(0, items.length - 1));
        });
        else if (event.key === "k") setCursor(function (c) {
          return Math.max(c - 1, 0);
        });
        else if (event.key === "a") submit("approved");
        else if (event.key === "r") setPendingReason({ decision: "rejected" });
        else if (event.key === "g") setPendingReason({ decision: "regenerate" });
        else return;
        event.preventDefault();
      }
      window.addEventListener("keydown", onKey);
      return function () {
        window.removeEventListener("keydown", onKey);
      };
    },
    [items.length, submit, pendingReason],
  );

  useEffect(
    function () {
      if (pendingReason && reasonInputRef.current) reasonInputRef.current.focus();
    },
    [pendingReason],
  );

  if (error) {
    return (
      <main className="max-w-3xl mx-auto p-8 space-y-3">
        <Eyebrow>Approval Inbox</Eyebrow>
        <div className="text-sm text-alert">{error.message}</div>
        {error.hint ? <div className="text-xs text-faint">{error.hint}</div> : null}
      </main>
    );
  }

  return (
    <main className="max-w-6xl mx-auto p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Eyebrow>Approval Inbox</Eyebrow>
          <div className="text-xs text-faint mt-1">
            j/k navigate · a approve · r reject · g regenerate
          </div>
        </div>
        <Link href="/" className="text-xs text-faint underline">
          ← command center
        </Link>
      </div>

      {flash ? <div className="text-xs text-signal">{flash}</div> : null}

      {inbox && !inbox.available ? (
        <div className="text-xs text-faint">
          No orchestrator state database yet — the inbox fills once the orchestrator is enabled.
        </div>
      ) : null}

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(280px,1fr)_2fr] gap-6">
        <section className="bg-panel/90 border border-seam rounded-panel p-4">
          <Eyebrow>Awaiting approval ({items.length})</Eyebrow>
          <ul className="mt-3 space-y-1">
            {items.length === 0 ? (
              <li className="text-xs text-faint py-3">Inbox empty.</li>
            ) : (
              items.map(function (item, index) {
                var active = index === cursor;
                return (
                  <li key={item.assetId}>
                    <button
                      type="button"
                      onClick={function () {
                        setCursor(index);
                      }}
                      className={
                        "w-full text-left px-3 py-2 rounded text-xs " +
                        (active ? "bg-seam text-ink" : "text-faint hover:bg-seam/50")
                      }
                    >
                      <div className="font-semibold truncate">{item.assetId}</div>
                      <div className="flex justify-between mt-0.5">
                        <span>rank {score(item.rankScore)}</span>
                        <span>{epochAgo(item.stateUpdatedAt)}</span>
                      </div>
                    </button>
                  </li>
                );
              })
            )}
          </ul>
        </section>

        <section className="bg-panel/90 border border-seam rounded-panel p-4 space-y-4">
          {selected ? (
            <>
              <div className="flex items-center justify-between">
                <Eyebrow>{selected.assetId}</Eyebrow>
                <span className="text-xs text-faint">
                  {selected.campaign} · {selected.runId} · attempt {selected.attempts}
                </span>
              </div>
              <MediaPreview item={selected} />
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <div className="text-faint">Caption</div>
                  <div className="whitespace-pre-wrap">
                    {(selected.lineage && selected.lineage.caption) || "—"}
                  </div>
                  {selected.lineage && selected.lineage.captionHash ? (
                    <div className="text-faint mt-1">hash {selected.lineage.captionHash}</div>
                  ) : null}
                </div>
                <div>
                  <div className="text-faint">Rank / predicted engagement</div>
                  <div>rank {score(selected.rankScore)}</div>
                  <pre className="text-[10px] text-faint overflow-x-auto mt-1">
                    {selected.predictedEngagement
                      ? JSON.stringify(selected.predictedEngagement, null, 1)
                      : "—"}
                  </pre>
                  {selected.lineage && selected.lineage.qc ? (
                    <pre className="text-[10px] text-faint overflow-x-auto mt-1">
                      {JSON.stringify(selected.lineage.qc, null, 1)}
                    </pre>
                  ) : null}
                </div>
              </div>
              {pendingReason ? (
                <form
                  onSubmit={function (event) {
                    event.preventDefault();
                    submit(pendingReason.decision, reasonText);
                  }}
                  className="flex gap-2 items-center"
                >
                  <span className="text-xs text-faint">{pendingReason.decision} reason:</span>
                  <input
                    ref={reasonInputRef}
                    value={reasonText}
                    onChange={function (event) {
                      setReasonText(event.target.value);
                    }}
                    onKeyDown={function (event) {
                      if (event.key === "Escape") {
                        setPendingReason(null);
                        setReasonText("");
                      }
                    }}
                    className="flex-1 bg-transparent border border-seam rounded px-2 py-1 text-xs"
                    placeholder="optional — becomes training signal (Enter to submit, Esc to cancel)"
                  />
                </form>
              ) : (
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={function () {
                      submit("approved");
                    }}
                    className="px-3 py-1.5 text-xs rounded border border-seam text-live"
                  >
                    approve (a)
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={function () {
                      setPendingReason({ decision: "rejected" });
                    }}
                    className="px-3 py-1.5 text-xs rounded border border-seam text-alert"
                  >
                    reject (r)
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={function () {
                      setPendingReason({ decision: "regenerate" });
                    }}
                    className="px-3 py-1.5 text-xs rounded border border-seam text-signal"
                  >
                    regenerate (g)
                  </button>
                </div>
              )}
            </>
          ) : (
            <div className="text-xs text-faint py-8 text-center">
              Nothing awaiting approval.
            </div>
          )}
        </section>
      </div>

      <section className="bg-panel/90 border border-seam rounded-panel p-4">
        <Eyebrow>History (last {history && history.items ? history.items.length : 0})</Eyebrow>
        <ul className="mt-3 space-y-1 text-xs">
          {history && history.items && history.items.length > 0 ? (
            history.items.map(function (item) {
              return (
                <li key={item.assetId + String(item.stateUpdatedAt)} className="flex justify-between gap-3">
                  <span className="truncate">{item.assetId}</span>
                  <span className="flex gap-3 shrink-0">
                    {item.reason ? <span className="text-faint truncate max-w-48">{item.reason}</span> : null}
                    <DecisionBadge decision={item.decision} />
                    <span className="text-faint">{epochAgo(item.approvedAt || item.stateUpdatedAt)}</span>
                  </span>
                </li>
              );
            })
          ) : (
            <li className="text-faint py-2">No decisions yet.</li>
          )}
        </ul>
      </section>
    </main>
  );
}
