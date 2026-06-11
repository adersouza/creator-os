import type React from 'react';
import { useState } from 'react';
import { cn } from '@/lib/utils';
import { getLocale, setLocale } from '@/lib/locale';
import { supabase } from '@/services/supabase';
import { upsertUserSetting } from '@/services/userSettingsService';
import { appToast } from '@/lib/toast';
import { Field as JunoField } from '@/components/ui/Field';
import { FormSection } from '@/components/ui/FormSection';
import { inputControlClass, inputDefaultToneClass, inputHeightClass } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Switch } from '@/components/ui/Switch';

/**
 * Shared Settings primitives. Kept separate from pages/Settings.tsx so tab
 * components extracted into this folder don't have to re-import from the page
 * file (a cycle).
 */

export function SectionHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string | undefined;
  action?: React.ReactNode | undefined;
}) {
  return (
    <div className="flex items-end justify-between gap-4 flex-wrap">
      <div>
        <h1 className="text-[1.75rem] font-bold tracking-[-0.02em] leading-[1.05] text-foreground">
          {title}
        </h1>
        {description && (
          <p className="mt-1.5 text-[0.8125rem] text-muted-foreground max-w-[60ch] leading-relaxed">
            {description}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: React.ReactNode | undefined;
  children: React.ReactNode;
}) {
  return <JunoField label={label} hint={hint}>{children}</JunoField>;
}

// Mobile uses 16px to suppress iOS Safari's auto-zoom on focus —
// anything < 16px triggers it. Desktop overrides back to the compact
// 13px size. Used by every settings tab (Profile / Workspace / Voice /
// Security / Connections) so the fix propagates fleet-wide.
export const inputClass = cn(
  inputControlClass,
  inputDefaultToneClass,
  inputHeightClass.md,
  'px-3',
);

export const selectClass = cn(inputClass, 'appearance-none pr-8');

export function Toggle({
  checked,
  onCheckedChange,
  label,
  sub,
}: {
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  label: string;
  sub?: string | undefined;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div className="min-w-0">
        <div className="text-[0.8125rem] font-medium text-foreground">{label}</div>
        {sub && <div className="text-[0.71875rem] text-muted-foreground mt-0.5 leading-relaxed">{sub}</div>}
      </div>
      <Switch
        checked={checked}
        onCheckedChange={onCheckedChange}
        aria-label={label}
        className="mt-0.5"
      />
    </div>
  );
}

export function Panel({ children, className }: { children: React.ReactNode; className?: string | undefined }) {
  return (
    <FormSection className={className} contentClassName="flex flex-col gap-5">
      {children}
    </FormSection>
  );
}

export function LocaleSelect() {
  const [value, setValueState] = useState<string>(() => getLocale());
  const [saving, setSaving] = useState(false);

  const LOCALES = [
    { value: 'en-US', label: 'English (US)' },
    { value: 'en-GB', label: 'English (UK)' },
    { value: 'es-ES', label: 'Español (España)' },
    { value: 'es-MX', label: 'Español (México)' },
    { value: 'pt-BR', label: 'Português (Brasil)' },
    { value: 'fr-FR', label: 'Français (France)' },
    { value: 'de-DE', label: 'Deutsch' },
    { value: 'it-IT', label: 'Italiano' },
    { value: 'ja-JP', label: '日本語' },
    { value: 'ko-KR', label: '한국어' },
    { value: 'zh-CN', label: '简体中文' },
    { value: 'zh-TW', label: '繁體中文' },
  ];

  const handleChange = async (next: string) => {
    setValueState(next);
    setLocale(next);
    setSaving(true);
    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (user) {
        await upsertUserSetting(user.id, 'locale', next);
      }
      appToast.success('Language updated', {
        description: 'New formatting takes effect on next page load.',
      });
    } catch {
      /* localStorage still persists; silent on network failure */
    } finally {
      setSaving(false);
    }
  };

  return (
    <Select
      className={selectClass}
      value={value}
      onChange={(e) => handleChange(e.target.value)}
      disabled={saving}
      options={LOCALES}
    />
  );
}
