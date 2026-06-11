import { describe, expect, it } from 'vitest';
import {
  calculateMonthlyCost,
  canManageRole,
  getEffectiveAccountLimit,
  hasPermission,
  isLiveStripePrice,
  PERMISSIONS,
  PRICING,
  STRIPE_PRICES,
  TIER_LIMITS,
} from './team';

// Core subscription + role math. If any of these regress, billing or access
// control is wrong — both are money-losing or security bugs. Cheap to keep green.
describe('team pricing', () => {
  it('charges Pro at $59/mo and Agency at $149/mo, matching Billing.tsx', () => {
    expect(PRICING.pro.month).toBe(5900);
    expect(PRICING.agency.month).toBe(14900);
    expect(PRICING.empire.month).toBe(69900);
  });

  it('applies ~20% yearly discount', () => {
    const discount = (tier: 'pro' | 'agency' | 'empire') =>
      1 - PRICING[tier].year / (PRICING[tier].month * 12);
    expect(discount('pro')).toBeCloseTo(0.2, 2);
    expect(discount('agency')).toBeCloseTo(0.2, 2);
    expect(discount('empire')).toBeCloseTo(0.2, 2);
  });

  it('calculateMonthlyCost returns 0 for free, adds Pro add-ons', () => {
    expect(calculateMonthlyCost('free', 'month')).toBe(0);
    expect(calculateMonthlyCost('pro', 'month', 0)).toBe(5900);
    expect(calculateMonthlyCost('pro', 'month', 2)).toBe(5900 + 1600);
    // Yearly divides the annual into 12 and adds the monthly add-on.
    expect(calculateMonthlyCost('pro', 'year', 0)).toBe(Math.round(56640 / 12));
  });

  it('recognises live Stripe price IDs from env fallbacks', () => {
    // Env-fallback defaults in STRIPE_PRICES point at live-mode Stripe price IDs.
    expect(isLiveStripePrice(STRIPE_PRICES.pro.month)).toBe(true);
    expect(isLiveStripePrice(STRIPE_PRICES.agency.year)).toBe(true);
    expect(isLiveStripePrice(STRIPE_PRICES.addon)).toBe(true);
    expect(isLiveStripePrice('price_pro_monthly')).toBe(false);
    expect(isLiveStripePrice('')).toBe(false);
  });
});

describe('team permissions', () => {
  it('editors can create posts but not access billing', () => {
    expect(hasPermission('editor', PERMISSIONS.CREATE_POST)).toBe(true);
    expect(hasPermission('editor', PERMISSIONS.ACCESS_BILLING)).toBe(false);
  });

  it('admins cannot delete the workspace or transfer ownership', () => {
    expect(hasPermission('admin', PERMISSIONS.DELETE_WORKSPACE)).toBe(false);
    expect(hasPermission('admin', PERMISSIONS.TRANSFER_OWNERSHIP)).toBe(false);
  });

  it('owners have every permission', () => {
    for (const key of Object.values(PERMISSIONS)) {
      expect(hasPermission('owner', key)).toBe(true);
    }
  });

  it('role hierarchy: owner > admin > editor', () => {
    expect(canManageRole('owner', 'admin')).toBe(true);
    expect(canManageRole('admin', 'editor')).toBe(true);
    expect(canManageRole('editor', 'admin')).toBe(false);
    expect(canManageRole('admin', 'owner')).toBe(false);
  });

  it('caps accounts per tier, respects Pro add-ons', () => {
    expect(getEffectiveAccountLimit('free')).toBe(TIER_LIMITS.free.maxAccounts);
    expect(getEffectiveAccountLimit('pro', 3)).toBe(TIER_LIMITS.pro.maxAccounts + 3);
    // Add-ons capped at 5
    expect(getEffectiveAccountLimit('pro', 99)).toBe(TIER_LIMITS.pro.maxAccounts + 5);
    expect(getEffectiveAccountLimit('agency')).toBe(Infinity);
  });
});
