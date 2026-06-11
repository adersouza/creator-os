/**
 * Team & Workspace Types
 * Updated with comprehensive subscription/monetization support
 */

// Self-serve tiers the API/subscription pipeline recognizes.
export type SubscriptionTier = 'free' | 'pro' | 'agency' | 'empire';
// Display tiers include contact-only plans surfaced in Billing/pricing UI.
export type DisplayTier = SubscriptionTier | 'creator' | 'white-label';
export type BillingInterval = 'month' | 'year';
export type SubscriptionStatus = 'active' | 'trialing' | 'past_due' | 'canceled' | 'incomplete';
export type TeamRole = 'owner' | 'admin' | 'editor';

// Stripe Price IDs (set these in environment)
export const STRIPE_PRICES = {
  pro: {
    month: import.meta.env.VITE_STRIPE_PRO_MONTHLY || 'price_1TN6L93aFLVx4e2S3BO2rEHk',
    year: import.meta.env.VITE_STRIPE_PRO_YEARLY || 'price_1TN6LA3aFLVx4e2SYoxKFlbG',
  },
  agency: {
    month: import.meta.env.VITE_STRIPE_AGENCY_MONTHLY || 'price_1TN6LX3aFLVx4e2Sm2QoFHGj',
    year: import.meta.env.VITE_STRIPE_AGENCY_YEARLY || 'price_1TN6LY3aFLVx4e2SutPAw9o2',
  },
  empire: {
    month: import.meta.env.VITE_STRIPE_EMPIRE_MONTHLY || 'price_1TN6LC3aFLVx4e2S3hZrl6o1',
    year: import.meta.env.VITE_STRIPE_EMPIRE_YEARLY || 'price_1TN6LD3aFLVx4e2Sz6IQl6h6',
  },
  addon: import.meta.env.VITE_STRIPE_ADDON || 'price_1SccMh3aFLVx4e2SxTTT6qSe',
} as const;

// Stripe price ids are opaque. Validate the real Stripe shape instead of a
// specific creation batch so older live add-on prices do not get flagged.
const STRIPE_PRICE_ID_PATTERN = /^price_[A-Za-z0-9]+$/;
export function isLiveStripePrice(id: string): boolean {
  return STRIPE_PRICE_ID_PATTERN.test(id);
}

// Pricing in cents — 5-tier ladder locked April 2026 (20% yearly discount).
export const PRICING = {
  pro: {
    month: 5900, // $59/mo
    year: 56640, // $566.40/yr (save 20%)
  },
  agency: {
    month: 14900, // $149/mo
    year: 143040, // $1,430.40/yr (save 20%)
  },
  empire: {
    month: 69900, // $699/mo
    year: 671040, // $6,710.40/yr (save 20%)
  },
  // Display-only contact-sales plans (not billed via self-serve Stripe)
  creator: {
    month: 1900, // $19/mo
    year: 18240, // $182.40/yr
  },
  'white-label': {
    month: 34900, // $349/mo
    year: 335040, // $3,350.40/yr
  },
  addon: 800, // $8/account/mo
} as const;

// Add-on configuration
export const ADDON_CONFIG = {
  pricePerAccount: 800, // cents
  maxAddons: 5,
  trialDays: 14,
  gracePeriodDays: 7,
} as const;

// Tier limits - the core of the subscription system
export const TIER_LIMITS: Record<SubscriptionTier, {
  name: string;
  maxAccounts: number;
  maxMembers: number;
  features: string[];
  highlight?: string | undefined;
}> = {
  free: {
    name: 'Free',
    maxAccounts: 1,
    maxMembers: 1,
    features: [
      '1 Threads account',
      '1 team member',
      'Basic analytics',
      'Manual posting',
    ],
  },
  pro: {
    name: 'Pro',
    maxAccounts: 10, // base, can add up to 5 more
    maxMembers: 4,
    features: [
      '10 Threads accounts (base)',
      'Up to 15 with add-ons',
      '4 team members',
      'Advanced analytics',
      'Scheduled posting',
      'AI content suggestions',
    ],
    highlight: '14-day free trial',
  },
  agency: {
    name: 'Agency',
    maxAccounts: Infinity,
    maxMembers: Infinity,
    features: [
      'Unlimited Threads accounts',
      'Unlimited team members',
      'Advanced analytics',
      'Scheduled posting',
      'AI content suggestions',
      'Priority support',
      'White-label options',
    ],
    highlight: 'Best for agencies',
  },
  empire: {
    name: 'Empire',
    maxAccounts: Infinity,
    maxMembers: Infinity,
    features: [
      'Everything in Agency',
      'Smart Auto-Poster (24/7)',
      'Group-specific media folders',
      'Auto-queue management',
      'Random media attachment',
      'Multi-account round-robin',
      'Anti-ban safety features',
      'Dedicated support',
    ],
    highlight: 'Full automation empire',
  },
};

export interface WorkspaceMember {
  userId: string;
  role: TeamRole;
  joinedAt: Date;
  invitedBy: string;
  displayName?: string | undefined;
  email?: string | undefined;
  photoURL?: string | undefined;
}

export interface WorkspaceSubscription {
  tier: SubscriptionTier;
  status: SubscriptionStatus;
  stripeCustomerId?: string | undefined;
  stripeSubscriptionId?: string | undefined;
  stripePriceId?: string | undefined;
  billingInterval?: BillingInterval | undefined;
  currentPeriodStart?: Date | undefined;
  currentPeriodEnd?: Date | undefined;
  trialEndAt?: Date | undefined;
  canceledAt?: Date | undefined;
  cancelAtPeriodEnd?: boolean | undefined;
  addOnsCount: number; // 0-5 extra accounts for Pro
}

export interface Workspace {
  id: string;
  name: string;
  ownerId: string;
  createdAt: Date;
  subscriptionTier: SubscriptionTier;
  memberCount?: number | undefined;
  // New subscription fields
  subscription?: WorkspaceSubscription | undefined;
  stripeCustomerId?: string | undefined;
  accountCount?: number | undefined; // current connected accounts
  theme?: {
            primaryHex?: string | undefined;
            accentHex?: string | undefined;
          } | undefined;
}

export interface WorkspaceInvite {
  id: string;
  code: string;
  email?: string | undefined;
  role: 'admin' | 'editor';
  expiresAt: Date;
  createdBy: string;
  createdAt: Date;
  used?: boolean | undefined;
  usedBy?: string | undefined;
  emailSent?: boolean | undefined;
}

export interface ActivityLogEntry {
  id: string;
  action: ActivityAction;
  userId: string;
  userName?: string | undefined;
  timestamp: Date;
  details?: Record<string, unknown> | undefined;
}

export type ActivityAction =
  | 'member_invited'
  | 'member_joined'
  | 'member_removed'
  | 'member_role_changed'
  | 'post_created'
  | 'post_published'
  | 'post_scheduled'
  | 'post_deleted'
  | 'account_connected'
  | 'account_removed'
  | 'workspace_created'
  | 'workspace_settings_updated'
  | 'invite_created'
  | 'invite_revoked'
  | 'ownership_transferred'
  | 'subscription_created'
  | 'subscription_updated'
  | 'subscription_canceled'
  | 'addon_added'
  | 'addon_removed'
  | 'trial_started'
  | 'trial_ended';

// Permission definitions
export const PERMISSIONS = {
  // Dashboard & Content
  VIEW_DASHBOARD: 'view_dashboard',
  VIEW_POSTS: 'view_posts',
  VIEW_CALENDAR: 'view_calendar',
  CREATE_POST: 'create_post',
  EDIT_POST: 'edit_post',
  DELETE_POST: 'delete_post',
  SCHEDULE_POST: 'schedule_post',
  PUBLISH_POST: 'publish_post',
  USE_MEDIA_LIBRARY: 'use_media_library',

  // Analytics
  VIEW_ANALYTICS: 'view_analytics',
  EXPORT_ANALYTICS: 'export_analytics',
  EXPORT_POSTS: 'export_posts',

  // Accounts
  VIEW_ACCOUNTS: 'view_accounts',
  ADD_ACCOUNT: 'add_account',
  REMOVE_ACCOUNT: 'remove_account',

  // Team Management
  VIEW_TEAM: 'view_team',
  INVITE_MEMBER: 'invite_member',
  REMOVE_MEMBER: 'remove_member',
  CHANGE_ROLE: 'change_role',

  // Approvals
  APPROVE_POST: 'approve_post',

  // Workspace Management
  ACCESS_BILLING: 'access_billing',
  DELETE_WORKSPACE: 'delete_workspace',
  TRANSFER_OWNERSHIP: 'transfer_ownership',
  UPDATE_WORKSPACE_SETTINGS: 'update_workspace_settings',
} as const;

export type Permission = typeof PERMISSIONS[keyof typeof PERMISSIONS];

// Role-based permission matrix
export const ROLE_PERMISSIONS: Record<TeamRole, Permission[]> = {
  owner: Object.values(PERMISSIONS),
  admin: [
    PERMISSIONS.VIEW_DASHBOARD,
    PERMISSIONS.VIEW_POSTS,
    PERMISSIONS.VIEW_CALENDAR,
    PERMISSIONS.CREATE_POST,
    PERMISSIONS.EDIT_POST,
    PERMISSIONS.DELETE_POST,
    PERMISSIONS.SCHEDULE_POST,
    PERMISSIONS.PUBLISH_POST,
    PERMISSIONS.USE_MEDIA_LIBRARY,
    PERMISSIONS.VIEW_ANALYTICS,
    PERMISSIONS.EXPORT_ANALYTICS,
    PERMISSIONS.EXPORT_POSTS,
    PERMISSIONS.VIEW_ACCOUNTS,
    PERMISSIONS.ADD_ACCOUNT,
    PERMISSIONS.REMOVE_ACCOUNT,
    PERMISSIONS.VIEW_TEAM,
    PERMISSIONS.INVITE_MEMBER,
    PERMISSIONS.REMOVE_MEMBER,
    PERMISSIONS.CHANGE_ROLE,
    PERMISSIONS.APPROVE_POST,
  ],
  editor: [
    PERMISSIONS.VIEW_DASHBOARD,
    PERMISSIONS.VIEW_POSTS,
    PERMISSIONS.VIEW_CALENDAR,
    PERMISSIONS.CREATE_POST,
    PERMISSIONS.EDIT_POST,
    PERMISSIONS.DELETE_POST,
    PERMISSIONS.SCHEDULE_POST,
    PERMISSIONS.PUBLISH_POST,
    PERMISSIONS.USE_MEDIA_LIBRARY,
    PERMISSIONS.VIEW_ANALYTICS,
    PERMISSIONS.VIEW_ACCOUNTS,
    PERMISSIONS.VIEW_TEAM,
  ],
};

// Helper function to check permission
export const hasPermission = (role: TeamRole, permission: Permission): boolean => {
  return ROLE_PERMISSIONS[role]?.includes(permission) ?? false;
};

// Helper function to check if user can perform action on target role
export const canManageRole = (userRole: TeamRole, targetRole: TeamRole): boolean => {
  const roleHierarchy: Record<TeamRole, number> = { owner: 3, admin: 2, editor: 1 };
  return roleHierarchy[userRole] > roleHierarchy[targetRole];
};

// Get role display info
export const getRoleInfo = (role: TeamRole) => {
  const roleInfo: Record<TeamRole, { label: string; color: string; description: string }> = {
    owner: {
      label: 'Owner',
      color: '#f59e0b',
      description: 'Full access to everything including billing and workspace deletion'
    },
    admin: {
      label: 'Admin',
      color: '#8b5cf6',
      description: 'Can manage team members, accounts, and all content'
    },
    editor: {
      label: 'Editor',
      color: '#3b82f6',
      description: 'Can create, edit, and publish posts'
    },
  };
  return roleInfo[role];
};

// Calculate effective account limit based on tier and add-ons
export const getEffectiveAccountLimit = (tier: SubscriptionTier, addOnsCount: number = 0): number => {
  if (tier === 'agency') return Infinity;
  if (tier === 'pro') return TIER_LIMITS.pro.maxAccounts + Math.min(addOnsCount, ADDON_CONFIG.maxAddons);
  return TIER_LIMITS.free.maxAccounts;
};

// Calculate monthly cost
export const calculateMonthlyCost = (tier: SubscriptionTier, billing: BillingInterval, addOnsCount: number = 0): number => {
  if (tier === 'free') return 0;

  const tierPricing = PRICING[tier as keyof typeof PRICING];
  if (!tierPricing || typeof tierPricing === 'number') return 0;
  const basePrice = (tierPricing as { month: number; year: number })[billing];
  const addonPrice = tier === 'pro' ? addOnsCount * ADDON_CONFIG.pricePerAccount : 0;

  if (billing === 'year') {
    return Math.round((basePrice / 12) + addonPrice);
  }
  return basePrice + addonPrice;
};

// Check if trial is active
export const isTrialActive = (subscription?: WorkspaceSubscription): boolean => {
  if (!subscription?.trialEndAt) return false;
  return new Date() < new Date(subscription.trialEndAt);
};

// Check if in grace period after cancellation
export const isInGracePeriod = (subscription?: WorkspaceSubscription): boolean => {
  if (!subscription?.canceledAt) return false;
  const gracePeriodEnd = new Date(subscription.canceledAt);
  gracePeriodEnd.setDate(gracePeriodEnd.getDate() + ADDON_CONFIG.gracePeriodDays);
  return new Date() < gracePeriodEnd;
};
