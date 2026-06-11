import type { RealtimeChannel } from '@supabase/supabase-js';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { AuthUserSummary } from '@/hooks/useAuthUser';
import { subscribe } from '@/services/realtimeManager';
import { supabase } from '@/services/supabase';

interface DraftingPresence {
  user_id: string;
  name: string;
  action: 'drafting';
  client_id: string;
}

export function useConversationPresence(user: AuthUserSummary | null, conversationKey: string | null) {
  const clientIdRef = useRef(`client-${Math.random().toString(36).slice(2)}-${Date.now()}`);
  const channelRef = useRef<RealtimeChannel | null>(null);
  const draftingRef = useRef(false);
  const [draftingUsers, setDraftingUsers] = useState<string[]>([]);

  const channelName = user && conversationKey ? `inbox:presence:${user.id}:${conversationKey}` : null;

  useEffect(() => {
    if (!user || !channelName) {
      setDraftingUsers([]);
      return;
    }

    const unsubscribe = subscribe(channelName, () => {
      const channel = supabase.channel(channelName, {
        config: { presence: { key: clientIdRef.current } },
      });
      channelRef.current = channel;

      channel
        .on('presence', { event: 'sync' }, () => {
          const state = channel.presenceState<DraftingPresence>();
          const names = new Set<string>();
          for (const presences of Object.values(state)) {
            for (const presence of presences) {
              if (presence.client_id === clientIdRef.current) continue;
              if (presence.action === 'drafting') names.add(presence.name || 'Someone');
            }
          }
          setDraftingUsers(Array.from(names));
        })
        .subscribe(async (status) => {
          if (status === 'SUBSCRIBED' && draftingRef.current) {
            await channel.track({
              user_id: user.id,
              name: user.name,
              action: 'drafting',
              client_id: clientIdRef.current,
            });
          }
        });

      return channel;
    });

    return () => {
      draftingRef.current = false;
      void channelRef.current?.untrack();
      channelRef.current = null;
      setDraftingUsers([]);
      unsubscribe();
    };
  }, [channelName, user]);

  const startDrafting = useCallback(() => {
    if (!user || !channelRef.current) return;
    draftingRef.current = true;
    void channelRef.current.track({
      user_id: user.id,
      name: user.name,
      action: 'drafting',
      client_id: clientIdRef.current,
    });
  }, [user]);

  const stopDrafting = useCallback(() => {
    draftingRef.current = false;
    void channelRef.current?.untrack();
  }, []);

  const draftingLabel = useMemo(() => {
    if (draftingUsers.length === 0) return null;
    if (draftingUsers.length === 1) return `${draftingUsers[0]} drafting...`;
    return `${draftingUsers[0]} +${draftingUsers.length - 1} drafting...`;
  }, [draftingUsers]);

  return { draftingLabel, startDrafting, stopDrafting };
}
