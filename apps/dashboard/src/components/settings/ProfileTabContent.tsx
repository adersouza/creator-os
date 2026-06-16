import React, { useEffect, useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { Camera } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Form, FormInputField } from '@/components/ui/Form';
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

const profileFormSchema = z.object({
  name: z.string().trim().min(1, 'Name cannot be empty.'),
  email: z.string(),
  handle: z.string().trim().min(1, 'Display handle cannot be empty.'),
});

type ProfileFormValues = z.infer<typeof profileFormSchema>;

export function ProfileTab() {
  const authUser = useAuthUser();
  const defaultHandle = `@${authUser?.firstName?.toLowerCase() ?? 'operator'}`;
  const [savedName, setSavedName] = useState(authUser?.name ?? '');
  const [savedHandle, setSavedHandle] = useState(defaultHandle);
  const [saving, setSaving] = useState(false);
  const initial = authUser?.initial ?? 'A';
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [avatarUploading, setAvatarUploading] = useState(false);
  const avatarInputRef = React.useRef<HTMLInputElement>(null);
  const profileForm = useForm<ProfileFormValues>({
    resolver: zodResolver(profileFormSchema),
    defaultValues: {
      name: authUser?.name ?? '',
      email: authUser?.email ?? '',
      handle: defaultHandle,
    },
  });
  const name = profileForm.watch('name');
  const email = profileForm.watch('email');

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
        profileForm.reset({
          name: canonicalName,
          email: authUser?.email ?? user.email ?? '',
          handle: canonicalHandle,
        });
        setSavedName(canonicalName);
        setSavedHandle(canonicalHandle);
      }
    })();
    return () => { cancelled = true; };
  }, [defaultHandle, authUser?.email, authUser?.name, profileForm]);

  const dirty = profileForm.formState.isDirty;

  const discard = () => {
    profileForm.reset({
      name: savedName,
      email,
      handle: savedHandle,
    });
  };

  const save = async (values: ProfileFormValues) => {
    if (!dirty || saving) return;
    const trimmedName = values.name.trim();
    const trimmedHandle = values.handle.trim();
    setSaving(true);
    try {
      const { error } = await supabase.auth.updateUser({
        data: { full_name: trimmedName, name: trimmedName, handle: trimmedHandle },
      });
      if (error) throw error;
      profileForm.reset({
        name: trimmedName,
        email: values.email,
        handle: trimmedHandle,
      });
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

        <Form
          form={profileForm}
          onSubmit={save}
          className="mt-6 gap-5"
        >
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <FormInputField
              name="name"
              label="Full name"
              placeholder="Ader Desouza"
              disabled={saving}
            />
            <FormInputField
              name="email"
              label="Email"
              hint="Contact support to change your login email."
              readOnly
              className="cursor-not-allowed opacity-70"
            />
            <FormInputField
              name="handle"
              label="Display handle"
              hint="Used internally; not public."
              disabled={saving}
            />
            <Field label="Language" hint="Controls date, time, and number formatting.">
              <LocaleSelect />
            </Field>
          </div>

          <Separator />
          <div className="flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              className="h-9 text-[0.8125rem]"
              onClick={discard}
              disabled={!dirty || saving}
            >
              Discard
            </Button>
            <Button
              type="submit"
              className="h-9 text-[0.8125rem]"
              disabled={!dirty || saving}
            >
              {saving ? 'Saving…' : 'Save changes'}
            </Button>
          </div>
        </Form>
      </Panel>
    </div>
  );
}
