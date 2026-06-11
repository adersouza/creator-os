import { AlertTriangle, Database, Search, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { MatrixLoader } from "@/components/ui/MatrixLoader";
import { Modal } from "@/components/ui/Modal";
import { Textarea } from "@/components/ui/Textarea";
import { type FleetAccount, useFleetAccounts } from "@/hooks/useFleetAccounts";
import {
  type InvestigateMetric,
  type InvestigationResult,
  useInvestigate,
} from "@/hooks/useInvestigate";

interface InvestigatePanelProps {
  open: boolean;
  onClose: () => void;
  accountId: string | null;
  metric: InvestigateMetric;
  metricLabel: string;
  periodDays?: number | undefined;
  focusDate?: string | undefined;
  accountHandle?: string | undefined;
}

/**
 * Centered investigation popup for a metric/account pair.
 * Lives at component level so any chart can drop an InvestigateButton
 * (which owns the open/closed state) in its header.
 */
export function InvestigatePanel({
  open,
  onClose,
  accountId,
  metric,
  metricLabel,
  periodDays = 30,
  focusDate,
  accountHandle,
}: InvestigatePanelProps) {
  const { mutate, data, streamingText, isPending, isError, error, reset } =
    useInvestigate();
  const [hypothesis, setHypothesis] = useState("");
  const [hasRun, setHasRun] = useState(false);
  const [selectedAccount, setSelectedAccount] = useState<{
    id: string;
    handle: string;
  } | null>(null);
  const selectedAccountId = accountId ?? selectedAccount?.id ?? null;
  const selectedAccountHandle =
    normalizeHandle(accountHandle) ?? selectedAccount?.handle ?? null;

  // Fire the investigation automatically the first time the panel opens.
  useEffect(() => {
    if (!open) return;
    if (!selectedAccountId) return;
    if (hasRun) return;
    setHasRun(true);
    mutate({ accountId: selectedAccountId, metric, periodDays, focusDate });
  }, [open, selectedAccountId, metric, periodDays, focusDate, hasRun, mutate]);

  // Reset when the panel closes so a re-open starts fresh.
  useEffect(() => {
    if (!open) {
      setHasRun(false);
      setHypothesis("");
      setSelectedAccount(null);
      reset();
    }
  }, [open, reset]);

  useEffect(() => {
    if (!open || !accountId) return;
    setSelectedAccount(null);
  }, [open, accountId]);

  const handleRerun = () => {
    if (!selectedAccountId) return;
    mutate({
      accountId: selectedAccountId,
      metric,
      periodDays,
      focusDate,
      hypothesis: hypothesis.trim() || undefined,
    });
  };

  const handleSelectAccount = (account: FleetAccount) => {
    reset();
    setHasRun(false);
    setHypothesis("");
    setSelectedAccount({ id: account.id, handle: account.handle });
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={
        <span className="flex items-center gap-2">
          <Sparkles
            className="h-4 w-4"
            style={{ color: "var(--color-oxblood)" }}
          />
          <span>Investigating {metricLabel}</span>
        </span>
      }
      description={
        selectedAccountHandle
          ? `${selectedAccountHandle} · last ${periodDays}d${
              focusDate ? ` · ${focusDate}` : ""
            }`
          : undefined
      }
      ariaLabel="Investigation"
      maxWidthClass="max-w-[680px]"
      panelClassName="flex max-h-[calc(100dvh-4rem)] flex-col overflow-hidden"
      bodyClassName="min-h-0 flex-1 overflow-y-auto"
      disablePanelBlur
    >
      {!selectedAccountId ? (
        <NeedsAccountState onSelectAccount={handleSelectAccount} />
      ) : (
        <div className="pr-1">
          {isPending ? (
            streamingText ? (
              <StreamingView text={streamingText} />
            ) : (
              <LoadingState />
            )
          ) : isError ? (
            <ErrorState message={error?.message ?? "Investigation failed"} />
          ) : data ? (
            <ResultView result={data} />
          ) : null}

          {/* Hypothesis input — available after first run so the user can nudge */}
          {!isPending && data ? (
            <div className="mt-6 pt-4 border-t border-border">
              <label
                htmlFor="hypothesis"
                className="text-[0.625rem] uppercase tracking-[0.08em] text-muted-foreground"
              >
                Re-run with a hypothesis
              </label>
              <Textarea
                id="hypothesis"
                value={hypothesis}
                onChange={(e) => setHypothesis(e.target.value)}
                placeholder="e.g. 'Reach dropped because Reels started crowding out regular posts'"
                className="mt-2 min-h-[64px]"
                style={{ resize: "vertical" }}
              />
              <div className="flex justify-end mt-2">
                <Button
                  type="button"
                  onClick={handleRerun}
                  disabled={!hypothesis.trim()}
                  variant="outline"
                  size="sm"
                  className="gap-1.5"
                >
                  <Search className="w-3.5 h-3.5" />
                  Re-investigate
                </Button>
              </div>
            </div>
          ) : null}
        </div>
      )}
    </Modal>
  );
}

function NeedsAccountState({
  onSelectAccount,
}: {
  onSelectAccount: (account: FleetAccount) => void;
}) {
  const { accounts, isLoading } = useFleetAccounts();
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const accountOptions = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return accounts
      .filter((account) => {
        if (!needle) return true;
        return (
          account.handle.toLowerCase().includes(needle) ||
          account.displayName.toLowerCase().includes(needle) ||
          account.groupName.toLowerCase().includes(needle) ||
          account.platform.toLowerCase().includes(needle)
        );
      })
      .sort((a, b) => {
        if (b.posts24h !== a.posts24h) return b.posts24h - a.posts24h;
        return b.healthScore - a.healthScore;
      });
  }, [accounts, query]);

  useEffect(() => {
    const id = window.setTimeout(() => searchRef.current?.focus(), 60);
    return () => window.clearTimeout(id);
  }, []);

  return (
    <div className="mx-auto flex w-full max-w-[560px] flex-col gap-4 py-3">
      <div className="flex shrink-0 items-start gap-3">
        <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-muted/40">
          <Database className="h-4 w-4 text-muted-foreground" />
        </div>
        <div className="min-w-0">
          <div className="text-[0.875rem] font-medium text-foreground">
            Choose an account to investigate
          </div>
          <div className="mt-1 text-[0.75rem] leading-relaxed text-muted-foreground">
            Investigations run on one connected account at a time. Pick an
            account here and the agent will start immediately.
          </div>
        </div>
      </div>

      <div className="relative block shrink-0">
        <Input
          ref={searchRef}
          autoComplete="off"
          spellCheck={false}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search account handle, group, or name"
          sizeVariant="lg"
          leadingIcon={<Search className="h-3.5 w-3.5" />}
        />
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-card/55">
        {isLoading ? (
          <div className="px-4 py-6 text-center text-[0.75rem] text-muted-foreground">
            Loading accounts...
          </div>
        ) : accountOptions.length > 0 ? (
          <div className="outline-none">
            {accountOptions.map((account) => (
              <Button
                key={account.id}
                type="button"
                variant="ghost"
                onClick={() => onSelectAccount(account)}
                className="group h-auto w-full justify-start gap-3 rounded-none border-b border-border px-3 py-3 text-left last:border-b-0"
              >
                <span
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-[0.6875rem] font-semibold uppercase"
                  style={{
                    borderColor: account.groupColor,
                    color: account.groupColor,
                    background:
                      "color-mix(in_srgb, currentColor 10%, transparent)",
                  }}
                >
                  {account.handle.replace("@", "").slice(0, 2) || "A"}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[0.8125rem] font-medium text-foreground">
                    {account.handle}
                  </span>
                  <span className="mt-0.5 block truncate text-[0.6875rem] text-muted-foreground">
                    {platformLabel(account.platform)} · {account.displayName} ·{" "}
                    {account.groupName}
                  </span>
                </span>
                <span className="hidden shrink-0 text-[0.68rem] font-medium uppercase tracking-wide text-muted-foreground sm:block">
                  {account.posts24h} posts 24h
                </span>
                <span className="shrink-0 rounded-full border border-border px-2 py-1 text-[0.68rem] font-medium uppercase tracking-wide text-muted-foreground group-hover:text-foreground">
                  Select
                </span>
              </Button>
            ))}
          </div>
        ) : (
          <div className="px-4 py-6 text-center text-[0.75rem] text-muted-foreground">
            No matching connected accounts.
          </div>
        )}
      </div>
    </div>
  );
}

function normalizeHandle(handle: string | undefined): string | null {
  if (!handle) return null;
  return handle.startsWith("@") ? handle : `@${handle}`;
}

function platformLabel(platform: FleetAccount["platform"]): string {
  return platform === "instagram" ? "Instagram" : "Threads";
}

function LoadingState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center gap-3">
      <MatrixLoader label="Running investigation" size="lg" tone="default" />
      <div className="text-[0.8125rem] text-muted-foreground">
        Pulling account history, posts, and trend data…
      </div>
      <div className="text-[0.6875rem] text-muted-foreground max-w-[280px]">
        The agent runs deterministic data collection first, then summarizes.
        Takes 5–12 seconds.
      </div>
    </div>
  );
}

/**
 * Streaming prose view — renders raw tokens as they arrive, before the final
 * parsed sections event lands. Keeps the reader engaged instead of staring
 * at a pulse dot.
 */
function StreamingView({ text }: { text: string }) {
  return (
    <div className="flex flex-col gap-2 py-2">
      <div className="flex items-center gap-2 text-[0.6875rem] uppercase tracking-[0.08em] text-muted-foreground">
        <Sparkles
          className="w-3 h-3 animate-pulse"
          style={{ color: "var(--color-oxblood)" }}
        />
        Drafting
      </div>
      <p className="text-[0.8125rem] text-foreground/85 leading-[1.55] whitespace-pre-wrap">
        {text}
        <span
          className="inline-block w-1.5 h-3 ml-0.5 align-middle animate-pulse"
          style={{ background: "var(--color-oxblood)" }}
          aria-hidden
        />
      </p>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-3 py-4">
      <AlertTriangle
        className="w-4 h-4 mt-0.5 shrink-0"
        style={{ color: "var(--color-health-warn)" }}
      />
      <div>
        <div className="text-[0.875rem] font-medium text-foreground">
          Investigation failed
        </div>
        <div className="text-[0.8125rem] text-muted-foreground mt-1 leading-[1.5]">
          {message}
        </div>
      </div>
    </div>
  );
}

function ResultView({ result }: { result: InvestigationResult }) {
  return (
    <div className="flex flex-col gap-4">
      {result.sections.map((section, i) => (
        <section
          key={`${section.title}-${i}`}
          className="border-b border-border pb-3 last:border-b-0"
        >
          <div className="text-[0.625rem] uppercase tracking-[0.08em] text-muted-foreground mb-1.5">
            {section.title}
          </div>
          <p className="text-[0.8125rem] text-foreground/90 leading-[1.55] whitespace-pre-wrap">
            {section.body}
          </p>
        </section>
      ))}

      {result.dataUsed.length > 0 ? (
        <div className="mt-2 flex items-center gap-2 flex-wrap">
          <Database className="w-3 h-3 text-muted-foreground" />
          <span className="text-[0.625rem] uppercase tracking-[0.08em] text-muted-foreground">
            Data used:
          </span>
          {result.dataUsed.map((src) => (
            <span
              key={src}
              className="text-[0.6875rem] px-1.5 py-0.5 rounded bg-muted text-muted-foreground"
            >
              {src}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
