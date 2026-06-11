import type React from 'react';

export type MessageType = 'dm' | 'mention' | 'comment';
export type TabKey = MessageType;
export type PlatformKind = 'threads' | 'instagram';
export type Sentiment = 'positive' | 'neutral' | 'negative';
export type InboxWorkflowFilter = 'attention' | 'open' | 'done';

export interface ChatTurn {
  id: string;
  from: 'them' | 'me';
  text: string;
  time: string;
}

export interface PostContext {
  caption: string;
  sentAt: string;
  kind: 'text' | 'image' | 'carousel' | 'reel';
  accent: string;
}

export interface Conversation {
  id: string;
  user: {
    name: string;
    handle: string;
    avatarFrom: string;
    avatarTo: string;
    verified?: boolean | undefined;
    followers: number;
  };
  toAccount: string;
  network: {
    id: string;
    label: string;
    color: string;
  };
  platform: PlatformKind;
  type: MessageType;
  snippet: string;
  ago: string;
  sentiment?: Sentiment | undefined;
  isTopEngager?: boolean | undefined;
  isRead?: boolean | undefined;
  postContext?: PostContext | undefined;
  turns: ChatTurn[];
  reply: {
    platform: PlatformKind;
    accountId: string | null;
    replyToId: string;
    conversationId?: string | undefined;
    kind: 'dm' | 'comment' | 'reply';
    context?: {
      conversationId?: string | undefined;
      lastSeenAt?: string | undefined;
      lastTurnId?: string | undefined;
    } | undefined;
  };
}

export interface InboxSuggestion {
  id: string;
  conversation_key: string;
  suggestion_text: string;
  reasoning: string | null;
  alternatives: string[];
  status: 'pending' | 'accepted' | 'rejected';
  created_at?: string | undefined;
}

export interface SafetyWarning {
  title: string;
  description: string;
  action: () => void | Promise<void>;
}

export type IconComponent = React.ComponentType<{ className?: string | undefined }>;
