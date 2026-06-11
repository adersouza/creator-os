export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.1"
  }
  public: {
    Tables: {
      account_analytics: {
        Row: {
          account_id: string
          created_at: string | null
          date: string
          engagement_rate: number | null
          follower_growth: number | null
          followers_count: number | null
          following_count: number | null
          id: string
          ig_accounts_engaged: number | null
          ig_content_type_breakdown: Json | null
          ig_follower_reach: number | null
          ig_impressions: number | null
          ig_new_follows: number | null
          ig_non_follower_reach: number | null
          ig_non_follower_reach_pct: number | null
          ig_online_followers: Json | null
          ig_profile_views: number | null
          ig_reach: number | null
          ig_tagged_media_count: number | null
          ig_total_interactions: number | null
          ig_unfollows: number | null
          ig_website_clicks: number | null
          posts_count: number | null
          threads_views_by_source: Json | null
          total_clicks: number | null
          total_likes: number | null
          total_quotes: number | null
          total_reach: number | null
          total_replies: number | null
          total_reposts: number | null
          total_saves: number | null
          total_shares: number | null
          total_views: number | null
        }
        Insert: {
          account_id: string
          created_at?: string | null
          date: string
          engagement_rate?: number | null
          follower_growth?: number | null
          followers_count?: number | null
          following_count?: number | null
          id?: string
          ig_accounts_engaged?: number | null
          ig_content_type_breakdown?: Json | null
          ig_follower_reach?: number | null
          ig_impressions?: number | null
          ig_new_follows?: number | null
          ig_non_follower_reach?: number | null
          ig_non_follower_reach_pct?: number | null
          ig_online_followers?: Json | null
          ig_profile_views?: number | null
          ig_reach?: number | null
          ig_tagged_media_count?: number | null
          ig_total_interactions?: number | null
          ig_unfollows?: number | null
          ig_website_clicks?: number | null
          posts_count?: number | null
          threads_views_by_source?: Json | null
          total_clicks?: number | null
          total_likes?: number | null
          total_quotes?: number | null
          total_reach?: number | null
          total_replies?: number | null
          total_reposts?: number | null
          total_saves?: number | null
          total_shares?: number | null
          total_views?: number | null
        }
        Update: {
          account_id?: string
          created_at?: string | null
          date?: string
          engagement_rate?: number | null
          follower_growth?: number | null
          followers_count?: number | null
          following_count?: number | null
          id?: string
          ig_accounts_engaged?: number | null
          ig_content_type_breakdown?: Json | null
          ig_follower_reach?: number | null
          ig_impressions?: number | null
          ig_new_follows?: number | null
          ig_non_follower_reach?: number | null
          ig_non_follower_reach_pct?: number | null
          ig_online_followers?: Json | null
          ig_profile_views?: number | null
          ig_reach?: number | null
          ig_tagged_media_count?: number | null
          ig_total_interactions?: number | null
          ig_unfollows?: number | null
          ig_website_clicks?: number | null
          posts_count?: number | null
          threads_views_by_source?: Json | null
          total_clicks?: number | null
          total_likes?: number | null
          total_quotes?: number | null
          total_reach?: number | null
          total_replies?: number | null
          total_reposts?: number | null
          total_saves?: number | null
          total_shares?: number | null
          total_views?: number | null
        }
        Relationships: []
      }
      account_autoposter_state: {
        Row: {
          account_health_reason: string | null
          account_health_score: number
          account_id: string
          avg_views_24h_30d: number | null
          best_content_types: Json | null
          blocked_until: string | null
          consecutive_flops: number
          created_at: string
          evaluated_at: string
          flop_proven_remaining: number | null
          flop_triggered_at: string | null
          group_id: string
          last_14d_avg_views: number | null
          last_flop_post_id: string | null
          last_health_recomputed_at: string | null
          last_performance_recomputed_at: string | null
          last_skip_at: string | null
          last_skip_reason: string | null
          max_30d_views: number | null
          median_30d_views: number | null
          median_views_24h_30d: number | null
          pct_under_5_views: number | null
          posts_above_100_views_rate: number | null
          probe_cycles_completed: number
          probe_posts_remaining: number | null
          profile_click_rate_30d: number | null
          recommended_posts_per_day: number | null
          recommended_strategy_mode: string | null
          restart_warmup_allowed_posts_per_day: number | null
          restart_warmup_day: number | null
          restart_warmup_last_evaluated_at: string | null
          restart_warmup_last_post_views: number | null
          restart_warmup_next_ramp_at: string | null
          restart_warmup_reason: string | null
          restart_warmup_started_at: string | null
          restart_warmup_status: string
          revenue_per_post_30d: number | null
          should_retire: boolean | null
          status: Database["public"]["Enums"]["account_autoposter_status"]
          status_reason: string | null
          updated_at: string
          warming_posts_today: number | null
          workspace_id: string
        }
        Insert: {
          account_health_reason?: string | null
          account_health_score?: number
          account_id: string
          avg_views_24h_30d?: number | null
          best_content_types?: Json | null
          blocked_until?: string | null
          consecutive_flops?: number
          created_at?: string
          evaluated_at?: string
          flop_proven_remaining?: number | null
          flop_triggered_at?: string | null
          group_id: string
          last_14d_avg_views?: number | null
          last_flop_post_id?: string | null
          last_health_recomputed_at?: string | null
          last_performance_recomputed_at?: string | null
          last_skip_at?: string | null
          last_skip_reason?: string | null
          max_30d_views?: number | null
          median_30d_views?: number | null
          median_views_24h_30d?: number | null
          pct_under_5_views?: number | null
          posts_above_100_views_rate?: number | null
          probe_cycles_completed?: number
          probe_posts_remaining?: number | null
          profile_click_rate_30d?: number | null
          recommended_posts_per_day?: number | null
          recommended_strategy_mode?: string | null
          restart_warmup_allowed_posts_per_day?: number | null
          restart_warmup_day?: number | null
          restart_warmup_last_evaluated_at?: string | null
          restart_warmup_last_post_views?: number | null
          restart_warmup_next_ramp_at?: string | null
          restart_warmup_reason?: string | null
          restart_warmup_started_at?: string | null
          restart_warmup_status?: string
          revenue_per_post_30d?: number | null
          should_retire?: boolean | null
          status?: Database["public"]["Enums"]["account_autoposter_status"]
          status_reason?: string | null
          updated_at?: string
          warming_posts_today?: number | null
          workspace_id: string
        }
        Update: {
          account_health_reason?: string | null
          account_health_score?: number
          account_id?: string
          avg_views_24h_30d?: number | null
          best_content_types?: Json | null
          blocked_until?: string | null
          consecutive_flops?: number
          created_at?: string
          evaluated_at?: string
          flop_proven_remaining?: number | null
          flop_triggered_at?: string | null
          group_id?: string
          last_14d_avg_views?: number | null
          last_flop_post_id?: string | null
          last_health_recomputed_at?: string | null
          last_performance_recomputed_at?: string | null
          last_skip_at?: string | null
          last_skip_reason?: string | null
          max_30d_views?: number | null
          median_30d_views?: number | null
          median_views_24h_30d?: number | null
          pct_under_5_views?: number | null
          posts_above_100_views_rate?: number | null
          probe_cycles_completed?: number
          probe_posts_remaining?: number | null
          profile_click_rate_30d?: number | null
          recommended_posts_per_day?: number | null
          recommended_strategy_mode?: string | null
          restart_warmup_allowed_posts_per_day?: number | null
          restart_warmup_day?: number | null
          restart_warmup_last_evaluated_at?: string | null
          restart_warmup_last_post_views?: number | null
          restart_warmup_next_ramp_at?: string | null
          restart_warmup_reason?: string | null
          restart_warmup_started_at?: string | null
          restart_warmup_status?: string
          revenue_per_post_30d?: number | null
          should_retire?: boolean | null
          status?: Database["public"]["Enums"]["account_autoposter_status"]
          status_reason?: string | null
          updated_at?: string
          warming_posts_today?: number | null
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "account_autoposter_state_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: true
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
        ]
      }
      account_capability_errors: {
        Row: {
          account_id: string
          blocked_until: string | null
          capability: string
          created_at: string
          error_code: string
          group_id: string | null
          id: string
          last_seen_at: string
          message: string
          metadata: Json
          platform: string
          resolved_at: string | null
          updated_at: string
          workspace_id: string
        }
        Insert: {
          account_id: string
          blocked_until?: string | null
          capability: string
          created_at?: string
          error_code: string
          group_id?: string | null
          id?: string
          last_seen_at?: string
          message: string
          metadata?: Json
          platform: string
          resolved_at?: string | null
          updated_at?: string
          workspace_id: string
        }
        Update: {
          account_id?: string
          blocked_until?: string | null
          capability?: string
          created_at?: string
          error_code?: string
          group_id?: string | null
          id?: string
          last_seen_at?: string
          message?: string
          metadata?: Json
          platform?: string
          resolved_at?: string | null
          updated_at?: string
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "account_capability_errors_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "account_capability_errors_group_id_fkey"
            columns: ["group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "account_capability_errors_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "account_capability_errors_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      account_content_arcs: {
        Row: {
          account_id: string
          completed_at: string | null
          cooldown_until: string | null
          created_at: string
          current_beat_index: number
          group_id: string | null
          id: string
          mood: string
          next_suggested_beat: string | null
          payoff_status: string
          source_summary: Json
          started_at: string
          status: string
          title: string
          updated_at: string
          workspace_id: string
        }
        Insert: {
          account_id: string
          completed_at?: string | null
          cooldown_until?: string | null
          created_at?: string
          current_beat_index?: number
          group_id?: string | null
          id?: string
          mood?: string
          next_suggested_beat?: string | null
          payoff_status?: string
          source_summary?: Json
          started_at?: string
          status?: string
          title: string
          updated_at?: string
          workspace_id: string
        }
        Update: {
          account_id?: string
          completed_at?: string | null
          cooldown_until?: string | null
          created_at?: string
          current_beat_index?: number
          group_id?: string | null
          id?: string
          mood?: string
          next_suggested_beat?: string | null
          payoff_status?: string
          source_summary?: Json
          started_at?: string
          status?: string
          title?: string
          updated_at?: string
          workspace_id?: string
        }
        Relationships: []
      }
      account_daily_summary: {
        Row: {
          account_id: string
          avg_views_per_post: number | null
          best_post_id: string | null
          best_post_views: number | null
          created_at: string | null
          date: string
          engagement_rate: number | null
          engagement_trend_pct: number | null
          follower_growth: number | null
          follower_trend_pct: number | null
          followers_count: number | null
          id: string
          platform: string
          posts_published: number | null
          total_likes: number | null
          total_replies: number | null
          total_reposts: number | null
          total_views: number | null
          updated_at: string | null
          user_id: string
          views_trend_pct: number | null
        }
        Insert: {
          account_id: string
          avg_views_per_post?: number | null
          best_post_id?: string | null
          best_post_views?: number | null
          created_at?: string | null
          date: string
          engagement_rate?: number | null
          engagement_trend_pct?: number | null
          follower_growth?: number | null
          follower_trend_pct?: number | null
          followers_count?: number | null
          id?: string
          platform?: string
          posts_published?: number | null
          total_likes?: number | null
          total_replies?: number | null
          total_reposts?: number | null
          total_views?: number | null
          updated_at?: string | null
          user_id: string
          views_trend_pct?: number | null
        }
        Update: {
          account_id?: string
          avg_views_per_post?: number | null
          best_post_id?: string | null
          best_post_views?: number | null
          created_at?: string | null
          date?: string
          engagement_rate?: number | null
          engagement_trend_pct?: number | null
          follower_growth?: number | null
          follower_trend_pct?: number | null
          followers_count?: number | null
          id?: string
          platform?: string
          posts_published?: number | null
          total_likes?: number | null
          total_replies?: number | null
          total_reposts?: number | null
          total_views?: number | null
          updated_at?: string | null
          user_id?: string
          views_trend_pct?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "account_daily_summary_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_account_daily_summary_account"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
        ]
      }
      account_dna: {
        Row: {
          account_flavor_id: string | null
          account_id: string
          allowed_mood_range: Json
          archetype: string
          average_length_max: number
          average_length_min: number
          backstory_facts: Json
          banned_phrases: Json
          casing_style: string
          confidence: number
          controversy_level: number
          created_at: string
          creator_dna_id: string | null
          cta_posture: string
          emoji_policy: string
          emotional_baseline: string
          flirt_level: number
          follower_promise: string
          generated_from: string
          group_id: string | null
          humor_level: number
          id: string
          identity_summary: string
          last_refreshed_at: string | null
          last_scored_at: string | null
          primary_topics: Json
          punctuation_habits: Json
          recurring_motifs: Json
          recurring_situations: Json
          secondary_topics: Json
          signature_beliefs: Json
          signature_phrases: Json
          source_summary: Json
          status: string
          storytelling_tendency: number
          style_embedding: string | null
          sub_archetype: string | null
          taboo_topics: Json
          topic_embedding: string | null
          updated_at: string
          version: number
          vocabulary_fingerprint: Json
          voice_embedding: string | null
          vulnerability_level: number
          workspace_id: string
        }
        Insert: {
          account_flavor_id?: string | null
          account_id: string
          allowed_mood_range?: Json
          archetype: string
          average_length_max?: number
          average_length_min?: number
          backstory_facts?: Json
          banned_phrases?: Json
          casing_style?: string
          confidence?: number
          controversy_level?: number
          created_at?: string
          creator_dna_id?: string | null
          cta_posture?: string
          emoji_policy?: string
          emotional_baseline: string
          flirt_level?: number
          follower_promise: string
          generated_from?: string
          group_id?: string | null
          humor_level?: number
          id?: string
          identity_summary: string
          last_refreshed_at?: string | null
          last_scored_at?: string | null
          primary_topics?: Json
          punctuation_habits?: Json
          recurring_motifs?: Json
          recurring_situations?: Json
          secondary_topics?: Json
          signature_beliefs?: Json
          signature_phrases?: Json
          source_summary?: Json
          status?: string
          storytelling_tendency?: number
          style_embedding?: string | null
          sub_archetype?: string | null
          taboo_topics?: Json
          topic_embedding?: string | null
          updated_at?: string
          version?: number
          vocabulary_fingerprint?: Json
          voice_embedding?: string | null
          vulnerability_level?: number
          workspace_id: string
        }
        Update: {
          account_flavor_id?: string | null
          account_id?: string
          allowed_mood_range?: Json
          archetype?: string
          average_length_max?: number
          average_length_min?: number
          backstory_facts?: Json
          banned_phrases?: Json
          casing_style?: string
          confidence?: number
          controversy_level?: number
          created_at?: string
          creator_dna_id?: string | null
          cta_posture?: string
          emoji_policy?: string
          emotional_baseline?: string
          flirt_level?: number
          follower_promise?: string
          generated_from?: string
          group_id?: string | null
          humor_level?: number
          id?: string
          identity_summary?: string
          last_refreshed_at?: string | null
          last_scored_at?: string | null
          primary_topics?: Json
          punctuation_habits?: Json
          recurring_motifs?: Json
          recurring_situations?: Json
          secondary_topics?: Json
          signature_beliefs?: Json
          signature_phrases?: Json
          source_summary?: Json
          status?: string
          storytelling_tendency?: number
          style_embedding?: string | null
          sub_archetype?: string | null
          taboo_topics?: Json
          topic_embedding?: string | null
          updated_at?: string
          version?: number
          vocabulary_fingerprint?: Json
          voice_embedding?: string | null
          vulnerability_level?: number
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "account_dna_account_flavor_id_fkey"
            columns: ["account_flavor_id"]
            isOneToOne: false
            referencedRelation: "account_flavor"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "account_dna_creator_dna_id_fkey"
            columns: ["creator_dna_id"]
            isOneToOne: false
            referencedRelation: "creator_dna"
            referencedColumns: ["id"]
          },
        ]
      }
      account_dna_examples: {
        Row: {
          account_id: string
          content: string
          content_length_bucket: string | null
          created_at: string
          dna_fit_score: number | null
          dna_id: string
          emotional_frame: string | null
          example_type: string
          format_type: string | null
          genericness_score: number | null
          group_id: string | null
          hook_type: string | null
          id: string
          media_style: string | null
          mood_fit_score: number | null
          reason: string | null
          reply_mechanism: string | null
          source_id: string | null
          source_type: string
          topic_fit_score: number | null
          topic_label: string | null
          uniqueness_score: number | null
          voice_fit_score: number | null
          weight: number
          workspace_id: string
        }
        Insert: {
          account_id: string
          content: string
          content_length_bucket?: string | null
          created_at?: string
          dna_fit_score?: number | null
          dna_id: string
          emotional_frame?: string | null
          example_type: string
          format_type?: string | null
          genericness_score?: number | null
          group_id?: string | null
          hook_type?: string | null
          id?: string
          media_style?: string | null
          mood_fit_score?: number | null
          reason?: string | null
          reply_mechanism?: string | null
          source_id?: string | null
          source_type: string
          topic_fit_score?: number | null
          topic_label?: string | null
          uniqueness_score?: number | null
          voice_fit_score?: number | null
          weight?: number
          workspace_id: string
        }
        Update: {
          account_id?: string
          content?: string
          content_length_bucket?: string | null
          created_at?: string
          dna_fit_score?: number | null
          dna_id?: string
          emotional_frame?: string | null
          example_type?: string
          format_type?: string | null
          genericness_score?: number | null
          group_id?: string | null
          hook_type?: string | null
          id?: string
          media_style?: string | null
          mood_fit_score?: number | null
          reason?: string | null
          reply_mechanism?: string | null
          source_id?: string | null
          source_type?: string
          topic_fit_score?: number | null
          topic_label?: string | null
          uniqueness_score?: number | null
          voice_fit_score?: number | null
          weight?: number
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "account_dna_examples_dna_id_fkey"
            columns: ["dna_id"]
            isOneToOne: false
            referencedRelation: "account_dna"
            referencedColumns: ["id"]
          },
        ]
      }
      account_dna_rules: {
        Row: {
          account_id: string
          action: string
          created_at: string
          created_by: string | null
          dna_id: string
          expires_at: string | null
          group_id: string | null
          id: string
          reason: string | null
          rule_payload: Json
          rule_type: string
          rule_value: string
          severity: string
          updated_at: string
          weight: number
          workspace_id: string
        }
        Insert: {
          account_id: string
          action: string
          created_at?: string
          created_by?: string | null
          dna_id: string
          expires_at?: string | null
          group_id?: string | null
          id?: string
          reason?: string | null
          rule_payload?: Json
          rule_type: string
          rule_value: string
          severity?: string
          updated_at?: string
          weight?: number
          workspace_id: string
        }
        Update: {
          account_id?: string
          action?: string
          created_at?: string
          created_by?: string | null
          dna_id?: string
          expires_at?: string | null
          group_id?: string | null
          id?: string
          reason?: string | null
          rule_payload?: Json
          rule_type?: string
          rule_value?: string
          severity?: string
          updated_at?: string
          weight?: number
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "account_dna_rules_dna_id_fkey"
            columns: ["dna_id"]
            isOneToOne: false
            referencedRelation: "account_dna"
            referencedColumns: ["id"]
          },
        ]
      }
      account_flavor: {
        Row: {
          account_id: string
          archetype_bias: Json
          created_at: string
          creator_dna_id: string
          flavor_name: string
          flavor_notes: string | null
          format_emphasis: Json
          group_id: string
          id: string
          motif_emphasis: Json
          phrase_cooldowns: Json
          source_account_dna_id: string | null
          source_summary: Json
          status: string
          topic_emphasis: Json
          updated_at: string
          workspace_id: string
        }
        Insert: {
          account_id: string
          archetype_bias?: Json
          created_at?: string
          creator_dna_id: string
          flavor_name?: string
          flavor_notes?: string | null
          format_emphasis?: Json
          group_id: string
          id?: string
          motif_emphasis?: Json
          phrase_cooldowns?: Json
          source_account_dna_id?: string | null
          source_summary?: Json
          status?: string
          topic_emphasis?: Json
          updated_at?: string
          workspace_id: string
        }
        Update: {
          account_id?: string
          archetype_bias?: Json
          created_at?: string
          creator_dna_id?: string
          flavor_name?: string
          flavor_notes?: string | null
          format_emphasis?: Json
          group_id?: string
          id?: string
          motif_emphasis?: Json
          phrase_cooldowns?: Json
          source_account_dna_id?: string | null
          source_summary?: Json
          status?: string
          topic_emphasis?: Json
          updated_at?: string
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "account_flavor_creator_dna_id_fkey"
            columns: ["creator_dna_id"]
            isOneToOne: false
            referencedRelation: "creator_dna"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "account_flavor_source_account_dna_id_fkey"
            columns: ["source_account_dna_id"]
            isOneToOne: false
            referencedRelation: "account_dna"
            referencedColumns: ["id"]
          },
        ]
      }
      account_groups: {
        Row: {
          account_ids: string[] | null
          bio_template: Json | null
          category: string | null
          color: string | null
          content_strategy: Json | null
          created_at: string | null
          id: string
          name: string
          sentence_length_target: Json | null
          time_of_day_modifiers: Json | null
          updated_at: string | null
          user_id: string
          voice_profile: Json | null
          vulnerability_ratio: number | null
        }
        Insert: {
          account_ids?: string[] | null
          bio_template?: Json | null
          category?: string | null
          color?: string | null
          content_strategy?: Json | null
          created_at?: string | null
          id?: string
          name: string
          sentence_length_target?: Json | null
          time_of_day_modifiers?: Json | null
          updated_at?: string | null
          user_id: string
          voice_profile?: Json | null
          vulnerability_ratio?: number | null
        }
        Update: {
          account_ids?: string[] | null
          bio_template?: Json | null
          category?: string | null
          color?: string | null
          content_strategy?: Json | null
          created_at?: string | null
          id?: string
          name?: string
          sentence_length_target?: Json | null
          time_of_day_modifiers?: Json | null
          updated_at?: string | null
          user_id?: string
          voice_profile?: Json | null
          vulnerability_ratio?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "account_groups_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      account_health_signals: {
        Row: {
          account_id: string
          detected_at: string
          id: string
          metadata: Json | null
          resolved_at: string | null
          severity: string
          signal_type: string
        }
        Insert: {
          account_id: string
          detected_at?: string
          id?: string
          metadata?: Json | null
          resolved_at?: string | null
          severity: string
          signal_type: string
        }
        Update: {
          account_id?: string
          detected_at?: string
          id?: string
          metadata?: Json | null
          resolved_at?: string | null
          severity?: string
          signal_type?: string
        }
        Relationships: [
          {
            foreignKeyName: "account_health_signals_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
        ]
      }
      account_health_snapshots: {
        Row: {
          account_age_days: number | null
          account_id: string
          account_name: string
          account_table: string
          anomaly_detail: string | null
          anomaly_severity: string | null
          auto_disabled: boolean | null
          auto_disabled_at: string | null
          computed_at: string | null
          consecutive_dead_days: number | null
          days_since_last_post: number | null
          days_since_zero_views: number | null
          engagement_rate: number | null
          follower_growth_7d: number | null
          followers_current: number | null
          followers_previous: number | null
          group_avg_er: number | null
          growth_pct: number | null
          has_anomaly: boolean | null
          health_score: number | null
          health_tier: string | null
          id: string
          is_shadowbanned: boolean | null
          last_recovery_attempt: string | null
          period_days: number
          platform: string
          posts_per_day_override: number | null
          posts_this_period: number | null
          reach_14day: number | null
          reach_3day: number | null
          reach_drop_pct: number | null
          recovery_attempts: number | null
          reply_rate_7d: number | null
          user_id: string
          views_per_post_7d: number | null
          workspace_id: string
        }
        Insert: {
          account_age_days?: number | null
          account_id: string
          account_name?: string
          account_table?: string
          anomaly_detail?: string | null
          anomaly_severity?: string | null
          auto_disabled?: boolean | null
          auto_disabled_at?: string | null
          computed_at?: string | null
          consecutive_dead_days?: number | null
          days_since_last_post?: number | null
          days_since_zero_views?: number | null
          engagement_rate?: number | null
          follower_growth_7d?: number | null
          followers_current?: number | null
          followers_previous?: number | null
          group_avg_er?: number | null
          growth_pct?: number | null
          has_anomaly?: boolean | null
          health_score?: number | null
          health_tier?: string | null
          id?: string
          is_shadowbanned?: boolean | null
          last_recovery_attempt?: string | null
          period_days?: number
          platform?: string
          posts_per_day_override?: number | null
          posts_this_period?: number | null
          reach_14day?: number | null
          reach_3day?: number | null
          reach_drop_pct?: number | null
          recovery_attempts?: number | null
          reply_rate_7d?: number | null
          user_id: string
          views_per_post_7d?: number | null
          workspace_id?: string
        }
        Update: {
          account_age_days?: number | null
          account_id?: string
          account_name?: string
          account_table?: string
          anomaly_detail?: string | null
          anomaly_severity?: string | null
          auto_disabled?: boolean | null
          auto_disabled_at?: string | null
          computed_at?: string | null
          consecutive_dead_days?: number | null
          days_since_last_post?: number | null
          days_since_zero_views?: number | null
          engagement_rate?: number | null
          follower_growth_7d?: number | null
          followers_current?: number | null
          followers_previous?: number | null
          group_avg_er?: number | null
          growth_pct?: number | null
          has_anomaly?: boolean | null
          health_score?: number | null
          health_tier?: string | null
          id?: string
          is_shadowbanned?: boolean | null
          last_recovery_attempt?: string | null
          period_days?: number
          platform?: string
          posts_per_day_override?: number | null
          posts_this_period?: number | null
          reach_14day?: number | null
          reach_3day?: number | null
          reach_drop_pct?: number | null
          recovery_attempts?: number | null
          reply_rate_7d?: number | null
          user_id?: string
          views_per_post_7d?: number | null
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "account_health_snapshots_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_account_health_snapshots_workspace"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_account_health_snapshots_workspace"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      account_metrics_history: {
        Row: {
          account_id: string
          created_at: string | null
          date: string
          engagement_rate: number | null
          followers_count: number | null
          id: string
          platform: string
          posts_count: number | null
          total_likes: number | null
          total_replies: number | null
          total_reposts: number | null
          total_shares: number | null
          total_views: number | null
        }
        Insert: {
          account_id: string
          created_at?: string | null
          date?: string
          engagement_rate?: number | null
          followers_count?: number | null
          id?: string
          platform?: string
          posts_count?: number | null
          total_likes?: number | null
          total_replies?: number | null
          total_reposts?: number | null
          total_shares?: number | null
          total_views?: number | null
        }
        Update: {
          account_id?: string
          created_at?: string | null
          date?: string
          engagement_rate?: number | null
          followers_count?: number | null
          id?: string
          platform?: string
          posts_count?: number | null
          total_likes?: number | null
          total_replies?: number | null
          total_reposts?: number | null
          total_shares?: number | null
          total_views?: number | null
        }
        Relationships: []
      }
      account_schedule: {
        Row: {
          account_id: string
          active_hours_end: number
          active_hours_start: number
          blocked_until: string | null
          group_id: string
          min_interval_minutes: number
          paused: boolean
          post_on_weekends: boolean
          posts_per_day: number
          status: string
          status_reason: string | null
          timezone: string
          updated_at: string
          workspace_id: string
        }
        Insert: {
          account_id: string
          active_hours_end?: number
          active_hours_start?: number
          blocked_until?: string | null
          group_id: string
          min_interval_minutes?: number
          paused?: boolean
          post_on_weekends?: boolean
          posts_per_day?: number
          status?: string
          status_reason?: string | null
          timezone?: string
          updated_at?: string
          workspace_id: string
        }
        Update: {
          account_id?: string
          active_hours_end?: number
          active_hours_start?: number
          blocked_until?: string | null
          group_id?: string
          min_interval_minutes?: number
          paused?: boolean
          post_on_weekends?: boolean
          posts_per_day?: number
          status?: string
          status_reason?: string | null
          timezone?: string
          updated_at?: string
          workspace_id?: string
        }
        Relationships: []
      }
      account_uniqueness_metrics: {
        Row: {
          account_id: string
          collided_hooks: Json
          collided_phrases: Json
          collided_topics: Json
          compared_account_id: string | null
          compared_post_count: number
          computed_at: string
          decision: string
          drift_score: number
          genericness_score: number
          group_id: string | null
          hook_similarity_score: number
          id: string
          opener_collision_score: number
          owned_phrase_hits: Json
          phrase_collision_score: number
          reason: string | null
          sample_post_count: number
          sibling_collision_score: number
          topic_similarity_score: number
          uniqueness_score: number
          voice_similarity_score: number
          window_end: string
          window_start: string
          workspace_id: string
        }
        Insert: {
          account_id: string
          collided_hooks?: Json
          collided_phrases?: Json
          collided_topics?: Json
          compared_account_id?: string | null
          compared_post_count?: number
          computed_at?: string
          decision?: string
          drift_score: number
          genericness_score: number
          group_id?: string | null
          hook_similarity_score: number
          id?: string
          opener_collision_score: number
          owned_phrase_hits?: Json
          phrase_collision_score: number
          reason?: string | null
          sample_post_count?: number
          sibling_collision_score: number
          topic_similarity_score: number
          uniqueness_score: number
          voice_similarity_score: number
          window_end: string
          window_start: string
          workspace_id: string
        }
        Update: {
          account_id?: string
          collided_hooks?: Json
          collided_phrases?: Json
          collided_topics?: Json
          compared_account_id?: string | null
          compared_post_count?: number
          computed_at?: string
          decision?: string
          drift_score?: number
          genericness_score?: number
          group_id?: string | null
          hook_similarity_score?: number
          id?: string
          opener_collision_score?: number
          owned_phrase_hits?: Json
          phrase_collision_score?: number
          reason?: string | null
          sample_post_count?: number
          sibling_collision_score?: number
          topic_similarity_score?: number
          uniqueness_score?: number
          voice_similarity_score?: number
          window_end?: string
          window_start?: string
          workspace_id?: string
        }
        Relationships: []
      }
      accounts: {
        Row: {
          ai_config: Json | null
          avatar_url: string | null
          baseline_followers_count: number | null
          baseline_following_count: number | null
          baseline_posts_count: number | null
          bio: string | null
          cohort_updated_at: string | null
          consecutive_refresh_failures: number
          created_at: string | null
          display_name: string | null
          followers_count: number | null
          following_count: number | null
          group_id: string | null
          id: string
          inferred_niche: string | null
          is_active: boolean | null
          is_eligible_for_geo_gating: boolean
          is_retired: boolean
          is_shadowbanned: boolean
          last_milestone_celebrated: number | null
          last_sync_at: string | null
          last_sync_cursor: string | null
          last_synced_at: string | null
          last_webhook_reply_at: string | null
          needs_reauth: boolean
          posting_method: string | null
          posting_phase_shift: number | null
          posts_count: number | null
          status: string | null
          sync_cohort: string | null
          tags: string[] | null
          threads_access_token_encrypted: string
          threads_user_id: string
          token_expires_at: string | null
          updated_at: string | null
          user_id: string
          user_niche: string | null
          username: string
          webhook_replies_active: boolean | null
        }
        Insert: {
          ai_config?: Json | null
          avatar_url?: string | null
          baseline_followers_count?: number | null
          baseline_following_count?: number | null
          baseline_posts_count?: number | null
          bio?: string | null
          cohort_updated_at?: string | null
          consecutive_refresh_failures?: number
          created_at?: string | null
          display_name?: string | null
          followers_count?: number | null
          following_count?: number | null
          group_id?: string | null
          id?: string
          inferred_niche?: string | null
          is_active?: boolean | null
          is_eligible_for_geo_gating?: boolean
          is_retired?: boolean
          is_shadowbanned?: boolean
          last_milestone_celebrated?: number | null
          last_sync_at?: string | null
          last_sync_cursor?: string | null
          last_synced_at?: string | null
          last_webhook_reply_at?: string | null
          needs_reauth?: boolean
          posting_method?: string | null
          posting_phase_shift?: number | null
          posts_count?: number | null
          status?: string | null
          sync_cohort?: string | null
          tags?: string[] | null
          threads_access_token_encrypted: string
          threads_user_id: string
          token_expires_at?: string | null
          updated_at?: string | null
          user_id: string
          user_niche?: string | null
          username: string
          webhook_replies_active?: boolean | null
        }
        Update: {
          ai_config?: Json | null
          avatar_url?: string | null
          baseline_followers_count?: number | null
          baseline_following_count?: number | null
          baseline_posts_count?: number | null
          bio?: string | null
          cohort_updated_at?: string | null
          consecutive_refresh_failures?: number
          created_at?: string | null
          display_name?: string | null
          followers_count?: number | null
          following_count?: number | null
          group_id?: string | null
          id?: string
          inferred_niche?: string | null
          is_active?: boolean | null
          is_eligible_for_geo_gating?: boolean
          is_retired?: boolean
          is_shadowbanned?: boolean
          last_milestone_celebrated?: number | null
          last_sync_at?: string | null
          last_sync_cursor?: string | null
          last_synced_at?: string | null
          last_webhook_reply_at?: string | null
          needs_reauth?: boolean
          posting_method?: string | null
          posting_phase_shift?: number | null
          posts_count?: number | null
          status?: string | null
          sync_cohort?: string | null
          tags?: string[] | null
          threads_access_token_encrypted?: string
          threads_user_id?: string
          token_expires_at?: string | null
          updated_at?: string | null
          user_id?: string
          user_niche?: string | null
          username?: string
          webhook_replies_active?: boolean | null
        }
        Relationships: [
          {
            foreignKeyName: "accounts_group_id_fkey"
            columns: ["group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "accounts_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      agency_branding: {
        Row: {
          agency_logo_url: string | null
          agency_name: string | null
          brand_color: string | null
          created_at: string | null
          id: string
          updated_at: string | null
          user_id: string
        }
        Insert: {
          agency_logo_url?: string | null
          agency_name?: string | null
          brand_color?: string | null
          created_at?: string | null
          id?: string
          updated_at?: string | null
          user_id: string
        }
        Update: {
          agency_logo_url?: string | null
          agency_name?: string | null
          brand_color?: string | null
          created_at?: string | null
          id?: string
          updated_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "agency_branding_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: true
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      agent_action_intents: {
        Row: {
          account_id: string | null
          action_name: string
          approval_id: string | null
          consumed_at: string | null
          content_hash: string | null
          created_at: string
          expires_at: string
          group_id: string | null
          id: string
          idempotency_key: string | null
          normalized_payload: Json
          payload_hash: string
          required_reviewer_role: string | null
          risk_level: string
          status: string
          updated_at: string
          user_id: string
          workspace_id: string | null
        }
        Insert: {
          account_id?: string | null
          action_name: string
          approval_id?: string | null
          consumed_at?: string | null
          content_hash?: string | null
          created_at?: string
          expires_at?: string
          group_id?: string | null
          id?: string
          idempotency_key?: string | null
          normalized_payload?: Json
          payload_hash: string
          required_reviewer_role?: string | null
          risk_level?: string
          status?: string
          updated_at?: string
          user_id: string
          workspace_id?: string | null
        }
        Update: {
          account_id?: string | null
          action_name?: string
          approval_id?: string | null
          consumed_at?: string | null
          content_hash?: string | null
          created_at?: string
          expires_at?: string
          group_id?: string | null
          id?: string
          idempotency_key?: string | null
          normalized_payload?: Json
          payload_hash?: string
          required_reviewer_role?: string | null
          risk_level?: string
          status?: string
          updated_at?: string
          user_id?: string
          workspace_id?: string | null
        }
        Relationships: []
      }
      agent_actions: {
        Row: {
          created_at: string
          duration_ms: number | null
          id: string
          params_json: Json | null
          reason: string | null
          result_summary: string | null
          session_id: string
          success: boolean
          tool_name: string
          user_id: string
        }
        Insert: {
          created_at?: string
          duration_ms?: number | null
          id?: string
          params_json?: Json | null
          reason?: string | null
          result_summary?: string | null
          session_id: string
          success?: boolean
          tool_name: string
          user_id: string
        }
        Update: {
          created_at?: string
          duration_ms?: number | null
          id?: string
          params_json?: Json | null
          reason?: string | null
          result_summary?: string | null
          session_id?: string
          success?: boolean
          tool_name?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "agent_actions_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      agent_approvals: {
        Row: {
          context: string
          created_at: string
          decided_at: string | null
          decision_note: string | null
          expires_at: string
          id: string
          proposed_actions: Json
          session_id: string | null
          status: string
          urgency: string
          user_id: string
        }
        Insert: {
          context: string
          created_at?: string
          decided_at?: string | null
          decision_note?: string | null
          expires_at?: string
          id?: string
          proposed_actions?: Json
          session_id?: string | null
          status?: string
          urgency?: string
          user_id: string
        }
        Update: {
          context?: string
          created_at?: string
          decided_at?: string | null
          decision_note?: string | null
          expires_at?: string
          id?: string
          proposed_actions?: Json
          session_id?: string | null
          status?: string
          urgency?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "agent_approvals_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      agent_notes: {
        Row: {
          account_group_id: string | null
          created_at: string
          id: string
          key: string
          updated_at: string
          user_id: string
          value: string
        }
        Insert: {
          account_group_id?: string | null
          created_at?: string
          id?: string
          key: string
          updated_at?: string
          user_id: string
          value: string
        }
        Update: {
          account_group_id?: string | null
          created_at?: string
          id?: string
          key?: string
          updated_at?: string
          user_id?: string
          value?: string
        }
        Relationships: [
          {
            foreignKeyName: "agent_notes_account_group_id_fkey"
            columns: ["account_group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "agent_notes_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      ai_action_log: {
        Row: {
          account_id: string | null
          action_type: string
          cost_usd: number | null
          created_at: string
          id: string
          input_text: string | null
          latency_ms: number | null
          metadata: Json | null
          model_used: string | null
          output_text: string | null
          provider: string | null
          surface: string
          tokens_in: number | null
          tokens_out: number | null
          user_id: string
        }
        Insert: {
          account_id?: string | null
          action_type: string
          cost_usd?: number | null
          created_at?: string
          id?: string
          input_text?: string | null
          latency_ms?: number | null
          metadata?: Json | null
          model_used?: string | null
          output_text?: string | null
          provider?: string | null
          surface: string
          tokens_in?: number | null
          tokens_out?: number | null
          user_id: string
        }
        Update: {
          account_id?: string | null
          action_type?: string
          cost_usd?: number | null
          created_at?: string
          id?: string
          input_text?: string | null
          latency_ms?: number | null
          metadata?: Json | null
          model_used?: string | null
          output_text?: string | null
          provider?: string | null
          surface?: string
          tokens_in?: number | null
          tokens_out?: number | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "ai_action_log_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "ai_action_log_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      ai_config: {
        Row: {
          api_key: string | null
          base_url: string | null
          created_at: string | null
          id: string
          last_validated_at: string | null
          model: string | null
          provider: string | null
          updated_at: string | null
          user_id: string
        }
        Insert: {
          api_key?: string | null
          base_url?: string | null
          created_at?: string | null
          id?: string
          last_validated_at?: string | null
          model?: string | null
          provider?: string | null
          updated_at?: string | null
          user_id: string
        }
        Update: {
          api_key?: string | null
          base_url?: string | null
          created_at?: string | null
          id?: string
          last_validated_at?: string | null
          model?: string | null
          provider?: string | null
          updated_at?: string | null
          user_id?: string
        }
        Relationships: []
      }
      ai_eval_snapshots: {
        Row: {
          account_id: string | null
          candidate_outputs: Json
          captured_at: string
          case_id: string
          category: string
          created_at: string
          failures: Json
          filter_results: Json
          group_id: string | null
          id: string
          inserted_ids: string[]
          judge_scores: Json
          metadata: Json
          model: string
          model_version: string | null
          parameters: Json
          passed: boolean
          performance_snapshot: Json
          prompt: string
          prompt_hash: string
          provider: string
          regression_score: number | null
          scheduled_ids: string[]
          selected_output: Json | null
          selected_output_id: string | null
          suite_name: string
          user_id: string
          workspace_id: string | null
        }
        Insert: {
          account_id?: string | null
          candidate_outputs?: Json
          captured_at?: string
          case_id: string
          category: string
          created_at?: string
          failures?: Json
          filter_results?: Json
          group_id?: string | null
          id?: string
          inserted_ids?: string[]
          judge_scores?: Json
          metadata?: Json
          model: string
          model_version?: string | null
          parameters?: Json
          passed?: boolean
          performance_snapshot?: Json
          prompt: string
          prompt_hash: string
          provider: string
          regression_score?: number | null
          scheduled_ids?: string[]
          selected_output?: Json | null
          selected_output_id?: string | null
          suite_name: string
          user_id: string
          workspace_id?: string | null
        }
        Update: {
          account_id?: string | null
          candidate_outputs?: Json
          captured_at?: string
          case_id?: string
          category?: string
          created_at?: string
          failures?: Json
          filter_results?: Json
          group_id?: string | null
          id?: string
          inserted_ids?: string[]
          judge_scores?: Json
          metadata?: Json
          model?: string
          model_version?: string | null
          parameters?: Json
          passed?: boolean
          performance_snapshot?: Json
          prompt?: string
          prompt_hash?: string
          provider?: string
          regression_score?: number | null
          scheduled_ids?: string[]
          selected_output?: Json | null
          selected_output_id?: string | null
          suite_name?: string
          user_id?: string
          workspace_id?: string | null
        }
        Relationships: []
      }
      ai_feedback: {
        Row: {
          context: Json | null
          created_at: string | null
          feature: string
          id: string
          suggestion_content: string | null
          suggestion_index: number | null
          user_id: string | null
          was_edited: boolean | null
          was_used: boolean | null
          workspace_id: string | null
        }
        Insert: {
          context?: Json | null
          created_at?: string | null
          feature: string
          id?: string
          suggestion_content?: string | null
          suggestion_index?: number | null
          user_id?: string | null
          was_edited?: boolean | null
          was_used?: boolean | null
          workspace_id?: string | null
        }
        Update: {
          context?: Json | null
          created_at?: string | null
          feature?: string
          id?: string
          suggestion_content?: string | null
          suggestion_index?: number | null
          user_id?: string | null
          was_edited?: boolean | null
          was_used?: boolean | null
          workspace_id?: string | null
        }
        Relationships: []
      }
      anomaly_alerts: {
        Row: {
          account_id: string | null
          ai_analysis: string | null
          alert_type: string
          created_at: string | null
          data: Json | null
          description: string | null
          dismissed_at: string | null
          id: string
          instagram_account_id: string | null
          platform: string
          severity: string
          title: string
          user_id: string
        }
        Insert: {
          account_id?: string | null
          ai_analysis?: string | null
          alert_type: string
          created_at?: string | null
          data?: Json | null
          description?: string | null
          dismissed_at?: string | null
          id?: string
          instagram_account_id?: string | null
          platform: string
          severity: string
          title: string
          user_id: string
        }
        Update: {
          account_id?: string | null
          ai_analysis?: string | null
          alert_type?: string
          created_at?: string | null
          data?: Json | null
          description?: string | null
          dismissed_at?: string | null
          id?: string
          instagram_account_id?: string | null
          platform?: string
          severity?: string
          title?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "anomaly_alerts_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "anomaly_alerts_instagram_account_id_fkey"
            columns: ["instagram_account_id"]
            isOneToOne: false
            referencedRelation: "instagram_accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "anomaly_alerts_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      api_idempotency_keys: {
        Row: {
          action: string
          completed_at: string | null
          created_at: string
          expires_at: string
          id: string
          idempotency_key: string
          payload_hash: string
          response_body: Json | null
          response_status: number | null
          route: string
          status: string
          user_id: string
        }
        Insert: {
          action: string
          completed_at?: string | null
          created_at?: string
          expires_at?: string
          id?: string
          idempotency_key: string
          payload_hash: string
          response_body?: Json | null
          response_status?: number | null
          route: string
          status?: string
          user_id: string
        }
        Update: {
          action?: string
          completed_at?: string | null
          created_at?: string
          expires_at?: string
          id?: string
          idempotency_key?: string
          payload_hash?: string
          response_body?: Json | null
          response_status?: number | null
          route?: string
          status?: string
          user_id?: string
        }
        Relationships: []
      }
      api_keys: {
        Row: {
          allowed_account_ids: string[] | null
          created_at: string | null
          expires_at: string | null
          id: string
          is_active: boolean | null
          key_hash: string
          key_prefix: string
          last_used_at: string | null
          name: string
          scopes: string[]
          user_id: string
        }
        Insert: {
          allowed_account_ids?: string[] | null
          created_at?: string | null
          expires_at?: string | null
          id?: string
          is_active?: boolean | null
          key_hash: string
          key_prefix: string
          last_used_at?: string | null
          name: string
          scopes?: string[]
          user_id: string
        }
        Update: {
          allowed_account_ids?: string[] | null
          created_at?: string | null
          expires_at?: string | null
          id?: string
          is_active?: boolean | null
          key_hash?: string
          key_prefix?: string
          last_used_at?: string | null
          name?: string
          scopes?: string[]
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "api_keys_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      api_usage: {
        Row: {
          call_count: number | null
          created_at: string | null
          endpoint: string
          id: string
          period_start: string
          updated_at: string | null
          user_id: string
        }
        Insert: {
          call_count?: number | null
          created_at?: string | null
          endpoint: string
          id?: string
          period_start?: string
          updated_at?: string | null
          user_id: string
        }
        Update: {
          call_count?: number | null
          created_at?: string | null
          endpoint?: string
          id?: string
          period_start?: string
          updated_at?: string | null
          user_id?: string
        }
        Relationships: []
      }
      arc_beats: {
        Row: {
          account_id: string
          arc_id: string
          beat_index: number
          beat_prompt: string
          beat_title: string
          created_at: string
          group_id: string | null
          id: string
          mood: string | null
          post_id: string | null
          posted_at: string | null
          queue_item_id: string | null
          status: string
          suggested_after: string | null
          updated_at: string
          workspace_id: string
        }
        Insert: {
          account_id: string
          arc_id: string
          beat_index: number
          beat_prompt: string
          beat_title: string
          created_at?: string
          group_id?: string | null
          id?: string
          mood?: string | null
          post_id?: string | null
          posted_at?: string | null
          queue_item_id?: string | null
          status?: string
          suggested_after?: string | null
          updated_at?: string
          workspace_id: string
        }
        Update: {
          account_id?: string
          arc_id?: string
          beat_index?: number
          beat_prompt?: string
          beat_title?: string
          created_at?: string
          group_id?: string | null
          id?: string
          mood?: string | null
          post_id?: string | null
          posted_at?: string | null
          queue_item_id?: string | null
          status?: string
          suggested_after?: string | null
          updated_at?: string
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "arc_beats_arc_id_fkey"
            columns: ["arc_id"]
            isOneToOne: false
            referencedRelation: "account_content_arcs"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "arc_beats_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "arc_beats_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "arc_beats_queue_item_id_fkey"
            columns: ["queue_item_id"]
            isOneToOne: false
            referencedRelation: "auto_post_queue"
            referencedColumns: ["id"]
          },
        ]
      }
      audience_demographics: {
        Row: {
          account_id: string
          audience_type: string
          breakdown_type: string
          breakdown_value: string
          count: number
          fetched_at: string | null
          fetched_date: string | null
          id: string
          instagram_account_id: string | null
          percentage: number | null
          platform: string
        }
        Insert: {
          account_id: string
          audience_type?: string
          breakdown_type: string
          breakdown_value: string
          count?: number
          fetched_at?: string | null
          fetched_date?: string | null
          id?: string
          instagram_account_id?: string | null
          percentage?: number | null
          platform: string
        }
        Update: {
          account_id?: string
          audience_type?: string
          breakdown_type?: string
          breakdown_value?: string
          count?: number
          fetched_at?: string | null
          fetched_date?: string | null
          id?: string
          instagram_account_id?: string | null
          percentage?: number | null
          platform?: string
        }
        Relationships: [
          {
            foreignKeyName: "audience_demographics_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "audience_demographics_instagram_account_id_fkey"
            columns: ["instagram_account_id"]
            isOneToOne: false
            referencedRelation: "instagram_accounts"
            referencedColumns: ["id"]
          },
        ]
      }
      audit_logs: {
        Row: {
          action: string
          created_at: string | null
          id: string
          ip_address: string | null
          metadata: Json | null
          resource_id: string | null
          resource_type: string | null
          user_agent: string | null
          user_id: string
        }
        Insert: {
          action: string
          created_at?: string | null
          id?: string
          ip_address?: string | null
          metadata?: Json | null
          resource_id?: string | null
          resource_type?: string | null
          user_agent?: string | null
          user_id: string
        }
        Update: {
          action?: string
          created_at?: string | null
          id?: string
          ip_address?: string | null
          metadata?: Json | null
          resource_id?: string | null
          resource_type?: string | null
          user_agent?: string | null
          user_id?: string
        }
        Relationships: []
      }
      auth_lockout_log: {
        Row: {
          attempts: number
          created_at: string | null
          id: string
          identifier: string
          identifier_type: string
          locked_until: string | null
          updated_at: string | null
        }
        Insert: {
          attempts?: number
          created_at?: string | null
          id?: string
          identifier: string
          identifier_type: string
          locked_until?: string | null
          updated_at?: string | null
        }
        Update: {
          attempts?: number
          created_at?: string | null
          id?: string
          identifier?: string
          identifier_type?: string
          locked_until?: string | null
          updated_at?: string | null
        }
        Relationships: []
      }
      auto_cross_replies: {
        Row: {
          chain_position: number
          content: string
          created_at: string | null
          error_message: string | null
          group_id: string
          id: string
          parent_reply_id: string | null
          published_at: string | null
          replier_account_id: string
          replier_threads_post_id: string | null
          retry_count: number | null
          scheduled_for: string
          status: string
          target_account_id: string
          target_post_id: string
          target_threads_post_id: string | null
          user_id: string
          workspace_id: string
        }
        Insert: {
          chain_position?: number
          content: string
          created_at?: string | null
          error_message?: string | null
          group_id: string
          id?: string
          parent_reply_id?: string | null
          published_at?: string | null
          replier_account_id: string
          replier_threads_post_id?: string | null
          retry_count?: number | null
          scheduled_for: string
          status?: string
          target_account_id: string
          target_post_id: string
          target_threads_post_id?: string | null
          user_id: string
          workspace_id?: string
        }
        Update: {
          chain_position?: number
          content?: string
          created_at?: string | null
          error_message?: string | null
          group_id?: string
          id?: string
          parent_reply_id?: string | null
          published_at?: string | null
          replier_account_id?: string
          replier_threads_post_id?: string | null
          retry_count?: number | null
          scheduled_for?: string
          status?: string
          target_account_id?: string
          target_post_id?: string
          target_threads_post_id?: string | null
          user_id?: string
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "auto_cross_replies_parent_reply_id_fkey"
            columns: ["parent_reply_id"]
            isOneToOne: false
            referencedRelation: "auto_cross_replies"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_cross_replies_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      auto_post_account_overrides: {
        Row: {
          account_id: string
          created_at: string | null
          group_id: string
          id: string
          overrides: Json
          updated_at: string | null
          workspace_id: string
        }
        Insert: {
          account_id: string
          created_at?: string | null
          group_id: string
          id?: string
          overrides?: Json
          updated_at?: string | null
          workspace_id: string
        }
        Update: {
          account_id?: string
          created_at?: string | null
          group_id?: string
          id?: string
          overrides?: Json
          updated_at?: string | null
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "auto_post_account_overrides_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_account_overrides_group_id_fkey"
            columns: ["group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_account_overrides_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_account_overrides_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      auto_post_activity: {
        Row: {
          account_handle: string | null
          activity_type: string
          created_at: string | null
          group_id: string | null
          group_name: string | null
          id: string
          message: string
          metadata: Json | null
          next_post_in: number | null
          post_index: number | null
          queue_item_id: string | null
          workspace_id: string
        }
        Insert: {
          account_handle?: string | null
          activity_type: string
          created_at?: string | null
          group_id?: string | null
          group_name?: string | null
          id?: string
          message: string
          metadata?: Json | null
          next_post_in?: number | null
          post_index?: number | null
          queue_item_id?: string | null
          workspace_id: string
        }
        Update: {
          account_handle?: string | null
          activity_type?: string
          created_at?: string | null
          group_id?: string | null
          group_name?: string | null
          id?: string
          message?: string
          metadata?: Json | null
          next_post_in?: number | null
          post_index?: number | null
          queue_item_id?: string | null
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "auto_post_activity_group_id_fkey"
            columns: ["group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_activity_queue_item_id_fkey"
            columns: ["queue_item_id"]
            isOneToOne: false
            referencedRelation: "auto_post_queue"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_activity_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_activity_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      auto_post_config: {
        Row: {
          ai_content_style: string | null
          ai_daily_generation_limit: number | null
          ai_generations_today: number | null
          ai_last_generation_date: string | null
          ai_posts_per_fill: number | null
          ai_provider: string | null
          ai_queue_min_threshold: number | null
          ai_style_guidelines: string | null
          boost_on_viral: boolean | null
          competitor_copy_max_words: number | null
          competitor_copy_ratio: number | null
          content_filter_max_emojis: number | null
          content_filter_max_length: number | null
          content_filter_min_length: number | null
          content_filter_patterns: Json | null
          created_at: string | null
          discord_webhook_url: string | null
          enable_ai_queue_fill: boolean | null
          enable_velocity_monitoring: boolean | null
          group_mode_enabled: boolean
          id: string
          is_enabled: boolean | null
          pause_on_declining_velocity: boolean | null
          pause_on_low_performance: boolean | null
          performance_threshold: number | null
          posting_times: Json | null
          scheduler_version: number
          updated_at: string | null
          use_smart_timing: boolean | null
          velocity_acceleration_threshold: number | null
          velocity_decline_threshold: number | null
          viral_interval_reduction_pct: number | null
          workspace_id: string
        }
        Insert: {
          ai_content_style?: string | null
          ai_daily_generation_limit?: number | null
          ai_generations_today?: number | null
          ai_last_generation_date?: string | null
          ai_posts_per_fill?: number | null
          ai_provider?: string | null
          ai_queue_min_threshold?: number | null
          ai_style_guidelines?: string | null
          boost_on_viral?: boolean | null
          competitor_copy_max_words?: number | null
          competitor_copy_ratio?: number | null
          content_filter_max_emojis?: number | null
          content_filter_max_length?: number | null
          content_filter_min_length?: number | null
          content_filter_patterns?: Json | null
          created_at?: string | null
          discord_webhook_url?: string | null
          enable_ai_queue_fill?: boolean | null
          enable_velocity_monitoring?: boolean | null
          group_mode_enabled?: boolean
          id?: string
          is_enabled?: boolean | null
          pause_on_declining_velocity?: boolean | null
          pause_on_low_performance?: boolean | null
          performance_threshold?: number | null
          posting_times?: Json | null
          scheduler_version?: number
          updated_at?: string | null
          use_smart_timing?: boolean | null
          velocity_acceleration_threshold?: number | null
          velocity_decline_threshold?: number | null
          viral_interval_reduction_pct?: number | null
          workspace_id: string
        }
        Update: {
          ai_content_style?: string | null
          ai_daily_generation_limit?: number | null
          ai_generations_today?: number | null
          ai_last_generation_date?: string | null
          ai_posts_per_fill?: number | null
          ai_provider?: string | null
          ai_queue_min_threshold?: number | null
          ai_style_guidelines?: string | null
          boost_on_viral?: boolean | null
          competitor_copy_max_words?: number | null
          competitor_copy_ratio?: number | null
          content_filter_max_emojis?: number | null
          content_filter_max_length?: number | null
          content_filter_min_length?: number | null
          content_filter_patterns?: Json | null
          created_at?: string | null
          discord_webhook_url?: string | null
          enable_ai_queue_fill?: boolean | null
          enable_velocity_monitoring?: boolean | null
          group_mode_enabled?: boolean
          id?: string
          is_enabled?: boolean | null
          pause_on_declining_velocity?: boolean | null
          pause_on_low_performance?: boolean | null
          performance_threshold?: number | null
          posting_times?: Json | null
          scheduler_version?: number
          updated_at?: string | null
          use_smart_timing?: boolean | null
          velocity_acceleration_threshold?: number | null
          velocity_decline_threshold?: number | null
          viral_interval_reduction_pct?: number | null
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "auto_post_config_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: true
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_config_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: true
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      auto_post_engagement_snapshots: {
        Row: {
          cumulative_engagement: number | null
          engagement_velocity: number | null
          hours_since_post: number | null
          id: string
          likes_count: number | null
          queue_item_id: string
          replies_count: number | null
          reposts_count: number | null
          snapshot_at: string
          views_count: number | null
        }
        Insert: {
          cumulative_engagement?: number | null
          engagement_velocity?: number | null
          hours_since_post?: number | null
          id?: string
          likes_count?: number | null
          queue_item_id: string
          replies_count?: number | null
          reposts_count?: number | null
          snapshot_at?: string
          views_count?: number | null
        }
        Update: {
          cumulative_engagement?: number | null
          engagement_velocity?: number | null
          hours_since_post?: number | null
          id?: string
          likes_count?: number | null
          queue_item_id?: string
          replies_count?: number | null
          reposts_count?: number | null
          snapshot_at?: string
          views_count?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "auto_post_engagement_snapshots_queue_item_id_fkey"
            columns: ["queue_item_id"]
            isOneToOne: false
            referencedRelation: "auto_post_queue"
            referencedColumns: ["id"]
          },
        ]
      }
      auto_post_group_config: {
        Row: {
          active_hours_end: number
          active_hours_start: number
          auto_reply_daily_limit: number
          auto_reply_ratio: number
          auto_reply_trigger_count: number
          auto_reply_window_hours: number
          content_sources: Json | null
          created_at: string | null
          crossreshare_to_ig: boolean
          crossreshare_to_ig_dark_mode: boolean
          cta_reply_delay_hours: number | null
          cta_reply_enabled: boolean | null
          cta_reply_min_likes: number | null
          cta_templates: Json | null
          enable_auto_reply: boolean
          enabled: boolean
          group_id: string
          id: string
          llm_judge_enabled: boolean
          llm_judge_min_score: number
          max_interval_minutes: number | null
          media_attachment_chance: number
          media_group_id: string | null
          media_source: string
          min_interval_minutes: number
          min_posts_per_account_per_day: number | null
          platform: string | null
          post_on_weekends: boolean
          posts_per_account_per_day: number
          require_approval: boolean
          rest_days_per_week: number | null
          round_robin_enabled: boolean
          timezone: string
          updated_at: string | null
          workspace_id: string
        }
        Insert: {
          active_hours_end?: number
          active_hours_start?: number
          auto_reply_daily_limit?: number
          auto_reply_ratio?: number
          auto_reply_trigger_count?: number
          auto_reply_window_hours?: number
          content_sources?: Json | null
          created_at?: string | null
          crossreshare_to_ig?: boolean
          crossreshare_to_ig_dark_mode?: boolean
          cta_reply_delay_hours?: number | null
          cta_reply_enabled?: boolean | null
          cta_reply_min_likes?: number | null
          cta_templates?: Json | null
          enable_auto_reply?: boolean
          enabled?: boolean
          group_id: string
          id?: string
          llm_judge_enabled?: boolean
          llm_judge_min_score?: number
          max_interval_minutes?: number | null
          media_attachment_chance?: number
          media_group_id?: string | null
          media_source?: string
          min_interval_minutes?: number
          min_posts_per_account_per_day?: number | null
          platform?: string | null
          post_on_weekends?: boolean
          posts_per_account_per_day?: number
          require_approval?: boolean
          rest_days_per_week?: number | null
          round_robin_enabled?: boolean
          timezone?: string
          updated_at?: string | null
          workspace_id: string
        }
        Update: {
          active_hours_end?: number
          active_hours_start?: number
          auto_reply_daily_limit?: number
          auto_reply_ratio?: number
          auto_reply_trigger_count?: number
          auto_reply_window_hours?: number
          content_sources?: Json | null
          created_at?: string | null
          crossreshare_to_ig?: boolean
          crossreshare_to_ig_dark_mode?: boolean
          cta_reply_delay_hours?: number | null
          cta_reply_enabled?: boolean | null
          cta_reply_min_likes?: number | null
          cta_templates?: Json | null
          enable_auto_reply?: boolean
          enabled?: boolean
          group_id?: string
          id?: string
          llm_judge_enabled?: boolean
          llm_judge_min_score?: number
          max_interval_minutes?: number | null
          media_attachment_chance?: number
          media_group_id?: string | null
          media_source?: string
          min_interval_minutes?: number
          min_posts_per_account_per_day?: number | null
          platform?: string | null
          post_on_weekends?: boolean
          posts_per_account_per_day?: number
          require_approval?: boolean
          rest_days_per_week?: number | null
          round_robin_enabled?: boolean
          timezone?: string
          updated_at?: string | null
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "auto_post_group_config_group_id_fkey"
            columns: ["group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_group_config_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_group_config_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      auto_post_group_state: {
        Row: {
          created_at: string | null
          current_account_index: number
          current_queue_index: number
          group_id: string
          id: string
          ig_current_account_index: number | null
          ig_current_queue_index: number | null
          ig_last_post_at: string | null
          ig_posts_today: number | null
          last_cron_run_at: string | null
          last_post_at: string | null
          last_reset_date: string | null
          posts_today: number
          updated_at: string | null
          workspace_id: string
        }
        Insert: {
          created_at?: string | null
          current_account_index?: number
          current_queue_index?: number
          group_id: string
          id?: string
          ig_current_account_index?: number | null
          ig_current_queue_index?: number | null
          ig_last_post_at?: string | null
          ig_posts_today?: number | null
          last_cron_run_at?: string | null
          last_post_at?: string | null
          last_reset_date?: string | null
          posts_today?: number
          updated_at?: string | null
          workspace_id: string
        }
        Update: {
          created_at?: string | null
          current_account_index?: number
          current_queue_index?: number
          group_id?: string
          id?: string
          ig_current_account_index?: number | null
          ig_current_queue_index?: number | null
          ig_last_post_at?: string | null
          ig_posts_today?: number | null
          last_cron_run_at?: string | null
          last_post_at?: string | null
          last_reset_date?: string | null
          posts_today?: number
          updated_at?: string | null
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "auto_post_group_state_group_id_fkey"
            columns: ["group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_group_state_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_group_state_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      auto_post_queue: {
        Row: {
          account_id: string | null
          active_arc_id: string | null
          ai_provider: string | null
          ai_style: string | null
          arc_beat_id: string | null
          claim_expires_at: string | null
          claim_token: string | null
          claimed_at: string | null
          content: string
          content_fingerprint: string | null
          content_length_bucket: string | null
          content_type: string | null
          created_at: string | null
          cta_replied_at: string | null
          cta_reply_thread_id: string | null
          dna_decision: string | null
          dna_fit_score: number | null
          dna_id: string | null
          dna_reasons: Json | null
          dna_version: number | null
          duplicate_of_queue_item_id: string | null
          duplicate_window_hours: number
          emotional_frame: string | null
          engagement_fetched_at: string | null
          engagement_rate: number | null
          engagement_velocity: number | null
          error_message: string | null
          external_published_at: string | null
          finalize_error: string | null
          format_type: string | null
          generation_id: string | null
          genericness_score: number | null
          group_id: string | null
          hook_type: string | null
          id: string
          last_error: string | null
          last_velocity_check: string | null
          likes_count: number | null
          media_fingerprint: string | null
          media_style: string | null
          media_urls: string[] | null
          metadata: Json | null
          model_provider: string | null
          mood_fit_score: number | null
          next_retry_at: string | null
          normalized_text_hash: string | null
          platform: string
          pool_status: string | null
          posted_at: string | null
          posting_hour: number | null
          predicted_viral_score: number | null
          prompt_version: string | null
          provenance: Json
          provenance_error: string | null
          provenance_status: string
          publish_fingerprint: string | null
          qstash_message_id: string | null
          rejection_reason: string | null
          replies_count: number | null
          reply_harvested_at: string | null
          reply_mechanism: string | null
          reposts_count: number | null
          retry_count: number | null
          schedule_nonce: string | null
          scheduled_for: string
          sibling_collision_score: number | null
          source_competitor_id: string | null
          source_competitor_username: string | null
          source_content: string | null
          source_id: string | null
          source_media_type: string | null
          source_pattern_id: string | null
          source_type: string | null
          status: string | null
          strategy_bucket: string
          strategy_recommendation_id: string | null
          template_id: string | null
          text_spoilers: Json | null
          threads_post_id: string | null
          topic_fit_score: number | null
          topic_label: string | null
          topic_tag: string | null
          uniqueness_score: number | null
          updated_at: string
          velocity_score: number | null
          velocity_trend: string | null
          views_at_24h: number | null
          voice_fit_score: number | null
          workspace_id: string
        }
        Insert: {
          account_id?: string | null
          active_arc_id?: string | null
          ai_provider?: string | null
          ai_style?: string | null
          arc_beat_id?: string | null
          claim_expires_at?: string | null
          claim_token?: string | null
          claimed_at?: string | null
          content: string
          content_fingerprint?: string | null
          content_length_bucket?: string | null
          content_type?: string | null
          created_at?: string | null
          cta_replied_at?: string | null
          cta_reply_thread_id?: string | null
          dna_decision?: string | null
          dna_fit_score?: number | null
          dna_id?: string | null
          dna_reasons?: Json | null
          dna_version?: number | null
          duplicate_of_queue_item_id?: string | null
          duplicate_window_hours?: number
          emotional_frame?: string | null
          engagement_fetched_at?: string | null
          engagement_rate?: number | null
          engagement_velocity?: number | null
          error_message?: string | null
          external_published_at?: string | null
          finalize_error?: string | null
          format_type?: string | null
          generation_id?: string | null
          genericness_score?: number | null
          group_id?: string | null
          hook_type?: string | null
          id?: string
          last_error?: string | null
          last_velocity_check?: string | null
          likes_count?: number | null
          media_fingerprint?: string | null
          media_style?: string | null
          media_urls?: string[] | null
          metadata?: Json | null
          model_provider?: string | null
          mood_fit_score?: number | null
          next_retry_at?: string | null
          normalized_text_hash?: string | null
          platform?: string
          pool_status?: string | null
          posted_at?: string | null
          posting_hour?: number | null
          predicted_viral_score?: number | null
          prompt_version?: string | null
          provenance?: Json
          provenance_error?: string | null
          provenance_status?: string
          publish_fingerprint?: string | null
          qstash_message_id?: string | null
          rejection_reason?: string | null
          replies_count?: number | null
          reply_harvested_at?: string | null
          reply_mechanism?: string | null
          reposts_count?: number | null
          retry_count?: number | null
          schedule_nonce?: string | null
          scheduled_for: string
          sibling_collision_score?: number | null
          source_competitor_id?: string | null
          source_competitor_username?: string | null
          source_content?: string | null
          source_id?: string | null
          source_media_type?: string | null
          source_pattern_id?: string | null
          source_type?: string | null
          status?: string | null
          strategy_bucket?: string
          strategy_recommendation_id?: string | null
          template_id?: string | null
          text_spoilers?: Json | null
          threads_post_id?: string | null
          topic_fit_score?: number | null
          topic_label?: string | null
          topic_tag?: string | null
          uniqueness_score?: number | null
          updated_at?: string
          velocity_score?: number | null
          velocity_trend?: string | null
          views_at_24h?: number | null
          voice_fit_score?: number | null
          workspace_id: string
        }
        Update: {
          account_id?: string | null
          active_arc_id?: string | null
          ai_provider?: string | null
          ai_style?: string | null
          arc_beat_id?: string | null
          claim_expires_at?: string | null
          claim_token?: string | null
          claimed_at?: string | null
          content?: string
          content_fingerprint?: string | null
          content_length_bucket?: string | null
          content_type?: string | null
          created_at?: string | null
          cta_replied_at?: string | null
          cta_reply_thread_id?: string | null
          dna_decision?: string | null
          dna_fit_score?: number | null
          dna_id?: string | null
          dna_reasons?: Json | null
          dna_version?: number | null
          duplicate_of_queue_item_id?: string | null
          duplicate_window_hours?: number
          emotional_frame?: string | null
          engagement_fetched_at?: string | null
          engagement_rate?: number | null
          engagement_velocity?: number | null
          error_message?: string | null
          external_published_at?: string | null
          finalize_error?: string | null
          format_type?: string | null
          generation_id?: string | null
          genericness_score?: number | null
          group_id?: string | null
          hook_type?: string | null
          id?: string
          last_error?: string | null
          last_velocity_check?: string | null
          likes_count?: number | null
          media_fingerprint?: string | null
          media_style?: string | null
          media_urls?: string[] | null
          metadata?: Json | null
          model_provider?: string | null
          mood_fit_score?: number | null
          next_retry_at?: string | null
          normalized_text_hash?: string | null
          platform?: string
          pool_status?: string | null
          posted_at?: string | null
          posting_hour?: number | null
          predicted_viral_score?: number | null
          prompt_version?: string | null
          provenance?: Json
          provenance_error?: string | null
          provenance_status?: string
          publish_fingerprint?: string | null
          qstash_message_id?: string | null
          rejection_reason?: string | null
          replies_count?: number | null
          reply_harvested_at?: string | null
          reply_mechanism?: string | null
          reposts_count?: number | null
          retry_count?: number | null
          schedule_nonce?: string | null
          scheduled_for?: string
          sibling_collision_score?: number | null
          source_competitor_id?: string | null
          source_competitor_username?: string | null
          source_content?: string | null
          source_id?: string | null
          source_media_type?: string | null
          source_pattern_id?: string | null
          source_type?: string | null
          status?: string | null
          strategy_bucket?: string
          strategy_recommendation_id?: string | null
          template_id?: string | null
          text_spoilers?: Json | null
          threads_post_id?: string | null
          topic_fit_score?: number | null
          topic_label?: string | null
          topic_tag?: string | null
          uniqueness_score?: number | null
          updated_at?: string
          velocity_score?: number | null
          velocity_trend?: string | null
          views_at_24h?: number | null
          voice_fit_score?: number | null
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "auto_post_queue_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_queue_active_arc_id_fkey"
            columns: ["active_arc_id"]
            isOneToOne: false
            referencedRelation: "account_content_arcs"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_queue_arc_beat_id_fkey"
            columns: ["arc_beat_id"]
            isOneToOne: false
            referencedRelation: "arc_beats"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_queue_dna_id_fkey"
            columns: ["dna_id"]
            isOneToOne: false
            referencedRelation: "account_dna"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_queue_group_id_fkey"
            columns: ["group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_queue_strategy_recommendation_id_fkey"
            columns: ["strategy_recommendation_id"]
            isOneToOne: false
            referencedRelation: "autoposter_strategy_recommendations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_queue_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_queue_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      auto_post_state: {
        Row: {
          account_post_counts: Json
          created_at: string
          current_account_index: number
          current_queue_index: number
          id: string
          last_post_at: string | null
          last_reset_date: string | null
          next_post_time: string | null
          posts_today: number
          updated_at: string
          workspace_id: string
        }
        Insert: {
          account_post_counts?: Json
          created_at?: string
          current_account_index?: number
          current_queue_index?: number
          id?: string
          last_post_at?: string | null
          last_reset_date?: string | null
          next_post_time?: string | null
          posts_today?: number
          updated_at?: string
          workspace_id: string
        }
        Update: {
          account_post_counts?: Json
          created_at?: string
          current_account_index?: number
          current_queue_index?: number
          id?: string
          last_post_at?: string | null
          last_reset_date?: string | null
          next_post_time?: string | null
          posts_today?: number
          updated_at?: string
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "auto_post_state_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: true
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_post_state_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: true
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      auto_reply_logs: {
        Row: {
          account_id: string
          created_at: string | null
          event_type: string
          id: string
          reply_text: string
          reply_to_id: string
          rule_id: string
          target_user_id: string
          target_username: string | null
        }
        Insert: {
          account_id: string
          created_at?: string | null
          event_type: string
          id?: string
          reply_text: string
          reply_to_id: string
          rule_id: string
          target_user_id: string
          target_username?: string | null
        }
        Update: {
          account_id?: string
          created_at?: string | null
          event_type?: string
          id?: string
          reply_text?: string
          reply_to_id?: string
          rule_id?: string
          target_user_id?: string
          target_username?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "auto_reply_logs_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_reply_logs_rule_id_fkey"
            columns: ["rule_id"]
            isOneToOne: false
            referencedRelation: "auto_reply_rules"
            referencedColumns: ["id"]
          },
        ]
      }
      auto_reply_queue: {
        Row: {
          account_id: string
          comment_id: string
          comment_text: string
          comment_username: string
          created_at: string
          error_message: string | null
          flagged_reason: string | null
          generated_reply: string | null
          group_id: string | null
          id: string
          posted_at: string | null
          retry_count: number
          source_post_id: string
          status: string
          threads_post_id: string
          workspace_id: string
        }
        Insert: {
          account_id: string
          comment_id: string
          comment_text: string
          comment_username: string
          created_at?: string
          error_message?: string | null
          flagged_reason?: string | null
          generated_reply?: string | null
          group_id?: string | null
          id?: string
          posted_at?: string | null
          retry_count?: number
          source_post_id: string
          status?: string
          threads_post_id: string
          workspace_id: string
        }
        Update: {
          account_id?: string
          comment_id?: string
          comment_text?: string
          comment_username?: string
          created_at?: string
          error_message?: string | null
          flagged_reason?: string | null
          generated_reply?: string | null
          group_id?: string | null
          id?: string
          posted_at?: string | null
          retry_count?: number
          source_post_id?: string
          status?: string
          threads_post_id?: string
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "auto_reply_queue_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_reply_queue_group_id_fkey"
            columns: ["group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_reply_queue_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_reply_queue_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      auto_reply_rules: {
        Row: {
          account_id: string | null
          created_at: string | null
          id: string
          is_active: boolean | null
          last_triggered_at: string | null
          reply_text: string
          trigger_pattern: string
          trigger_type: string
          updated_at: string | null
          workspace_id: string
        }
        Insert: {
          account_id?: string | null
          created_at?: string | null
          id?: string
          is_active?: boolean | null
          last_triggered_at?: string | null
          reply_text: string
          trigger_pattern: string
          trigger_type: string
          updated_at?: string | null
          workspace_id: string
        }
        Update: {
          account_id?: string | null
          created_at?: string | null
          id?: string
          is_active?: boolean | null
          last_triggered_at?: string | null
          reply_text?: string
          trigger_pattern?: string
          trigger_type?: string
          updated_at?: string | null
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "auto_reply_rules_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_reply_rules_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "auto_reply_rules_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      auto_self_replies: {
        Row: {
          account_id: string
          content: string
          created_at: string | null
          eligible_reason: string | null
          error_message: string | null
          group_id: string | null
          id: string
          post_id: string
          published_at: string | null
          replies_at_check: number | null
          reply_number: number
          retry_count: number | null
          scheduled_for: string
          status: string
          threads_post_id: string | null
          threads_reply_id: string | null
          updated_at: string | null
          user_id: string
          views_at_check: number | null
          workspace_id: string
        }
        Insert: {
          account_id: string
          content: string
          created_at?: string | null
          eligible_reason?: string | null
          error_message?: string | null
          group_id?: string | null
          id?: string
          post_id: string
          published_at?: string | null
          replies_at_check?: number | null
          reply_number?: number
          retry_count?: number | null
          scheduled_for: string
          status?: string
          threads_post_id?: string | null
          threads_reply_id?: string | null
          updated_at?: string | null
          user_id: string
          views_at_check?: number | null
          workspace_id?: string
        }
        Update: {
          account_id?: string
          content?: string
          created_at?: string | null
          eligible_reason?: string | null
          error_message?: string | null
          group_id?: string | null
          id?: string
          post_id?: string
          published_at?: string | null
          replies_at_check?: number | null
          reply_number?: number
          retry_count?: number | null
          scheduled_for?: string
          status?: string
          threads_post_id?: string | null
          threads_reply_id?: string | null
          updated_at?: string | null
          user_id?: string
          views_at_check?: number | null
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "auto_self_replies_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      autopilot_run_steps: {
        Row: {
          duration_ms: number | null
          error_message: string | null
          finished_at: string | null
          id: string
          inputs: Json | null
          outputs: Json | null
          run_id: string
          started_at: string
          status: string
          step_index: number
          step_name: string
        }
        Insert: {
          duration_ms?: number | null
          error_message?: string | null
          finished_at?: string | null
          id?: string
          inputs?: Json | null
          outputs?: Json | null
          run_id: string
          started_at: string
          status: string
          step_index: number
          step_name: string
        }
        Update: {
          duration_ms?: number | null
          error_message?: string | null
          finished_at?: string | null
          id?: string
          inputs?: Json | null
          outputs?: Json | null
          run_id?: string
          started_at?: string
          status?: string
          step_index?: number
          step_name?: string
        }
        Relationships: [
          {
            foreignKeyName: "autopilot_run_steps_run_id_fkey"
            columns: ["run_id"]
            isOneToOne: false
            referencedRelation: "autopilot_runs"
            referencedColumns: ["id"]
          },
        ]
      }
      autopilot_runs: {
        Row: {
          account_id: string | null
          finished_at: string | null
          id: string
          metadata: Json | null
          parent_run_id: string | null
          post_id: string | null
          run_type: string
          started_at: string
          status: string
          trigger: string | null
          user_id: string
        }
        Insert: {
          account_id?: string | null
          finished_at?: string | null
          id?: string
          metadata?: Json | null
          parent_run_id?: string | null
          post_id?: string | null
          run_type: string
          started_at?: string
          status: string
          trigger?: string | null
          user_id: string
        }
        Update: {
          account_id?: string | null
          finished_at?: string | null
          id?: string
          metadata?: Json | null
          parent_run_id?: string | null
          post_id?: string | null
          run_type?: string
          started_at?: string
          status?: string
          trigger?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "autopilot_runs_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "autopilot_runs_parent_run_id_fkey"
            columns: ["parent_run_id"]
            isOneToOne: false
            referencedRelation: "autopilot_runs"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "autopilot_runs_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "autopilot_runs_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "autopilot_runs_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      autoposter_account_hour_performance: {
        Row: {
          above_100_rate: number
          account_id: string
          avg_replies_24h: number
          avg_views_24h: number
          computed_at: string
          confidence: number
          effective_sample_size: number
          fallback_source: string
          group_id: string | null
          hour: number
          last_seen_at: string | null
          median_views_24h: number
          platform: string
          posts_count: number
          profile_clicks_proxy: number
          weighted_score: number
          workspace_id: string
        }
        Insert: {
          above_100_rate?: number
          account_id: string
          avg_replies_24h?: number
          avg_views_24h?: number
          computed_at?: string
          confidence?: number
          effective_sample_size?: number
          fallback_source?: string
          group_id?: string | null
          hour: number
          last_seen_at?: string | null
          median_views_24h?: number
          platform?: string
          posts_count?: number
          profile_clicks_proxy?: number
          weighted_score?: number
          workspace_id: string
        }
        Update: {
          above_100_rate?: number
          account_id?: string
          avg_replies_24h?: number
          avg_views_24h?: number
          computed_at?: string
          confidence?: number
          effective_sample_size?: number
          fallback_source?: string
          group_id?: string | null
          hour?: number
          last_seen_at?: string | null
          median_views_24h?: number
          platform?: string
          posts_count?: number
          profile_clicks_proxy?: number
          weighted_score?: number
          workspace_id?: string
        }
        Relationships: []
      }
      autoposter_post_performance_facts: {
        Row: {
          account_flavor_score: number | null
          account_id: string | null
          account_username: string | null
          clone_family: string | null
          computed_at: string
          content: string | null
          content_archetype: string | null
          content_length_bucket: string | null
          created_at: string
          creator_fit_score: number | null
          creator_key: string | null
          current_likes: number
          current_replies: number
          current_views: number
          direct_copy_reason: string | null
          dna_fit_score: number | null
          emotional_frame: string | null
          format_type: string | null
          genericness_score: number | null
          group_id: string | null
          group_name: string | null
          has_media: boolean
          hook_type: string | null
          likes_24h: number
          media_style: string | null
          media_type: string | null
          metric_notes: Json
          metrics_quality: string
          microcopy_confidence: number | null
          model_provider: string | null
          platform: string
          post_id: string
          posting_hour: number | null
          profile_clicks_proxy: number | null
          profile_clicks_proxy_scope: string | null
          prompt_version: string | null
          published_at: string | null
          quality_gate_lane: string | null
          quality_gate_reason: string | null
          question_subtype: string | null
          quotes_count: number
          replies_1h: number
          replies_24h: number
          reply_mechanism: string | null
          reposts_count: number
          shape_id: string | null
          smart_link_clicks: number
          smart_link_conversions: number
          smart_link_revenue: number
          source_competitor_id: string | null
          source_competitor_username: string | null
          source_id: string | null
          source_pattern_id: string | null
          source_type: string | null
          strategy_bucket: string | null
          strategy_recommendation_id: string | null
          template_id: string | null
          topic_label: string | null
          updated_at: string
          user_id: string
          views_1h: number
          views_24h: number
          workspace_id: string | null
        }
        Insert: {
          account_flavor_score?: number | null
          account_id?: string | null
          account_username?: string | null
          clone_family?: string | null
          computed_at?: string
          content?: string | null
          content_archetype?: string | null
          content_length_bucket?: string | null
          created_at?: string
          creator_fit_score?: number | null
          creator_key?: string | null
          current_likes?: number
          current_replies?: number
          current_views?: number
          direct_copy_reason?: string | null
          dna_fit_score?: number | null
          emotional_frame?: string | null
          format_type?: string | null
          genericness_score?: number | null
          group_id?: string | null
          group_name?: string | null
          has_media?: boolean
          hook_type?: string | null
          likes_24h?: number
          media_style?: string | null
          media_type?: string | null
          metric_notes?: Json
          metrics_quality?: string
          microcopy_confidence?: number | null
          model_provider?: string | null
          platform?: string
          post_id: string
          posting_hour?: number | null
          profile_clicks_proxy?: number | null
          profile_clicks_proxy_scope?: string | null
          prompt_version?: string | null
          published_at?: string | null
          quality_gate_lane?: string | null
          quality_gate_reason?: string | null
          question_subtype?: string | null
          quotes_count?: number
          replies_1h?: number
          replies_24h?: number
          reply_mechanism?: string | null
          reposts_count?: number
          shape_id?: string | null
          smart_link_clicks?: number
          smart_link_conversions?: number
          smart_link_revenue?: number
          source_competitor_id?: string | null
          source_competitor_username?: string | null
          source_id?: string | null
          source_pattern_id?: string | null
          source_type?: string | null
          strategy_bucket?: string | null
          strategy_recommendation_id?: string | null
          template_id?: string | null
          topic_label?: string | null
          updated_at?: string
          user_id: string
          views_1h?: number
          views_24h?: number
          workspace_id?: string | null
        }
        Update: {
          account_flavor_score?: number | null
          account_id?: string | null
          account_username?: string | null
          clone_family?: string | null
          computed_at?: string
          content?: string | null
          content_archetype?: string | null
          content_length_bucket?: string | null
          created_at?: string
          creator_fit_score?: number | null
          creator_key?: string | null
          current_likes?: number
          current_replies?: number
          current_views?: number
          direct_copy_reason?: string | null
          dna_fit_score?: number | null
          emotional_frame?: string | null
          format_type?: string | null
          genericness_score?: number | null
          group_id?: string | null
          group_name?: string | null
          has_media?: boolean
          hook_type?: string | null
          likes_24h?: number
          media_style?: string | null
          media_type?: string | null
          metric_notes?: Json
          metrics_quality?: string
          microcopy_confidence?: number | null
          model_provider?: string | null
          platform?: string
          post_id?: string
          posting_hour?: number | null
          profile_clicks_proxy?: number | null
          profile_clicks_proxy_scope?: string | null
          prompt_version?: string | null
          published_at?: string | null
          quality_gate_lane?: string | null
          quality_gate_reason?: string | null
          question_subtype?: string | null
          quotes_count?: number
          replies_1h?: number
          replies_24h?: number
          reply_mechanism?: string | null
          reposts_count?: number
          shape_id?: string | null
          smart_link_clicks?: number
          smart_link_conversions?: number
          smart_link_revenue?: number
          source_competitor_id?: string | null
          source_competitor_username?: string | null
          source_id?: string | null
          source_pattern_id?: string | null
          source_type?: string | null
          strategy_bucket?: string | null
          strategy_recommendation_id?: string | null
          template_id?: string | null
          topic_label?: string | null
          updated_at?: string
          user_id?: string
          views_1h?: number
          views_24h?: number
          workspace_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "autoposter_post_performance_fac_strategy_recommendation_id_fkey"
            columns: ["strategy_recommendation_id"]
            isOneToOne: false
            referencedRelation: "autoposter_strategy_recommendations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "autoposter_post_performance_facts_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: true
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "autoposter_post_performance_facts_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: true
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
        ]
      }
      autoposter_strategy_recommendations: {
        Row: {
          account_id: string | null
          below_baseline_count: number
          confidence: number
          created_at: string
          downgraded_at: string | null
          expired_early_at: string | null
          expires_at: string
          group_id: string | null
          id: string
          last_outcome_checked_at: string | null
          metric_basis: Json
          outcome_sample_count: number
          pattern_type: string
          pattern_value: string
          reason: string
          recommendation: string
          updated_at: string
          workspace_id: string
        }
        Insert: {
          account_id?: string | null
          below_baseline_count?: number
          confidence?: number
          created_at?: string
          downgraded_at?: string | null
          expired_early_at?: string | null
          expires_at: string
          group_id?: string | null
          id?: string
          last_outcome_checked_at?: string | null
          metric_basis?: Json
          outcome_sample_count?: number
          pattern_type: string
          pattern_value: string
          reason: string
          recommendation: string
          updated_at?: string
          workspace_id: string
        }
        Update: {
          account_id?: string | null
          below_baseline_count?: number
          confidence?: number
          created_at?: string
          downgraded_at?: string | null
          expired_early_at?: string | null
          expires_at?: string
          group_id?: string | null
          id?: string
          last_outcome_checked_at?: string | null
          metric_basis?: Json
          outcome_sample_count?: number
          pattern_type?: string
          pattern_value?: string
          reason?: string
          recommendation?: string
          updated_at?: string
          workspace_id?: string
        }
        Relationships: []
      }
      autoposter_winner_patterns: {
        Row: {
          account_id: string | null
          clone_family: string | null
          clone_prompt: string
          confidence: number
          content_archetype: string | null
          content_length_bucket: string | null
          created_at: string
          creator_key: string | null
          emotional_frame: string | null
          expires_at: string
          group_id: string | null
          id: string
          link_clicks: number
          media_style: string | null
          performance_basis: string
          posting_hour: number | null
          question_subtype: string | null
          replies_1h: number
          reply_mechanism: string | null
          revenue: number
          shape_id: string | null
          source_post_id: string
          source_text: string
          source_type: string | null
          topic_label: string | null
          updated_at: string
          views_24h: number
          workspace_id: string
        }
        Insert: {
          account_id?: string | null
          clone_family?: string | null
          clone_prompt: string
          confidence?: number
          content_archetype?: string | null
          content_length_bucket?: string | null
          created_at?: string
          creator_key?: string | null
          emotional_frame?: string | null
          expires_at?: string
          group_id?: string | null
          id?: string
          link_clicks?: number
          media_style?: string | null
          performance_basis: string
          posting_hour?: number | null
          question_subtype?: string | null
          replies_1h?: number
          reply_mechanism?: string | null
          revenue?: number
          shape_id?: string | null
          source_post_id: string
          source_text: string
          source_type?: string | null
          topic_label?: string | null
          updated_at?: string
          views_24h?: number
          workspace_id: string
        }
        Update: {
          account_id?: string | null
          clone_family?: string | null
          clone_prompt?: string
          confidence?: number
          content_archetype?: string | null
          content_length_bucket?: string | null
          created_at?: string
          creator_key?: string | null
          emotional_frame?: string | null
          expires_at?: string
          group_id?: string | null
          id?: string
          link_clicks?: number
          media_style?: string | null
          performance_basis?: string
          posting_hour?: number | null
          question_subtype?: string | null
          replies_1h?: number
          reply_mechanism?: string | null
          revenue?: number
          shape_id?: string | null
          source_post_id?: string
          source_text?: string
          source_type?: string | null
          topic_label?: string | null
          updated_at?: string
          views_24h?: number
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "autoposter_winner_patterns_source_post_id_fkey"
            columns: ["source_post_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "autoposter_winner_patterns_source_post_id_fkey"
            columns: ["source_post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
        ]
      }
      banned_phrases: {
        Row: {
          created_at: string
          created_by: string | null
          id: string
          pattern_type: string
          phrase: string
          reason: string | null
          severity: string
          updated_at: string
          workspace_id: string
        }
        Insert: {
          created_at?: string
          created_by?: string | null
          id?: string
          pattern_type?: string
          phrase: string
          reason?: string | null
          severity?: string
          updated_at?: string
          workspace_id: string
        }
        Update: {
          created_at?: string
          created_by?: string | null
          id?: string
          pattern_type?: string
          phrase?: string
          reason?: string | null
          severity?: string
          updated_at?: string
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "banned_phrases_created_by_fkey"
            columns: ["created_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "banned_phrases_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "banned_phrases_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      calendar_reschedule_log: {
        Row: {
          batch_id: string
          created_at: string
          id: string
          new_scheduled_at: string | null
          post_id: string
          prev_scheduled_at: string | null
          reason: string | null
          reverted_at: string | null
          triggered_by: string | null
          user_id: string
        }
        Insert: {
          batch_id?: string
          created_at?: string
          id?: string
          new_scheduled_at?: string | null
          post_id: string
          prev_scheduled_at?: string | null
          reason?: string | null
          reverted_at?: string | null
          triggered_by?: string | null
          user_id: string
        }
        Update: {
          batch_id?: string
          created_at?: string
          id?: string
          new_scheduled_at?: string | null
          post_id?: string
          prev_scheduled_at?: string | null
          reason?: string | null
          reverted_at?: string | null
          triggered_by?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "calendar_reschedule_log_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "calendar_reschedule_log_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "calendar_reschedule_log_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      campaign_factory_audio_events: {
        Row: {
          action: string
          campaign_id: string | null
          created_at: string
          id: string
          metadata: Json
          next_status: string | null
          note: string | null
          platform_audio_id: string | null
          platform_url: string | null
          post_id: string
          previous_status: string | null
          proof_complete: boolean
          rendered_asset_id: string | null
          user_id: string
        }
        Insert: {
          action: string
          campaign_id?: string | null
          created_at?: string
          id?: string
          metadata?: Json
          next_status?: string | null
          note?: string | null
          platform_audio_id?: string | null
          platform_url?: string | null
          post_id: string
          previous_status?: string | null
          proof_complete?: boolean
          rendered_asset_id?: string | null
          user_id: string
        }
        Update: {
          action?: string
          campaign_id?: string | null
          created_at?: string
          id?: string
          metadata?: Json
          next_status?: string | null
          note?: string | null
          platform_audio_id?: string | null
          platform_url?: string | null
          post_id?: string
          previous_status?: string | null
          proof_complete?: boolean
          rendered_asset_id?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "campaign_factory_audio_events_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "campaign_factory_audio_events_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "campaign_factory_audio_events_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      campaign_factory_edges: {
        Row: {
          campaign_id: string | null
          created_at: string
          evidence: Json
          from_global_id: string
          id: string
          relation_type: string
          to_global_id: string
        }
        Insert: {
          campaign_id?: string | null
          created_at?: string
          evidence?: Json
          from_global_id: string
          id?: string
          relation_type: string
          to_global_id: string
        }
        Update: {
          campaign_id?: string | null
          created_at?: string
          evidence?: Json
          from_global_id?: string
          id?: string
          relation_type?: string
          to_global_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "campaign_factory_edges_from_global_id_fkey"
            columns: ["from_global_id"]
            isOneToOne: false
            referencedRelation: "campaign_factory_entities"
            referencedColumns: ["global_id"]
          },
          {
            foreignKeyName: "campaign_factory_edges_to_global_id_fkey"
            columns: ["to_global_id"]
            isOneToOne: false
            referencedRelation: "campaign_factory_entities"
            referencedColumns: ["global_id"]
          },
        ]
      }
      campaign_factory_entities: {
        Row: {
          campaign_id: string | null
          created_at: string
          entity_type: string
          global_id: string
          local_id: string | null
          local_table: string | null
          payload: Json
          updated_at: string
        }
        Insert: {
          campaign_id?: string | null
          created_at?: string
          entity_type: string
          global_id: string
          local_id?: string | null
          local_table?: string | null
          payload?: Json
          updated_at?: string
        }
        Update: {
          campaign_id?: string | null
          created_at?: string
          entity_type?: string
          global_id?: string
          local_id?: string | null
          local_table?: string | null
          payload?: Json
          updated_at?: string
        }
        Relationships: []
      }
      campaign_factory_post_links: {
        Row: {
          audit_graph_id: string | null
          campaign_graph_id: string | null
          campaign_id: string | null
          created_at: string
          draft_key: string | null
          export_run_id: string | null
          media_id: string | null
          media_key: string | null
          metadata: Json
          post_graph_id: string | null
          post_id: string
          post_key: string | null
          rendered_asset_graph_id: string | null
          rendered_asset_id: string | null
          source_asset_graph_id: string | null
          source_asset_id: string | null
          status: string | null
          updated_at: string
          user_id: string
        }
        Insert: {
          audit_graph_id?: string | null
          campaign_graph_id?: string | null
          campaign_id?: string | null
          created_at?: string
          draft_key?: string | null
          export_run_id?: string | null
          media_id?: string | null
          media_key?: string | null
          metadata?: Json
          post_graph_id?: string | null
          post_id: string
          post_key?: string | null
          rendered_asset_graph_id?: string | null
          rendered_asset_id?: string | null
          source_asset_graph_id?: string | null
          source_asset_id?: string | null
          status?: string | null
          updated_at?: string
          user_id: string
        }
        Update: {
          audit_graph_id?: string | null
          campaign_graph_id?: string | null
          campaign_id?: string | null
          created_at?: string
          draft_key?: string | null
          export_run_id?: string | null
          media_id?: string | null
          media_key?: string | null
          metadata?: Json
          post_graph_id?: string | null
          post_id?: string
          post_key?: string | null
          rendered_asset_graph_id?: string | null
          rendered_asset_id?: string | null
          source_asset_graph_id?: string | null
          source_asset_id?: string | null
          status?: string | null
          updated_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "campaign_factory_post_links_media_id_fkey"
            columns: ["media_id"]
            isOneToOne: false
            referencedRelation: "media"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "campaign_factory_post_links_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: true
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "campaign_factory_post_links_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: true
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "campaign_factory_post_links_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      campaign_schedule_batch_items: {
        Row: {
          batch_id: string
          campaign_factory_asset_id: string | null
          campaign_factory_distribution_plan_id: string | null
          created_at: string
          failure_reason: string | null
          id: string
          instagram_account_id: string | null
          metadata: Json
          post_id: string | null
          qstash_message_id: string | null
          scheduled_for: string | null
          status: string
          updated_at: string
          user_id: string
        }
        Insert: {
          batch_id: string
          campaign_factory_asset_id?: string | null
          campaign_factory_distribution_plan_id?: string | null
          created_at?: string
          failure_reason?: string | null
          id?: string
          instagram_account_id?: string | null
          metadata?: Json
          post_id?: string | null
          qstash_message_id?: string | null
          scheduled_for?: string | null
          status?: string
          updated_at?: string
          user_id: string
        }
        Update: {
          batch_id?: string
          campaign_factory_asset_id?: string | null
          campaign_factory_distribution_plan_id?: string | null
          created_at?: string
          failure_reason?: string | null
          id?: string
          instagram_account_id?: string | null
          metadata?: Json
          post_id?: string | null
          qstash_message_id?: string | null
          scheduled_for?: string | null
          status?: string
          updated_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "campaign_schedule_batch_items_batch_id_fkey"
            columns: ["batch_id"]
            isOneToOne: false
            referencedRelation: "campaign_schedule_batches"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "campaign_schedule_batch_items_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "campaign_schedule_batch_items_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "campaign_schedule_batch_items_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      campaign_schedule_batches: {
        Row: {
          created_at: string
          dry_run: boolean
          failed_count: number
          id: string
          metadata: Json
          requested_count: number
          scheduled_count: number
          status: string
          updated_at: string
          user_id: string
        }
        Insert: {
          created_at?: string
          dry_run?: boolean
          failed_count?: number
          id?: string
          metadata?: Json
          requested_count?: number
          scheduled_count?: number
          status?: string
          updated_at?: string
          user_id: string
        }
        Update: {
          created_at?: string
          dry_run?: boolean
          failed_count?: number
          id?: string
          metadata?: Json
          requested_count?: number
          scheduled_count?: number
          status?: string
          updated_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "campaign_schedule_batches_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      chart_annotations: {
        Row: {
          account_id: string
          annotation_date: string
          annotation_type: string | null
          color: string | null
          created_at: string | null
          id: string
          label: string
          user_id: string
        }
        Insert: {
          account_id: string
          annotation_date: string
          annotation_type?: string | null
          color?: string | null
          created_at?: string | null
          id?: string
          label: string
          user_id: string
        }
        Update: {
          account_id?: string
          annotation_date?: string
          annotation_type?: string | null
          color?: string | null
          created_at?: string | null
          id?: string
          label?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "chart_annotations_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "chart_annotations_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      competitor_alerts: {
        Row: {
          alert_type: string
          competitor_id: string
          created_at: string | null
          id: string
          message: string
          metadata: Json | null
          read: boolean | null
          user_id: string
        }
        Insert: {
          alert_type: string
          competitor_id: string
          created_at?: string | null
          id?: string
          message: string
          metadata?: Json | null
          read?: boolean | null
          user_id: string
        }
        Update: {
          alert_type?: string
          competitor_id?: string
          created_at?: string | null
          id?: string
          message?: string
          metadata?: Json | null
          read?: boolean | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "competitor_alerts_competitor_id_fkey"
            columns: ["competitor_id"]
            isOneToOne: false
            referencedRelation: "competitors"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "competitor_alerts_competitor_id_fkey"
            columns: ["competitor_id"]
            isOneToOne: false
            referencedRelation: "instagram_competitors"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "competitor_alerts_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      competitor_metrics_history: {
        Row: {
          avg_engagement_rate: number | null
          avg_likes: number | null
          avg_views: number | null
          competitor_id: string
          created_at: string | null
          date: string
          followers_count: number | null
          id: string
          top_post_engagement: number | null
          total_posts: number | null
          user_id: string
        }
        Insert: {
          avg_engagement_rate?: number | null
          avg_likes?: number | null
          avg_views?: number | null
          competitor_id: string
          created_at?: string | null
          date?: string
          followers_count?: number | null
          id?: string
          top_post_engagement?: number | null
          total_posts?: number | null
          user_id: string
        }
        Update: {
          avg_engagement_rate?: number | null
          avg_likes?: number | null
          avg_views?: number | null
          competitor_id?: string
          created_at?: string | null
          date?: string
          followers_count?: number | null
          id?: string
          top_post_engagement?: number | null
          total_posts?: number | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "competitor_metrics_history_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_competitor_metrics_history_competitor"
            columns: ["competitor_id"]
            isOneToOne: false
            referencedRelation: "competitors"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_competitor_metrics_history_competitor"
            columns: ["competitor_id"]
            isOneToOne: false
            referencedRelation: "instagram_competitors"
            referencedColumns: ["id"]
          },
        ]
      }
      competitor_post_metric_snapshots: {
        Row: {
          competitor_id: string
          competitor_post_id: string | null
          created_at: string
          engagement_score: number
          follower_count_at_scrape: number | null
          id: string
          last_metric_checked_at: string | null
          likes: number
          metric_quality: string
          metric_source: string
          platform: string
          quotes: number
          raw_metrics: Json
          replies: number
          reposts: number
          scraped_at: string
          threads_post_id: string | null
          user_id: string | null
          views: number
        }
        Insert: {
          competitor_id: string
          competitor_post_id?: string | null
          created_at?: string
          engagement_score?: number
          follower_count_at_scrape?: number | null
          id?: string
          last_metric_checked_at?: string | null
          likes?: number
          metric_quality?: string
          metric_source?: string
          platform?: string
          quotes?: number
          raw_metrics?: Json
          replies?: number
          reposts?: number
          scraped_at?: string
          threads_post_id?: string | null
          user_id?: string | null
          views?: number
        }
        Update: {
          competitor_id?: string
          competitor_post_id?: string | null
          created_at?: string
          engagement_score?: number
          follower_count_at_scrape?: number | null
          id?: string
          last_metric_checked_at?: string | null
          likes?: number
          metric_quality?: string
          metric_source?: string
          platform?: string
          quotes?: number
          raw_metrics?: Json
          replies?: number
          reposts?: number
          scraped_at?: string
          threads_post_id?: string | null
          user_id?: string | null
          views?: number
        }
        Relationships: [
          {
            foreignKeyName: "competitor_post_metric_snapshots_competitor_post_id_fkey"
            columns: ["competitor_post_id"]
            isOneToOne: false
            referencedRelation: "competitor_top_posts"
            referencedColumns: ["id"]
          },
        ]
      }
      competitor_snapshots: {
        Row: {
          avg_comments: number | null
          avg_likes: number | null
          competitor_id: string
          created_at: string | null
          engagement_rate: number | null
          follower_count: number | null
          id: string
          likes_count_7d: number | null
          media_count: number | null
          quotes_count_7d: number | null
          replies_count_7d: number | null
          reposts_count_7d: number | null
          snapshot_date: string
          user_id: string | null
          views_count_7d: number | null
        }
        Insert: {
          avg_comments?: number | null
          avg_likes?: number | null
          competitor_id: string
          created_at?: string | null
          engagement_rate?: number | null
          follower_count?: number | null
          id?: string
          likes_count_7d?: number | null
          media_count?: number | null
          quotes_count_7d?: number | null
          replies_count_7d?: number | null
          reposts_count_7d?: number | null
          snapshot_date: string
          user_id?: string | null
          views_count_7d?: number | null
        }
        Update: {
          avg_comments?: number | null
          avg_likes?: number | null
          competitor_id?: string
          created_at?: string | null
          engagement_rate?: number | null
          follower_count?: number | null
          id?: string
          likes_count_7d?: number | null
          media_count?: number | null
          quotes_count_7d?: number | null
          replies_count_7d?: number | null
          reposts_count_7d?: number | null
          snapshot_date?: string
          user_id?: string | null
          views_count_7d?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "competitor_snapshots_competitor_id_fkey"
            columns: ["competitor_id"]
            isOneToOne: false
            referencedRelation: "competitors"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "competitor_snapshots_competitor_id_fkey"
            columns: ["competitor_id"]
            isOneToOne: false
            referencedRelation: "instagram_competitors"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "competitor_snapshots_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      competitor_top_posts: {
        Row: {
          account_size_bucket: string | null
          benchmark_classified_at: string | null
          comments_count: number | null
          competitor_avatar_url: string | null
          competitor_id: string
          competitor_username: string | null
          content: string | null
          content_length_bucket: string | null
          controversy_level: string | null
          created_at: string | null
          cta_style: string | null
          emotional_frame: string | null
          engagement_score: number | null
          enriched_at: string | null
          format_type: string | null
          hook_type: string | null
          id: string
          last_metric_checked_at: string | null
          like_count: number | null
          media_style: string | null
          media_type: string | null
          media_url: string | null
          metric_quality: string
          metric_quality_reason: string | null
          metric_source: string
          permalink: string | null
          platform: string | null
          posting_hour: number | null
          published_at: string | null
          reply_count: number | null
          reply_mechanism: string | null
          repost_count: number | null
          scraped_at: string | null
          threads_post_id: string
          topic_label: string | null
          topic_tag: string | null
          user_id: string | null
          view_count: number | null
        }
        Insert: {
          account_size_bucket?: string | null
          benchmark_classified_at?: string | null
          comments_count?: number | null
          competitor_avatar_url?: string | null
          competitor_id: string
          competitor_username?: string | null
          content?: string | null
          content_length_bucket?: string | null
          controversy_level?: string | null
          created_at?: string | null
          cta_style?: string | null
          emotional_frame?: string | null
          engagement_score?: number | null
          enriched_at?: string | null
          format_type?: string | null
          hook_type?: string | null
          id?: string
          last_metric_checked_at?: string | null
          like_count?: number | null
          media_style?: string | null
          media_type?: string | null
          media_url?: string | null
          metric_quality?: string
          metric_quality_reason?: string | null
          metric_source?: string
          permalink?: string | null
          platform?: string | null
          posting_hour?: number | null
          published_at?: string | null
          reply_count?: number | null
          reply_mechanism?: string | null
          repost_count?: number | null
          scraped_at?: string | null
          threads_post_id: string
          topic_label?: string | null
          topic_tag?: string | null
          user_id?: string | null
          view_count?: number | null
        }
        Update: {
          account_size_bucket?: string | null
          benchmark_classified_at?: string | null
          comments_count?: number | null
          competitor_avatar_url?: string | null
          competitor_id?: string
          competitor_username?: string | null
          content?: string | null
          content_length_bucket?: string | null
          controversy_level?: string | null
          created_at?: string | null
          cta_style?: string | null
          emotional_frame?: string | null
          engagement_score?: number | null
          enriched_at?: string | null
          format_type?: string | null
          hook_type?: string | null
          id?: string
          last_metric_checked_at?: string | null
          like_count?: number | null
          media_style?: string | null
          media_type?: string | null
          media_url?: string | null
          metric_quality?: string
          metric_quality_reason?: string | null
          metric_source?: string
          permalink?: string | null
          platform?: string | null
          posting_hour?: number | null
          published_at?: string | null
          reply_count?: number | null
          reply_mechanism?: string | null
          repost_count?: number | null
          scraped_at?: string | null
          threads_post_id?: string
          topic_label?: string | null
          topic_tag?: string | null
          user_id?: string | null
          view_count?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "competitor_top_posts_competitor_id_fkey"
            columns: ["competitor_id"]
            isOneToOne: false
            referencedRelation: "competitors"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "competitor_top_posts_competitor_id_fkey"
            columns: ["competitor_id"]
            isOneToOne: false
            referencedRelation: "instagram_competitors"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "competitor_top_posts_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      competitors: {
        Row: {
          added_at: string | null
          avatar_url: string | null
          avg_comments: number | null
          avg_likes: number | null
          bio: string | null
          consecutive_failures: number | null
          display_name: string | null
          engagement_rate: number | null
          follower_count: number | null
          human_verified: boolean | null
          id: string
          instagram_user_id: string | null
          is_verified: boolean | null
          last_synced_at: string | null
          likes_count_7d: number | null
          media_count: number | null
          platform: string | null
          quotes_count_7d: number | null
          replies_count_7d: number | null
          reposts_count_7d: number | null
          sync_status: string | null
          threads_numeric_id: string | null
          threads_user_id: string
          user_id: string
          username: string
          verified_at: string | null
          verified_by: string | null
          views_count_7d: number | null
          website: string | null
        }
        Insert: {
          added_at?: string | null
          avatar_url?: string | null
          avg_comments?: number | null
          avg_likes?: number | null
          bio?: string | null
          consecutive_failures?: number | null
          display_name?: string | null
          engagement_rate?: number | null
          follower_count?: number | null
          human_verified?: boolean | null
          id?: string
          instagram_user_id?: string | null
          is_verified?: boolean | null
          last_synced_at?: string | null
          likes_count_7d?: number | null
          media_count?: number | null
          platform?: string | null
          quotes_count_7d?: number | null
          replies_count_7d?: number | null
          reposts_count_7d?: number | null
          sync_status?: string | null
          threads_numeric_id?: string | null
          threads_user_id: string
          user_id: string
          username: string
          verified_at?: string | null
          verified_by?: string | null
          views_count_7d?: number | null
          website?: string | null
        }
        Update: {
          added_at?: string | null
          avatar_url?: string | null
          avg_comments?: number | null
          avg_likes?: number | null
          bio?: string | null
          consecutive_failures?: number | null
          display_name?: string | null
          engagement_rate?: number | null
          follower_count?: number | null
          human_verified?: boolean | null
          id?: string
          instagram_user_id?: string | null
          is_verified?: boolean | null
          last_synced_at?: string | null
          likes_count_7d?: number | null
          media_count?: number | null
          platform?: string | null
          quotes_count_7d?: number | null
          replies_count_7d?: number | null
          reposts_count_7d?: number | null
          sync_status?: string | null
          threads_numeric_id?: string | null
          threads_user_id?: string
          user_id?: string
          username?: string
          verified_at?: string | null
          verified_by?: string | null
          views_count_7d?: number | null
          website?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "competitors_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      content_collections: {
        Row: {
          created_at: string | null
          id: string
          item_ids: Json | null
          name: string
          user_id: string
        }
        Insert: {
          created_at?: string | null
          id?: string
          item_ids?: Json | null
          name: string
          user_id: string
        }
        Update: {
          created_at?: string | null
          id?: string
          item_ids?: Json | null
          name?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "content_collections_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      copilot_memory: {
        Row: {
          id: string
          key: string
          updated_at: string
          user_id: string
          value: string
        }
        Insert: {
          id?: string
          key: string
          updated_at?: string
          user_id: string
          value: string
        }
        Update: {
          id?: string
          key?: string
          updated_at?: string
          user_id?: string
          value?: string
        }
        Relationships: [
          {
            foreignKeyName: "copilot_memory_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      creator_dna: {
        Row: {
          allowed_moods: Json
          archetype: string
          confidence: number
          core_motifs: Json
          core_topics: Json
          created_at: string
          creator_key: string
          creator_name: string
          follower_promise: string
          generated_from: string
          group_id: string
          id: string
          identity_summary: string
          last_refreshed_at: string | null
          last_scored_at: string | null
          shared_phrase_bank: Json
          shared_voice_traits: Json
          signature_beliefs: Json
          source_summary: Json
          status: string
          taboo_topics: Json
          updated_at: string
          version: number
          workspace_id: string
        }
        Insert: {
          allowed_moods?: Json
          archetype: string
          confidence?: number
          core_motifs?: Json
          core_topics?: Json
          created_at?: string
          creator_key: string
          creator_name: string
          follower_promise: string
          generated_from?: string
          group_id: string
          id?: string
          identity_summary: string
          last_refreshed_at?: string | null
          last_scored_at?: string | null
          shared_phrase_bank?: Json
          shared_voice_traits?: Json
          signature_beliefs?: Json
          source_summary?: Json
          status?: string
          taboo_topics?: Json
          updated_at?: string
          version?: number
          workspace_id: string
        }
        Update: {
          allowed_moods?: Json
          archetype?: string
          confidence?: number
          core_motifs?: Json
          core_topics?: Json
          created_at?: string
          creator_key?: string
          creator_name?: string
          follower_promise?: string
          generated_from?: string
          group_id?: string
          id?: string
          identity_summary?: string
          last_refreshed_at?: string | null
          last_scored_at?: string | null
          shared_phrase_bank?: Json
          shared_voice_traits?: Json
          signature_beliefs?: Json
          source_summary?: Json
          status?: string
          taboo_topics?: Json
          updated_at?: string
          version?: number
          workspace_id?: string
        }
        Relationships: []
      }
      creator_events: {
        Row: {
          account_id: string
          created_at: string
          description: string
          event_date: string
          event_type: string
          id: string
          impact_duration_days: number | null
          metrics_snapshot: Json | null
          user_id: string
        }
        Insert: {
          account_id: string
          created_at?: string
          description: string
          event_date?: string
          event_type: string
          id?: string
          impact_duration_days?: number | null
          metrics_snapshot?: Json | null
          user_id: string
        }
        Update: {
          account_id?: string
          created_at?: string
          description?: string
          event_date?: string
          event_type?: string
          id?: string
          impact_duration_days?: number | null
          metrics_snapshot?: Json | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "creator_events_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_creator_events_account"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
        ]
      }
      creator_identity_shape_usage: {
        Row: {
          account_id: string | null
          content: string
          created_at: string
          creator_dna_id: string | null
          group_id: string
          id: string
          normalized_content_hash: string | null
          shape_id: string | null
          source_id: string | null
          source_table: string
          used_at: string
          workspace_id: string
        }
        Insert: {
          account_id?: string | null
          content: string
          created_at?: string
          creator_dna_id?: string | null
          group_id: string
          id?: string
          normalized_content_hash?: string | null
          shape_id?: string | null
          source_id?: string | null
          source_table: string
          used_at?: string
          workspace_id: string
        }
        Update: {
          account_id?: string | null
          content?: string
          created_at?: string
          creator_dna_id?: string | null
          group_id?: string
          id?: string
          normalized_content_hash?: string | null
          shape_id?: string | null
          source_id?: string | null
          source_table?: string
          used_at?: string
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "creator_identity_shape_usage_creator_dna_id_fkey"
            columns: ["creator_dna_id"]
            isOneToOne: false
            referencedRelation: "creator_dna"
            referencedColumns: ["id"]
          },
        ]
      }
      creator_links: {
        Row: {
          click_count: number | null
          created_at: string | null
          id: string
          is_active: boolean | null
          label: string
          url: string
          workspace_id: string
        }
        Insert: {
          click_count?: number | null
          created_at?: string | null
          id?: string
          is_active?: boolean | null
          label: string
          url: string
          workspace_id: string
        }
        Update: {
          click_count?: number | null
          created_at?: string | null
          id?: string
          is_active?: boolean | null
          label?: string
          url?: string
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "creator_links_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "creator_links_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      crisis_events: {
        Row: {
          created_at: string | null
          id: string
          negative_count: number | null
          negative_ratio: number | null
          post_id: string | null
          resolved_at: string | null
          severity: string
          total_count: number | null
          trigger_reason: string
          user_id: string | null
          workspace_id: string | null
        }
        Insert: {
          created_at?: string | null
          id?: string
          negative_count?: number | null
          negative_ratio?: number | null
          post_id?: string | null
          resolved_at?: string | null
          severity: string
          total_count?: number | null
          trigger_reason: string
          user_id?: string | null
          workspace_id?: string | null
        }
        Update: {
          created_at?: string | null
          id?: string
          negative_count?: number | null
          negative_ratio?: number | null
          post_id?: string | null
          resolved_at?: string | null
          severity?: string
          total_count?: number | null
          trigger_reason?: string
          user_id?: string | null
          workspace_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "crisis_events_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_crisis_events_post"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_crisis_events_post"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_crisis_events_workspace"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_crisis_events_workspace"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      cron_locks: {
        Row: {
          expires_at: string | null
          job_name: string
          locked_at: string | null
          locked_by: string | null
        }
        Insert: {
          expires_at?: string | null
          job_name: string
          locked_at?: string | null
          locked_by?: string | null
        }
        Update: {
          expires_at?: string | null
          job_name?: string
          locked_at?: string | null
          locked_by?: string | null
        }
        Relationships: []
      }
      cron_runs: {
        Row: {
          error: string | null
          finished_at: string | null
          id: string
          items_processed: number | null
          job_name: string
          metadata: Json | null
          started_at: string
          status: string
        }
        Insert: {
          error?: string | null
          finished_at?: string | null
          id?: string
          items_processed?: number | null
          job_name: string
          metadata?: Json | null
          started_at?: string
          status?: string
        }
        Update: {
          error?: string | null
          finished_at?: string | null
          id?: string
          items_processed?: number | null
          job_name?: string
          metadata?: Json | null
          started_at?: string
          status?: string
        }
        Relationships: []
      }
      cross_post_settings: {
        Row: {
          adaptation_style: string | null
          auto_approve: boolean | null
          auto_hashtags: boolean | null
          created_at: string | null
          delay_minutes: number | null
          enabled: boolean | null
          id: string
          updated_at: string | null
          workspace_id: string
        }
        Insert: {
          adaptation_style?: string | null
          auto_approve?: boolean | null
          auto_hashtags?: boolean | null
          created_at?: string | null
          delay_minutes?: number | null
          enabled?: boolean | null
          id?: string
          updated_at?: string | null
          workspace_id: string
        }
        Update: {
          adaptation_style?: string | null
          auto_approve?: boolean | null
          auto_hashtags?: boolean | null
          created_at?: string | null
          delay_minutes?: number | null
          enabled?: boolean | null
          id?: string
          updated_at?: string | null
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "cross_post_settings_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: true
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "cross_post_settings_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: true
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      data_deletion_requests: {
        Row: {
          completed_at: string | null
          confirmation_code: string
          created_at: string
          error_message: string | null
          id: string
          meta_user_id: string
          requested_at: string
          status: string
          user_id: string | null
        }
        Insert: {
          completed_at?: string | null
          confirmation_code: string
          created_at?: string
          error_message?: string | null
          id?: string
          meta_user_id: string
          requested_at?: string
          status?: string
          user_id?: string | null
        }
        Update: {
          completed_at?: string | null
          confirmation_code?: string
          created_at?: string
          error_message?: string | null
          id?: string
          meta_user_id?: string
          requested_at?: string
          status?: string
          user_id?: string | null
        }
        Relationships: []
      }
      data_export_jobs: {
        Row: {
          completed_at: string | null
          created_at: string | null
          error_message: string | null
          expires_at: string | null
          file_path: string | null
          id: string
          status: string
          user_id: string
        }
        Insert: {
          completed_at?: string | null
          created_at?: string | null
          error_message?: string | null
          expires_at?: string | null
          file_path?: string | null
          id?: string
          status?: string
          user_id: string
        }
        Update: {
          completed_at?: string | null
          created_at?: string | null
          error_message?: string | null
          expires_at?: string | null
          file_path?: string | null
          id?: string
          status?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "data_export_jobs_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      demographics_snapshots: {
        Row: {
          account_id: string | null
          created_at: string | null
          date: string
          demographics_data: Json | null
          id: string
          instagram_account_id: string | null
          platform: string
          user_id: string
        }
        Insert: {
          account_id?: string | null
          created_at?: string | null
          date: string
          demographics_data?: Json | null
          id?: string
          instagram_account_id?: string | null
          platform?: string
          user_id: string
        }
        Update: {
          account_id?: string | null
          created_at?: string | null
          date?: string
          demographics_data?: Json | null
          id?: string
          instagram_account_id?: string | null
          platform?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "demographics_snapshots_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "demographics_snapshots_instagram_account_id_fkey"
            columns: ["instagram_account_id"]
            isOneToOne: false
            referencedRelation: "instagram_accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "demographics_snapshots_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      domain_verifications: {
        Row: {
          cname_target: string
          created_at: string | null
          domain: string
          expires_at: string | null
          id: string
          last_checked_at: string | null
          page_id: string | null
          smart_link_id: string | null
          status: string
          user_id: string
          verification_token: string
          verified_at: string | null
        }
        Insert: {
          cname_target?: string
          created_at?: string | null
          domain: string
          expires_at?: string | null
          id?: string
          last_checked_at?: string | null
          page_id?: string | null
          smart_link_id?: string | null
          status?: string
          user_id: string
          verification_token: string
          verified_at?: string | null
        }
        Update: {
          cname_target?: string
          created_at?: string | null
          domain?: string
          expires_at?: string | null
          id?: string
          last_checked_at?: string | null
          page_id?: string | null
          smart_link_id?: string | null
          status?: string
          user_id?: string
          verification_token?: string
          verified_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "domain_verifications_page_id_fkey"
            columns: ["page_id"]
            isOneToOne: false
            referencedRelation: "link_pages"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "domain_verifications_page_id_fkey"
            columns: ["page_id"]
            isOneToOne: false
            referencedRelation: "unified_link_roi"
            referencedColumns: ["page_id"]
          },
          {
            foreignKeyName: "domain_verifications_smart_link_id_fkey"
            columns: ["smart_link_id"]
            isOneToOne: false
            referencedRelation: "smart_links"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "domain_verifications_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      draft_folders: {
        Row: {
          account_group_id: string | null
          color: string | null
          created_at: string | null
          icon: string | null
          id: string
          name: string
          sort_order: number | null
          user_id: string
        }
        Insert: {
          account_group_id?: string | null
          color?: string | null
          created_at?: string | null
          icon?: string | null
          id?: string
          name: string
          sort_order?: number | null
          user_id: string
        }
        Update: {
          account_group_id?: string | null
          color?: string | null
          created_at?: string | null
          icon?: string | null
          id?: string
          name?: string
          sort_order?: number | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "draft_folders_account_group_id_fkey"
            columns: ["account_group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "draft_folders_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      favorites: {
        Row: {
          content: string | null
          created_at: string | null
          id: string
          media_urls: string[] | null
          notes: string | null
          post_id: string | null
          source_url: string | null
          source_username: string | null
          tags: string[] | null
          threads_post_id: string | null
          user_id: string
        }
        Insert: {
          content?: string | null
          created_at?: string | null
          id?: string
          media_urls?: string[] | null
          notes?: string | null
          post_id?: string | null
          source_url?: string | null
          source_username?: string | null
          tags?: string[] | null
          threads_post_id?: string | null
          user_id: string
        }
        Update: {
          content?: string | null
          created_at?: string | null
          id?: string
          media_urls?: string[] | null
          notes?: string | null
          post_id?: string | null
          source_url?: string | null
          source_username?: string | null
          tags?: string[] | null
          threads_post_id?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "favorites_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_favorites_post"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_favorites_post"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
        ]
      }
      feature_usage: {
        Row: {
          feature_name: string
          id: string
          used_at: string | null
          user_id: string
        }
        Insert: {
          feature_name: string
          id?: string
          used_at?: string | null
          user_id: string
        }
        Update: {
          feature_name?: string
          id?: string
          used_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "feature_usage_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      follower_history: {
        Row: {
          account_id: string
          created_at: string | null
          date: string
          follower_count: number
          id: string
          platform: string
        }
        Insert: {
          account_id: string
          created_at?: string | null
          date: string
          follower_count?: number
          id?: string
          platform?: string
        }
        Update: {
          account_id?: string
          created_at?: string | null
          date?: string
          follower_count?: number
          id?: string
          platform?: string
        }
        Relationships: []
      }
      group_analytics: {
        Row: {
          accounts_count: number | null
          avg_engagement_rate: number | null
          created_at: string | null
          date: string
          follower_growth: number | null
          group_id: string
          id: string
          posts_count: number | null
          top_performing_account_id: string | null
          total_followers: number | null
          total_likes: number | null
          total_quotes: number | null
          total_replies: number | null
          total_reposts: number | null
          total_views: number | null
          updated_at: string | null
          user_id: string
        }
        Insert: {
          accounts_count?: number | null
          avg_engagement_rate?: number | null
          created_at?: string | null
          date: string
          follower_growth?: number | null
          group_id: string
          id?: string
          posts_count?: number | null
          top_performing_account_id?: string | null
          total_followers?: number | null
          total_likes?: number | null
          total_quotes?: number | null
          total_replies?: number | null
          total_reposts?: number | null
          total_views?: number | null
          updated_at?: string | null
          user_id: string
        }
        Update: {
          accounts_count?: number | null
          avg_engagement_rate?: number | null
          created_at?: string | null
          date?: string
          follower_growth?: number | null
          group_id?: string
          id?: string
          posts_count?: number | null
          top_performing_account_id?: string | null
          total_followers?: number | null
          total_likes?: number | null
          total_quotes?: number | null
          total_replies?: number | null
          total_reposts?: number | null
          total_views?: number | null
          updated_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "group_analytics_group_id_fkey"
            columns: ["group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "group_analytics_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      ig_auto_responders: {
        Row: {
          ai_conversation_depth: number | null
          ai_response_intent: string | null
          ai_system_prompt: string | null
          created_at: string
          custom_response: string | null
          delay_seconds: number | null
          id: string
          ig_account_id: string
          is_enabled: boolean | null
          max_responses_per_user: number | null
          name: string
          only_new_conversations: boolean | null
          template_id: string | null
          trigger_keywords: string[] | null
          trigger_type: string
          updated_at: string
          use_ai_response: boolean | null
          user_id: string
        }
        Insert: {
          ai_conversation_depth?: number | null
          ai_response_intent?: string | null
          ai_system_prompt?: string | null
          created_at?: string
          custom_response?: string | null
          delay_seconds?: number | null
          id?: string
          ig_account_id: string
          is_enabled?: boolean | null
          max_responses_per_user?: number | null
          name: string
          only_new_conversations?: boolean | null
          template_id?: string | null
          trigger_keywords?: string[] | null
          trigger_type: string
          updated_at?: string
          use_ai_response?: boolean | null
          user_id: string
        }
        Update: {
          ai_conversation_depth?: number | null
          ai_response_intent?: string | null
          ai_system_prompt?: string | null
          created_at?: string
          custom_response?: string | null
          delay_seconds?: number | null
          id?: string
          ig_account_id?: string
          is_enabled?: boolean | null
          max_responses_per_user?: number | null
          name?: string
          only_new_conversations?: boolean | null
          template_id?: string | null
          trigger_keywords?: string[] | null
          trigger_type?: string
          updated_at?: string
          use_ai_response?: boolean | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "ig_auto_responders_template_id_fkey"
            columns: ["template_id"]
            isOneToOne: false
            referencedRelation: "ig_dm_templates"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "ig_auto_responders_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      ig_carousel_insights: {
        Row: {
          child_media_id: string
          comments: number | null
          fetched_at: string | null
          id: string
          impressions: number | null
          likes: number | null
          media_type: string | null
          media_url: string | null
          position: number
          post_id: string
          reach: number | null
          saved: number | null
          shares: number | null
        }
        Insert: {
          child_media_id: string
          comments?: number | null
          fetched_at?: string | null
          id?: string
          impressions?: number | null
          likes?: number | null
          media_type?: string | null
          media_url?: string | null
          position: number
          post_id: string
          reach?: number | null
          saved?: number | null
          shares?: number | null
        }
        Update: {
          child_media_id?: string
          comments?: number | null
          fetched_at?: string | null
          id?: string
          impressions?: number | null
          likes?: number | null
          media_type?: string | null
          media_url?: string | null
          position?: number
          post_id?: string
          reach?: number | null
          saved?: number | null
          shares?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "ig_carousel_insights_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "ig_carousel_insights_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
        ]
      }
      ig_collab_invites: {
        Row: {
          account_id: string
          caption: string | null
          discovered_at: string | null
          id: string
          media_type: string | null
          media_url: string | null
          owner_id: string | null
          owner_username: string | null
          permalink: string | null
          resolved_at: string | null
          status: string | null
          user_id: string
        }
        Insert: {
          account_id: string
          caption?: string | null
          discovered_at?: string | null
          id: string
          media_type?: string | null
          media_url?: string | null
          owner_id?: string | null
          owner_username?: string | null
          permalink?: string | null
          resolved_at?: string | null
          status?: string | null
          user_id: string
        }
        Update: {
          account_id?: string
          caption?: string | null
          discovered_at?: string | null
          id?: string
          media_type?: string | null
          media_url?: string | null
          owner_id?: string | null
          owner_username?: string | null
          permalink?: string | null
          resolved_at?: string | null
          status?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "ig_collab_invites_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "instagram_accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "ig_collab_invites_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      ig_comments: {
        Row: {
          account_id: string | null
          comment_id: string
          created_at: string
          id: string
          ig_user_id: string
          is_own_reply: boolean | null
          is_read: boolean | null
          like_count: number | null
          media_id: string
          parent_comment_id: string | null
          post_id: string
          text: string
          username: string
        }
        Insert: {
          account_id?: string | null
          comment_id: string
          created_at?: string
          id?: string
          ig_user_id: string
          is_own_reply?: boolean | null
          is_read?: boolean | null
          like_count?: number | null
          media_id: string
          parent_comment_id?: string | null
          post_id: string
          text?: string
          username?: string
        }
        Update: {
          account_id?: string | null
          comment_id?: string
          created_at?: string
          id?: string
          ig_user_id?: string
          is_own_reply?: boolean | null
          is_read?: boolean | null
          like_count?: number | null
          media_id?: string
          parent_comment_id?: string | null
          post_id?: string
          text?: string
          username?: string
        }
        Relationships: [
          {
            foreignKeyName: "ig_comments_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "ig_comments_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
        ]
      }
      ig_dm_ai_rate_limits: {
        Row: {
          account_id: string
          day_reset_at: string | null
          hour_reset_at: string | null
          responses_this_hour: number | null
          responses_today: number | null
        }
        Insert: {
          account_id: string
          day_reset_at?: string | null
          hour_reset_at?: string | null
          responses_this_hour?: number | null
          responses_today?: number | null
        }
        Update: {
          account_id?: string
          day_reset_at?: string | null
          hour_reset_at?: string | null
          responses_this_hour?: number | null
          responses_today?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "ig_dm_ai_rate_limits_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: true
            referencedRelation: "instagram_accounts"
            referencedColumns: ["id"]
          },
        ]
      }
      ig_dm_ai_responses: {
        Row: {
          account_id: string | null
          ai_response: string
          conversation_id: string
          converted_to_link: boolean | null
          created_at: string | null
          id: string
          incoming_message: string
          response_intent: string
          response_time_ms: number | null
          tokens_used: number | null
          user_replied_after: boolean | null
          voice_profile_used: boolean | null
        }
        Insert: {
          account_id?: string | null
          ai_response: string
          conversation_id: string
          converted_to_link?: boolean | null
          created_at?: string | null
          id?: string
          incoming_message: string
          response_intent: string
          response_time_ms?: number | null
          tokens_used?: number | null
          user_replied_after?: boolean | null
          voice_profile_used?: boolean | null
        }
        Update: {
          account_id?: string | null
          ai_response?: string
          conversation_id?: string
          converted_to_link?: boolean | null
          created_at?: string | null
          id?: string
          incoming_message?: string
          response_intent?: string
          response_time_ms?: number | null
          tokens_used?: number | null
          user_replied_after?: boolean | null
          voice_profile_used?: boolean | null
        }
        Relationships: [
          {
            foreignKeyName: "ig_dm_ai_responses_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "instagram_accounts"
            referencedColumns: ["id"]
          },
        ]
      }
      ig_dm_templates: {
        Row: {
          category: string | null
          content: string
          created_at: string
          id: string
          name: string
          shortcut: string | null
          updated_at: string
          use_count: number | null
          user_id: string
        }
        Insert: {
          category?: string | null
          content: string
          created_at?: string
          id?: string
          name: string
          shortcut?: string | null
          updated_at?: string
          use_count?: number | null
          user_id: string
        }
        Update: {
          category?: string | null
          content?: string
          created_at?: string
          id?: string
          name?: string
          shortcut?: string | null
          updated_at?: string
          use_count?: number | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "ig_dm_templates_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      ig_endpoint_rate_limits: {
        Row: {
          account_id: string
          created_at: string | null
          day_window_start: string | null
          endpoint: string
          hour_window_start: string | null
          id: string
          last_request_at: string | null
          requests_this_hour: number | null
          requests_today: number | null
        }
        Insert: {
          account_id: string
          created_at?: string | null
          day_window_start?: string | null
          endpoint: string
          hour_window_start?: string | null
          id?: string
          last_request_at?: string | null
          requests_this_hour?: number | null
          requests_today?: number | null
        }
        Update: {
          account_id?: string
          created_at?: string | null
          day_window_start?: string | null
          endpoint?: string
          hour_window_start?: string | null
          id?: string
          last_request_at?: string | null
          requests_this_hour?: number | null
          requests_today?: number | null
        }
        Relationships: []
      }
      ig_hashtag_tracking: {
        Row: {
          hashtag_ig_id: string
          hashtag_name: string
          id: string
          ig_account_id: string
          searched_at: string
          user_id: string
        }
        Insert: {
          hashtag_ig_id: string
          hashtag_name: string
          id?: string
          ig_account_id: string
          searched_at?: string
          user_id: string
        }
        Update: {
          hashtag_ig_id?: string
          hashtag_name?: string
          id?: string
          ig_account_id?: string
          searched_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "ig_hashtag_tracking_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      ig_mentions: {
        Row: {
          caption: string | null
          id: string
          ig_account_id: string
          ig_user_id: string
          is_read: boolean | null
          media_id: string
          media_type: string | null
          mentioned_at: string
          permalink: string | null
          user_id: string
          username: string
        }
        Insert: {
          caption?: string | null
          id?: string
          ig_account_id: string
          ig_user_id: string
          is_read?: boolean | null
          media_id: string
          media_type?: string | null
          mentioned_at?: string
          permalink?: string | null
          user_id: string
          username?: string
        }
        Update: {
          caption?: string | null
          id?: string
          ig_account_id?: string
          ig_user_id?: string
          is_read?: boolean | null
          media_id?: string
          media_type?: string | null
          mentioned_at?: string
          permalink?: string | null
          user_id?: string
          username?: string
        }
        Relationships: [
          {
            foreignKeyName: "ig_mentions_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      ig_pending_containers: {
        Row: {
          account_id: string
          check_count: number | null
          container_id: string
          created_at: string | null
          dead_letter: boolean | null
          dead_letter_at: string | null
          dead_letter_reason: string | null
          error: string | null
          id: string
          last_checked_at: string | null
          login_type: string | null
          post_id: string | null
          status: string
          updated_at: string | null
        }
        Insert: {
          account_id: string
          check_count?: number | null
          container_id: string
          created_at?: string | null
          dead_letter?: boolean | null
          dead_letter_at?: string | null
          dead_letter_reason?: string | null
          error?: string | null
          id?: string
          last_checked_at?: string | null
          login_type?: string | null
          post_id?: string | null
          status?: string
          updated_at?: string | null
        }
        Update: {
          account_id?: string
          check_count?: number | null
          container_id?: string
          created_at?: string | null
          dead_letter?: boolean | null
          dead_letter_at?: string | null
          dead_letter_reason?: string | null
          error?: string | null
          id?: string
          last_checked_at?: string | null
          login_type?: string | null
          post_id?: string | null
          status?: string
          updated_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "ig_pending_containers_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "ig_pending_containers_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
        ]
      }
      ig_rate_limit_tracking: {
        Row: {
          account_id: string
          created_at: string | null
          daily_count: number | null
          daily_reset_at: string | null
          id: string
          updated_at: string | null
        }
        Insert: {
          account_id: string
          created_at?: string | null
          daily_count?: number | null
          daily_reset_at?: string | null
          id?: string
          updated_at?: string | null
        }
        Update: {
          account_id?: string
          created_at?: string | null
          daily_count?: number | null
          daily_reset_at?: string | null
          id?: string
          updated_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "ig_rate_limit_tracking_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: true
            referencedRelation: "instagram_accounts"
            referencedColumns: ["id"]
          },
        ]
      }
      ig_story_insights: {
        Row: {
          exits: number
          follows: number | null
          id: string
          ig_user_id: string
          impressions: number
          media_id: string
          navigation: Json | null
          reach: number
          recorded_at: string
          replies: number
          shares: number | null
          taps_back: number
          taps_forward: number
          total_interactions: number | null
          views: number | null
        }
        Insert: {
          exits?: number
          follows?: number | null
          id?: string
          ig_user_id: string
          impressions?: number
          media_id: string
          navigation?: Json | null
          reach?: number
          recorded_at?: string
          replies?: number
          shares?: number | null
          taps_back?: number
          taps_forward?: number
          total_interactions?: number | null
          views?: number | null
        }
        Update: {
          exits?: number
          follows?: number | null
          id?: string
          ig_user_id?: string
          impressions?: number
          media_id?: string
          navigation?: Json | null
          reach?: number
          recorded_at?: string
          replies?: number
          shares?: number | null
          taps_back?: number
          taps_forward?: number
          total_interactions?: number | null
          views?: number | null
        }
        Relationships: []
      }
      ig_webhook_events: {
        Row: {
          dead_letter: boolean | null
          dead_letter_at: string | null
          dead_letter_reason: string | null
          error: string | null
          event_type: string
          id: string
          ig_user_id: string
          last_error: string | null
          lifetime_retry_count: number
          next_retry_at: string | null
          payload: Json
          payload_id: string
          processed: boolean
          processed_at: string | null
          received_at: string
          retry_count: number
        }
        Insert: {
          dead_letter?: boolean | null
          dead_letter_at?: string | null
          dead_letter_reason?: string | null
          error?: string | null
          event_type: string
          id?: string
          ig_user_id: string
          last_error?: string | null
          lifetime_retry_count?: number
          next_retry_at?: string | null
          payload: Json
          payload_id?: string
          processed?: boolean
          processed_at?: string | null
          received_at?: string
          retry_count?: number
        }
        Update: {
          dead_letter?: boolean | null
          dead_letter_at?: string | null
          dead_letter_reason?: string | null
          error?: string | null
          event_type?: string
          id?: string
          ig_user_id?: string
          last_error?: string | null
          lifetime_retry_count?: number
          next_retry_at?: string | null
          payload?: Json
          payload_id?: string
          processed?: boolean
          processed_at?: string | null
          received_at?: string
          retry_count?: number
        }
        Relationships: []
      }
      inbox_ai_buckets: {
        Row: {
          created_at: string
          icon: string | null
          id: string
          name: string
          query: Json
          sort_order: number | null
          user_id: string
        }
        Insert: {
          created_at?: string
          icon?: string | null
          id?: string
          name: string
          query: Json
          sort_order?: number | null
          user_id: string
        }
        Update: {
          created_at?: string
          icon?: string | null
          id?: string
          name?: string
          query?: Json
          sort_order?: number | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "inbox_ai_buckets_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      inbox_ai_suggestions: {
        Row: {
          alternatives: Json
          conversation_key: string
          created_at: string
          id: string
          reasoning: string | null
          status: string
          suggestion_text: string
          user_id: string
        }
        Insert: {
          alternatives?: Json
          conversation_key: string
          created_at?: string
          id?: string
          reasoning?: string | null
          status?: string
          suggestion_text: string
          user_id: string
        }
        Update: {
          alternatives?: Json
          conversation_key?: string
          created_at?: string
          id?: string
          reasoning?: string | null
          status?: string
          suggestion_text?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "inbox_ai_suggestions_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      inbox_assignments: {
        Row: {
          assigned_at: string | null
          assigned_by: string
          assigned_to: string
          id: string
          message_id: string
          note: string | null
          source: string
          workspace_id: string
        }
        Insert: {
          assigned_at?: string | null
          assigned_by: string
          assigned_to: string
          id?: string
          message_id: string
          note?: string | null
          source: string
          workspace_id: string
        }
        Update: {
          assigned_at?: string | null
          assigned_by?: string
          assigned_to?: string
          id?: string
          message_id?: string
          note?: string | null
          source?: string
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "inbox_assignments_assigned_by_fkey"
            columns: ["assigned_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "inbox_assignments_assigned_to_fkey"
            columns: ["assigned_to"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "inbox_assignments_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "inbox_assignments_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      inbox_conversation_state: {
        Row: {
          conversation_key: string
          snoozed_until: string | null
          state: string
          updated_at: string
          user_id: string
        }
        Insert: {
          conversation_key: string
          snoozed_until?: string | null
          state?: string
          updated_at?: string
          user_id: string
        }
        Update: {
          conversation_key?: string
          snoozed_until?: string | null
          state?: string
          updated_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "inbox_conversation_state_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      inbox_dm_cache: {
        Row: {
          account_id: string
          conversation_name: string | null
          created_at: string | null
          id: string
          is_read: boolean | null
          last_message_at: string | null
          last_message_text: string | null
          participant_id: string | null
          participant_username: string | null
          raw_data: Json | null
          updated_at: string | null
          user_id: string
        }
        Insert: {
          account_id: string
          conversation_name?: string | null
          created_at?: string | null
          id: string
          is_read?: boolean | null
          last_message_at?: string | null
          last_message_text?: string | null
          participant_id?: string | null
          participant_username?: string | null
          raw_data?: Json | null
          updated_at?: string | null
          user_id: string
        }
        Update: {
          account_id?: string
          conversation_name?: string | null
          created_at?: string | null
          id?: string
          is_read?: boolean | null
          last_message_at?: string | null
          last_message_text?: string | null
          participant_id?: string | null
          participant_username?: string | null
          raw_data?: Json | null
          updated_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "inbox_dm_cache_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      inbox_dm_messages: {
        Row: {
          attachment_type: string | null
          attachment_url: string | null
          conversation_id: string
          created_at: string
          id: string
          ig_account_id: string
          is_echo: boolean | null
          message_text: string | null
          sender_id: string | null
          sender_username: string | null
          synced_at: string | null
          user_id: string
        }
        Insert: {
          attachment_type?: string | null
          attachment_url?: string | null
          conversation_id: string
          created_at: string
          id: string
          ig_account_id: string
          is_echo?: boolean | null
          message_text?: string | null
          sender_id?: string | null
          sender_username?: string | null
          synced_at?: string | null
          user_id: string
        }
        Update: {
          attachment_type?: string | null
          attachment_url?: string | null
          conversation_id?: string
          created_at?: string
          id?: string
          ig_account_id?: string
          is_echo?: boolean | null
          message_text?: string | null
          sender_id?: string | null
          sender_username?: string | null
          synced_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "inbox_dm_messages_ig_account_id_fkey"
            columns: ["ig_account_id"]
            isOneToOne: false
            referencedRelation: "instagram_accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "inbox_dm_messages_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      inbox_saved_views: {
        Row: {
          created_at: string
          icon: string | null
          id: string
          name: string
          query: Json
          sort_order: number | null
          user_id: string
        }
        Insert: {
          created_at?: string
          icon?: string | null
          id?: string
          name: string
          query: Json
          sort_order?: number | null
          user_id: string
        }
        Update: {
          created_at?: string
          icon?: string | null
          id?: string
          name?: string
          query?: Json
          sort_order?: number | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "inbox_saved_views_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      influencer_collab_posts: {
        Row: {
          collab_id: string
          created_at: string | null
          id: string
          is_partner_post: boolean | null
          post_id: string
        }
        Insert: {
          collab_id: string
          created_at?: string | null
          id?: string
          is_partner_post?: boolean | null
          post_id: string
        }
        Update: {
          collab_id?: string
          created_at?: string | null
          id?: string
          is_partner_post?: boolean | null
          post_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "influencer_collab_posts_collab_id_fkey"
            columns: ["collab_id"]
            isOneToOne: false
            referencedRelation: "influencer_collabs"
            referencedColumns: ["id"]
          },
        ]
      }
      influencer_collabs: {
        Row: {
          collab_type: string
          cost_cents: number | null
          cost_type: string | null
          created_at: string | null
          end_date: string | null
          id: string
          notes: string | null
          outreach_template: string | null
          partner_avatar_url: string | null
          partner_follower_count: number | null
          partner_handle: string
          partner_platform: string
          revenue_share_pct: number | null
          start_date: string | null
          status: string
          updated_at: string | null
          user_id: string
          workspace_id: string | null
        }
        Insert: {
          collab_type?: string
          cost_cents?: number | null
          cost_type?: string | null
          created_at?: string | null
          end_date?: string | null
          id?: string
          notes?: string | null
          outreach_template?: string | null
          partner_avatar_url?: string | null
          partner_follower_count?: number | null
          partner_handle: string
          partner_platform?: string
          revenue_share_pct?: number | null
          start_date?: string | null
          status?: string
          updated_at?: string | null
          user_id: string
          workspace_id?: string | null
        }
        Update: {
          collab_type?: string
          cost_cents?: number | null
          cost_type?: string | null
          created_at?: string | null
          end_date?: string | null
          id?: string
          notes?: string | null
          outreach_template?: string | null
          partner_avatar_url?: string | null
          partner_follower_count?: number | null
          partner_handle?: string
          partner_platform?: string
          revenue_share_pct?: number | null
          start_date?: string | null
          status?: string
          updated_at?: string | null
          user_id?: string
          workspace_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "fk_influencer_collabs_workspace"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_influencer_collabs_workspace"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "influencer_collabs_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      inspiration_config: {
        Row: {
          adaptation_style: string | null
          created_at: string | null
          daily_digest_enabled: boolean | null
          enabled: boolean | null
          id: string
          ideas_generated_today: number | null
          ideas_per_competitor: number | null
          last_generation_reset: string | null
          last_scan_at: string | null
          notify_new_ideas: boolean | null
          topic_filters: string[] | null
          updated_at: string | null
          user_id: string
          workspace_id: string | null
        }
        Insert: {
          adaptation_style?: string | null
          created_at?: string | null
          daily_digest_enabled?: boolean | null
          enabled?: boolean | null
          id?: string
          ideas_generated_today?: number | null
          ideas_per_competitor?: number | null
          last_generation_reset?: string | null
          last_scan_at?: string | null
          notify_new_ideas?: boolean | null
          topic_filters?: string[] | null
          updated_at?: string | null
          user_id: string
          workspace_id?: string | null
        }
        Update: {
          adaptation_style?: string | null
          created_at?: string | null
          daily_digest_enabled?: boolean | null
          enabled?: boolean | null
          id?: string
          ideas_generated_today?: number | null
          ideas_per_competitor?: number | null
          last_generation_reset?: string | null
          last_scan_at?: string | null
          notify_new_ideas?: boolean | null
          topic_filters?: string[] | null
          updated_at?: string | null
          user_id?: string
          workspace_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "inspiration_config_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: true
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "inspiration_config_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "inspiration_config_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      inspiration_ideas: {
        Row: {
          adaptation_angle: string | null
          adaptation_style: string | null
          adapted_content: string
          ai_insight: string | null
          competitor_avatar_url: string | null
          competitor_id: string | null
          competitor_username: string
          created_at: string | null
          expires_at: string | null
          generated_at: string | null
          id: string
          original_post: Json
          posted_at: string | null
          queued: boolean | null
          queued_at: string | null
          saved: boolean | null
          status: string | null
          topic_tags: string[] | null
          updated_at: string | null
          user_id: string
          viral_formula: string | null
          viral_score: number | null
          workspace_id: string | null
        }
        Insert: {
          adaptation_angle?: string | null
          adaptation_style?: string | null
          adapted_content: string
          ai_insight?: string | null
          competitor_avatar_url?: string | null
          competitor_id?: string | null
          competitor_username: string
          created_at?: string | null
          expires_at?: string | null
          generated_at?: string | null
          id?: string
          original_post: Json
          posted_at?: string | null
          queued?: boolean | null
          queued_at?: string | null
          saved?: boolean | null
          status?: string | null
          topic_tags?: string[] | null
          updated_at?: string | null
          user_id: string
          viral_formula?: string | null
          viral_score?: number | null
          workspace_id?: string | null
        }
        Update: {
          adaptation_angle?: string | null
          adaptation_style?: string | null
          adapted_content?: string
          ai_insight?: string | null
          competitor_avatar_url?: string | null
          competitor_id?: string | null
          competitor_username?: string
          created_at?: string | null
          expires_at?: string | null
          generated_at?: string | null
          id?: string
          original_post?: Json
          posted_at?: string | null
          queued?: boolean | null
          queued_at?: string | null
          saved?: boolean | null
          status?: string | null
          topic_tags?: string[] | null
          updated_at?: string | null
          user_id?: string
          viral_formula?: string | null
          viral_score?: number | null
          workspace_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "inspiration_ideas_competitor_id_fkey"
            columns: ["competitor_id"]
            isOneToOne: false
            referencedRelation: "competitors"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "inspiration_ideas_competitor_id_fkey"
            columns: ["competitor_id"]
            isOneToOne: false
            referencedRelation: "instagram_competitors"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "inspiration_ideas_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "inspiration_ideas_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "inspiration_ideas_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      instagram_account_restriction_events: {
        Row: {
          created_at: string
          created_by: string | null
          ends_at: string | null
          evidence: Json
          id: string
          instagram_account_id: string
          notes: string | null
          recommendation_eligibility_state: string
          resolved_at: string | null
          resolved_by: string | null
          resolved_reason: string | null
          restriction_type: string
          review_required: boolean
          severity: string
          source: string
          source_confidence: string
          started_at: string
          status: string
          updated_at: string
          updated_by: string | null
          user_id: string
        }
        Insert: {
          created_at?: string
          created_by?: string | null
          ends_at?: string | null
          evidence?: Json
          id?: string
          instagram_account_id: string
          notes?: string | null
          recommendation_eligibility_state?: string
          resolved_at?: string | null
          resolved_by?: string | null
          resolved_reason?: string | null
          restriction_type: string
          review_required?: boolean
          severity?: string
          source?: string
          source_confidence?: string
          started_at?: string
          status?: string
          updated_at?: string
          updated_by?: string | null
          user_id: string
        }
        Update: {
          created_at?: string
          created_by?: string | null
          ends_at?: string | null
          evidence?: Json
          id?: string
          instagram_account_id?: string
          notes?: string | null
          recommendation_eligibility_state?: string
          resolved_at?: string | null
          resolved_by?: string | null
          resolved_reason?: string | null
          restriction_type?: string
          review_required?: boolean
          severity?: string
          source?: string
          source_confidence?: string
          started_at?: string
          status?: string
          updated_at?: string
          updated_by?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "instagram_account_restriction_events_instagram_account_id_fkey"
            columns: ["instagram_account_id"]
            isOneToOne: false
            referencedRelation: "instagram_accounts"
            referencedColumns: ["id"]
          },
        ]
      }
      instagram_accounts: {
        Row: {
          account_type: string | null
          ai_config: Json | null
          avatar_url: string | null
          baseline_follower_count: number | null
          baseline_following_count: number | null
          baseline_media_count: number | null
          bio: string | null
          cohort_updated_at: string | null
          consecutive_refresh_failures: number
          created_at: string | null
          display_name: string | null
          facebook_page_access_token_encrypted: string | null
          facebook_page_id: string | null
          facebook_page_name: string | null
          follower_count: number | null
          following_count: number | null
          group_id: string | null
          id: string
          inferred_niche: string | null
          instagram_access_token_encrypted: string | null
          instagram_user_id: string
          is_active: boolean | null
          last_dm_sync_at: string | null
          last_dm_sync_cursor: string | null
          last_milestone_celebrated: number | null
          last_synced_at: string | null
          login_type: string | null
          media_count: number | null
          needs_reauth: boolean
          status: string | null
          sync_cohort: string | null
          token_expires_at: string | null
          updated_at: string | null
          user_id: string
          user_niche: string | null
          username: string | null
        }
        Insert: {
          account_type?: string | null
          ai_config?: Json | null
          avatar_url?: string | null
          baseline_follower_count?: number | null
          baseline_following_count?: number | null
          baseline_media_count?: number | null
          bio?: string | null
          cohort_updated_at?: string | null
          consecutive_refresh_failures?: number
          created_at?: string | null
          display_name?: string | null
          facebook_page_access_token_encrypted?: string | null
          facebook_page_id?: string | null
          facebook_page_name?: string | null
          follower_count?: number | null
          following_count?: number | null
          group_id?: string | null
          id?: string
          inferred_niche?: string | null
          instagram_access_token_encrypted?: string | null
          instagram_user_id: string
          is_active?: boolean | null
          last_dm_sync_at?: string | null
          last_dm_sync_cursor?: string | null
          last_milestone_celebrated?: number | null
          last_synced_at?: string | null
          login_type?: string | null
          media_count?: number | null
          needs_reauth?: boolean
          status?: string | null
          sync_cohort?: string | null
          token_expires_at?: string | null
          updated_at?: string | null
          user_id: string
          user_niche?: string | null
          username?: string | null
        }
        Update: {
          account_type?: string | null
          ai_config?: Json | null
          avatar_url?: string | null
          baseline_follower_count?: number | null
          baseline_following_count?: number | null
          baseline_media_count?: number | null
          bio?: string | null
          cohort_updated_at?: string | null
          consecutive_refresh_failures?: number
          created_at?: string | null
          display_name?: string | null
          facebook_page_access_token_encrypted?: string | null
          facebook_page_id?: string | null
          facebook_page_name?: string | null
          follower_count?: number | null
          following_count?: number | null
          group_id?: string | null
          id?: string
          inferred_niche?: string | null
          instagram_access_token_encrypted?: string | null
          instagram_user_id?: string
          is_active?: boolean | null
          last_dm_sync_at?: string | null
          last_dm_sync_cursor?: string | null
          last_milestone_celebrated?: number | null
          last_synced_at?: string | null
          login_type?: string | null
          media_count?: number | null
          needs_reauth?: boolean
          status?: string | null
          sync_cohort?: string | null
          token_expires_at?: string | null
          updated_at?: string | null
          user_id?: string
          user_niche?: string | null
          username?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "instagram_accounts_group_id_fkey"
            columns: ["group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "instagram_accounts_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      link_benchmarks: {
        Row: {
          instagram_epc: number | null
          niche: string
          threads_epc: number | null
        }
        Insert: {
          instagram_epc?: number | null
          niche: string
          threads_epc?: number | null
        }
        Update: {
          instagram_epc?: number | null
          niche?: string
          threads_epc?: number | null
        }
        Relationships: []
      }
      link_clicks: {
        Row: {
          clicked_at: string | null
          country: string | null
          device_type: string | null
          event_name: string | null
          id: string
          is_crawler: boolean | null
          link_id: string | null
          page_id: string | null
          referrer: string | null
          source_app: string | null
          user_agent: string | null
          variant_id: string | null
        }
        Insert: {
          clicked_at?: string | null
          country?: string | null
          device_type?: string | null
          event_name?: string | null
          id?: string
          is_crawler?: boolean | null
          link_id?: string | null
          page_id?: string | null
          referrer?: string | null
          source_app?: string | null
          user_agent?: string | null
          variant_id?: string | null
        }
        Update: {
          clicked_at?: string | null
          country?: string | null
          device_type?: string | null
          event_name?: string | null
          id?: string
          is_crawler?: boolean | null
          link_id?: string | null
          page_id?: string | null
          referrer?: string | null
          source_app?: string | null
          user_agent?: string | null
          variant_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "link_clicks_link_id_fkey"
            columns: ["link_id"]
            isOneToOne: false
            referencedRelation: "link_items"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "link_clicks_page_id_fkey"
            columns: ["page_id"]
            isOneToOne: false
            referencedRelation: "link_pages"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "link_clicks_page_id_fkey"
            columns: ["page_id"]
            isOneToOne: false
            referencedRelation: "unified_link_roi"
            referencedColumns: ["page_id"]
          },
          {
            foreignKeyName: "link_clicks_variant_id_fkey"
            columns: ["variant_id"]
            isOneToOne: false
            referencedRelation: "link_page_variants"
            referencedColumns: ["id"]
          },
        ]
      }
      link_items: {
        Row: {
          click_count: number | null
          created_at: string | null
          deep_link_config: Json | null
          deep_link_url: string | null
          icon: string | null
          id: string
          is_primary: boolean | null
          is_visible: boolean | null
          page_id: string | null
          platform: string | null
          position: number
          pricing_config: Json | null
          redirect_id: string | null
          style: Json | null
          target_smart_link_id: string | null
          thumbnail_url: string | null
          title: string
          url: string
        }
        Insert: {
          click_count?: number | null
          created_at?: string | null
          deep_link_config?: Json | null
          deep_link_url?: string | null
          icon?: string | null
          id?: string
          is_primary?: boolean | null
          is_visible?: boolean | null
          page_id?: string | null
          platform?: string | null
          position: number
          pricing_config?: Json | null
          redirect_id?: string | null
          style?: Json | null
          target_smart_link_id?: string | null
          thumbnail_url?: string | null
          title: string
          url: string
        }
        Update: {
          click_count?: number | null
          created_at?: string | null
          deep_link_config?: Json | null
          deep_link_url?: string | null
          icon?: string | null
          id?: string
          is_primary?: boolean | null
          is_visible?: boolean | null
          page_id?: string | null
          platform?: string | null
          position?: number
          pricing_config?: Json | null
          redirect_id?: string | null
          style?: Json | null
          target_smart_link_id?: string | null
          thumbnail_url?: string | null
          title?: string
          url?: string
        }
        Relationships: [
          {
            foreignKeyName: "link_items_page_id_fkey"
            columns: ["page_id"]
            isOneToOne: false
            referencedRelation: "link_pages"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "link_items_page_id_fkey"
            columns: ["page_id"]
            isOneToOne: false
            referencedRelation: "unified_link_roi"
            referencedColumns: ["page_id"]
          },
          {
            foreignKeyName: "link_items_target_smart_link_id_fkey"
            columns: ["target_smart_link_id"]
            isOneToOne: false
            referencedRelation: "smart_links"
            referencedColumns: ["id"]
          },
        ]
      }
      link_page_variants: {
        Row: {
          account_id: string | null
          alpha: number
          beta: number
          confidence: number | null
          config: Json
          conversions: number
          created_at: string
          declared_at: string | null
          group_id: string | null
          id: string
          impressions: number
          is_active: boolean
          is_winner: boolean
          level: string
          page_id: string
          updated_at: string
          variant_label: string
          variant_type: string
        }
        Insert: {
          account_id?: string | null
          alpha?: number
          beta?: number
          confidence?: number | null
          config?: Json
          conversions?: number
          created_at?: string
          declared_at?: string | null
          group_id?: string | null
          id?: string
          impressions?: number
          is_active?: boolean
          is_winner?: boolean
          level?: string
          page_id: string
          updated_at?: string
          variant_label: string
          variant_type?: string
        }
        Update: {
          account_id?: string | null
          alpha?: number
          beta?: number
          confidence?: number | null
          config?: Json
          conversions?: number
          created_at?: string
          declared_at?: string | null
          group_id?: string | null
          id?: string
          impressions?: number
          is_active?: boolean
          is_winner?: boolean
          level?: string
          page_id?: string
          updated_at?: string
          variant_label?: string
          variant_type?: string
        }
        Relationships: [
          {
            foreignKeyName: "link_page_variants_page_id_fkey"
            columns: ["page_id"]
            isOneToOne: false
            referencedRelation: "link_pages"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "link_page_variants_page_id_fkey"
            columns: ["page_id"]
            isOneToOne: false
            referencedRelation: "unified_link_roi"
            referencedColumns: ["page_id"]
          },
        ]
      }
      link_pages: {
        Row: {
          age_gate: boolean | null
          age_gate_message: string | null
          avatar_url: string | null
          background_color: string | null
          bio: string | null
          brand_color: string | null
          cache_bust: number | null
          created_at: string | null
          custom_domain: string | null
          default_destination: string | null
          domain_verified: boolean | null
          domain_verified_at: string | null
          enable_deeplink_escape: boolean | null
          geo_rules: Json | null
          id: string
          is_published: boolean | null
          promo_text: string | null
          shield_config: Json | null
          shield_mode: string | null
          show_online_badge: boolean | null
          slug: string
          title: string | null
          tracking_pixels: Json | null
          updated_at: string | null
          user_id: string | null
          view_count: number | null
        }
        Insert: {
          age_gate?: boolean | null
          age_gate_message?: string | null
          avatar_url?: string | null
          background_color?: string | null
          bio?: string | null
          brand_color?: string | null
          cache_bust?: number | null
          created_at?: string | null
          custom_domain?: string | null
          default_destination?: string | null
          domain_verified?: boolean | null
          domain_verified_at?: string | null
          enable_deeplink_escape?: boolean | null
          geo_rules?: Json | null
          id?: string
          is_published?: boolean | null
          promo_text?: string | null
          shield_config?: Json | null
          shield_mode?: string | null
          show_online_badge?: boolean | null
          slug: string
          title?: string | null
          tracking_pixels?: Json | null
          updated_at?: string | null
          user_id?: string | null
          view_count?: number | null
        }
        Update: {
          age_gate?: boolean | null
          age_gate_message?: string | null
          avatar_url?: string | null
          background_color?: string | null
          bio?: string | null
          brand_color?: string | null
          cache_bust?: number | null
          created_at?: string | null
          custom_domain?: string | null
          default_destination?: string | null
          domain_verified?: boolean | null
          domain_verified_at?: string | null
          enable_deeplink_escape?: boolean | null
          geo_rules?: Json | null
          id?: string
          is_published?: boolean | null
          promo_text?: string | null
          shield_config?: Json | null
          shield_mode?: string | null
          show_online_badge?: boolean | null
          slug?: string
          title?: string | null
          tracking_pixels?: Json | null
          updated_at?: string | null
          user_id?: string | null
          view_count?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "link_pages_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      link_visitor_signals: {
        Row: {
          fingerprint: string
          id: string
          last_seen: string | null
          link_page_id: string
          referrer: string | null
          visited_blocks: string[] | null
        }
        Insert: {
          fingerprint: string
          id?: string
          last_seen?: string | null
          link_page_id: string
          referrer?: string | null
          visited_blocks?: string[] | null
        }
        Update: {
          fingerprint?: string
          id?: string
          last_seen?: string | null
          link_page_id?: string
          referrer?: string | null
          visited_blocks?: string[] | null
        }
        Relationships: [
          {
            foreignKeyName: "link_visitor_signals_link_page_id_fkey"
            columns: ["link_page_id"]
            isOneToOne: false
            referencedRelation: "smart_links"
            referencedColumns: ["id"]
          },
        ]
      }
      listening_alerts: {
        Row: {
          alert_type: string
          created_at: string | null
          id: string
          is_active: boolean | null
          keyword: string
          last_checked_at: string | null
          last_triggered_at: string | null
          threshold_value: number | null
          updated_at: string | null
          user_id: string | null
          workspace_id: string
        }
        Insert: {
          alert_type: string
          created_at?: string | null
          id?: string
          is_active?: boolean | null
          keyword: string
          last_checked_at?: string | null
          last_triggered_at?: string | null
          threshold_value?: number | null
          updated_at?: string | null
          user_id?: string | null
          workspace_id: string
        }
        Update: {
          alert_type?: string
          created_at?: string | null
          id?: string
          is_active?: boolean | null
          keyword?: string
          last_checked_at?: string | null
          last_triggered_at?: string | null
          threshold_value?: number | null
          updated_at?: string | null
          user_id?: string | null
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "listening_alerts_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "listening_alerts_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "listening_alerts_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      listening_results: {
        Row: {
          alert_id: string | null
          checked_at: string | null
          id: string
          keyword: string
          result_count: number
          sample_posts: Json | null
          sentiment_breakdown: Json | null
          source: string
          workspace_id: string | null
        }
        Insert: {
          alert_id?: string | null
          checked_at?: string | null
          id?: string
          keyword: string
          result_count?: number
          sample_posts?: Json | null
          sentiment_breakdown?: Json | null
          source?: string
          workspace_id?: string | null
        }
        Update: {
          alert_id?: string | null
          checked_at?: string | null
          id?: string
          keyword?: string
          result_count?: number
          sample_posts?: Json | null
          sentiment_breakdown?: Json | null
          source?: string
          workspace_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "fk_listening_results_workspace"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_listening_results_workspace"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "listening_results_alert_id_fkey"
            columns: ["alert_id"]
            isOneToOne: false
            referencedRelation: "listening_alerts"
            referencedColumns: ["id"]
          },
        ]
      }
      manager_cycles: {
        Row: {
          completed_at: string | null
          created_at: string
          evidence_snapshot: Json
          id: string
          objective: string
          started_at: string
          status: string
          user_id: string
        }
        Insert: {
          completed_at?: string | null
          created_at?: string
          evidence_snapshot?: Json
          id?: string
          objective: string
          started_at?: string
          status?: string
          user_id: string
        }
        Update: {
          completed_at?: string | null
          created_at?: string
          evidence_snapshot?: Json
          id?: string
          objective?: string
          started_at?: string
          status?: string
          user_id?: string
        }
        Relationships: []
      }
      manager_decisions: {
        Row: {
          action_hash: string | null
          actual_outcome: Json | null
          approval_id: string | null
          confidence: number | null
          created_at: string
          decision_type: string
          evidence_refs: Json
          expected_outcome: Json
          id: string
          options_json: Json
          plan_item_id: string | null
          review_status: string
          risk_level: string
          scope: Json
          selected_option: Json
          user_id: string
        }
        Insert: {
          action_hash?: string | null
          actual_outcome?: Json | null
          approval_id?: string | null
          confidence?: number | null
          created_at?: string
          decision_type: string
          evidence_refs?: Json
          expected_outcome?: Json
          id?: string
          options_json?: Json
          plan_item_id?: string | null
          review_status?: string
          risk_level?: string
          scope?: Json
          selected_option?: Json
          user_id: string
        }
        Update: {
          action_hash?: string | null
          actual_outcome?: Json | null
          approval_id?: string | null
          confidence?: number | null
          created_at?: string
          decision_type?: string
          evidence_refs?: Json
          expected_outcome?: Json
          id?: string
          options_json?: Json
          plan_item_id?: string | null
          review_status?: string
          risk_level?: string
          scope?: Json
          selected_option?: Json
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "manager_decisions_plan_item_id_fkey"
            columns: ["plan_item_id"]
            isOneToOne: false
            referencedRelation: "manager_plan_items"
            referencedColumns: ["id"]
          },
        ]
      }
      manager_goals: {
        Row: {
          account_id: string | null
          baseline: number | null
          constraints: Json
          created_at: string
          deadline: string | null
          group_id: string | null
          id: string
          metric: string
          priority: string
          status: string
          target: number | null
          updated_at: string
          user_id: string
          workspace_id: string | null
        }
        Insert: {
          account_id?: string | null
          baseline?: number | null
          constraints?: Json
          created_at?: string
          deadline?: string | null
          group_id?: string | null
          id?: string
          metric: string
          priority?: string
          status?: string
          target?: number | null
          updated_at?: string
          user_id: string
          workspace_id?: string | null
        }
        Update: {
          account_id?: string | null
          baseline?: number | null
          constraints?: Json
          created_at?: string
          deadline?: string | null
          group_id?: string | null
          id?: string
          metric?: string
          priority?: string
          status?: string
          target?: number | null
          updated_at?: string
          user_id?: string
          workspace_id?: string | null
        }
        Relationships: []
      }
      manager_plan_items: {
        Row: {
          actual_outcome: Json | null
          alternatives: Json
          approval_id: string | null
          confidence: number | null
          created_at: string
          expected_outcome: Json
          id: string
          intent_id: string | null
          plan_id: string
          risk_level: string
          selected_action: Json
          status: string
          title: string
          updated_at: string
          user_id: string
        }
        Insert: {
          actual_outcome?: Json | null
          alternatives?: Json
          approval_id?: string | null
          confidence?: number | null
          created_at?: string
          expected_outcome?: Json
          id?: string
          intent_id?: string | null
          plan_id: string
          risk_level?: string
          selected_action?: Json
          status?: string
          title: string
          updated_at?: string
          user_id: string
        }
        Update: {
          actual_outcome?: Json | null
          alternatives?: Json
          approval_id?: string | null
          confidence?: number | null
          created_at?: string
          expected_outcome?: Json
          id?: string
          intent_id?: string | null
          plan_id?: string
          risk_level?: string
          selected_action?: Json
          status?: string
          title?: string
          updated_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "manager_plan_items_intent_id_fkey"
            columns: ["intent_id"]
            isOneToOne: false
            referencedRelation: "agent_action_intents"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "manager_plan_items_plan_id_fkey"
            columns: ["plan_id"]
            isOneToOne: false
            referencedRelation: "manager_plans"
            referencedColumns: ["id"]
          },
        ]
      }
      manager_plans: {
        Row: {
          confidence: number | null
          created_at: string
          cycle_id: string | null
          expected_outcome: Json
          goal_id: string | null
          id: string
          risk_level: string
          status: string
          title: string
          updated_at: string
          user_id: string
        }
        Insert: {
          confidence?: number | null
          created_at?: string
          cycle_id?: string | null
          expected_outcome?: Json
          goal_id?: string | null
          id?: string
          risk_level?: string
          status?: string
          title: string
          updated_at?: string
          user_id: string
        }
        Update: {
          confidence?: number | null
          created_at?: string
          cycle_id?: string | null
          expected_outcome?: Json
          goal_id?: string | null
          id?: string
          risk_level?: string
          status?: string
          title?: string
          updated_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "manager_plans_cycle_id_fkey"
            columns: ["cycle_id"]
            isOneToOne: false
            referencedRelation: "manager_cycles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "manager_plans_goal_id_fkey"
            columns: ["goal_id"]
            isOneToOne: false
            referencedRelation: "manager_goals"
            referencedColumns: ["id"]
          },
        ]
      }
      media: {
        Row: {
          account_id: string | null
          account_platform: string | null
          ai_description: string | null
          ai_tags: Json | null
          created_at: string | null
          duration: number | null
          file_name: string
          file_size: number
          file_type: string
          file_url: string
          folder_id: string | null
          group_id: string | null
          height: number | null
          id: string
          last_used_at: string | null
          mime_type: string | null
          spotlight_eligible: boolean
          storage_path: string | null
          storage_url: string | null
          tags: string[] | null
          thumbnail_url: string | null
          updated_at: string | null
          url: string | null
          user_id: string
          width: number | null
          workspace_id: string | null
        }
        Insert: {
          account_id?: string | null
          account_platform?: string | null
          ai_description?: string | null
          ai_tags?: Json | null
          created_at?: string | null
          duration?: number | null
          file_name: string
          file_size: number
          file_type: string
          file_url: string
          folder_id?: string | null
          group_id?: string | null
          height?: number | null
          id?: string
          last_used_at?: string | null
          mime_type?: string | null
          spotlight_eligible?: boolean
          storage_path?: string | null
          storage_url?: string | null
          tags?: string[] | null
          thumbnail_url?: string | null
          updated_at?: string | null
          url?: string | null
          user_id: string
          width?: number | null
          workspace_id?: string | null
        }
        Update: {
          account_id?: string | null
          account_platform?: string | null
          ai_description?: string | null
          ai_tags?: Json | null
          created_at?: string | null
          duration?: number | null
          file_name?: string
          file_size?: number
          file_type?: string
          file_url?: string
          folder_id?: string | null
          group_id?: string | null
          height?: number | null
          id?: string
          last_used_at?: string | null
          mime_type?: string | null
          spotlight_eligible?: boolean
          storage_path?: string | null
          storage_url?: string | null
          tags?: string[] | null
          thumbnail_url?: string | null
          updated_at?: string | null
          url?: string | null
          user_id?: string
          width?: number | null
          workspace_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "fk_media_group"
            columns: ["group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "media_folder_id_fkey"
            columns: ["folder_id"]
            isOneToOne: false
            referencedRelation: "media_folders"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "media_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "media_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "media_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      media_folders: {
        Row: {
          color: string | null
          created_at: string | null
          id: string
          is_shared: boolean | null
          name: string
          parent_id: string | null
          updated_at: string | null
          user_id: string
          workspace_id: string | null
        }
        Insert: {
          color?: string | null
          created_at?: string | null
          id?: string
          is_shared?: boolean | null
          name: string
          parent_id?: string | null
          updated_at?: string | null
          user_id: string
          workspace_id?: string | null
        }
        Update: {
          color?: string | null
          created_at?: string | null
          id?: string
          is_shared?: boolean | null
          name?: string
          parent_id?: string | null
          updated_at?: string | null
          user_id?: string
          workspace_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "media_folders_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "media_folders_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "media_folders_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      mentions: {
        Row: {
          account_id: string | null
          content: string | null
          created_at: string | null
          id: string
          is_read: boolean | null
          likes: number | null
          media_urls: string[] | null
          mentioned_at: string | null
          mentioned_by_avatar: string | null
          mentioned_by_username: string | null
          permalink: string | null
          replies: number | null
          threads_post_id: string | null
          user_id: string
        }
        Insert: {
          account_id?: string | null
          content?: string | null
          created_at?: string | null
          id?: string
          is_read?: boolean | null
          likes?: number | null
          media_urls?: string[] | null
          mentioned_at?: string | null
          mentioned_by_avatar?: string | null
          mentioned_by_username?: string | null
          permalink?: string | null
          replies?: number | null
          threads_post_id?: string | null
          user_id: string
        }
        Update: {
          account_id?: string | null
          content?: string | null
          created_at?: string | null
          id?: string
          is_read?: boolean | null
          likes?: number | null
          media_urls?: string[] | null
          mentioned_at?: string | null
          mentioned_by_avatar?: string | null
          mentioned_by_username?: string | null
          permalink?: string | null
          replies?: number | null
          threads_post_id?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "fk_mentions_account"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_mentions_user"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      meta_api_usage_snapshots: {
        Row: {
          account_id: string | null
          app_usage: Json | null
          business_usage: Json | null
          captured_at: string
          endpoint_family: string
          id: string
          meta_code: string | null
          meta_subcode: string | null
          platform: string
          request_id: string | null
          retry_after_seconds: number | null
          status: number | null
          tone: string
          usage_percent: number | null
          user_id: string | null
          workspace_id: string | null
        }
        Insert: {
          account_id?: string | null
          app_usage?: Json | null
          business_usage?: Json | null
          captured_at?: string
          endpoint_family: string
          id?: string
          meta_code?: string | null
          meta_subcode?: string | null
          platform: string
          request_id?: string | null
          retry_after_seconds?: number | null
          status?: number | null
          tone?: string
          usage_percent?: number | null
          user_id?: string | null
          workspace_id?: string | null
        }
        Update: {
          account_id?: string | null
          app_usage?: Json | null
          business_usage?: Json | null
          captured_at?: string
          endpoint_family?: string
          id?: string
          meta_code?: string | null
          meta_subcode?: string | null
          platform?: string
          request_id?: string | null
          retry_after_seconds?: number | null
          status?: number | null
          tone?: string
          usage_percent?: number | null
          user_id?: string | null
          workspace_id?: string | null
        }
        Relationships: []
      }
      notifications: {
        Row: {
          created_at: string | null
          data: Json | null
          id: string
          message: string | null
          read: boolean | null
          title: string
          type: string
          user_id: string
        }
        Insert: {
          created_at?: string | null
          data?: Json | null
          id?: string
          message?: string | null
          read?: boolean | null
          title: string
          type: string
          user_id: string
        }
        Update: {
          created_at?: string | null
          data?: Json | null
          id?: string
          message?: string | null
          read?: boolean | null
          title?: string
          type?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "notifications_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      operator_action_audit_logs: {
        Row: {
          account_id: string | null
          action_name: string
          actor_user_id: string
          approval_id: string | null
          body_hash: string | null
          content_hash: string | null
          created_at: string
          error: string | null
          group_id: string | null
          id: string
          idempotency_key: string | null
          intent_id: string | null
          ip_address: string | null
          message: string | null
          metadata: Json
          outcome: string
          payload_hash: string | null
          phase: string
          request_id: string | null
          request_method: string | null
          request_path: string | null
          risk_level: string | null
          scope: Json
          user_agent: string | null
          user_id: string
          workspace_id: string | null
        }
        Insert: {
          account_id?: string | null
          action_name: string
          actor_user_id: string
          approval_id?: string | null
          body_hash?: string | null
          content_hash?: string | null
          created_at?: string
          error?: string | null
          group_id?: string | null
          id?: string
          idempotency_key?: string | null
          intent_id?: string | null
          ip_address?: string | null
          message?: string | null
          metadata?: Json
          outcome: string
          payload_hash?: string | null
          phase: string
          request_id?: string | null
          request_method?: string | null
          request_path?: string | null
          risk_level?: string | null
          scope?: Json
          user_agent?: string | null
          user_id: string
          workspace_id?: string | null
        }
        Update: {
          account_id?: string | null
          action_name?: string
          actor_user_id?: string
          approval_id?: string | null
          body_hash?: string | null
          content_hash?: string | null
          created_at?: string
          error?: string | null
          group_id?: string | null
          id?: string
          idempotency_key?: string | null
          intent_id?: string | null
          ip_address?: string | null
          message?: string | null
          metadata?: Json
          outcome?: string
          payload_hash?: string | null
          phase?: string
          request_id?: string | null
          request_method?: string | null
          request_path?: string | null
          risk_level?: string | null
          scope?: Json
          user_agent?: string | null
          user_id?: string
          workspace_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "operator_action_audit_logs_intent_id_fkey"
            columns: ["intent_id"]
            isOneToOne: false
            referencedRelation: "agent_action_intents"
            referencedColumns: ["id"]
          },
        ]
      }
      operator_kill_switches: {
        Row: {
          action_name: string | null
          created_at: string
          created_by: string | null
          expires_at: string | null
          id: string
          is_active: boolean
          metadata: Json
          min_risk_level: string | null
          reason: string
          scope_id: string | null
          scope_type: string
          updated_at: string
          user_id: string
        }
        Insert: {
          action_name?: string | null
          created_at?: string
          created_by?: string | null
          expires_at?: string | null
          id?: string
          is_active?: boolean
          metadata?: Json
          min_risk_level?: string | null
          reason: string
          scope_id?: string | null
          scope_type: string
          updated_at?: string
          user_id: string
        }
        Update: {
          action_name?: string | null
          created_at?: string
          created_by?: string | null
          expires_at?: string | null
          id?: string
          is_active?: boolean
          metadata?: Json
          min_risk_level?: string | null
          reason?: string
          scope_id?: string | null
          scope_type?: string
          updated_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "operator_kill_switches_created_by_fkey"
            columns: ["created_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "operator_kill_switches_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      operator_tasks: {
        Row: {
          account_id: string | null
          assigned_to: string | null
          created_at: string
          description: string | null
          due_at: string | null
          group_id: string | null
          id: string
          linked_entity_id: string | null
          linked_entity_type: string | null
          priority: string
          recommended_action: Json
          resolution_reason: string | null
          resolved_at: string | null
          sla_at: string | null
          snoozed_until: string | null
          source: string
          source_id: string | null
          status: string
          title: string
          updated_at: string
          user_id: string
          workspace_id: string | null
        }
        Insert: {
          account_id?: string | null
          assigned_to?: string | null
          created_at?: string
          description?: string | null
          due_at?: string | null
          group_id?: string | null
          id?: string
          linked_entity_id?: string | null
          linked_entity_type?: string | null
          priority?: string
          recommended_action?: Json
          resolution_reason?: string | null
          resolved_at?: string | null
          sla_at?: string | null
          snoozed_until?: string | null
          source: string
          source_id?: string | null
          status?: string
          title: string
          updated_at?: string
          user_id: string
          workspace_id?: string | null
        }
        Update: {
          account_id?: string | null
          assigned_to?: string | null
          created_at?: string
          description?: string | null
          due_at?: string | null
          group_id?: string | null
          id?: string
          linked_entity_id?: string | null
          linked_entity_type?: string | null
          priority?: string
          recommended_action?: Json
          resolution_reason?: string | null
          resolved_at?: string | null
          sla_at?: string | null
          snoozed_until?: string | null
          source?: string
          source_id?: string | null
          status?: string
          title?: string
          updated_at?: string
          user_id?: string
          workspace_id?: string | null
        }
        Relationships: []
      }
      overnight_briefs: {
        Row: {
          ai_model: string | null
          ai_provider: string | null
          anomalies_jsonb: Json
          expires_at: string
          generated_at: string
          id: string
          moves_jsonb: Json
          narrative_text: string
          user_id: string
          window_end: string
          window_start: string
          workspace_id: string | null
        }
        Insert: {
          ai_model?: string | null
          ai_provider?: string | null
          anomalies_jsonb?: Json
          expires_at?: string
          generated_at?: string
          id?: string
          moves_jsonb?: Json
          narrative_text: string
          user_id: string
          window_end: string
          window_start: string
          workspace_id?: string | null
        }
        Update: {
          ai_model?: string | null
          ai_provider?: string | null
          anomalies_jsonb?: Json
          expires_at?: string
          generated_at?: string
          id?: string
          moves_jsonb?: Json
          narrative_text?: string
          user_id?: string
          window_end?: string
          window_start?: string
          workspace_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "overnight_briefs_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      portfolio_account_health: {
        Row: {
          account_group_id: string | null
          account_id: string
          computed_at: string
          days_of_content: number | null
          empty_days_next_7d: number | null
          health_tier: string | null
          last_published_at: string | null
          posts_next_7d: number | null
          user_id: string
        }
        Insert: {
          account_group_id?: string | null
          account_id: string
          computed_at?: string
          days_of_content?: number | null
          empty_days_next_7d?: number | null
          health_tier?: string | null
          last_published_at?: string | null
          posts_next_7d?: number | null
          user_id: string
        }
        Update: {
          account_group_id?: string | null
          account_id?: string
          computed_at?: string
          days_of_content?: number | null
          empty_days_next_7d?: number | null
          health_tier?: string | null
          last_published_at?: string | null
          posts_next_7d?: number | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "portfolio_account_health_account_group_id_fkey"
            columns: ["account_group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "portfolio_account_health_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: true
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "portfolio_account_health_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      post_channel_diffs: {
        Row: {
          created_at: string
          divergence_type: string | null
          draft_id: string
          id: string
          master_caption: string
          platform: string
          resolved_at: string | null
          status: string
          user_id: string
          variant_caption: string
        }
        Insert: {
          created_at?: string
          divergence_type?: string | null
          draft_id: string
          id?: string
          master_caption: string
          platform: string
          resolved_at?: string | null
          status?: string
          user_id: string
          variant_caption: string
        }
        Update: {
          created_at?: string
          divergence_type?: string | null
          draft_id?: string
          id?: string
          master_caption?: string
          platform?: string
          resolved_at?: string | null
          status?: string
          user_id?: string
          variant_caption?: string
        }
        Relationships: [
          {
            foreignKeyName: "post_channel_diffs_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      post_metric_history: {
        Row: {
          account_id: string
          engagement_rate: number | null
          hours_since_publish: number | null
          id: string
          likes_count: number | null
          platform: string
          post_id: string
          quotes_count: number | null
          reach: number | null
          replies_count: number | null
          reposts_count: number | null
          saves_count: number | null
          shares_count: number | null
          snapshot_at: string | null
          views_count: number | null
        }
        Insert: {
          account_id: string
          engagement_rate?: number | null
          hours_since_publish?: number | null
          id?: string
          likes_count?: number | null
          platform: string
          post_id: string
          quotes_count?: number | null
          reach?: number | null
          replies_count?: number | null
          reposts_count?: number | null
          saves_count?: number | null
          shares_count?: number | null
          snapshot_at?: string | null
          views_count?: number | null
        }
        Update: {
          account_id?: string
          engagement_rate?: number | null
          hours_since_publish?: number | null
          id?: string
          likes_count?: number | null
          platform?: string
          post_id?: string
          quotes_count?: number | null
          reach?: number | null
          replies_count?: number | null
          reposts_count?: number | null
          saves_count?: number | null
          shares_count?: number | null
          snapshot_at?: string | null
          views_count?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "fk_post_metric_history_account"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "post_metric_history_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "post_metric_history_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
        ]
      }
      post_originality_signals: {
        Row: {
          account_id: string | null
          captured_at: string
          id: string
          instagram_account_id: string | null
          media_url_hashes: string[]
          perceptual_hashes: string[]
          platform: string
          post_id: string
          provenance: Json
          text_hash: string | null
          updated_at: string
          user_id: string
          watermark_applied: boolean
        }
        Insert: {
          account_id?: string | null
          captured_at?: string
          id?: string
          instagram_account_id?: string | null
          media_url_hashes?: string[]
          perceptual_hashes?: string[]
          platform: string
          post_id: string
          provenance?: Json
          text_hash?: string | null
          updated_at?: string
          user_id: string
          watermark_applied?: boolean
        }
        Update: {
          account_id?: string | null
          captured_at?: string
          id?: string
          instagram_account_id?: string | null
          media_url_hashes?: string[]
          perceptual_hashes?: string[]
          platform?: string
          post_id?: string
          provenance?: Json
          text_hash?: string | null
          updated_at?: string
          user_id?: string
          watermark_applied?: boolean
        }
        Relationships: [
          {
            foreignKeyName: "post_originality_signals_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "post_originality_signals_instagram_account_id_fkey"
            columns: ["instagram_account_id"]
            isOneToOne: false
            referencedRelation: "instagram_accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "post_originality_signals_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: true
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "post_originality_signals_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: true
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "post_originality_signals_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      post_reflections: {
        Row: {
          ai_analysis: string | null
          created_at: string
          id: string
          met_expectations: boolean
          post_id: string
          user_id: string
        }
        Insert: {
          ai_analysis?: string | null
          created_at?: string
          id?: string
          met_expectations: boolean
          post_id: string
          user_id: string
        }
        Update: {
          ai_analysis?: string | null
          created_at?: string
          id?: string
          met_expectations?: boolean
          post_id?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "post_reflections_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      post_replies: {
        Row: {
          avatar_url: string | null
          content: string
          created_at: string | null
          display_name: string | null
          id: string
          is_read: boolean | null
          likes_count: number | null
          post_id: string
          replies_count: number | null
          synced_at: string | null
          threads_reply_id: string
          threads_user_id: string
          username: string
        }
        Insert: {
          avatar_url?: string | null
          content: string
          created_at?: string | null
          display_name?: string | null
          id?: string
          is_read?: boolean | null
          likes_count?: number | null
          post_id: string
          replies_count?: number | null
          synced_at?: string | null
          threads_reply_id: string
          threads_user_id: string
          username: string
        }
        Update: {
          avatar_url?: string | null
          content?: string
          created_at?: string | null
          display_name?: string | null
          id?: string
          is_read?: boolean | null
          likes_count?: number | null
          post_id?: string
          replies_count?: number | null
          synced_at?: string | null
          threads_reply_id?: string
          threads_user_id?: string
          username?: string
        }
        Relationships: [
          {
            foreignKeyName: "fk_post_replies_post"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_post_replies_post"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
        ]
      }
      post_success_signals: {
        Row: {
          created_at: string | null
          id: string
          post_id: string
          signal: string
          user_id: string
        }
        Insert: {
          created_at?: string | null
          id?: string
          post_id: string
          signal: string
          user_id: string
        }
        Update: {
          created_at?: string | null
          id?: string
          post_id?: string
          signal?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "post_success_signals_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      post_tags: {
        Row: {
          created_at: string | null
          id: string
          post_id: string
          tag_color: string | null
          tag_name: string
          user_id: string
        }
        Insert: {
          created_at?: string | null
          id?: string
          post_id: string
          tag_color?: string | null
          tag_name: string
          user_id: string
        }
        Update: {
          created_at?: string | null
          id?: string
          post_id?: string
          tag_color?: string | null
          tag_name?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "post_tags_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "post_tags_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "post_tags_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      post_templates: {
        Row: {
          account_group_id: string | null
          category: string | null
          created_at: string | null
          hashtags: string[] | null
          id: string
          is_shared: boolean | null
          last_used_at: string | null
          media_urls: string[] | null
          metadata: Json
          name: string
          platform: string | null
          poll_options: Json | null
          text_template: string
          times_used: number | null
          updated_at: string | null
          user_id: string
          workspace_id: string | null
        }
        Insert: {
          account_group_id?: string | null
          category?: string | null
          created_at?: string | null
          hashtags?: string[] | null
          id?: string
          is_shared?: boolean | null
          last_used_at?: string | null
          media_urls?: string[] | null
          metadata?: Json
          name: string
          platform?: string | null
          poll_options?: Json | null
          text_template: string
          times_used?: number | null
          updated_at?: string | null
          user_id: string
          workspace_id?: string | null
        }
        Update: {
          account_group_id?: string | null
          category?: string | null
          created_at?: string | null
          hashtags?: string[] | null
          id?: string
          is_shared?: boolean | null
          last_used_at?: string | null
          media_urls?: string[] | null
          metadata?: Json
          name?: string
          platform?: string | null
          poll_options?: Json | null
          text_template?: string
          times_used?: number | null
          updated_at?: string | null
          user_id?: string
          workspace_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "post_templates_account_group_id_fkey"
            columns: ["account_group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "post_templates_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "post_templates_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "post_templates_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      post_variants: {
        Row: {
          content: string
          created_at: string
          draft_id: string | null
          id: string
          live_engagement_rate: number | null
          live_views_count: number | null
          post_id: string | null
          predicted_confidence: number | null
          predicted_score: number | null
          promoted_at: string | null
          reasoning_json: Json | null
          user_id: string
          variant_label: string
          variant_type: string | null
        }
        Insert: {
          content: string
          created_at?: string
          draft_id?: string | null
          id?: string
          live_engagement_rate?: number | null
          live_views_count?: number | null
          post_id?: string | null
          predicted_confidence?: number | null
          predicted_score?: number | null
          promoted_at?: string | null
          reasoning_json?: Json | null
          user_id: string
          variant_label: string
          variant_type?: string | null
        }
        Update: {
          content?: string
          created_at?: string
          draft_id?: string | null
          id?: string
          live_engagement_rate?: number | null
          live_views_count?: number | null
          post_id?: string | null
          predicted_confidence?: number | null
          predicted_score?: number | null
          promoted_at?: string | null
          reasoning_json?: Json | null
          user_id?: string
          variant_label?: string
          variant_type?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "post_variants_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "post_variants_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "post_variants_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      posts: {
        Row: {
          account_id: string | null
          active_arc_id: string | null
          alt_text: string | null
          approval_notes: string | null
          approval_status: string | null
          approved_at: string | null
          approved_by: string | null
          arc_beat_id: string | null
          audio_name: string | null
          auto_post_queue_id: string | null
          avg_reply_response_mins: number | null
          campaign_factory_asset_id: string | null
          campaign_factory_caption_hash: string | null
          campaign_factory_concept_id: string | null
          campaign_factory_content_fingerprint: string | null
          campaign_factory_distribution_plan_id: string | null
          campaign_factory_parent_asset_id: string | null
          campaign_factory_post_key: string | null
          campaign_factory_variant_family_id: string | null
          campaign_factory_variant_id: string | null
          caption_copied_at: string | null
          collaborators: string[] | null
          content: string
          content_category: string | null
          content_category_confidence: number | null
          content_fingerprint: string | null
          content_length_bucket: string | null
          content_surface: string | null
          cover_url: string | null
          created_at: string | null
          cross_fb: boolean
          cross_post_group_id: string | null
          dna_decision: string | null
          dna_fit_score: number | null
          dna_id: string | null
          dna_reasons: Json | null
          dna_version: number | null
          draft_folder_id: string | null
          duplicate_window_hours: number | null
          emotional_frame: string | null
          engagement_rate: number | null
          error_message: string | null
          evergreen_interval_days: number | null
          evergreen_min_engagement: number | null
          first_comment: string | null
          format_type: string | null
          generation_id: string | null
          genericness_score: number | null
          graduation: string | null
          handoff_opened_at: string | null
          handoff_status: string | null
          hashtags: string[] | null
          hook_class: string | null
          hook_class_confidence: number | null
          hook_classified_at: string | null
          hook_type: string | null
          id: string
          ig_clips_replays: number | null
          ig_clips_replays_count: number | null
          ig_comment_count: number | null
          ig_container_created_at: string | null
          ig_container_id: string | null
          ig_container_status: string | null
          ig_crossposted_views: number | null
          ig_facebook_views: number | null
          ig_follows_count: number | null
          ig_impressions: number | null
          ig_media_type: string | null
          ig_plays: number | null
          ig_post_profile_activity: Json | null
          ig_profile_visits: number | null
          ig_publish_attempts: number | null
          ig_reach: number | null
          ig_reels_aggregated_all_plays_count: number | null
          ig_reels_avg_watch_time: number | null
          ig_reels_plays: number | null
          ig_reels_video_view_total_time: number | null
          ig_replays: number | null
          ig_reposts: number | null
          ig_saved: number | null
          ig_shares: number | null
          ig_skip_rate: number | null
          ig_story_exits: number | null
          ig_story_expires_at: string | null
          ig_story_replies: number | null
          ig_story_taps_back: number | null
          ig_story_taps_forward: number | null
          ig_video_views: number | null
          ig_views: number | null
          instagram_account_id: string | null
          instagram_post_id: string | null
          is_carousel: boolean | null
          is_evergreen: boolean | null
          is_quote: boolean | null
          last_recycled_at: string | null
          likes_count: number | null
          link_url: string | null
          location_id: string | null
          location_name: string | null
          manual_publish_confirmed_at: string | null
          max_recycles: number | null
          media_audio_type: string | null
          media_downloaded_at: string | null
          media_fingerprint: string | null
          media_ids: string[] | null
          media_shared_at: string | null
          media_style: string | null
          media_type: string | null
          media_urls: string[] | null
          metadata: Json | null
          metrics_archived: boolean | null
          model_provider: string | null
          mood_fit_score: number | null
          normalized_text_hash: string | null
          notification_sent_at: string | null
          permalink: string | null
          persona: string | null
          platform: string | null
          platform_draft_validated: boolean
          poll_options: Json | null
          posting_hour: number | null
          predicted_viral_score: number | null
          product_tags: Json | null
          prompt_version: string | null
          provenance_error: string | null
          provenance_status: string | null
          publish_fingerprint: string | null
          publish_mode: string
          published_at: string | null
          qstash_dispatch_status: string | null
          qstash_dispatched_at: string | null
          qstash_failure_reason: string | null
          qstash_message_id: string | null
          quote_chain_depth: number | null
          quoted_by_count: number | null
          quoted_post_id: string | null
          quotes_count: number | null
          recycle_count: number | null
          recycled_from_id: string | null
          reel_cover: Json | null
          rejected_at: string | null
          rejected_by: string | null
          rejection_notes: string | null
          reminder_count: number
          replies_count: number | null
          reply_chain: Json | null
          reply_chain_synced_at: string | null
          reply_depth: number | null
          reply_mechanism: string | null
          reply_response_count: number | null
          reply_to_id: string | null
          reposts_count: number | null
          retry_count: number | null
          scheduled_for: string | null
          share_to_feed: boolean
          shares_count: number | null
          sibling_collision_score: number | null
          source: string | null
          source_id: string | null
          source_pattern_id: string | null
          status: string | null
          story_expires_at: string | null
          strategy_bucket: string
          strategy_recommendation_id: string | null
          template_id: string | null
          text_spoilers: Json | null
          thread_chain: boolean
          threads_post_id: string | null
          topic_fit_score: number | null
          topic_label: string | null
          topic_tag: string | null
          uniqueness_score: number | null
          updated_at: string | null
          user_id: string
          user_tags: Json | null
          views_count: number | null
          viral_score: number | null
          voice_fit_score: number | null
        }
        Insert: {
          account_id?: string | null
          active_arc_id?: string | null
          alt_text?: string | null
          approval_notes?: string | null
          approval_status?: string | null
          approved_at?: string | null
          approved_by?: string | null
          arc_beat_id?: string | null
          audio_name?: string | null
          auto_post_queue_id?: string | null
          avg_reply_response_mins?: number | null
          campaign_factory_asset_id?: string | null
          campaign_factory_caption_hash?: string | null
          campaign_factory_concept_id?: string | null
          campaign_factory_content_fingerprint?: string | null
          campaign_factory_distribution_plan_id?: string | null
          campaign_factory_parent_asset_id?: string | null
          campaign_factory_post_key?: string | null
          campaign_factory_variant_family_id?: string | null
          campaign_factory_variant_id?: string | null
          caption_copied_at?: string | null
          collaborators?: string[] | null
          content: string
          content_category?: string | null
          content_category_confidence?: number | null
          content_fingerprint?: string | null
          content_length_bucket?: string | null
          content_surface?: string | null
          cover_url?: string | null
          created_at?: string | null
          cross_fb?: boolean
          cross_post_group_id?: string | null
          dna_decision?: string | null
          dna_fit_score?: number | null
          dna_id?: string | null
          dna_reasons?: Json | null
          dna_version?: number | null
          draft_folder_id?: string | null
          duplicate_window_hours?: number | null
          emotional_frame?: string | null
          engagement_rate?: number | null
          error_message?: string | null
          evergreen_interval_days?: number | null
          evergreen_min_engagement?: number | null
          first_comment?: string | null
          format_type?: string | null
          generation_id?: string | null
          genericness_score?: number | null
          graduation?: string | null
          handoff_opened_at?: string | null
          handoff_status?: string | null
          hashtags?: string[] | null
          hook_class?: string | null
          hook_class_confidence?: number | null
          hook_classified_at?: string | null
          hook_type?: string | null
          id?: string
          ig_clips_replays?: number | null
          ig_clips_replays_count?: number | null
          ig_comment_count?: number | null
          ig_container_created_at?: string | null
          ig_container_id?: string | null
          ig_container_status?: string | null
          ig_crossposted_views?: number | null
          ig_facebook_views?: number | null
          ig_follows_count?: number | null
          ig_impressions?: number | null
          ig_media_type?: string | null
          ig_plays?: number | null
          ig_post_profile_activity?: Json | null
          ig_profile_visits?: number | null
          ig_publish_attempts?: number | null
          ig_reach?: number | null
          ig_reels_aggregated_all_plays_count?: number | null
          ig_reels_avg_watch_time?: number | null
          ig_reels_plays?: number | null
          ig_reels_video_view_total_time?: number | null
          ig_replays?: number | null
          ig_reposts?: number | null
          ig_saved?: number | null
          ig_shares?: number | null
          ig_skip_rate?: number | null
          ig_story_exits?: number | null
          ig_story_expires_at?: string | null
          ig_story_replies?: number | null
          ig_story_taps_back?: number | null
          ig_story_taps_forward?: number | null
          ig_video_views?: number | null
          ig_views?: number | null
          instagram_account_id?: string | null
          instagram_post_id?: string | null
          is_carousel?: boolean | null
          is_evergreen?: boolean | null
          is_quote?: boolean | null
          last_recycled_at?: string | null
          likes_count?: number | null
          link_url?: string | null
          location_id?: string | null
          location_name?: string | null
          manual_publish_confirmed_at?: string | null
          max_recycles?: number | null
          media_audio_type?: string | null
          media_downloaded_at?: string | null
          media_fingerprint?: string | null
          media_ids?: string[] | null
          media_shared_at?: string | null
          media_style?: string | null
          media_type?: string | null
          media_urls?: string[] | null
          metadata?: Json | null
          metrics_archived?: boolean | null
          model_provider?: string | null
          mood_fit_score?: number | null
          normalized_text_hash?: string | null
          notification_sent_at?: string | null
          permalink?: string | null
          persona?: string | null
          platform?: string | null
          platform_draft_validated?: boolean
          poll_options?: Json | null
          posting_hour?: number | null
          predicted_viral_score?: number | null
          product_tags?: Json | null
          prompt_version?: string | null
          provenance_error?: string | null
          provenance_status?: string | null
          publish_fingerprint?: string | null
          publish_mode?: string
          published_at?: string | null
          qstash_dispatch_status?: string | null
          qstash_dispatched_at?: string | null
          qstash_failure_reason?: string | null
          qstash_message_id?: string | null
          quote_chain_depth?: number | null
          quoted_by_count?: number | null
          quoted_post_id?: string | null
          quotes_count?: number | null
          recycle_count?: number | null
          recycled_from_id?: string | null
          reel_cover?: Json | null
          rejected_at?: string | null
          rejected_by?: string | null
          rejection_notes?: string | null
          reminder_count?: number
          replies_count?: number | null
          reply_chain?: Json | null
          reply_chain_synced_at?: string | null
          reply_depth?: number | null
          reply_mechanism?: string | null
          reply_response_count?: number | null
          reply_to_id?: string | null
          reposts_count?: number | null
          retry_count?: number | null
          scheduled_for?: string | null
          share_to_feed?: boolean
          shares_count?: number | null
          sibling_collision_score?: number | null
          source?: string | null
          source_id?: string | null
          source_pattern_id?: string | null
          status?: string | null
          story_expires_at?: string | null
          strategy_bucket?: string
          strategy_recommendation_id?: string | null
          template_id?: string | null
          text_spoilers?: Json | null
          thread_chain?: boolean
          threads_post_id?: string | null
          topic_fit_score?: number | null
          topic_label?: string | null
          topic_tag?: string | null
          uniqueness_score?: number | null
          updated_at?: string | null
          user_id: string
          user_tags?: Json | null
          views_count?: number | null
          viral_score?: number | null
          voice_fit_score?: number | null
        }
        Update: {
          account_id?: string | null
          active_arc_id?: string | null
          alt_text?: string | null
          approval_notes?: string | null
          approval_status?: string | null
          approved_at?: string | null
          approved_by?: string | null
          arc_beat_id?: string | null
          audio_name?: string | null
          auto_post_queue_id?: string | null
          avg_reply_response_mins?: number | null
          campaign_factory_asset_id?: string | null
          campaign_factory_caption_hash?: string | null
          campaign_factory_concept_id?: string | null
          campaign_factory_content_fingerprint?: string | null
          campaign_factory_distribution_plan_id?: string | null
          campaign_factory_parent_asset_id?: string | null
          campaign_factory_post_key?: string | null
          campaign_factory_variant_family_id?: string | null
          campaign_factory_variant_id?: string | null
          caption_copied_at?: string | null
          collaborators?: string[] | null
          content?: string
          content_category?: string | null
          content_category_confidence?: number | null
          content_fingerprint?: string | null
          content_length_bucket?: string | null
          content_surface?: string | null
          cover_url?: string | null
          created_at?: string | null
          cross_fb?: boolean
          cross_post_group_id?: string | null
          dna_decision?: string | null
          dna_fit_score?: number | null
          dna_id?: string | null
          dna_reasons?: Json | null
          dna_version?: number | null
          draft_folder_id?: string | null
          duplicate_window_hours?: number | null
          emotional_frame?: string | null
          engagement_rate?: number | null
          error_message?: string | null
          evergreen_interval_days?: number | null
          evergreen_min_engagement?: number | null
          first_comment?: string | null
          format_type?: string | null
          generation_id?: string | null
          genericness_score?: number | null
          graduation?: string | null
          handoff_opened_at?: string | null
          handoff_status?: string | null
          hashtags?: string[] | null
          hook_class?: string | null
          hook_class_confidence?: number | null
          hook_classified_at?: string | null
          hook_type?: string | null
          id?: string
          ig_clips_replays?: number | null
          ig_clips_replays_count?: number | null
          ig_comment_count?: number | null
          ig_container_created_at?: string | null
          ig_container_id?: string | null
          ig_container_status?: string | null
          ig_crossposted_views?: number | null
          ig_facebook_views?: number | null
          ig_follows_count?: number | null
          ig_impressions?: number | null
          ig_media_type?: string | null
          ig_plays?: number | null
          ig_post_profile_activity?: Json | null
          ig_profile_visits?: number | null
          ig_publish_attempts?: number | null
          ig_reach?: number | null
          ig_reels_aggregated_all_plays_count?: number | null
          ig_reels_avg_watch_time?: number | null
          ig_reels_plays?: number | null
          ig_reels_video_view_total_time?: number | null
          ig_replays?: number | null
          ig_reposts?: number | null
          ig_saved?: number | null
          ig_shares?: number | null
          ig_skip_rate?: number | null
          ig_story_exits?: number | null
          ig_story_expires_at?: string | null
          ig_story_replies?: number | null
          ig_story_taps_back?: number | null
          ig_story_taps_forward?: number | null
          ig_video_views?: number | null
          ig_views?: number | null
          instagram_account_id?: string | null
          instagram_post_id?: string | null
          is_carousel?: boolean | null
          is_evergreen?: boolean | null
          is_quote?: boolean | null
          last_recycled_at?: string | null
          likes_count?: number | null
          link_url?: string | null
          location_id?: string | null
          location_name?: string | null
          manual_publish_confirmed_at?: string | null
          max_recycles?: number | null
          media_audio_type?: string | null
          media_downloaded_at?: string | null
          media_fingerprint?: string | null
          media_ids?: string[] | null
          media_shared_at?: string | null
          media_style?: string | null
          media_type?: string | null
          media_urls?: string[] | null
          metadata?: Json | null
          metrics_archived?: boolean | null
          model_provider?: string | null
          mood_fit_score?: number | null
          normalized_text_hash?: string | null
          notification_sent_at?: string | null
          permalink?: string | null
          persona?: string | null
          platform?: string | null
          platform_draft_validated?: boolean
          poll_options?: Json | null
          posting_hour?: number | null
          predicted_viral_score?: number | null
          product_tags?: Json | null
          prompt_version?: string | null
          provenance_error?: string | null
          provenance_status?: string | null
          publish_fingerprint?: string | null
          publish_mode?: string
          published_at?: string | null
          qstash_dispatch_status?: string | null
          qstash_dispatched_at?: string | null
          qstash_failure_reason?: string | null
          qstash_message_id?: string | null
          quote_chain_depth?: number | null
          quoted_by_count?: number | null
          quoted_post_id?: string | null
          quotes_count?: number | null
          recycle_count?: number | null
          recycled_from_id?: string | null
          reel_cover?: Json | null
          rejected_at?: string | null
          rejected_by?: string | null
          rejection_notes?: string | null
          reminder_count?: number
          replies_count?: number | null
          reply_chain?: Json | null
          reply_chain_synced_at?: string | null
          reply_depth?: number | null
          reply_mechanism?: string | null
          reply_response_count?: number | null
          reply_to_id?: string | null
          reposts_count?: number | null
          retry_count?: number | null
          scheduled_for?: string | null
          share_to_feed?: boolean
          shares_count?: number | null
          sibling_collision_score?: number | null
          source?: string | null
          source_id?: string | null
          source_pattern_id?: string | null
          status?: string | null
          story_expires_at?: string | null
          strategy_bucket?: string
          strategy_recommendation_id?: string | null
          template_id?: string | null
          text_spoilers?: Json | null
          thread_chain?: boolean
          threads_post_id?: string | null
          topic_fit_score?: number | null
          topic_label?: string | null
          topic_tag?: string | null
          uniqueness_score?: number | null
          updated_at?: string | null
          user_id?: string
          user_tags?: Json | null
          views_count?: number | null
          viral_score?: number | null
          voice_fit_score?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "posts_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_active_arc_id_fkey"
            columns: ["active_arc_id"]
            isOneToOne: false
            referencedRelation: "account_content_arcs"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_approved_by_fkey"
            columns: ["approved_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_arc_beat_id_fkey"
            columns: ["arc_beat_id"]
            isOneToOne: false
            referencedRelation: "arc_beats"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_dna_id_fkey"
            columns: ["dna_id"]
            isOneToOne: false
            referencedRelation: "account_dna"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_draft_folder_id_fkey"
            columns: ["draft_folder_id"]
            isOneToOne: false
            referencedRelation: "draft_folders"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_instagram_account_id_fkey"
            columns: ["instagram_account_id"]
            isOneToOne: false
            referencedRelation: "instagram_accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_recycled_from_id_fkey"
            columns: ["recycled_from_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_recycled_from_id_fkey"
            columns: ["recycled_from_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_rejected_by_fkey"
            columns: ["rejected_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_reply_to_id_fkey"
            columns: ["reply_to_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_reply_to_id_fkey"
            columns: ["reply_to_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_strategy_recommendation_id_fkey"
            columns: ["strategy_recommendation_id"]
            isOneToOne: false
            referencedRelation: "autoposter_strategy_recommendations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      profiles: {
        Row: {
          agent_paused: boolean
          avatar_url: string | null
          beta_discount_code: string | null
          beta_feedback: Json | null
          beta_invite_code: string | null
          beta_joined_at: string | null
          billing_interval: string | null
          created_at: string | null
          creator_archetype: string | null
          display_name: string | null
          email: string | null
          extra_accounts: number | null
          extra_team_members: number | null
          has_used_trial: boolean | null
          id: string
          is_beta_user: boolean | null
          onboarding_completed: boolean | null
          power_user_score: number | null
          referral_reward_months_earned: number | null
          referral_reward_months_used: number | null
          referral_trial_ends_at: string | null
          referred_by: string | null
          stripe_customer_id: string | null
          stripe_subscription_id: string | null
          subscription_status: string | null
          subscription_tier: string | null
          timezone: string | null
          trial_ends_at: string | null
          trial_started_at: string | null
          trial_used: boolean | null
          updated_at: string | null
        }
        Insert: {
          agent_paused?: boolean
          avatar_url?: string | null
          beta_discount_code?: string | null
          beta_feedback?: Json | null
          beta_invite_code?: string | null
          beta_joined_at?: string | null
          billing_interval?: string | null
          created_at?: string | null
          creator_archetype?: string | null
          display_name?: string | null
          email?: string | null
          extra_accounts?: number | null
          extra_team_members?: number | null
          has_used_trial?: boolean | null
          id: string
          is_beta_user?: boolean | null
          onboarding_completed?: boolean | null
          power_user_score?: number | null
          referral_reward_months_earned?: number | null
          referral_reward_months_used?: number | null
          referral_trial_ends_at?: string | null
          referred_by?: string | null
          stripe_customer_id?: string | null
          stripe_subscription_id?: string | null
          subscription_status?: string | null
          subscription_tier?: string | null
          timezone?: string | null
          trial_ends_at?: string | null
          trial_started_at?: string | null
          trial_used?: boolean | null
          updated_at?: string | null
        }
        Update: {
          agent_paused?: boolean
          avatar_url?: string | null
          beta_discount_code?: string | null
          beta_feedback?: Json | null
          beta_invite_code?: string | null
          beta_joined_at?: string | null
          billing_interval?: string | null
          created_at?: string | null
          creator_archetype?: string | null
          display_name?: string | null
          email?: string | null
          extra_accounts?: number | null
          extra_team_members?: number | null
          has_used_trial?: boolean | null
          id?: string
          is_beta_user?: boolean | null
          onboarding_completed?: boolean | null
          power_user_score?: number | null
          referral_reward_months_earned?: number | null
          referral_reward_months_used?: number | null
          referral_trial_ends_at?: string | null
          referred_by?: string | null
          stripe_customer_id?: string | null
          stripe_subscription_id?: string | null
          subscription_status?: string | null
          subscription_tier?: string | null
          timezone?: string | null
          trial_ends_at?: string | null
          trial_started_at?: string | null
          trial_used?: boolean | null
          updated_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "profiles_referred_by_fkey"
            columns: ["referred_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      proof_runs: {
        Row: {
          asset_id: string
          blocking_reason: string | null
          caption_report_generated_at: string | null
          completed_at: string | null
          distribution_plan_id: string | null
          failed_stage: string | null
          id: string
          metadata: Json
          metrics_eligible: boolean
          metrics_imported_at: string | null
          root_cause: string | null
          started_at: string
          status: string
          threadsdash_draft_id: string | null
          threadsdash_post_id: string | null
          user_id: string
        }
        Insert: {
          asset_id: string
          blocking_reason?: string | null
          caption_report_generated_at?: string | null
          completed_at?: string | null
          distribution_plan_id?: string | null
          failed_stage?: string | null
          id?: string
          metadata?: Json
          metrics_eligible?: boolean
          metrics_imported_at?: string | null
          root_cause?: string | null
          started_at?: string
          status?: string
          threadsdash_draft_id?: string | null
          threadsdash_post_id?: string | null
          user_id: string
        }
        Update: {
          asset_id?: string
          blocking_reason?: string | null
          caption_report_generated_at?: string | null
          completed_at?: string | null
          distribution_plan_id?: string | null
          failed_stage?: string | null
          id?: string
          metadata?: Json
          metrics_eligible?: boolean
          metrics_imported_at?: string | null
          root_cause?: string | null
          started_at?: string
          status?: string
          threadsdash_draft_id?: string | null
          threadsdash_post_id?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "proof_runs_threadsdash_draft_id_fkey"
            columns: ["threadsdash_draft_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "proof_runs_threadsdash_draft_id_fkey"
            columns: ["threadsdash_draft_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "proof_runs_threadsdash_post_id_fkey"
            columns: ["threadsdash_post_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "proof_runs_threadsdash_post_id_fkey"
            columns: ["threadsdash_post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "proof_runs_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      publish_attempts: {
        Row: {
          account_id: string | null
          attempt_number: number
          claim_token: string | null
          completed_at: string | null
          created_at: string
          error_code: string | null
          error_message: string | null
          group_id: string | null
          id: string
          meta_container_id: string | null
          metadata: Json
          queue_item_id: string
          result: string
          started_at: string
          threads_post_id: string | null
          user_id: string | null
          workspace_id: string | null
        }
        Insert: {
          account_id?: string | null
          attempt_number?: number
          claim_token?: string | null
          completed_at?: string | null
          created_at?: string
          error_code?: string | null
          error_message?: string | null
          group_id?: string | null
          id?: string
          meta_container_id?: string | null
          metadata?: Json
          queue_item_id: string
          result?: string
          started_at?: string
          threads_post_id?: string | null
          user_id?: string | null
          workspace_id?: string | null
        }
        Update: {
          account_id?: string | null
          attempt_number?: number
          claim_token?: string | null
          completed_at?: string | null
          created_at?: string
          error_code?: string | null
          error_message?: string | null
          group_id?: string | null
          id?: string
          meta_container_id?: string | null
          metadata?: Json
          queue_item_id?: string
          result?: string
          started_at?: string
          threads_post_id?: string | null
          user_id?: string | null
          workspace_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "publish_attempts_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "publish_attempts_group_id_fkey"
            columns: ["group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "publish_attempts_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "publish_attempts_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "publish_attempts_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      publish_jobs: {
        Row: {
          account_id: string | null
          attempt_count: number
          completed_at: string | null
          created_at: string
          error_code: string | null
          error_message: string | null
          id: string
          idempotency_key: string | null
          payload: Json
          platform: string
          post_id: string | null
          qstash_message_id: string | null
          request_id: string | null
          result: Json | null
          stage: string
          started_at: string | null
          status: string
          updated_at: string
          user_id: string
          workspace_id: string | null
        }
        Insert: {
          account_id?: string | null
          attempt_count?: number
          completed_at?: string | null
          created_at?: string
          error_code?: string | null
          error_message?: string | null
          id?: string
          idempotency_key?: string | null
          payload: Json
          platform: string
          post_id?: string | null
          qstash_message_id?: string | null
          request_id?: string | null
          result?: Json | null
          stage?: string
          started_at?: string | null
          status?: string
          updated_at?: string
          user_id: string
          workspace_id?: string | null
        }
        Update: {
          account_id?: string | null
          attempt_count?: number
          completed_at?: string | null
          created_at?: string
          error_code?: string | null
          error_message?: string | null
          id?: string
          idempotency_key?: string | null
          payload?: Json
          platform?: string
          post_id?: string | null
          qstash_message_id?: string | null
          request_id?: string | null
          result?: Json | null
          stage?: string
          started_at?: string | null
          status?: string
          updated_at?: string
          user_id?: string
          workspace_id?: string | null
        }
        Relationships: []
      }
      publish_locks: {
        Row: {
          account_id: string
          created_at: string
          expires_at: string
          owner_token: string
          updated_at: string
        }
        Insert: {
          account_id: string
          created_at?: string
          expires_at: string
          owner_token: string
          updated_at?: string
        }
        Update: {
          account_id?: string
          created_at?: string
          expires_at?: string
          owner_token?: string
          updated_at?: string
        }
        Relationships: []
      }
      push_subscriptions: {
        Row: {
          auth: string
          created_at: string | null
          endpoint: string
          id: string
          last_used_at: string | null
          p256dh: string
          user_agent: string | null
          user_id: string
        }
        Insert: {
          auth: string
          created_at?: string | null
          endpoint: string
          id?: string
          last_used_at?: string | null
          p256dh: string
          user_agent?: string | null
          user_id: string
        }
        Update: {
          auth?: string
          created_at?: string | null
          endpoint?: string
          id?: string
          last_used_at?: string | null
          p256dh?: string
          user_agent?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "push_subscriptions_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      quarantined_assets: {
        Row: {
          asset_id: string
          blocked_stage: string | null
          can_retry: boolean
          created_at: string
          excluded_from_metrics: boolean
          id: string
          metadata: Json
          reason: string
          retry_requires_new_render: boolean
          root_cause: string | null
          user_id: string
        }
        Insert: {
          asset_id: string
          blocked_stage?: string | null
          can_retry?: boolean
          created_at?: string
          excluded_from_metrics?: boolean
          id?: string
          metadata?: Json
          reason: string
          retry_requires_new_render?: boolean
          root_cause?: string | null
          user_id: string
        }
        Update: {
          asset_id?: string
          blocked_stage?: string | null
          can_retry?: boolean
          created_at?: string
          excluded_from_metrics?: boolean
          id?: string
          metadata?: Json
          reason?: string
          retry_requires_new_render?: boolean
          root_cause?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "quarantined_assets_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      queue_fill_log: {
        Row: {
          account_summary: Json | null
          completed_at: string
          duration_ms: number | null
          early_exit_reason: string | null
          group_id: string | null
          id: string
          posts_generated: number
          posts_inserted: number
          posts_rejected: number
          rejection_summary: Json | null
          skip_details: Json | null
          started_at: string
          strategy_summary: Json
          workspace_id: string
        }
        Insert: {
          account_summary?: Json | null
          completed_at?: string
          duration_ms?: number | null
          early_exit_reason?: string | null
          group_id?: string | null
          id?: string
          posts_generated?: number
          posts_inserted?: number
          posts_rejected?: number
          rejection_summary?: Json | null
          skip_details?: Json | null
          started_at: string
          strategy_summary?: Json
          workspace_id: string
        }
        Update: {
          account_summary?: Json | null
          completed_at?: string
          duration_ms?: number | null
          early_exit_reason?: string | null
          group_id?: string | null
          id?: string
          posts_generated?: number
          posts_inserted?: number
          posts_rejected?: number
          rejection_summary?: Json | null
          skip_details?: Json | null
          started_at?: string
          strategy_summary?: Json
          workspace_id?: string
        }
        Relationships: []
      }
      quick_wins: {
        Row: {
          account_id: string
          category: string
          completed_at: string | null
          created_at: string | null
          description: string | null
          id: string
          measured_impact: number | null
          priority: number
          status: string
          title: string
          updated_at: string | null
          user_id: string
        }
        Insert: {
          account_id: string
          category?: string
          completed_at?: string | null
          created_at?: string | null
          description?: string | null
          id?: string
          measured_impact?: number | null
          priority?: number
          status?: string
          title: string
          updated_at?: string | null
          user_id: string
        }
        Update: {
          account_id?: string
          category?: string
          completed_at?: string | null
          created_at?: string | null
          description?: string | null
          id?: string
          measured_impact?: number | null
          priority?: number
          status?: string
          title?: string
          updated_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "fk_quick_wins_account"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "quick_wins_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      rate_limit_tracking: {
        Row: {
          account_id: string
          created_at: string | null
          day_window_start: string | null
          hour_window_start: string | null
          id: string
          last_post_at: string | null
          posts_this_hour: number | null
          posts_today: number | null
          updated_at: string | null
        }
        Insert: {
          account_id: string
          created_at?: string | null
          day_window_start?: string | null
          hour_window_start?: string | null
          id?: string
          last_post_at?: string | null
          posts_this_hour?: number | null
          posts_today?: number | null
          updated_at?: string | null
        }
        Update: {
          account_id?: string
          created_at?: string | null
          day_window_start?: string | null
          hour_window_start?: string | null
          id?: string
          last_post_at?: string | null
          posts_this_hour?: number | null
          posts_today?: number | null
          updated_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "fk_rate_limit_tracking_account"
            columns: ["account_id"]
            isOneToOne: true
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
        ]
      }
      recommendation_baselines: {
        Row: {
          account_id: string
          baseline_value: number
          category: string
          created_at: string | null
          icon: string | null
          id: string
          platform: string
          post_opt_value: number | null
          rec_id: string
          regression_detected_at: string | null
          regression_expired: boolean | null
          regression_pct: number | null
          regression_status: string | null
          solved: boolean
          solved_at: string | null
          threshold: number
          title: string
          updated_at: string | null
        }
        Insert: {
          account_id: string
          baseline_value?: number
          category: string
          created_at?: string | null
          icon?: string | null
          id?: string
          platform?: string
          post_opt_value?: number | null
          rec_id: string
          regression_detected_at?: string | null
          regression_expired?: boolean | null
          regression_pct?: number | null
          regression_status?: string | null
          solved?: boolean
          solved_at?: string | null
          threshold?: number
          title: string
          updated_at?: string | null
        }
        Update: {
          account_id?: string
          baseline_value?: number
          category?: string
          created_at?: string | null
          icon?: string | null
          id?: string
          platform?: string
          post_opt_value?: number | null
          rec_id?: string
          regression_detected_at?: string | null
          regression_expired?: boolean | null
          regression_pct?: number | null
          regression_status?: string | null
          solved?: boolean
          solved_at?: string | null
          threshold?: number
          title?: string
          updated_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "fk_recommendation_baselines_account"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
        ]
      }
      recommendation_dismissals: {
        Row: {
          account_id: string
          action: string | null
          actioned_at: string | null
          auto_solved: boolean | null
          category: string | null
          dismissed_at: string | null
          icon: string | null
          id: string
          platform: string | null
          reason: string | null
          rec_id: string
          recommendation_text: string | null
          resurface_at: string | null
          user_id: string
        }
        Insert: {
          account_id: string
          action?: string | null
          actioned_at?: string | null
          auto_solved?: boolean | null
          category?: string | null
          dismissed_at?: string | null
          icon?: string | null
          id?: string
          platform?: string | null
          reason?: string | null
          rec_id: string
          recommendation_text?: string | null
          resurface_at?: string | null
          user_id: string
        }
        Update: {
          account_id?: string
          action?: string | null
          actioned_at?: string | null
          auto_solved?: boolean | null
          category?: string | null
          dismissed_at?: string | null
          icon?: string | null
          id?: string
          platform?: string | null
          reason?: string | null
          rec_id?: string
          recommendation_text?: string | null
          resurface_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "fk_recommendation_dismissals_account"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "recommendation_dismissals_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      reconciliation_runs: {
        Row: {
          accounts_checked: number
          accounts_errored: number
          completed_at: string | null
          details: Json | null
          duration_ms: number | null
          error_summary: string | null
          id: string
          orphans_inserted: number
          platform: string
          posts_checked: number
          started_at: string
          status: string
        }
        Insert: {
          accounts_checked?: number
          accounts_errored?: number
          completed_at?: string | null
          details?: Json | null
          duration_ms?: number | null
          error_summary?: string | null
          id?: string
          orphans_inserted?: number
          platform: string
          posts_checked?: number
          started_at?: string
          status?: string
        }
        Update: {
          accounts_checked?: number
          accounts_errored?: number
          completed_at?: string | null
          details?: Json | null
          duration_ms?: number | null
          error_summary?: string | null
          id?: string
          orphans_inserted?: number
          platform?: string
          posts_checked?: number
          started_at?: string
          status?: string
        }
        Relationships: []
      }
      recovery_codes: {
        Row: {
          code_hash: string
          created_at: string
          id: string
          used_at: string | null
          user_id: string
        }
        Insert: {
          code_hash: string
          created_at?: string
          id?: string
          used_at?: string | null
          user_id: string
        }
        Update: {
          code_hash?: string
          created_at?: string
          id?: string
          used_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "recovery_codes_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      referral_codes: {
        Row: {
          code: string
          created_at: string
          id: string
          is_active: boolean
          max_uses: number
          reward_type: string
          reward_value: number
          updated_at: string
          user_id: string
          uses: number
        }
        Insert: {
          code: string
          created_at?: string
          id?: string
          is_active?: boolean
          max_uses?: number
          reward_type?: string
          reward_value?: number
          updated_at?: string
          user_id: string
          uses?: number
        }
        Update: {
          code?: string
          created_at?: string
          id?: string
          is_active?: boolean
          max_uses?: number
          reward_type?: string
          reward_value?: number
          updated_at?: string
          user_id?: string
          uses?: number
        }
        Relationships: [
          {
            foreignKeyName: "referral_codes_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      referrals: {
        Row: {
          created_at: string
          id: string
          referral_code_id: string | null
          referred_id: string
          referrer_id: string
          status: string
        }
        Insert: {
          created_at?: string
          id?: string
          referral_code_id?: string | null
          referred_id: string
          referrer_id: string
          status?: string
        }
        Update: {
          created_at?: string
          id?: string
          referral_code_id?: string | null
          referred_id?: string
          referrer_id?: string
          status?: string
        }
        Relationships: [
          {
            foreignKeyName: "referrals_referral_code_id_fkey"
            columns: ["referral_code_id"]
            isOneToOne: false
            referencedRelation: "referral_codes"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "referrals_referred_id_fkey"
            columns: ["referred_id"]
            isOneToOne: true
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "referrals_referrer_id_fkey"
            columns: ["referrer_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      reliability_slo_snapshots: {
        Row: {
          avg_drift_seconds: number
          backlog_count: number
          created_at: string
          dlq_count: number
          failed_total: number
          id: string
          impacted_account_ids: string[]
          late_over_5m: number
          max_drift_seconds: number
          on_time_60s: number
          on_time_rate: number
          p50_drift_seconds: number
          p95_drift_seconds: number
          p99_drift_seconds: number
          published_total: number
          qstash_failures: number
          scheduled_total: number
          success_rate: number
          tone: string
          updated_at: string
          user_id: string
          window_end: string
          window_hours: number
          window_start: string
          workspace_id: string | null
        }
        Insert: {
          avg_drift_seconds?: number
          backlog_count?: number
          created_at?: string
          dlq_count?: number
          failed_total?: number
          id?: string
          impacted_account_ids?: string[]
          late_over_5m?: number
          max_drift_seconds?: number
          on_time_60s?: number
          on_time_rate?: number
          p50_drift_seconds?: number
          p95_drift_seconds?: number
          p99_drift_seconds?: number
          published_total?: number
          qstash_failures?: number
          scheduled_total?: number
          success_rate?: number
          tone?: string
          updated_at?: string
          user_id: string
          window_end: string
          window_hours?: number
          window_start: string
          workspace_id?: string | null
        }
        Update: {
          avg_drift_seconds?: number
          backlog_count?: number
          created_at?: string
          dlq_count?: number
          failed_total?: number
          id?: string
          impacted_account_ids?: string[]
          late_over_5m?: number
          max_drift_seconds?: number
          on_time_60s?: number
          on_time_rate?: number
          p50_drift_seconds?: number
          p95_drift_seconds?: number
          p99_drift_seconds?: number
          published_total?: number
          qstash_failures?: number
          scheduled_total?: number
          success_rate?: number
          tone?: string
          updated_at?: string
          user_id?: string
          window_end?: string
          window_hours?: number
          window_start?: string
          workspace_id?: string | null
        }
        Relationships: []
      }
      reply_response_times: {
        Row: {
          account_id: string
          avg_response_mins: number | null
          computed_at: string | null
          id: string
          platform: string
        }
        Insert: {
          account_id: string
          avg_response_mins?: number | null
          computed_at?: string | null
          id?: string
          platform?: string
        }
        Update: {
          account_id?: string
          avg_response_mins?: number | null
          computed_at?: string | null
          id?: string
          platform?: string
        }
        Relationships: [
          {
            foreignKeyName: "reply_response_times_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
        ]
      }
      report_schedules: {
        Row: {
          account_id: string
          client_name: string | null
          created_at: string | null
          day_of_month: number | null
          day_of_week: number | null
          id: string
          include_recommendations: boolean | null
          is_active: boolean | null
          last_sent_at: string | null
          platform: string | null
          recipient_emails: string[] | null
          report_type: string
          schedule_type: string
          updated_at: string | null
          user_id: string
        }
        Insert: {
          account_id: string
          client_name?: string | null
          created_at?: string | null
          day_of_month?: number | null
          day_of_week?: number | null
          id?: string
          include_recommendations?: boolean | null
          is_active?: boolean | null
          last_sent_at?: string | null
          platform?: string | null
          recipient_emails?: string[] | null
          report_type: string
          schedule_type: string
          updated_at?: string | null
          user_id: string
        }
        Update: {
          account_id?: string
          client_name?: string | null
          created_at?: string | null
          day_of_month?: number | null
          day_of_week?: number | null
          id?: string
          include_recommendations?: boolean | null
          is_active?: boolean | null
          last_sent_at?: string | null
          platform?: string | null
          recipient_emails?: string[] | null
          report_type?: string
          schedule_type?: string
          updated_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "report_schedules_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      report_send_log: {
        Row: {
          error: string | null
          id: string
          recipients: string[]
          report_id: string
          sent_at: string
          status: string
        }
        Insert: {
          error?: string | null
          id?: string
          recipients?: string[]
          report_id: string
          sent_at?: string
          status: string
        }
        Update: {
          error?: string | null
          id?: string
          recipients?: string[]
          report_id?: string
          sent_at?: string
          status?: string
        }
        Relationships: [
          {
            foreignKeyName: "report_send_log_report_id_fkey"
            columns: ["report_id"]
            isOneToOne: false
            referencedRelation: "reports"
            referencedColumns: ["id"]
          },
        ]
      }
      reports: {
        Row: {
          cadence: string
          config: Json
          created_at: string
          id: string
          last_run_at: string | null
          last_sent_at: string | null
          name: string
          network: string | null
          next_run_at: string | null
          recipients: Json
          status: string
          type: string
          updated_at: string
          user_id: string
        }
        Insert: {
          cadence: string
          config?: Json
          created_at?: string
          id?: string
          last_run_at?: string | null
          last_sent_at?: string | null
          name: string
          network?: string | null
          next_run_at?: string | null
          recipients?: Json
          status?: string
          type: string
          updated_at?: string
          user_id: string
        }
        Update: {
          cadence?: string
          config?: Json
          created_at?: string
          id?: string
          last_run_at?: string | null
          last_sent_at?: string | null
          name?: string
          network?: string | null
          next_run_at?: string | null
          recipients?: Json
          status?: string
          type?: string
          updated_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "reports_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      revenue_snapshots: {
        Row: {
          account_group_id: string
          created_at: string
          id: string
          notes: string | null
          recorded_at: string
          revenue: number | null
          subscribers: number | null
          user_id: string
        }
        Insert: {
          account_group_id: string
          created_at?: string
          id?: string
          notes?: string | null
          recorded_at?: string
          revenue?: number | null
          subscribers?: number | null
          user_id: string
        }
        Update: {
          account_group_id?: string
          created_at?: string
          id?: string
          notes?: string | null
          recorded_at?: string
          revenue?: number | null
          subscribers?: number | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "revenue_snapshots_account_group_id_fkey"
            columns: ["account_group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "revenue_snapshots_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      saved_competitor_posts: {
        Row: {
          author_avatar_url: string | null
          author_name: string | null
          auto_populated: boolean | null
          avatar_url: string | null
          competitor_post_id: string | null
          content: string | null
          created_at: string | null
          engagement_score: number | null
          id: string
          is_favorite: boolean | null
          like_count: number | null
          media_type: string | null
          media_url: string | null
          media_urls: string[] | null
          notes: string | null
          post_text: string | null
          post_url: string | null
          reply_count: number | null
          repost_count: number | null
          saved_at: string | null
          source_type: string | null
          tags: string[] | null
          threads_post_id: string | null
          thumbnail_url: string | null
          timestamp: string | null
          user_id: string
          username: string | null
          view_count: number | null
          workspace_id: string | null
        }
        Insert: {
          author_avatar_url?: string | null
          author_name?: string | null
          auto_populated?: boolean | null
          avatar_url?: string | null
          competitor_post_id?: string | null
          content?: string | null
          created_at?: string | null
          engagement_score?: number | null
          id?: string
          is_favorite?: boolean | null
          like_count?: number | null
          media_type?: string | null
          media_url?: string | null
          media_urls?: string[] | null
          notes?: string | null
          post_text?: string | null
          post_url?: string | null
          reply_count?: number | null
          repost_count?: number | null
          saved_at?: string | null
          source_type?: string | null
          tags?: string[] | null
          threads_post_id?: string | null
          thumbnail_url?: string | null
          timestamp?: string | null
          user_id: string
          username?: string | null
          view_count?: number | null
          workspace_id?: string | null
        }
        Update: {
          author_avatar_url?: string | null
          author_name?: string | null
          auto_populated?: boolean | null
          avatar_url?: string | null
          competitor_post_id?: string | null
          content?: string | null
          created_at?: string | null
          engagement_score?: number | null
          id?: string
          is_favorite?: boolean | null
          like_count?: number | null
          media_type?: string | null
          media_url?: string | null
          media_urls?: string[] | null
          notes?: string | null
          post_text?: string | null
          post_url?: string | null
          reply_count?: number | null
          repost_count?: number | null
          saved_at?: string | null
          source_type?: string | null
          tags?: string[] | null
          threads_post_id?: string | null
          thumbnail_url?: string | null
          timestamp?: string | null
          user_id?: string
          username?: string | null
          view_count?: number | null
          workspace_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "saved_competitor_posts_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "saved_competitor_posts_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      saved_nl_queries: {
        Row: {
          created_at: string | null
          id: string
          name: string | null
          prompt: string
          spec: Json
          user_id: string
        }
        Insert: {
          created_at?: string | null
          id?: string
          name?: string | null
          prompt: string
          spec: Json
          user_id: string
        }
        Update: {
          created_at?: string | null
          id?: string
          name?: string | null
          prompt?: string
          spec?: Json
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "saved_nl_queries_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      saved_views: {
        Row: {
          created_at: string
          filters: Json
          id: string
          name: string
          scope: string
          updated_at: string
          user_id: string
        }
        Insert: {
          created_at?: string
          filters?: Json
          id?: string
          name: string
          scope?: string
          updated_at?: string
          user_id: string
        }
        Update: {
          created_at?: string
          filters?: Json
          id?: string
          name?: string
          scope?: string
          updated_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "saved_views_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      scheduler_decisions: {
        Row: {
          account_id: string
          account_status: string | null
          cap_limit: number | null
          cap_used: number | null
          created_at: string
          decision: string
          group_id: string
          id: string
          minutes_since_last_post: number | null
          queue_depth: number | null
          reason: string
          run_id: string
          window_hour: number | null
          workspace_id: string
        }
        Insert: {
          account_id: string
          account_status?: string | null
          cap_limit?: number | null
          cap_used?: number | null
          created_at?: string
          decision: string
          group_id: string
          id?: string
          minutes_since_last_post?: number | null
          queue_depth?: number | null
          reason: string
          run_id: string
          window_hour?: number | null
          workspace_id: string
        }
        Update: {
          account_id?: string
          account_status?: string | null
          cap_limit?: number | null
          cap_used?: number | null
          created_at?: string
          decision?: string
          group_id?: string
          id?: string
          minutes_since_last_post?: number | null
          queue_depth?: number | null
          reason?: string
          run_id?: string
          window_hour?: number | null
          workspace_id?: string
        }
        Relationships: []
      }
      sent_replies: {
        Row: {
          account_handle: string | null
          account_id: string
          avatar_url: string | null
          content: string
          created_at: string | null
          id: string
          likes_count: number | null
          metrics_synced_at: string | null
          replies_count: number | null
          reply_to_post_id: string
          reply_to_username: string
          reposts_count: number | null
          threads_reply_id: string
          user_id: string
        }
        Insert: {
          account_handle?: string | null
          account_id: string
          avatar_url?: string | null
          content: string
          created_at?: string | null
          id?: string
          likes_count?: number | null
          metrics_synced_at?: string | null
          replies_count?: number | null
          reply_to_post_id: string
          reply_to_username: string
          reposts_count?: number | null
          threads_reply_id: string
          user_id: string
        }
        Update: {
          account_handle?: string | null
          account_id?: string
          avatar_url?: string | null
          content?: string
          created_at?: string | null
          id?: string
          likes_count?: number | null
          metrics_synced_at?: string | null
          replies_count?: number | null
          reply_to_post_id?: string
          reply_to_username?: string
          reposts_count?: number | null
          threads_reply_id?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "sent_replies_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "sent_replies_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      share_of_voice_history: {
        Row: {
          account_id: string
          competitor_id: string | null
          content_volume_share: number | null
          date: string
          engagement_share: number | null
          follower_share: number | null
          id: string
          recorded_at: string | null
          user_id: string
        }
        Insert: {
          account_id: string
          competitor_id?: string | null
          content_volume_share?: number | null
          date: string
          engagement_share?: number | null
          follower_share?: number | null
          id?: string
          recorded_at?: string | null
          user_id: string
        }
        Update: {
          account_id?: string
          competitor_id?: string | null
          content_volume_share?: number | null
          date?: string
          engagement_share?: number | null
          follower_share?: number | null
          id?: string
          recorded_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "share_of_voice_history_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      shared_reports: {
        Row: {
          created_at: string | null
          expires_at: string
          id: string
          report_data: Json
          share_token: string
          user_id: string
          view_count: number | null
        }
        Insert: {
          created_at?: string | null
          expires_at: string
          id?: string
          report_data: Json
          share_token?: string
          user_id: string
          view_count?: number | null
        }
        Update: {
          created_at?: string | null
          expires_at?: string
          id?: string
          report_data?: Json
          share_token?: string
          user_id?: string
          view_count?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "shared_reports_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      shield_log: {
        Row: {
          bot_type: string
          country: string | null
          created_at: string | null
          id: number
          page_id: string
          shield_mode: string
        }
        Insert: {
          bot_type: string
          country?: string | null
          created_at?: string | null
          id?: never
          page_id: string
          shield_mode: string
        }
        Update: {
          bot_type?: string
          country?: string | null
          created_at?: string | null
          id?: never
          page_id?: string
          shield_mode?: string
        }
        Relationships: [
          {
            foreignKeyName: "shield_log_page_id_fkey"
            columns: ["page_id"]
            isOneToOne: false
            referencedRelation: "link_pages"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "shield_log_page_id_fkey"
            columns: ["page_id"]
            isOneToOne: false
            referencedRelation: "unified_link_roi"
            referencedColumns: ["page_id"]
          },
        ]
      }
      smart_link_clicks: {
        Row: {
          block_id: string | null
          clicked_at: string | null
          country: string | null
          deep_link_attempted: boolean | null
          device_type: string | null
          event_name: string | null
          fingerprint: string | null
          id: string
          referrer: string | null
          smart_link_id: string
          source_platform: string | null
          user_agent: string | null
          utm_campaign: string | null
          utm_content: string | null
          utm_medium: string | null
          utm_source: string | null
        }
        Insert: {
          block_id?: string | null
          clicked_at?: string | null
          country?: string | null
          deep_link_attempted?: boolean | null
          device_type?: string | null
          event_name?: string | null
          fingerprint?: string | null
          id?: string
          referrer?: string | null
          smart_link_id: string
          source_platform?: string | null
          user_agent?: string | null
          utm_campaign?: string | null
          utm_content?: string | null
          utm_medium?: string | null
          utm_source?: string | null
        }
        Update: {
          block_id?: string | null
          clicked_at?: string | null
          country?: string | null
          deep_link_attempted?: boolean | null
          device_type?: string | null
          event_name?: string | null
          fingerprint?: string | null
          id?: string
          referrer?: string | null
          smart_link_id?: string
          source_platform?: string | null
          user_agent?: string | null
          utm_campaign?: string | null
          utm_content?: string | null
          utm_medium?: string | null
          utm_source?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "smart_link_clicks_smart_link_id_fkey"
            columns: ["smart_link_id"]
            isOneToOne: false
            referencedRelation: "smart_links"
            referencedColumns: ["id"]
          },
        ]
      }
      smart_link_conversions: {
        Row: {
          click_id: string | null
          conversion_value: number
          converted_at: string
          created_at: string
          currency: string
          id: string
          ip_address: string | null
          order_id: string
          smart_link_id: string
          source: string | null
        }
        Insert: {
          click_id?: string | null
          conversion_value?: number
          converted_at?: string
          created_at?: string
          currency?: string
          id?: string
          ip_address?: string | null
          order_id: string
          smart_link_id: string
          source?: string | null
        }
        Update: {
          click_id?: string | null
          conversion_value?: number
          converted_at?: string
          created_at?: string
          currency?: string
          id?: string
          ip_address?: string | null
          order_id?: string
          smart_link_id?: string
          source?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "smart_link_conversions_click_id_fkey"
            columns: ["click_id"]
            isOneToOne: false
            referencedRelation: "smart_link_clicks"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "smart_link_conversions_smart_link_id_fkey"
            columns: ["smart_link_id"]
            isOneToOne: false
            referencedRelation: "smart_links"
            referencedColumns: ["id"]
          },
        ]
      }
      smart_links: {
        Row: {
          blocks: Json
          click_count: number | null
          code: string
          created_at: string | null
          custom_domain: string | null
          domain_verified: boolean | null
          domain_verified_at: string | null
          enable_deep_links: boolean | null
          est_conversion_rate: number | null
          est_conversion_value: number | null
          id: string
          ig_deep_link: string | null
          ig_redirect_url: string | null
          is_active: boolean | null
          items: Json | null
          metadata: Json
          mobile_redirect_url: string | null
          post_id: string | null
          target_url: string
          theme: string | null
          threads_deep_link: string | null
          threads_redirect_url: string | null
          title: string | null
          updated_at: string | null
          user_id: string
          utm: Json | null
          webhook_secret: string | null
        }
        Insert: {
          blocks?: Json
          click_count?: number | null
          code: string
          created_at?: string | null
          custom_domain?: string | null
          domain_verified?: boolean | null
          domain_verified_at?: string | null
          enable_deep_links?: boolean | null
          est_conversion_rate?: number | null
          est_conversion_value?: number | null
          id?: string
          ig_deep_link?: string | null
          ig_redirect_url?: string | null
          is_active?: boolean | null
          items?: Json | null
          metadata?: Json
          mobile_redirect_url?: string | null
          post_id?: string | null
          target_url: string
          theme?: string | null
          threads_deep_link?: string | null
          threads_redirect_url?: string | null
          title?: string | null
          updated_at?: string | null
          user_id: string
          utm?: Json | null
          webhook_secret?: string | null
        }
        Update: {
          blocks?: Json
          click_count?: number | null
          code?: string
          created_at?: string | null
          custom_domain?: string | null
          domain_verified?: boolean | null
          domain_verified_at?: string | null
          enable_deep_links?: boolean | null
          est_conversion_rate?: number | null
          est_conversion_value?: number | null
          id?: string
          ig_deep_link?: string | null
          ig_redirect_url?: string | null
          is_active?: boolean | null
          items?: Json | null
          metadata?: Json
          mobile_redirect_url?: string | null
          post_id?: string | null
          target_url?: string
          theme?: string | null
          threads_deep_link?: string | null
          threads_redirect_url?: string | null
          title?: string | null
          updated_at?: string | null
          user_id?: string
          utm?: Json | null
          webhook_secret?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "smart_links_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "smart_links_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "smart_links_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      stripe_processed_events: {
        Row: {
          claimed_at: string
          event_id: string
          event_type: string
          processed_at: string
          status: string
        }
        Insert: {
          claimed_at?: string
          event_id: string
          event_type: string
          processed_at?: string
          status?: string
        }
        Update: {
          claimed_at?: string
          event_id?: string
          event_type?: string
          processed_at?: string
          status?: string
        }
        Relationships: []
      }
      style_bibles: {
        Row: {
          account_id: string | null
          created_at: string
          extracted_profile: Json
          id: string
          sample_captions: Json
          updated_at: string
          user_id: string
        }
        Insert: {
          account_id?: string | null
          created_at?: string
          extracted_profile?: Json
          id?: string
          sample_captions?: Json
          updated_at?: string
          user_id: string
        }
        Update: {
          account_id?: string | null
          created_at?: string
          extracted_profile?: Json
          id?: string
          sample_captions?: Json
          updated_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "fk_style_bibles_account"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "style_bibles_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      sync_jobs: {
        Row: {
          account_count: number
          competitors_synced: number | null
          completed_at: string | null
          created_at: string
          current_account: string | null
          current_progress: number
          engagement_updated: number | null
          error_message: string | null
          failed_count: number
          id: string
          job_type: string
          mentions_found: number | null
          posts_processed: number | null
          reactivated_accounts: string[] | null
          replies_found: number | null
          started_at: string | null
          status: string
          success_count: number
          suspended_accounts: string[] | null
          updated_at: string
          user_id: string
        }
        Insert: {
          account_count?: number
          competitors_synced?: number | null
          completed_at?: string | null
          created_at?: string
          current_account?: string | null
          current_progress?: number
          engagement_updated?: number | null
          error_message?: string | null
          failed_count?: number
          id: string
          job_type?: string
          mentions_found?: number | null
          posts_processed?: number | null
          reactivated_accounts?: string[] | null
          replies_found?: number | null
          started_at?: string | null
          status?: string
          success_count?: number
          suspended_accounts?: string[] | null
          updated_at?: string
          user_id: string
        }
        Update: {
          account_count?: number
          competitors_synced?: number | null
          completed_at?: string | null
          created_at?: string
          current_account?: string | null
          current_progress?: number
          engagement_updated?: number | null
          error_message?: string | null
          failed_count?: number
          id?: string
          job_type?: string
          mentions_found?: number | null
          posts_processed?: number | null
          reactivated_accounts?: string[] | null
          replies_found?: number | null
          started_at?: string | null
          status?: string
          success_count?: number
          suspended_accounts?: string[] | null
          updated_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "sync_jobs_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      threads_link_click_breakdown: {
        Row: {
          account_id: string
          clicks: number
          fetched_at: string
          fetched_date: string
          id: string
          link_url: string
        }
        Insert: {
          account_id: string
          clicks?: number
          fetched_at?: string
          fetched_date?: string
          id?: string
          link_url: string
        }
        Update: {
          account_id?: string
          clicks?: number
          fetched_at?: string
          fetched_date?: string
          id?: string
          link_url?: string
        }
        Relationships: [
          {
            foreignKeyName: "threads_link_click_breakdown_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
        ]
      }
      threads_webhook_events: {
        Row: {
          created_at: string
          dead_letter: boolean | null
          dead_letter_at: string | null
          dead_letter_reason: string | null
          error: string | null
          event_type: string
          id: string
          last_error: string | null
          lifetime_retry_count: number
          next_retry_at: string | null
          payload: Json
          payload_id: string | null
          processed: boolean
          processed_at: string | null
          received_at: string
          retry_count: number
          threads_user_id: string
        }
        Insert: {
          created_at?: string
          dead_letter?: boolean | null
          dead_letter_at?: string | null
          dead_letter_reason?: string | null
          error?: string | null
          event_type: string
          id?: string
          last_error?: string | null
          lifetime_retry_count?: number
          next_retry_at?: string | null
          payload: Json
          payload_id?: string | null
          processed?: boolean
          processed_at?: string | null
          received_at?: string
          retry_count?: number
          threads_user_id: string
        }
        Update: {
          created_at?: string
          dead_letter?: boolean | null
          dead_letter_at?: string | null
          dead_letter_reason?: string | null
          error?: string | null
          event_type?: string
          id?: string
          last_error?: string | null
          lifetime_retry_count?: number
          next_retry_at?: string | null
          payload?: Json
          payload_id?: string | null
          processed?: boolean
          processed_at?: string | null
          received_at?: string
          retry_count?: number
          threads_user_id?: string
        }
        Relationships: []
      }
      trend_discoveries: {
        Row: {
          account_group_id: string
          context: string | null
          created_at: string | null
          discovered_at: string
          expired_at: string | null
          id: string
          posted_at: string | null
          relevance_score: number | null
          source_data: Json | null
          status: string
          topic: string
          topic_hash: string
          user_id: string
        }
        Insert: {
          account_group_id: string
          context?: string | null
          created_at?: string | null
          discovered_at?: string
          expired_at?: string | null
          id?: string
          posted_at?: string | null
          relevance_score?: number | null
          source_data?: Json | null
          status?: string
          topic: string
          topic_hash: string
          user_id: string
        }
        Update: {
          account_group_id?: string
          context?: string | null
          created_at?: string | null
          discovered_at?: string
          expired_at?: string | null
          id?: string
          posted_at?: string | null
          relevance_score?: number | null
          source_data?: Json | null
          status?: string
          topic?: string
          topic_hash?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "trend_discoveries_account_group_id_fkey"
            columns: ["account_group_id"]
            isOneToOne: false
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "trend_discoveries_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      trend_forecasts: {
        Row: {
          account_id: string | null
          avg_engagement_rate: number | null
          best_content_types: Json | null
          best_hours: Json | null
          created_at: string | null
          data_points_used: number | null
          declining_topics: Json | null
          engagement_forecast: Json | null
          engagement_trend: string | null
          follower_forecast: Json | null
          follower_trend: string | null
          follower_velocity: number | null
          forecast_date: string
          id: string
          r_squared: number | null
          rising_topics: Json | null
          seasonal_pattern: Json | null
          signals: Json | null
          user_id: string
        }
        Insert: {
          account_id?: string | null
          avg_engagement_rate?: number | null
          best_content_types?: Json | null
          best_hours?: Json | null
          created_at?: string | null
          data_points_used?: number | null
          declining_topics?: Json | null
          engagement_forecast?: Json | null
          engagement_trend?: string | null
          follower_forecast?: Json | null
          follower_trend?: string | null
          follower_velocity?: number | null
          forecast_date: string
          id?: string
          r_squared?: number | null
          rising_topics?: Json | null
          seasonal_pattern?: Json | null
          signals?: Json | null
          user_id: string
        }
        Update: {
          account_id?: string | null
          avg_engagement_rate?: number | null
          best_content_types?: Json | null
          best_hours?: Json | null
          created_at?: string | null
          data_points_used?: number | null
          declining_topics?: Json | null
          engagement_forecast?: Json | null
          engagement_trend?: string | null
          follower_forecast?: Json | null
          follower_trend?: string | null
          follower_velocity?: number | null
          forecast_date?: string
          id?: string
          r_squared?: number | null
          rising_topics?: Json | null
          seasonal_pattern?: Json | null
          signals?: Json | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "trend_forecasts_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "trend_forecasts_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      trend_keywords: {
        Row: {
          category: string | null
          created_at: string | null
          id: string
          is_active: boolean | null
          keyword: string
          last_synced_at: string | null
          post_count: number | null
          total_engagement: number | null
          updated_at: string | null
          user_id: string
        }
        Insert: {
          category?: string | null
          created_at?: string | null
          id?: string
          is_active?: boolean | null
          keyword: string
          last_synced_at?: string | null
          post_count?: number | null
          total_engagement?: number | null
          updated_at?: string | null
          user_id: string
        }
        Update: {
          category?: string | null
          created_at?: string | null
          id?: string
          is_active?: boolean | null
          keyword?: string
          last_synced_at?: string | null
          post_count?: number | null
          total_engagement?: number | null
          updated_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "trend_keywords_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      trend_posts: {
        Row: {
          content: string | null
          engagement_score: number | null
          fetched_at: string | null
          id: string
          keyword_id: string
          like_count: number | null
          media_type: string | null
          media_url: string | null
          permalink: string | null
          posted_at: string | null
          reply_count: number | null
          repost_count: number | null
          threads_post_id: string
          user_id: string
          username: string
          view_count: number | null
        }
        Insert: {
          content?: string | null
          engagement_score?: number | null
          fetched_at?: string | null
          id?: string
          keyword_id: string
          like_count?: number | null
          media_type?: string | null
          media_url?: string | null
          permalink?: string | null
          posted_at?: string | null
          reply_count?: number | null
          repost_count?: number | null
          threads_post_id: string
          user_id: string
          username: string
          view_count?: number | null
        }
        Update: {
          content?: string | null
          engagement_score?: number | null
          fetched_at?: string | null
          id?: string
          keyword_id?: string
          like_count?: number | null
          media_type?: string | null
          media_url?: string | null
          permalink?: string | null
          posted_at?: string | null
          reply_count?: number | null
          repost_count?: number | null
          threads_post_id?: string
          user_id?: string
          username?: string
          view_count?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "trend_posts_keyword_id_fkey"
            columns: ["keyword_id"]
            isOneToOne: false
            referencedRelation: "trend_keywords"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "trend_posts_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      trend_snapshots: {
        Row: {
          avg_engagement: number | null
          created_at: string | null
          id: string
          keyword_id: string
          snapshot_date: string
          top_hashtags: Json | null
          top_post_ids: Json | null
          total_engagement: number | null
          total_posts: number | null
          user_id: string
        }
        Insert: {
          avg_engagement?: number | null
          created_at?: string | null
          id?: string
          keyword_id: string
          snapshot_date: string
          top_hashtags?: Json | null
          top_post_ids?: Json | null
          total_engagement?: number | null
          total_posts?: number | null
          user_id: string
        }
        Update: {
          avg_engagement?: number | null
          created_at?: string | null
          id?: string
          keyword_id?: string
          snapshot_date?: string
          top_hashtags?: Json | null
          top_post_ids?: Json | null
          total_engagement?: number | null
          total_posts?: number | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "trend_snapshots_keyword_id_fkey"
            columns: ["keyword_id"]
            isOneToOne: false
            referencedRelation: "trend_keywords"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "trend_snapshots_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      trending_topic_config: {
        Row: {
          account_group_id: string
          blocklist: string[]
          content_preferences: Json
          created_at: string
          daily_post_cap: number
          enabled: boolean
          id: string
          keywords: string[]
          last_scan_at: string | null
          scan_frequency_hours: number
          updated_at: string
          user_id: string
        }
        Insert: {
          account_group_id: string
          blocklist?: string[]
          content_preferences?: Json
          created_at?: string
          daily_post_cap?: number
          enabled?: boolean
          id?: string
          keywords?: string[]
          last_scan_at?: string | null
          scan_frequency_hours?: number
          updated_at?: string
          user_id: string
        }
        Update: {
          account_group_id?: string
          blocklist?: string[]
          content_preferences?: Json
          created_at?: string
          daily_post_cap?: number
          enabled?: boolean
          id?: string
          keywords?: string[]
          last_scan_at?: string | null
          scan_frequency_hours?: number
          updated_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "trending_topic_config_account_group_id_fkey"
            columns: ["account_group_id"]
            isOneToOne: true
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "trending_topic_config_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      unified_links: {
        Row: {
          created_at: string | null
          id: string
          name: string
          source_id: string
          type: string
          updated_at: string | null
          user_id: string | null
          workspace_id: string | null
        }
        Insert: {
          created_at?: string | null
          id?: string
          name: string
          source_id: string
          type: string
          updated_at?: string | null
          user_id?: string | null
          workspace_id?: string | null
        }
        Update: {
          created_at?: string | null
          id?: string
          name?: string
          source_id?: string
          type?: string
          updated_at?: string | null
          user_id?: string | null
          workspace_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "unified_links_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "unified_links_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "unified_links_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      user_preferences: {
        Row: {
          created_at: string | null
          data_contribution_opted_in: boolean | null
          id: string
          last_login_at: string | null
          onboarding_completed: boolean | null
          updated_at: string | null
          user_id: string
        }
        Insert: {
          created_at?: string | null
          data_contribution_opted_in?: boolean | null
          id?: string
          last_login_at?: string | null
          onboarding_completed?: boolean | null
          updated_at?: string | null
          user_id: string
        }
        Update: {
          created_at?: string | null
          data_contribution_opted_in?: boolean | null
          id?: string
          last_login_at?: string | null
          onboarding_completed?: boolean | null
          updated_at?: string | null
          user_id?: string
        }
        Relationships: []
      }
      user_settings: {
        Row: {
          created_at: string | null
          id: string
          setting_key: string
          setting_value: Json
          updated_at: string | null
          user_id: string
        }
        Insert: {
          created_at?: string | null
          id?: string
          setting_key: string
          setting_value: Json
          updated_at?: string | null
          user_id: string
        }
        Update: {
          created_at?: string | null
          id?: string
          setting_key?: string
          setting_value?: Json
          updated_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "user_settings_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      user_tag_palette: {
        Row: {
          created_at: string | null
          id: string
          tag_color: string | null
          tag_name: string
          user_id: string
        }
        Insert: {
          created_at?: string | null
          id?: string
          tag_color?: string | null
          tag_name: string
          user_id: string
        }
        Update: {
          created_at?: string | null
          id?: string
          tag_color?: string | null
          tag_name?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "user_tag_palette_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      user_webhooks: {
        Row: {
          created_at: string | null
          events: string[]
          id: string
          is_active: boolean | null
          last_triggered_at: string | null
          secret: string
          url: string
          user_id: string
        }
        Insert: {
          created_at?: string | null
          events?: string[]
          id?: string
          is_active?: boolean | null
          last_triggered_at?: string | null
          secret: string
          url: string
          user_id: string
        }
        Update: {
          created_at?: string | null
          events?: string[]
          id?: string
          is_active?: boolean | null
          last_triggered_at?: string | null
          secret?: string
          url?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "user_webhooks_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      viral_score_calibration: {
        Row: {
          actual: number
          created_at: string
          id: string
          post_id: string
          predicted: number
          user_id: string
        }
        Insert: {
          actual: number
          created_at?: string
          id?: string
          post_id: string
          predicted: number
          user_id: string
        }
        Update: {
          actual?: number
          created_at?: string
          id?: string
          post_id?: string
          predicted?: number
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "viral_score_calibration_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: true
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "viral_score_calibration_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: true
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "viral_score_calibration_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      voice_context_files: {
        Row: {
          account_group_id: string
          audience: string | null
          banned_patterns: string[] | null
          content: string
          last_edited_at: string
          top_patterns: Json | null
          user_id: string
          version: number
        }
        Insert: {
          account_group_id: string
          audience?: string | null
          banned_patterns?: string[] | null
          content: string
          last_edited_at?: string
          top_patterns?: Json | null
          user_id: string
          version?: number
        }
        Update: {
          account_group_id?: string
          audience?: string | null
          banned_patterns?: string[] | null
          content?: string
          last_edited_at?: string
          top_patterns?: Json | null
          user_id?: string
          version?: number
        }
        Relationships: [
          {
            foreignKeyName: "voice_context_files_account_group_id_fkey"
            columns: ["account_group_id"]
            isOneToOne: true
            referencedRelation: "account_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "voice_context_files_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      watchdog_alerts: {
        Row: {
          check_name: string
          created_at: string | null
          details: Json | null
          id: string
          message: string
          resolved_at: string | null
          severity: string
          workspace_id: string
        }
        Insert: {
          check_name: string
          created_at?: string | null
          details?: Json | null
          id?: string
          message: string
          resolved_at?: string | null
          severity?: string
          workspace_id: string
        }
        Update: {
          check_name?: string
          created_at?: string | null
          details?: Json | null
          id?: string
          message?: string
          resolved_at?: string | null
          severity?: string
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "watchdog_alerts_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "watchdog_alerts_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      webhook_deliveries: {
        Row: {
          attempts: number
          created_at: string
          delivered_at: string | null
          event: string
          id: string
          last_attempt_at: string | null
          last_error: string | null
          max_attempts: number
          next_retry_at: string | null
          payload: Json
          status: string
          subscription_id: string
          user_id: string
        }
        Insert: {
          attempts?: number
          created_at?: string
          delivered_at?: string | null
          event: string
          id?: string
          last_attempt_at?: string | null
          last_error?: string | null
          max_attempts?: number
          next_retry_at?: string | null
          payload: Json
          status?: string
          subscription_id: string
          user_id: string
        }
        Update: {
          attempts?: number
          created_at?: string
          delivered_at?: string | null
          event?: string
          id?: string
          last_attempt_at?: string | null
          last_error?: string | null
          max_attempts?: number
          next_retry_at?: string | null
          payload?: Json
          status?: string
          subscription_id?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "webhook_deliveries_subscription_id_fkey"
            columns: ["subscription_id"]
            isOneToOne: false
            referencedRelation: "webhook_subscriptions"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "webhook_deliveries_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      webhook_subscriptions: {
        Row: {
          active: boolean | null
          created_at: string | null
          events: string[]
          id: string
          secret: string | null
          secret_expires_at: string | null
          secret_rotated_at: string | null
          updated_at: string | null
          url: string
          user_id: string
        }
        Insert: {
          active?: boolean | null
          created_at?: string | null
          events?: string[]
          id?: string
          secret?: string | null
          secret_expires_at?: string | null
          secret_rotated_at?: string | null
          updated_at?: string | null
          url: string
          user_id: string
        }
        Update: {
          active?: boolean | null
          created_at?: string | null
          events?: string[]
          id?: string
          secret?: string | null
          secret_expires_at?: string | null
          secret_rotated_at?: string | null
          updated_at?: string | null
          url?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "webhook_subscriptions_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      workspace_activity: {
        Row: {
          action_details: Json | null
          action_type: string
          created_at: string | null
          id: string
          user_id: string | null
          workspace_id: string
        }
        Insert: {
          action_details?: Json | null
          action_type: string
          created_at?: string | null
          id?: string
          user_id?: string | null
          workspace_id: string
        }
        Update: {
          action_details?: Json | null
          action_type?: string
          created_at?: string | null
          id?: string
          user_id?: string | null
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "fk_workspace_activity_user"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      workspace_invites: {
        Row: {
          code: string | null
          created_at: string | null
          created_by: string | null
          email: string
          expires_at: string
          id: string
          invited_by: string
          role: string | null
          status: string | null
          used: boolean | null
          used_by: string | null
          workspace_id: string
        }
        Insert: {
          code?: string | null
          created_at?: string | null
          created_by?: string | null
          email: string
          expires_at: string
          id?: string
          invited_by: string
          role?: string | null
          status?: string | null
          used?: boolean | null
          used_by?: string | null
          workspace_id: string
        }
        Update: {
          code?: string | null
          created_at?: string | null
          created_by?: string | null
          email?: string
          expires_at?: string
          id?: string
          invited_by?: string
          role?: string | null
          status?: string | null
          used?: boolean | null
          used_by?: string | null
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "workspace_invites_invited_by_fkey"
            columns: ["invited_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "workspace_invites_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "workspace_invites_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      workspace_members: {
        Row: {
          display_name: string | null
          email: string | null
          id: string
          invited_by: string | null
          joined_at: string | null
          photo_url: string | null
          role: string | null
          user_id: string
          workspace_id: string
        }
        Insert: {
          display_name?: string | null
          email?: string | null
          id?: string
          invited_by?: string | null
          joined_at?: string | null
          photo_url?: string | null
          role?: string | null
          user_id: string
          workspace_id: string
        }
        Update: {
          display_name?: string | null
          email?: string | null
          id?: string
          invited_by?: string | null
          joined_at?: string | null
          photo_url?: string | null
          role?: string | null
          user_id?: string
          workspace_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "workspace_members_invited_by_fkey"
            columns: ["invited_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "workspace_members_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "workspace_members_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "user_workspaces"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "workspace_members_workspace_id_fkey"
            columns: ["workspace_id"]
            isOneToOne: false
            referencedRelation: "workspaces"
            referencedColumns: ["id"]
          },
        ]
      }
      workspaces: {
        Row: {
          account_count: number | null
          created_at: string | null
          extra_accounts: number | null
          extra_team_members: number | null
          id: string
          max_accounts: number | null
          max_members: number | null
          member_count: number | null
          name: string
          owner_id: string
          settings: Json | null
          subscription: Json | null
          tier: string | null
          updated_at: string | null
        }
        Insert: {
          account_count?: number | null
          created_at?: string | null
          extra_accounts?: number | null
          extra_team_members?: number | null
          id?: string
          max_accounts?: number | null
          max_members?: number | null
          member_count?: number | null
          name: string
          owner_id: string
          settings?: Json | null
          subscription?: Json | null
          tier?: string | null
          updated_at?: string | null
        }
        Update: {
          account_count?: number | null
          created_at?: string | null
          extra_accounts?: number | null
          extra_team_members?: number | null
          id?: string
          max_accounts?: number | null
          max_members?: number | null
          member_count?: number | null
          name?: string
          owner_id?: string
          settings?: Json | null
          subscription?: Json | null
          tier?: string | null
          updated_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "workspaces_owner_id_fkey"
            columns: ["owner_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
    }
    Views: {
      export_jobs: {
        Row: {
          completed_at: string | null
          created_at: string | null
          error_message: string | null
          expires_at: string | null
          file_path: string | null
          id: string | null
          status: string | null
          user_id: string | null
        }
        Insert: {
          completed_at?: string | null
          created_at?: string | null
          error_message?: string | null
          expires_at?: string | null
          file_path?: string | null
          id?: string | null
          status?: string | null
          user_id?: string | null
        }
        Update: {
          completed_at?: string | null
          created_at?: string | null
          error_message?: string | null
          expires_at?: string | null
          file_path?: string | null
          id?: string | null
          status?: string | null
          user_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "data_export_jobs_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      exports: {
        Row: {
          completed_at: string | null
          created_at: string | null
          error_message: string | null
          expires_at: string | null
          file_path: string | null
          id: string | null
          status: string | null
          user_id: string | null
        }
        Insert: {
          completed_at?: string | null
          created_at?: string | null
          error_message?: string | null
          expires_at?: string | null
          file_path?: string | null
          id?: string | null
          status?: string | null
          user_id?: string | null
        }
        Update: {
          completed_at?: string | null
          created_at?: string | null
          error_message?: string | null
          expires_at?: string | null
          file_path?: string | null
          id?: string | null
          status?: string | null
          user_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "data_export_jobs_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      instagram_competitors: {
        Row: {
          added_at: string | null
          avatar_url: string | null
          avg_comments: number | null
          avg_likes: number | null
          bio: string | null
          consecutive_failures: number | null
          display_name: string | null
          engagement_rate: number | null
          follower_count: number | null
          human_verified: boolean | null
          id: string | null
          instagram_user_id: string | null
          is_verified: boolean | null
          last_synced_at: string | null
          likes_count_7d: number | null
          media_count: number | null
          platform: string | null
          quotes_count_7d: number | null
          replies_count_7d: number | null
          reposts_count_7d: number | null
          sync_status: string | null
          threads_numeric_id: string | null
          threads_user_id: string | null
          user_id: string | null
          username: string | null
          verified_at: string | null
          verified_by: string | null
          views_count_7d: number | null
          website: string | null
        }
        Insert: {
          added_at?: string | null
          avatar_url?: string | null
          avg_comments?: number | null
          avg_likes?: number | null
          bio?: string | null
          consecutive_failures?: number | null
          display_name?: string | null
          engagement_rate?: number | null
          follower_count?: number | null
          human_verified?: boolean | null
          id?: string | null
          instagram_user_id?: string | null
          is_verified?: boolean | null
          last_synced_at?: string | null
          likes_count_7d?: number | null
          media_count?: number | null
          platform?: string | null
          quotes_count_7d?: number | null
          replies_count_7d?: number | null
          reposts_count_7d?: number | null
          sync_status?: string | null
          threads_numeric_id?: string | null
          threads_user_id?: string | null
          user_id?: string | null
          username?: string | null
          verified_at?: string | null
          verified_by?: string | null
          views_count_7d?: number | null
          website?: string | null
        }
        Update: {
          added_at?: string | null
          avatar_url?: string | null
          avg_comments?: number | null
          avg_likes?: number | null
          bio?: string | null
          consecutive_failures?: number | null
          display_name?: string | null
          engagement_rate?: number | null
          follower_count?: number | null
          human_verified?: boolean | null
          id?: string | null
          instagram_user_id?: string | null
          is_verified?: boolean | null
          last_synced_at?: string | null
          likes_count_7d?: number | null
          media_count?: number | null
          platform?: string | null
          quotes_count_7d?: number | null
          replies_count_7d?: number | null
          reposts_count_7d?: number | null
          sync_status?: string | null
          threads_numeric_id?: string | null
          threads_user_id?: string | null
          user_id?: string | null
          username?: string | null
          verified_at?: string | null
          verified_by?: string | null
          views_count_7d?: number | null
          website?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "competitors_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      instagram_posts: {
        Row: {
          account_id: string | null
          alt_text: string | null
          approval_notes: string | null
          approval_status: string | null
          approved_at: string | null
          approved_by: string | null
          avg_reply_response_mins: number | null
          collaborators: string[] | null
          content: string | null
          content_category: string | null
          content_category_confidence: number | null
          created_at: string | null
          cross_post_group_id: string | null
          draft_folder_id: string | null
          engagement_rate: number | null
          error_message: string | null
          evergreen_interval_days: number | null
          evergreen_min_engagement: number | null
          hashtags: string[] | null
          id: string | null
          ig_clips_replays: number | null
          ig_clips_replays_count: number | null
          ig_comment_count: number | null
          ig_container_created_at: string | null
          ig_container_id: string | null
          ig_container_status: string | null
          ig_crossposted_views: number | null
          ig_facebook_views: number | null
          ig_impressions: number | null
          ig_media_type: string | null
          ig_plays: number | null
          ig_profile_visits: number | null
          ig_publish_attempts: number | null
          ig_reach: number | null
          ig_reels_aggregated_all_plays_count: number | null
          ig_reels_avg_watch_time: number | null
          ig_reels_plays: number | null
          ig_reels_video_view_total_time: number | null
          ig_replays: number | null
          ig_saved: number | null
          ig_shares: number | null
          ig_skip_rate: number | null
          ig_story_exits: number | null
          ig_story_expires_at: string | null
          ig_story_replies: number | null
          ig_story_taps_back: number | null
          ig_story_taps_forward: number | null
          ig_video_views: number | null
          instagram_account_id: string | null
          instagram_post_id: string | null
          is_carousel: boolean | null
          is_evergreen: boolean | null
          is_quote: boolean | null
          last_recycled_at: string | null
          likes_count: number | null
          link_url: string | null
          location_id: string | null
          location_name: string | null
          max_recycles: number | null
          media_ids: string[] | null
          media_type: string | null
          media_urls: string[] | null
          metadata: Json | null
          metrics_archived: boolean | null
          permalink: string | null
          platform: string | null
          poll_options: Json | null
          predicted_viral_score: number | null
          published_at: string | null
          quote_chain_depth: number | null
          quoted_by_count: number | null
          quoted_post_id: string | null
          quotes_count: number | null
          recycle_count: number | null
          recycled_from_id: string | null
          rejected_at: string | null
          rejected_by: string | null
          rejection_notes: string | null
          replies_count: number | null
          reply_response_count: number | null
          reposts_count: number | null
          retry_count: number | null
          scheduled_for: string | null
          shares_count: number | null
          source: string | null
          status: string | null
          story_expires_at: string | null
          text_spoilers: Json | null
          threads_post_id: string | null
          topic_tag: string | null
          updated_at: string | null
          user_id: string | null
          views_count: number | null
          viral_score: number | null
        }
        Insert: {
          account_id?: string | null
          alt_text?: string | null
          approval_notes?: string | null
          approval_status?: string | null
          approved_at?: string | null
          approved_by?: string | null
          avg_reply_response_mins?: number | null
          collaborators?: string[] | null
          content?: string | null
          content_category?: string | null
          content_category_confidence?: number | null
          created_at?: string | null
          cross_post_group_id?: string | null
          draft_folder_id?: string | null
          engagement_rate?: number | null
          error_message?: string | null
          evergreen_interval_days?: number | null
          evergreen_min_engagement?: number | null
          hashtags?: string[] | null
          id?: string | null
          ig_clips_replays?: number | null
          ig_clips_replays_count?: number | null
          ig_comment_count?: number | null
          ig_container_created_at?: string | null
          ig_container_id?: string | null
          ig_container_status?: string | null
          ig_crossposted_views?: number | null
          ig_facebook_views?: number | null
          ig_impressions?: number | null
          ig_media_type?: string | null
          ig_plays?: number | null
          ig_profile_visits?: number | null
          ig_publish_attempts?: number | null
          ig_reach?: number | null
          ig_reels_aggregated_all_plays_count?: number | null
          ig_reels_avg_watch_time?: number | null
          ig_reels_plays?: number | null
          ig_reels_video_view_total_time?: number | null
          ig_replays?: number | null
          ig_saved?: number | null
          ig_shares?: number | null
          ig_skip_rate?: number | null
          ig_story_exits?: number | null
          ig_story_expires_at?: string | null
          ig_story_replies?: number | null
          ig_story_taps_back?: number | null
          ig_story_taps_forward?: number | null
          ig_video_views?: number | null
          instagram_account_id?: string | null
          instagram_post_id?: string | null
          is_carousel?: boolean | null
          is_evergreen?: boolean | null
          is_quote?: boolean | null
          last_recycled_at?: string | null
          likes_count?: number | null
          link_url?: string | null
          location_id?: string | null
          location_name?: string | null
          max_recycles?: number | null
          media_ids?: string[] | null
          media_type?: string | null
          media_urls?: string[] | null
          metadata?: Json | null
          metrics_archived?: boolean | null
          permalink?: string | null
          platform?: string | null
          poll_options?: Json | null
          predicted_viral_score?: number | null
          published_at?: string | null
          quote_chain_depth?: number | null
          quoted_by_count?: number | null
          quoted_post_id?: string | null
          quotes_count?: number | null
          recycle_count?: number | null
          recycled_from_id?: string | null
          rejected_at?: string | null
          rejected_by?: string | null
          rejection_notes?: string | null
          replies_count?: number | null
          reply_response_count?: number | null
          reposts_count?: number | null
          retry_count?: number | null
          scheduled_for?: string | null
          shares_count?: number | null
          source?: string | null
          status?: string | null
          story_expires_at?: string | null
          text_spoilers?: Json | null
          threads_post_id?: string | null
          topic_tag?: string | null
          updated_at?: string | null
          user_id?: string | null
          views_count?: number | null
          viral_score?: number | null
        }
        Update: {
          account_id?: string | null
          alt_text?: string | null
          approval_notes?: string | null
          approval_status?: string | null
          approved_at?: string | null
          approved_by?: string | null
          avg_reply_response_mins?: number | null
          collaborators?: string[] | null
          content?: string | null
          content_category?: string | null
          content_category_confidence?: number | null
          created_at?: string | null
          cross_post_group_id?: string | null
          draft_folder_id?: string | null
          engagement_rate?: number | null
          error_message?: string | null
          evergreen_interval_days?: number | null
          evergreen_min_engagement?: number | null
          hashtags?: string[] | null
          id?: string | null
          ig_clips_replays?: number | null
          ig_clips_replays_count?: number | null
          ig_comment_count?: number | null
          ig_container_created_at?: string | null
          ig_container_id?: string | null
          ig_container_status?: string | null
          ig_crossposted_views?: number | null
          ig_facebook_views?: number | null
          ig_impressions?: number | null
          ig_media_type?: string | null
          ig_plays?: number | null
          ig_profile_visits?: number | null
          ig_publish_attempts?: number | null
          ig_reach?: number | null
          ig_reels_aggregated_all_plays_count?: number | null
          ig_reels_avg_watch_time?: number | null
          ig_reels_plays?: number | null
          ig_reels_video_view_total_time?: number | null
          ig_replays?: number | null
          ig_saved?: number | null
          ig_shares?: number | null
          ig_skip_rate?: number | null
          ig_story_exits?: number | null
          ig_story_expires_at?: string | null
          ig_story_replies?: number | null
          ig_story_taps_back?: number | null
          ig_story_taps_forward?: number | null
          ig_video_views?: number | null
          instagram_account_id?: string | null
          instagram_post_id?: string | null
          is_carousel?: boolean | null
          is_evergreen?: boolean | null
          is_quote?: boolean | null
          last_recycled_at?: string | null
          likes_count?: number | null
          link_url?: string | null
          location_id?: string | null
          location_name?: string | null
          max_recycles?: number | null
          media_ids?: string[] | null
          media_type?: string | null
          media_urls?: string[] | null
          metadata?: Json | null
          metrics_archived?: boolean | null
          permalink?: string | null
          platform?: string | null
          poll_options?: Json | null
          predicted_viral_score?: number | null
          published_at?: string | null
          quote_chain_depth?: number | null
          quoted_by_count?: number | null
          quoted_post_id?: string | null
          quotes_count?: number | null
          recycle_count?: number | null
          recycled_from_id?: string | null
          rejected_at?: string | null
          rejected_by?: string | null
          rejection_notes?: string | null
          replies_count?: number | null
          reply_response_count?: number | null
          reposts_count?: number | null
          retry_count?: number | null
          scheduled_for?: string | null
          shares_count?: number | null
          source?: string | null
          status?: string | null
          story_expires_at?: string | null
          text_spoilers?: Json | null
          threads_post_id?: string | null
          topic_tag?: string | null
          updated_at?: string | null
          user_id?: string | null
          views_count?: number | null
          viral_score?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "posts_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_approved_by_fkey"
            columns: ["approved_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_draft_folder_id_fkey"
            columns: ["draft_folder_id"]
            isOneToOne: false
            referencedRelation: "draft_folders"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_instagram_account_id_fkey"
            columns: ["instagram_account_id"]
            isOneToOne: false
            referencedRelation: "instagram_accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_recycled_from_id_fkey"
            columns: ["recycled_from_id"]
            isOneToOne: false
            referencedRelation: "instagram_posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_recycled_from_id_fkey"
            columns: ["recycled_from_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_rejected_by_fkey"
            columns: ["rejected_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "posts_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      unified_link_roi: {
        Row: {
          button_count: number | null
          estimated_revenue: number | null
          page_id: string | null
          page_title: string | null
          page_views: number | null
          total_redirect_clicks: number | null
          user_id: string | null
        }
        Relationships: [
          {
            foreignKeyName: "link_pages_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      user_workspaces: {
        Row: {
          account_count: number | null
          created_at: string | null
          extra_accounts: number | null
          extra_team_members: number | null
          id: string | null
          joined_at: string | null
          max_accounts: number | null
          max_members: number | null
          member_count: number | null
          name: string | null
          owner_id: string | null
          role: string | null
          settings: Json | null
          subscription: Json | null
          tier: string | null
          updated_at: string | null
          user_id: string | null
        }
        Relationships: [
          {
            foreignKeyName: "workspace_members_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "workspaces_owner_id_fkey"
            columns: ["owner_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
    }
    Functions: {
      aal2_or_no_mfa: { Args: never; Returns: boolean }
      acquire_cron_lock: {
        Args: {
          p_job_name: string
          p_locked_by: string
          p_ttl_seconds?: number
        }
        Returns: boolean
      }
      analyze_small_tables: { Args: never; Returns: undefined }
      assign_account_to_group: {
        Args: {
          p_account_id: string
          p_target_group_id: string
          p_user_id: string
        }
        Returns: undefined
      }
      check_and_increment_rate_limit: {
        Args: {
          p_account_id: string
          p_daily_limit?: number
          p_hourly_limit?: number
        }
        Returns: {
          allowed: boolean
          posts_this_hour: number
          posts_today: number
          reason: string
        }[]
      }
      check_ig_endpoint_limit: {
        Args: {
          p_account_id: string
          p_daily_limit: number
          p_endpoint: string
          p_hourly_limit: number
        }
        Returns: {
          allowed: boolean
          reason: string
        }[]
      }
      check_publish_rate_limit: {
        Args: { p_account_id: string; p_platform?: string }
        Returns: {
          allowed: boolean
          daily_limit: number
          daily_used: number
          reason: string
        }[]
      }
      check_reply_rate_limit: {
        Args: {
          p_account_id: string
          p_daily_limit?: number
          p_hourly_limit?: number
        }
        Returns: Json
      }
      check_trigram_dupe: {
        Args: {
          p_content: string
          p_threshold?: number
          p_workspace_id: string
        }
        Returns: {
          matched_id: string
          matched_similarity: number
        }[]
      }
      claim_auto_post_queue_item_for_publish: {
        Args: {
          p_claim_expires_at?: string
          p_claim_token?: string
          p_now?: string
          p_queue_item_id: string
          p_schedule_nonce?: string
        }
        Returns: {
          id: string
        }[]
      }
      claim_beta_spot: {
        Args: { p_total_spots?: number; p_user_id: string }
        Returns: Json
      }
      classify_account_cohorts: { Args: never; Returns: number }
      cleanup_old_audit_logs: { Args: never; Returns: number }
      cleanup_old_cron_runs: {
        Args: { p_retention_days?: number }
        Returns: number
      }
      create_link_item_with_quota: {
        Args: {
          p_limit: number
          p_page_id: string
          p_payload: Json
          p_user_id: string
        }
        Returns: Json
      }
      create_link_page_with_quota: {
        Args: { p_limit: number; p_payload: Json; p_user_id: string }
        Returns: Json
      }
      create_smart_link_with_quota: {
        Args: { p_limit: number; p_payload: Json; p_user_id: string }
        Returns: Json
      }
      finalize_autoposter_publish: {
        Args: {
          p_account_id: string
          p_claim_token: string
          p_content: string
          p_group_id: string
          p_media_urls?: Json
          p_published_at?: string
          p_queue_item_id: string
          p_source_type?: string
          p_threads_post_id: string
          p_workspace_id: string
        }
        Returns: {
          inserted: boolean
          post_id: string
        }[]
      }
      generate_referral_code: { Args: { username: string }; Returns: string }
      get_activity_events: { Args: { p_bucket_limit?: number }; Returns: Json }
      get_aggregated_analytics: {
        Args: {
          p_account_ids?: string[]
          p_days?: number
          p_platform?: string
          p_user_id: string
        }
        Returns: {
          date: string
          engagement_rate: number
          followers_count: number
          total_clicks: number
          total_likes: number
          total_quotes: number
          total_replies: number
          total_reposts: number
          total_shares: number
          total_views: number
        }[]
      }
      get_calendar_week: {
        Args: {
          p_gap_window_hours?: number
          p_target_posts_per_day?: number
          p_week_start: string
        }
        Returns: Json
      }
      get_fleet_health: { Args: never; Returns: Json }
      get_fleet_metrics: {
        Args: {
          p_user_id: string
          p_window_end: string
          p_window_start: string
        }
        Returns: Json
      }
      get_next_up_posts: {
        Args: {
          p_account_ids?: string[]
          p_limit?: number
          p_platform?: string
          p_scoped_account_id?: string
          p_scoped_platform?: string
          p_window_minutes?: number
        }
        Returns: Json
      }
      get_post_floor_aggregates: {
        Args: {
          p_account_ids: string[]
          p_platform?: string
          p_since: string
          p_user_id: string
        }
        Returns: {
          post_count: number
          total_likes: number
          total_replies: number
          total_shares: number
          total_views: number
        }[]
      }
      get_rate_limit_status:
        | {
            Args: { p_account_id: string }
            Returns: {
              daily_remaining: number
              hourly_remaining: number
              next_day_reset: string
              next_hour_reset: string
              posts_this_hour: number
              posts_today: number
            }[]
          }
        | {
            Args: {
              p_account_id: string
              p_daily_limit?: number
              p_hourly_limit?: number
            }
            Returns: {
              daily_remaining: number
              hourly_remaining: number
              next_day_reset: string
              next_hour_reset: string
              posts_this_hour: number
              posts_today: number
            }[]
          }
      get_smart_link_revenue_summary: {
        Args: { p_days?: number; p_user_id: string }
        Returns: {
          conversion_rate: number
          total_actual_revenue: number
          total_clicks: number
          total_conversions: number
          total_estimated_revenue: number
        }[]
      }
      get_system_status: { Args: never; Returns: Json }
      ig_check_and_increment_rate_limit: {
        Args: { p_account_id: string; p_daily_limit?: number }
        Returns: {
          allowed: boolean
          reason: string
        }[]
      }
      increment_ai_generations:
        | {
            Args: {
              p_count: number
              p_reset?: boolean
              p_today: string
              p_workspace_id: string
            }
            Returns: undefined
          }
        | {
            Args: {
              p_count: number
              p_limit?: number
              p_reset?: boolean
              p_today: string
              p_workspace_id: string
            }
            Returns: number
          }
      increment_api_usage: {
        Args: { p_endpoint: string; p_user_id: string }
        Returns: undefined
      }
      increment_dm_template_use: {
        Args: { p_template_id: string; p_user_id: string }
        Returns: undefined
      }
      increment_group_posts_today: {
        Args: { p_column?: string; p_group_id: string; p_workspace_id: string }
        Returns: number
      }
      increment_link_click: { Args: { p_link_id: string }; Returns: undefined }
      increment_referral_uses: { Args: { p_code: string }; Returns: undefined }
      increment_smart_link_click: {
        Args: { p_link_id: string }
        Returns: undefined
      }
      increment_view_count: { Args: { p_page_id: string }; Returns: undefined }
      is_workspace_admin: { Args: { ws_id: string }; Returns: boolean }
      is_workspace_member:
        | { Args: { ws_id: string }; Returns: boolean }
        | { Args: { uid: string; ws_id: string }; Returns: boolean }
      is_workspace_owner: {
        Args: { uid: string; ws_id: string }
        Returns: boolean
      }
      mark_all_replies_as_read: {
        Args: { p_post_id?: string }
        Returns: number
      }
      mark_reply_as_read: { Args: { p_reply_id: string }; Returns: boolean }
      reconcile_autoposter_publish: {
        Args: { p_queue_item_id: string }
        Returns: {
          inserted: boolean
          post_id: string
        }[]
      }
      record_variant_click: {
        Args: { p_variant_id: string }
        Returns: undefined
      }
      record_variant_impression: {
        Args: { p_variant_id: string }
        Returns: undefined
      }
      refresh_group_analytics:
        | { Args: never; Returns: undefined }
        | { Args: { p_date?: string; p_user_id: string }; Returns: number }
      release_cron_lock: {
        Args: { p_job_name: string; p_locked_by: string }
        Returns: undefined
      }
      smart_link_analytics:
        | { Args: { p_link_id: string; p_since: string }; Returns: Json }
        | {
            Args: { p_link_id: string; p_since: string; p_user_id: string }
            Returns: Json
          }
      update_ig_post_metrics_if_newer: {
        Args: {
          p_engagement_rate?: number
          p_ig_clips_replays_count?: number
          p_ig_crossposted_views?: number
          p_ig_facebook_views?: number
          p_ig_impressions?: number
          p_ig_plays?: number
          p_ig_reach?: number
          p_ig_reels_aggregated_all_plays_count?: number
          p_ig_reels_avg_watch_time?: number
          p_ig_reels_video_view_total_time?: number
          p_ig_saved?: number
          p_ig_shares?: number
          p_ig_video_views?: number
          p_likes_count?: number
          p_post_id: string
          p_replies_count?: number
          p_total_engagement?: number
        }
        Returns: undefined
      }
      update_post_metrics_if_newer: {
        Args: {
          p_engagement_rate?: number
          p_likes_count?: number
          p_post_id?: string
          p_quotes_count?: number
          p_replies_count?: number
          p_reposts_count?: number
          p_shares_count?: number
          p_threads_post_id?: string
          p_total_engagement?: number
          p_views_count?: number
        }
        Returns: undefined
      }
      upsert_account_analytics_atomic: {
        Args: { p_analytics: Json; p_metrics_history: Json }
        Returns: Json
      }
      webhook_p95_latency_seconds: {
        Args: { since: string; tbl: string }
        Returns: number
      }
    }
    Enums: {
      account_autoposter_status:
        | "active"
        | "warming_silent"
        | "warming_limited"
        | "viral_suppress"
        | "flop_delay"
        | "view_cooldown"
        | "suppressed"
        | "suppressed_probe"
        | "shadowban_throttle"
        | "inactive"
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {
      account_autoposter_status: [
        "active",
        "warming_silent",
        "warming_limited",
        "viral_suppress",
        "flop_delay",
        "view_cooldown",
        "suppressed",
        "suppressed_probe",
        "shadowban_throttle",
        "inactive",
      ],
    },
  },
} as const
