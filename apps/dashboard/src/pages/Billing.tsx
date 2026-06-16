import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Badge } from "@/components/ui/Badge";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { Button } from "@/components/ui/Button";
import {
  NovaCard,
  NovaDataPanel,
  NovaHeader,
  NovaSection,
  NovaToolbar,
  NovaUsageList,
} from "@/components/ui/NovaPrimitives";
import { Progress } from "@/components/ui/Progress";
import { Separator } from "@/components/ui/Separator";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusPill } from "@/components/ui/StatusPill";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/ToggleGroup";
import {
  Check,
  Zap,
  ShieldCheck,
  ExternalLink,
  ArrowUpRight,
  Users,
  CreditCard,
} from "lucide-react";
import { appToast } from "@/lib/toast";
import {
  subscriptionService,
  type StripePlanPriceKey,
  type StripePlanPrices,
  type UsageStats,
} from "@/services/subscriptionService";
import { supabase } from "@/services/supabase";
import { useWorkspaceStore } from "@/stores/useWorkspaceStore";
import { PRICING, type SubscriptionTier } from "@/types/team";

import { apiUrl } from "@/lib/apiUrl";
import { cn } from "@/lib/utils";
// Tier keys mirror juno33_pricing.html and Signup.tsx
const PENDING_PLAN_KEY = "juno33-pending-plan";

// CardKey matches `plan.name` strings rendered by the plans grid.
type PlanCardKey = "Creator" | "Pro" | "Agency" | "White-Label" | "Empire";

// API tier slug accepted by the current subscription backend.
type SupportedApiTier = "pro" | "agency" | "empire";

const PLAN_META: Record<
  string,
  {
    label: string;
    cardKey?: PlanCardKey | undefined;
    apiTier?: SupportedApiTier | undefined;
    cta: string;
    trial?: boolean | undefined;
    contactOnly?: boolean | undefined;
  }
> = {
  free: { label: "Free", cta: "Continue on Free" },
  creator: {
    label: "Creator",
    cardKey: "Creator",
    cta: "Contact support",
    contactOnly: true,
  },
  pro: { label: "Pro", cardKey: "Pro", apiTier: "pro", cta: "Upgrade to Pro" },
  agency: {
    label: "Agency · 14-day trial",
    cardKey: "Agency",
    apiTier: "agency",
    cta: "Start Agency trial",
    trial: true,
  },
  "white-label": {
    label: "White-Label",
    cardKey: "White-Label",
    cta: "Contact support",
    contactOnly: true,
  },
  empire: {
    label: "Empire",
    cardKey: "Empire",
    apiTier: "empire",
    cta: "Upgrade to Empire",
  },
};

const CARD_TO_PENDING: Record<PlanCardKey, string> = {
  Creator: "creator",
  Pro: "pro",
  Agency: "agency",
  "White-Label": "white-label",
  Empire: "empire",
};

const CARD_TO_STRIPE_PRICE_KEY: Record<PlanCardKey, StripePlanPriceKey> = {
  Creator: "creator",
  Pro: "pro",
  Agency: "agency",
  "White-Label": "white_label",
  Empire: "empire",
};

function planPriceDisplay(
  plan: PlanCardKey,
  billingCycle: "monthly" | "yearly",
  prices: StripePlanPrices | null,
): string {
  return (
    prices?.[CARD_TO_STRIPE_PRICE_KEY[plan]]?.[billingCycle]?.display ??
    staticPlanPriceDisplay(plan, billingCycle)
  );
}

function staticPlanPriceDisplay(
  plan: PlanCardKey,
  billingCycle: "monthly" | "yearly",
): string {
  const pricingKey = CARD_TO_PENDING[plan] as Exclude<
    keyof typeof PRICING,
    "addon"
  >;
  const tierPricing = PRICING[pricingKey];
  if (!tierPricing) return "Contact";

  const priceCents = tierPricing[billingCycle === "yearly" ? "year" : "month"];
  if (typeof priceCents !== "number") return "Contact";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: priceCents % 100 === 0 ? 0 : 2,
  }).format(priceCents / 100);
}

// Display labels for the current plan card (top-left). Keyed off the live
// workspace.subscriptionTier, not hardcoded strings.
const TIER_DISPLAY: Record<
  SubscriptionTier,
  { label: string; tagline?: string | undefined }
> = {
  free: { label: "Free", tagline: "Solo operator · 1 account" },
  pro: { label: "Pro", tagline: "Power users" },
  agency: { label: "Agency", tagline: "Teams & approvals" },
  empire: { label: "Empire", tagline: "High-throughput auto-posting" },
};

const PLAN_COMPARE_ROWS: Array<{
  label: string;
  values: Record<PlanCardKey, string>;
  strength: Record<PlanCardKey, number>;
}> = [
  {
    label: "Social accounts",
    values: {
      Creator: "2",
      Pro: "5",
      Agency: "unlimited",
      "White-Label": "unlimited",
      Empire: "unlimited",
    },
    strength: {
      Creator: 24,
      Pro: 42,
      Agency: 78,
      "White-Label": 86,
      Empire: 100,
    },
  },
  {
    label: "AI generation",
    values: {
      Creator: "150/mo",
      Pro: "unlimited",
      Agency: "unlimited",
      "White-Label": "unlimited",
      Empire: "unlimited",
    },
    strength: {
      Creator: 28,
      Pro: 72,
      Agency: 82,
      "White-Label": 90,
      Empire: 100,
    },
  },
  {
    label: "Reporting",
    values: {
      Creator: "basic",
      Pro: "advanced",
      Agency: "white-label",
      "White-Label": "embedded",
      Empire: "embedded",
    },
    strength: {
      Creator: 24,
      Pro: 50,
      Agency: 74,
      "White-Label": 90,
      Empire: 100,
    },
  },
  {
    label: "Automation",
    values: {
      Creator: "manual",
      Pro: "assisted",
      Agency: "approvals",
      "White-Label": "high-limit",
      Empire: "24/7 loop",
    },
    strength: {
      Creator: 18,
      Pro: 45,
      Agency: 68,
      "White-Label": 82,
      Empire: 100,
    },
  },
  {
    label: "Support",
    values: {
      Creator: "standard",
      Pro: "priority",
      Agency: "success",
      "White-Label": "onboarding",
      Empire: "dedicated",
    },
    strength: {
      Creator: 22,
      Pro: 48,
      Agency: 74,
      "White-Label": 86,
      Empire: 100,
    },
  },
];

export function Billing() {
  const [billingCycle, setBillingCycle] = useState<"monthly" | "yearly">(
    "yearly",
  );
  const [pendingPlan, setPendingPlan] = useState<string | null>(null);
  const [checkoutLoading, setCheckoutLoading] =
    useState<SupportedApiTier | null>(null);
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [planPrices, setPlanPrices] = useState<StripePlanPrices | null>(null);
  const [portalLoading, setPortalLoading] = useState(false);
  const planSectionRef = useRef<HTMLDivElement>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const currentWorkspace = useWorkspaceStore((s) => s.currentWorkspace);

  const tier: SubscriptionTier =
    (currentWorkspace?.subscriptionTier as SubscriptionTier | undefined) ??
    "free";
  const tierDisplay = TIER_DISPLAY[tier] ?? TIER_DISPLAY.free;

  useEffect(() => {
    try {
      const stored = localStorage.getItem(PENDING_PLAN_KEY);
      if (stored && PLAN_META[stored]) setPendingPlan(stored);
    } catch {}
  }, []);

  // Load live usage stats (account/member count + limits) from Supabase.
  // Falls back to null so the UI can show an honest empty state if the
  // workspace row isn't readable yet.
  useEffect(() => {
    let cancelled = false;
    if (!currentWorkspace?.id) {
      setUsage(null);
      return;
    }
    (async () => {
      try {
        const stats = await subscriptionService.getUsageStats(
          currentWorkspace.id,
        );
        if (!cancelled) setUsage(stats);
      } catch {
        if (!cancelled) setUsage(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentWorkspace?.id]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const prices = await subscriptionService.getPlanPrices();
      if (!cancelled) setPlanPrices(prices);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Route "Update payment method" through Stripe Customer Portal — we never
  // collect card details in-app (PCI scope + design policy).
  const openPortal = async () => {
    if (portalLoading) return;
    if (!currentWorkspace?.id) {
      appToast.error("No workspace selected", {
        description: "Choose a workspace before opening billing portal.",
      });
      return;
    }
    if (tier === "free") {
      appToast.info("Add a plan first", {
        description: "Upgrade to a paid plan to manage payment methods.",
      });
      return;
    }
    setPortalLoading(true);
    try {
      const url = await subscriptionService.createPortalSession(
        currentWorkspace.id,
      );
      window.location.href = url;
    } catch (err) {
      const description =
        err instanceof Error ? err.message : "Unable to open billing portal.";
      appToast.error("Could not open billing portal", { description });
      setPortalLoading(false);
    }
  };

  // Handle Stripe Checkout return. Stripe webhooks are async (~5–10s), so we
  // poll the subscription check endpoint until the server reflects the new plan
  // before surfacing the success toast.
  useEffect(() => {
    const outcome = searchParams.get("checkout");
    if (outcome === "success") {
      const syncId = appToast.loading("Syncing your new plan…", {
        description: "This takes a moment while Stripe finishes.",
      });
      try {
        localStorage.removeItem(PENDING_PLAN_KEY);
      } catch {}
      setPendingPlan(null);
      setSearchParams({}, { replace: true });

      // Poll up to 15 × 2s = 30s.
      let attempts = 0;
      const interval = setInterval(async () => {
        attempts += 1;
        try {
          const {
            data: { session },
          } = await supabase.auth.getSession();
          const resp = await fetch(
            apiUrl("/api/subscription?action=check-trial"),
            {
              method: "POST",
              headers: {
                Authorization: `Bearer ${session?.access_token || ""}`,
                "Content-Type": "application/json",
              },
              body: "{}",
            },
          );
          if (resp.ok) {
            const res = await resp.json();
            // If the tier no longer says "trial" or a numeric tier resolves, we're done.
            if (res && (res.tier || res.plan || res.active === true)) {
              clearInterval(interval);
              appToast.success("Plan activated", {
                id: syncId,
                description: "Welcome to your new plan.",
              });
              return;
            }
          }
        } catch {
          /* ignore transient — keep polling */
        }
        if (attempts >= 15) {
          clearInterval(interval);
          appToast.success("Subscription activated", {
            id: syncId,
            description:
              "Still syncing — refresh the page if your plan hasn't updated.",
          });
        }
      }, 2000);

      return () => clearInterval(interval);
    } else if (outcome === "cancel") {
      appToast.info("Checkout canceled", {
        description:
          "Your plan is unchanged. Pick up where you left off whenever you're ready.",
      });
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const pendingMeta = pendingPlan ? PLAN_META[pendingPlan] : null;

  const clearPending = () => {
    try {
      localStorage.removeItem(PENDING_PLAN_KEY);
    } catch {}
    setPendingPlan(null);
  };

  const startCheckout = async (apiTier: SupportedApiTier, trial = false) => {
    if (checkoutLoading) return;
    if (!currentWorkspace?.id) {
      appToast.error("No workspace selected", {
        description: "Choose a workspace before starting checkout.",
      });
      return;
    }
    setCheckoutLoading(apiTier);
    try {
      const billing = billingCycle === "yearly" ? "year" : "month";

      if (
        apiTier === "empire" &&
        currentWorkspace.subscriptionTier === "agency"
      ) {
        const result = await subscriptionService.upgradeToEmpire(
          currentWorkspace.id,
          billing,
        );
        window.location.href = result.url;
        return;
      }

      const result = await subscriptionService.createCheckoutSession(
        currentWorkspace.id,
        apiTier,
        billing,
        {
          requestTrial: trial,
          successUrl: `${window.location.origin}/billing?checkout=success`,
          cancelUrl: `${window.location.origin}/billing?checkout=cancel`,
        },
      );
      window.location.href = result.url;
    } catch (err) {
      const description =
        err instanceof Error ? err.message : "Unable to start checkout.";
      appToast.error("Checkout failed", { description });
      setCheckoutLoading(null);
    }
  };

  const handleConfirm = () => {
    const pendingCard = pendingMeta?.cardKey;
    const pendingHasLivePrice = pendingCard
      ? Boolean(
          planPrices?.[CARD_TO_STRIPE_PRICE_KEY[pendingCard]]?.[billingCycle]
            ?.display,
        )
      : false;
    if (
      pendingMeta?.contactOnly ||
      (pendingMeta?.apiTier && !pendingHasLivePrice)
    ) {
      appToast.info("Sales-assisted plan", {
        description: `${pendingMeta.label} is not available through self-serve checkout yet.`,
      });
      return;
    }
    if (!pendingMeta?.apiTier) return;
    startCheckout(pendingMeta.apiTier, pendingMeta.trial === true);
  };

  const scrollToPlans = () => {
    planSectionRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  };

  // Prices come from Stripe Price objects. If a price env var is absent or
  // Stripe lookup fails, the card shows an explicit unavailable state instead
  // of stale hardcoded dollars.
  const plans: {
    name: PlanCardKey;
    price: string;
    description: string;
    features: string[];
    popular?: boolean | undefined;
    currentTier?: SubscriptionTier | undefined;
  }[] = [
    {
      name: "Creator",
      price: planPriceDisplay("Creator", billingCycle, planPrices),
      description: "For solo operators managing their own brand.",
      features: [
        "Up to 2 social accounts",
        "Basic analytics",
        "AI generation included",
        "Standard support",
      ],
      currentTier: "free",
    },
    {
      name: "Pro",
      price: planPriceDisplay("Pro", billingCycle, planPrices),
      description: "Power users who need advanced tooling and higher limits.",
      features: [
        "Up to 5 social accounts",
        "Advanced analytics & reports",
        "Unlimited AI generations",
        "Competitor tracking",
      ],
      popular: true,
      currentTier: "pro",
    },
    {
      name: "Agency",
      price: planPriceDisplay("Agency", billingCycle, planPrices),
      description:
        "Teams managing multiple client brands, with approvals. Includes a 14-day trial.",
      features: [
        "Unlimited social accounts",
        "Team collaboration & approvals",
        "Custom brand-voice profiles",
        "White-label reports",
      ],
      currentTier: "agency",
    },
    {
      name: "White-Label",
      price: planPriceDisplay("White-Label", billingCycle, planPrices),
      description:
        "Ship Juno33 as your own product with custom branding and domains.",
      features: ["Everything in Agency", "Custom domain & branding"],
    },
    {
      name: "Empire",
      price: planPriceDisplay("Empire", billingCycle, planPrices),
      description: "Max-throughput auto-posting for large fleets.",
      features: [
        "Everything in White-Label",
        "24/7 auto-posting",
        "Multi-account round-robin",
      ],
      currentTier: "empire",
    },
  ];
  const planRank: Record<SubscriptionTier, number> = {
    free: 0,
    pro: 1,
    agency: 2,
    empire: 4,
  };
  const planCardRank: Record<PlanCardKey, number> = {
    Creator: 0,
    Pro: 1,
    Agency: 2,
    "White-Label": 3,
    Empire: 4,
  };
  const currentRank = planRank[tier] ?? 0;
  const recommendedPlan =
    tier === "free"
      ? plans.find((plan) => plan.name === "Pro")
      : tier === "pro"
        ? plans.find((plan) => plan.name === "Agency")
        : tier === "agency"
          ? plans.find((plan) => plan.name === "Empire")
          : null;
  const recommendedMeta = recommendedPlan
    ? PLAN_META[CARD_TO_PENDING[recommendedPlan.name]]
    : null;
  const usageRows = usage
    ? [
        {
          label: "Connected accounts",
          value: usage.accountCount,
          max: usage.accountLimit,
          helper:
            usage.accountLimit === Infinity
              ? "Unlimited account pool"
              : `${Math.max(0, usage.accountLimit - usage.accountCount)} slots remaining`,
        },
        {
          label: "Team members",
          value: usage.memberCount,
          max: usage.memberLimit,
          helper:
            usage.memberLimit === Infinity
              ? "Unlimited seats"
              : `${Math.max(0, usage.memberLimit - usage.memberCount)} seats remaining`,
        },
      ]
    : [];
  const usageItems = usageRows.map((row) => {
    const unlimited = row.max === Infinity;
    const safeMax = row.max <= 0 || unlimited ? Math.max(row.value, 1) : row.max;
    const progress = unlimited ? undefined : Math.min(100, Math.round((row.value / safeMax) * 100));
    const nearCap = !unlimited && progress !== undefined && progress >= 80;
    return {
      label: row.label,
      value: unlimited
        ? row.value.toLocaleString()
        : `${row.value.toLocaleString()} / ${safeMax.toLocaleString()}`,
      description: row.helper,
      limit: unlimited ? "unlimited" : `${safeMax.toLocaleString()} max`,
      progress,
      tone: nearCap ? "warning" : unlimited ? "success" : "primary",
    } as const;
  });

  return (
    <NovaScreen className="billing-page" width="narrow">
      <NovaHeader
        eyebrow="Billing"
        title="Billing & plans"
        meta={
          <span className="inline-flex items-center gap-1.5">
            <BrandLogo name="stripe" size="xs" />
            Stripe · live
          </span>
        }
        description={
          <>
            <strong className="font-semibold text-foreground">
              Keep limits, billing, and upgrades in one operator view.
            </strong>{" "}
            Review usage, compare tiers, and switch plans through Stripe
            checkout.
          </>
        }
        actions={
          <Badge tone={tier === "free" ? "secondary" : "oxblood"}>
            {tierDisplay.label}
          </Badge>
        }
      />

      {pendingMeta && (
        <NovaCard
          className="border-[color-mix(in_srgb,var(--color-oxblood)_22%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-oxblood)_8%,var(--color-card))] text-[color:var(--color-oxblood)]"
          contentClassName="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center"
        >
          <div className="flex items-center gap-3">
            <span className="w-1.5 h-1.5 rounded-full bg-current" />
            <div>
              <div className="text-[0.68rem] font-medium uppercase tracking-wide opacity-80">
                You selected
              </div>
              <div className="text-sm font-semibold mt-0.5">
                {pendingMeta.label}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {pendingMeta.cardKey ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={scrollToPlans}
                className="border-current text-current opacity-80 hover:opacity-100"
              >
                Review {pendingMeta.cardKey}
              </Button>
            ) : (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleConfirm}
                className="border-current text-current opacity-80 hover:opacity-100"
              >
                {pendingMeta.cta}
              </Button>
            )}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={clearPending}
              className="text-current opacity-60 hover:opacity-90"
            >
              Dismiss
            </Button>
          </div>
        </NovaCard>
      )}

      <NovaSection className="mb-10 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
        <NovaCard
          eyebrow="Current plan"
          title={tierDisplay.label}
          description={
            tierDisplay.tagline ??
            "Workspace limits and billing state are synced from your subscription."
          }
          action={
            <StatusPill
              tone={tier === "free" ? "idle" : "good"}
              size="xs"
              icon={<ShieldCheck className="h-3 w-3" />}
            >
              {tier === "free" ? "Free" : "Active"}
            </StatusPill>
          }
        >
          <div className="grid gap-4 md:grid-cols-[minmax(0,0.95fr)_minmax(280px,0.65fr)]">
            <NovaCard
              eyebrow="Subscription"
              title={tier === "free" ? "No active paid plan" : "Paid plan active"}
              description={
                tier === "free"
                  ? "Upgrade when you need more connected accounts, team seats, and reporting headroom."
                  : "Invoices, payment methods, and receipts are managed in the Stripe portal."
              }
              action={
                tier === "free" ? (
                  <Badge tone="secondary">Self-serve ready</Badge>
                ) : (
                  <ShieldCheck
                    className="size-4 text-[color:var(--color-health-good)]"
                    aria-hidden="true"
                  />
                )
              }
              variant="panel"
            >
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-border bg-muted/35 p-3">
                  <div className="app-caption text-muted-foreground">
                    Current tier
                  </div>
                  <div className="mt-1 text-lg font-semibold text-foreground">
                    {tierDisplay.label}
                  </div>
                  <div className="app-caption mt-1 text-muted-foreground">
                    {tierDisplay.tagline ?? "Workspace subscription"}
                  </div>
                </div>
                <div className="rounded-lg border border-border bg-muted/35 p-3">
                  <div className="app-caption text-muted-foreground">
                    Billing status
                  </div>
                  <div className="mt-1 text-lg font-semibold text-foreground">
                    {tier === "free" ? "Not connected" : "Stripe"}
                  </div>
                  <div className="app-caption mt-1 text-muted-foreground">
                    {tier === "free"
                      ? "No card required on Free"
                      : "Secure customer portal"}
                  </div>
                </div>
              </div>
              <Button
                variant={tier === "free" ? "default" : "outline"}
                className="mt-4 w-full justify-between"
                disabled={portalLoading}
                onClick={() => {
                  if (tier === "free") {
                    scrollToPlans();
                    return;
                  }
                  void openPortal();
                }}
              >
                {tier === "free" ? (
                  <>
                    Compare paid plans
                    <ArrowUpRight data-icon="inline-end" aria-hidden="true" />
                  </>
                ) : portalLoading ? (
                  "Opening Stripe..."
                ) : (
                  <>
                    Manage billing in Stripe
                    <ExternalLink data-icon="inline-end" aria-hidden="true" />
                  </>
                )}
              </Button>
            </NovaCard>

            <NovaCard
              eyebrow="Usage"
              title="Workspace headroom"
              action={
                <Users
                  className="size-4 text-muted-foreground"
                  aria-hidden="true"
                />
              }
              variant="panel"
            >
              <div className="flex flex-col gap-5">
                {usage ? (
                  <NovaUsageList items={usageItems} />
                ) : (
                  <div
                    className="flex flex-col gap-3"
                    role="status"
                    aria-label="Waiting for subscription usage"
                  >
                    <Skeleton className="h-3 w-28 rounded-full" />
                    <Skeleton className="h-1.5 w-full rounded-full" />
                    <Skeleton className="h-3 w-24 rounded-full" />
                  </div>
                )}
              </div>
            </NovaCard>
          </div>

          <NovaCard
            className="mt-4"
            eyebrow="Payment method"
            variant="panel"
            contentClassName="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-12 items-center justify-center rounded-md border border-border bg-muted/35">
                {tier === "free" ? (
                  <CreditCard
                    className="size-4 text-muted-foreground"
                    aria-hidden="true"
                  />
                ) : (
                  <BrandLogo name="stripe" size="sm" />
                )}
              </div>
              <div className="min-w-0">
                <div className="app-card-title text-foreground">
                  {tier === "free"
                    ? "No payment method on file"
                    : "Stripe-managed"}
                </div>
                <div className="app-caption mt-1 text-muted-foreground">
                  {tier === "free"
                    ? "Payment details are requested only during checkout."
                    : "Update cards, invoices, tax details, and receipts in Stripe."}
                </div>
              </div>
            </div>
            <Button
              variant="outline"
              className="w-full sm:w-auto"
              disabled={portalLoading || tier === "free"}
              onClick={() => void openPortal()}
            >
              {portalLoading ? (
                "Opening..."
              ) : (
                <>
                  Open portal
                  <ExternalLink data-icon="inline-end" aria-hidden="true" />
                </>
              )}
            </Button>
          </NovaCard>
        </NovaCard>

        <NovaCard
          eyebrow="Recommended next step"
          className="h-full"
          contentClassName="flex h-full flex-col"
        >
          {recommendedPlan && recommendedMeta ? (
            <>
              <div className="flex flex-1 flex-col">
                <h3 className="text-lg font-semibold tracking-[-0.02em] text-foreground">
                  {recommendedPlan.name}
                </h3>
                <p className="app-body mt-2 text-muted-foreground">
                  {recommendedPlan.description}
                </p>
                <div className="mt-5">
                  <div className="app-kpi-value text-[2rem] font-bold text-foreground">
                    {recommendedPlan.price}
                  </div>
                  <div className="app-caption mt-1 text-muted-foreground">
                    {billingCycle === "yearly"
                      ? "Annual billing selected"
                      : "Monthly billing selected"}
                  </div>
                </div>
                <ul className="mt-5 flex flex-col gap-2">
                  {recommendedPlan.features.slice(0, 3).map((feature) => (
                    <li key={feature} className="flex items-start gap-2">
                      <Check
                        className="mt-0.5 size-3.5 shrink-0 text-[color:var(--color-health-good)]"
                        aria-hidden="true"
                      />
                      <span className="app-caption text-muted-foreground">
                        {feature}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
              <Button
                variant="default"
                className="mt-5 w-full"
                disabled={
                  checkoutLoading !== null ||
                  !recommendedMeta.apiTier ||
                  recommendedMeta.contactOnly
                }
                onClick={() => {
                  if (!recommendedMeta.apiTier || recommendedMeta.contactOnly) {
                    scrollToPlans();
                    return;
                  }
                  startCheckout(
                    recommendedMeta.apiTier,
                    recommendedMeta.trial === true,
                  );
                }}
              >
                {checkoutLoading === recommendedMeta.apiTier
                  ? "Starting checkout..."
                  : (recommendedMeta.cta ??
                    `Upgrade to ${recommendedPlan.name}`)}
                <ArrowUpRight data-icon="inline-end" aria-hidden="true" />
              </Button>
            </>
          ) : (
            <div className="flex h-full flex-col justify-between gap-5">
              <div>
                <div className="mb-4 inline-flex h-10 w-10 items-center justify-center rounded-lg border border-border bg-muted/35">
                  <ShieldCheck
                    className="size-4 text-[color:var(--color-health-good)]"
                    aria-hidden="true"
                  />
                </div>
                <h3 className="text-lg font-semibold tracking-[-0.02em] text-foreground">
                  Highest tier active
                </h3>
                <p className="app-body mt-2 text-muted-foreground">
                  Your workspace is already on the top self-serve plan. Keep
                  invoices and payment methods in Stripe, or contact support for
                  custom limits.
                </p>
              </div>
              <div className="rounded-lg border border-border bg-muted/35 p-3">
                <div className="flex items-center gap-2">
                  <BrandLogo name="stripe" size="xs" />
                  <span className="text-sm font-semibold text-foreground">
                    Stripe portal
                  </span>
                </div>
                <p className="app-caption mt-2 text-muted-foreground">
                  Receipts, billing contacts, tax details, and cards stay in the
                  secure portal.
                </p>
              </div>
              <Button
                variant="outline"
                className="w-full justify-between"
                disabled={portalLoading || tier === "free"}
                onClick={() => void openPortal()}
              >
                {portalLoading ? "Opening..." : "Open billing portal"}
                <ExternalLink data-icon="inline-end" aria-hidden="true" />
              </Button>
            </div>
          )}
        </NovaCard>
      </NovaSection>

      <div
        ref={planSectionRef}
        className="mb-5 flex flex-col sm:flex-row items-end justify-between gap-4 scroll-mt-6"
      >
        <div>
          <div className="text-[0.68rem] font-medium uppercase tracking-wide text-muted-foreground">
            Upgrade path
          </div>
          <h2 className="mt-1 text-[1.25rem] font-semibold tracking-[-0.03em] text-foreground">
            Available plans
          </h2>
        </div>
        <NovaToolbar>
          <ToggleGroup
            type="single"
            value={billingCycle}
            onValueChange={(value) => {
              if (value === "monthly" || value === "yearly") {
                setBillingCycle(value);
              }
            }}
            aria-label="Billing cycle"
            className="rounded-md"
          >
            <ToggleGroupItem value="monthly" sizeVariant="sm">
              Monthly
            </ToggleGroupItem>
            <ToggleGroupItem value="yearly" sizeVariant="sm">
              Yearly
              <span className="ml-1.5 text-[0.625rem] font-semibold text-[color:var(--color-oxblood)] data-[state=on]:text-current">
                -20%
              </span>
            </ToggleGroupItem>
          </ToggleGroup>
        </NovaToolbar>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {plans.map((plan) => {
          const isSelected = pendingMeta?.cardKey === plan.name;
          const meta = PLAN_META[CARD_TO_PENDING[plan.name]];
          const apiTier = meta?.apiTier;
          const isCurrentTier =
            currentWorkspace?.subscriptionTier === plan.currentTier;
          const planRankValue = planCardRank[plan.name];
          const relationLabel = isCurrentTier
            ? "Current"
            : planRankValue > currentRank
              ? "Upgrade"
              : "Available";
          const busy = apiTier !== undefined && checkoutLoading === apiTier;
          const isSelfServe = apiTier !== undefined;
          const hasLivePrice = Boolean(
            planPrices?.[CARD_TO_STRIPE_PRICE_KEY[plan.name]]?.[billingCycle]
              ?.display,
          );
          const needsSalesAssist = Boolean(
            meta?.contactOnly || (isSelfServe && !hasLivePrice),
          );
          const checkColor = isSelected
            ? "var(--color-oxblood)"
            : plan.popular
              ? "var(--color-foreground)"
              : "var(--color-muted-foreground)";
          return (
            <NovaCard
              key={plan.name}
              className={cn(
                "relative flex flex-col",
                isSelected &&
                  "border-[color:var(--color-oxblood)] shadow-[0_8px_24px_color-mix(in_srgb,var(--color-oxblood)_14%,transparent)]",
                !isSelected &&
                  plan.popular &&
                  "shadow-[0_8px_24px_color-mix(in_srgb,var(--color-foreground)_6%,transparent)]",
              )}
              contentClassName="flex h-full flex-col"
            >
              {(isSelected || plan.popular) && (
                <Badge
                  tone={isSelected ? "oxblood" : "secondary"}
                  className="absolute -top-2.5 left-1/2 -translate-x-1/2"
                >
                  {isSelected ? (
                    "Your selection"
                  ) : (
                    <>
                      <Zap data-icon="inline-start" aria-hidden="true" />{" "}
                      Popular
                    </>
                  )}
                </Badge>
              )}

              <div className="mb-4">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h3 className="app-card-title text-foreground">
                    {plan.name}
                  </h3>
                  <StatusPill
                    tone={isCurrentTier ? "good" : "info"}
                    size="xs"
                    className="border-border"
                  >
                    {relationLabel}
                  </StatusPill>
                </div>
                <p className="app-caption min-h-[40px] text-muted-foreground">
                  {plan.description}
                </p>
              </div>

              <div className="mb-5">
                <div className="flex items-baseline gap-1">
                  <span className="app-kpi-value text-[1.75rem] font-bold text-foreground tabular-nums">
                    {plan.price}
                  </span>
                  {hasLivePrice && (
                    <span className="text-[0.71875rem] text-muted-foreground">
                      {billingCycle === "yearly" ? "/ yr" : "/ mo"}
                    </span>
                  )}
                </div>
                <div className="app-caption mt-1 text-muted-foreground">
                  {hasLivePrice
                    ? billingCycle === "yearly"
                      ? "Billed annually through Stripe"
                      : "Billed monthly through Stripe"
                    : "Sales-assisted billing"}
                </div>
              </div>

              <ul className="mb-5 flex flex-1 flex-col gap-2">
                {plan.features.map((feature, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <Check
                      className="mt-0.5 size-3.5 shrink-0"
                      style={{ color: checkColor }}
                      strokeWidth={2}
                    />
                    <span className="text-[0.75rem] text-muted-foreground leading-relaxed">
                      {feature}
                    </span>
                  </li>
                ))}
              </ul>
              <Separator className="mb-4" />

              <Button
                variant={isSelected || plan.popular ? "default" : "outline"}
                disabled={
                  busy ||
                  checkoutLoading !== null ||
                  isCurrentTier ||
                  (!isSelfServe && !meta?.contactOnly)
                }
                onClick={() => {
                  if (needsSalesAssist) {
                    appToast.info("Sales-assisted plan", {
                      description: `${plan.name} is not available through self-serve checkout yet.`,
                    });
                    return;
                  }
                  if (!apiTier) return;
                  startCheckout(apiTier, meta?.trial === true);
                }}
                className="w-full"
              >
                {busy
                  ? "Starting checkout…"
                  : isCurrentTier
                    ? "Current plan"
                    : needsSalesAssist
                      ? "Contact support"
                      : isSelected
                        ? (meta?.cta ?? `Confirm ${plan.name}`)
                        : meta?.contactOnly
                          ? "Contact support"
                          : plan.popular
                            ? "Upgrade to Pro"
                            : (meta?.cta ?? `Select ${plan.name}`)}
              </Button>
            </NovaCard>
          );
        })}
      </div>

      <PlanCompareTable
        plans={plans.map((plan) => plan.name)}
        current={
          plans.find(
            (plan) => currentWorkspace?.subscriptionTier === plan.currentTier,
          )?.name
        }
      />
    </NovaScreen>
  );
}

function PlanCompareTable({
  plans,
  current,
}: {
  plans: PlanCardKey[];
  current?: PlanCardKey | undefined;
}) {
  return (
    <NovaDataPanel
      className="mt-8"
      eyebrow="Compare plans"
      title="Capability matrix"
      description="Oxblood bars show relative operating headroom."
    >
      <div className="overflow-x-auto">
        <div className="min-w-[760px]">
          <div className="grid grid-cols-[150px_repeat(5,minmax(116px,1fr))] border-b border-border bg-muted/40">
            <div className="px-4 py-2 text-[0.68rem] font-medium uppercase tracking-wide text-muted-foreground">
              Feature
            </div>
            {plans.map((plan) => (
              <div
                key={plan}
                className="px-3 py-2 text-[0.68rem] font-medium uppercase tracking-wide text-muted-foreground"
              >
                {plan}
                {current === plan ? (
                  <span className="ml-1 text-[color:var(--color-oxblood)]">
                    current
                  </span>
                ) : null}
              </div>
            ))}
          </div>

          {PLAN_COMPARE_ROWS.map((row) => (
            <div
              key={row.label}
              className="grid grid-cols-[150px_repeat(5,minmax(116px,1fr))] border-b border-border last:border-b-0"
            >
              <div className="px-4 py-3 text-[0.75rem] font-semibold text-foreground">
                {row.label}
              </div>
              {plans.map((plan) => (
                <div key={plan} className="px-3 py-3">
                  <Progress value={row.strength[plan]} />
                  <div className="mt-2 text-[0.68rem] font-medium uppercase tracking-wide text-muted-foreground">
                    {row.values[plan]}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </NovaDataPanel>
  );
}
