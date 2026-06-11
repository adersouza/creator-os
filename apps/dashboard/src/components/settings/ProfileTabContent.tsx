import React, { useEffect, useState } from 'react';
import { Camera } from 'lucide-react';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Separator } from '@/components/ui/Separator';
import { appToast } from '@/lib/toast';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import {
  SectionHeader,
  Panel,
  Field,
  LocaleSelect,
} from './shared';

export function ProfileTab() {
  const authUser = useAuthUser();
  const defaultHandle = `@${authUser?.firstName?.toLowerCase() ?? 'operator'}`;
  const [name, setName] = useState(authUser?.name ?? '');
  const [email] = useState(authUser?.email ?? '');
  const [handle, setHandle] = useState(defaultHandle);
  const [savedName, setSavedName] = useState(authUser?.name ?? '');
  const [savedHandle, setSavedHandle] = useState(defaultHandle);
  const [saving, setSaving] = useState(false);
  const initial = authUser?.initial ?? 'A';
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [avatarUploading, setAvatarUploading] = useState(false);
  const avatarInputRef = React.useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (authUser && !name) setName(authUser.name);
  }, [authUser, name]);

  // Hydrate name + handle from auth metadata so edits round-trip across reloads.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user || cancelled) return;
      const meta = (user.user_metadata ?? {}) as {
        avatar_url?: string | undefined;
        full_name?: string | undefined;
        name?: string | undefined;
        handle?: string | undefined;
      };
      if (meta.avatar_url && !cancelled) setAvatarUrl(meta.avatar_url);
      const canonicalName = meta.full_name || meta.name || authUser?.name || '';
      const canonicalHandle = meta.handle || defaultHandle;
      if (!cancelled) {
        setName(canonicalName);
        setSavedName(canonicalName);
        setHandle(canonicalHandle);
        setSavedHandle(canonicalHandle);
      }
    })();
    return () => { cancelled = true; };
  }, [defaultHandle, authUser?.name]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = name !== savedName || handle !== savedHandle;

  const discard = () => {
    setName(savedName);
    setHandle(savedHandle);
  };

  const save = async () => {
    if (!dirty || saving) return;
    const trimmedName = name.trim();
    const trimmedHandle = handle.trim();
    if (!trimmedName) {
      appToast.error('Name cannot be empty.');
      return;
    }
    setSaving(true);
    try {
      const { error } = await supabase.auth.updateUser({
        data: { full_name: trimmedName, name: trimmedName, handle: trimmedHandle },
      });
      if (error) throw error;
      setName(trimmedName);
      setHandle(trimmedHandle);
      setSavedName(trimmedName);
      setSavedHandle(trimmedHandle);
      appToast.success('Profile updated');
    } catch (err) {
      appToast.error('Could not save profile', {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setSaving(false);
    }
  };

  const handleAvatarChange = async (file: File) => {
    const isImage = file.type.startsWith('image/');
    if (!isImage) {
      appToast.error('Avatar must be an image.');
      return;
    }
    if (file.size > 4 * 1024 * 1024) {
      appToast.error('Avatar must be under 4 MB.');
      return;
    }
    setAvatarUploading(true);
    try {
      const [{ uploadToBucket }, { compressImage }] = await Promise.all([
        import('@/services/mediaService'),
        import('@/utils/imageCompress'),
      ]);
      const prepared = await compressImage(file, { maxDimension: 512, quality: 0.82, skipBelowBytes: 0 });
      const url = await uploadToBucket('avatars', prepared);
      const { error } = await supabase.auth.updateUser({ data: { avatar_url: url } });
      if (error) throw error;
      setAvatarUrl(url);
      appToast.success('Avatar updated');
    } catch (err) {
      appToast.error('Avatar upload failed', {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setAvatarUploading(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <SectionHeader
        title="Profile"
        description="Your identity across the workspace. Shown on comments, approvals, and audit logs."
      />

      <Panel>
        <div className="flex items-start gap-5">
          <div className="relative shrink-0">
            <Avatar className="size-[72px] text-[1.625rem]">
              {avatarUrl ? <AvatarImage src={avatarUrl} alt={`${name || 'Operator'} avatar`} /> : null}
              <AvatarFallback className="bg-primary text-primary-foreground">
                {initial}
              </AvatarFallback>
              {avatarUploading && (
                <div className="absolute inset-0 bg-[color-mix(in_srgb,var(--color-foreground)_55%,transparent)] backdrop-blur-sm flex items-center justify-center text-[0.625rem] font-semibold uppercase tracking-[0.12em] text-white">
                  …
                </div>
              )}
            </Avatar>
            <input
              ref={avatarInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleAvatarChange(f);
                if (avatarInputRef.current) avatarInputRef.current.value = '';
              }}
            />
            <Button
              type="button"
              onClick={() => avatarInputRef.current?.click()}
              disabled={avatarUploading}
              variant="secondary"
              size="icon"
              className="absolute -bottom-1 -right-1 size-8 rounded-full"
              aria-label="Change avatar"
            >
              <Camera data-icon aria-hidden="true" />
            </Button>
          </div>
          <div className="flex-1 min-w-0 pt-1">
            <div className="text-[0.9375rem] font-medium text-foreground">{name || 'Operator'}</div>
            <div className="text-[0.78125rem] text-muted-foreground">{email || '—'}</div>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-6">
          <Field label="Full name">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ader Desouza"
            />
          </Field>
          <Field label="Email" hint="Contact support to change your login email.">
            <Input className="opacity-70 cursor-not-allowed" value={email} readOnly />
          </Field>
          <Field label="Display handle" hint="Used internally; not public.">
            <Input
              value={handle}
              onChange={(e) => setHandle(e.target.value)}
            />
          </Field>
          <Field label="Language" hint="Controls date, time, and number formatting.">
            <LocaleSelect />
          </Field>
        </div>

        <Separator />
        <div className="flex items-center justify-end gap-2">
          <Button
            variant="ghost"
            className="h-9 text-[0.8125rem]"
            onClick={discard}
            disabled={!dirty || saving}
          >
            Discard
          </Button>
          <Button
            className="h-9 text-[0.8125rem]"
            onClick={() => void save()}
            disabled={!dirty || saving}
          >
            {saving ? 'Saving…' : 'Save changes'}
          </Button>
        </div>
      </Panel>
    </div>
  );
}
