# Operator Action Manifest

Last updated: 2026-05-25

This document describes the machine-readable action manifest exposed to Codex,
the hosted MCP server, and external operator clients.

Canonical endpoint:

```text
GET /api/operator?action=manifest
```

Related MCP tool:

```text
get_operator_manifest
```

## Fields

Each action entry includes:

| Field | Meaning |
|---|---|
| `toolName` | Canonical MCP/operator action name. |
| `riskLevel` | `low`, `medium`, `high`, or `critical`. |
| `sideEffectType` | Side-effect class, such as `external_publish`, `settings_write`, or `destructive`. |
| `requiresApproval` | Whether the action must be bound to an exact approved intent before execution. |
| `requiresIdempotencyKey` | Whether direct execution must carry an idempotency key. |
| `supportsDryRun` | Whether Codex can preview the action without side effects. |
| `hostedAvailable` | Whether hosted MCP exposes the action. |
| `rollbackSupport` | `none`, `compensating_action`, or `delete_or_revert`. |
| `compensationActionName` | Optional canonical action to use for rollback/recovery. |
| `compensationDescription` | Operator-facing recovery guidance. |
| `compensationRequiresApproval` | Whether the recovery action also requires approval. |
| `rollbackWindowHours` | Optional recommended window for effective rollback. |

## Rollback Classes

`compensating_action` means the original side effect cannot be undone in place,
but the app knows a safe follow-up action. Examples: delete/cancel a post after
publish/schedule, reschedule back to a prior time, or send a corrective reply.

`delete_or_revert` means the previous values in the audit log can be used to
create a new approved intent that restores settings or content state.

`none` means there is no reliable automatic rollback. Destructive actions and
AI-only generation outputs fall into this class for different reasons:
destructive writes may require backups or manual recreation, while generation
outputs can simply be discarded.

## Execution Rule

Rollback metadata is descriptive and does not bypass the control plane. Any
high-risk compensation action still needs the same dry-run, exact approval,
idempotency, kill-switch, and audit gates as the original action.

## Representative Actions

Common high-value actions exposed by the manifest include:

| Action | Expected class |
|---|---|
| `publish_post` | Critical external publish; exact approval and idempotency required. |
| `schedule_post` | Critical scheduling write; exact approval and idempotency required. |
| `reschedule_post` | Critical schedule mutation; exact approval and idempotency required. |
| `send_reply` | Critical external reply/message write; exact approval and idempotency required. |
| `trigger_queue_fill` | High-risk queue/fleet write; exact approval and idempotency required. |
| `override_account_state` | High-risk account state write; exact approval and idempotency required. |

## Verification

Runtime coverage lives in:

```text
tests/unit/mcp-runtime-parity.test.ts
scripts/check-operator-docs.mjs
```

The test registers the local MCP runtime through the shared control plane,
asserts canonical hosted/local module parity, proves write tools receive
`dryRun` and `approvalId`, verifies default dry-run behavior, and checks that
the manifest includes compensation metadata for representative action classes.
The docs check verifies that the generated/reference documentation still covers
the canonical manifest fields and every canonical action name.

## Canonical Action Index

The docs parity check fails if any write tool in the canonical manifest is
missing from this index:

`accept_ig_collaboration`, `add_bio_link`, `add_competitor`, `ai_copilot`, `ai_feedback`, `ai_generate`, `ai_generate_image`, `ai_generate_single`, `ai_growth_simulator`, `ai_post_autopsy`, `ai_vision_score`, `analyze_competitor`, `approve_post`, `assign_accounts_to_group`, `assign_competitors_to_group`, `assign_inbox_message`, `assign_tag_to_posts`, `bulk_add_competitors`, `bulk_apply_quick_wins`, `bulk_assign_accounts_to_group`, `bulk_cancel_scheduled`, `bulk_cap_status`, `bulk_clear_all_queues`, `bulk_clear_queue`, `bulk_delete_ig_comments`, `bulk_delete_ig_media`, `bulk_delete_posts`, `bulk_delete_queue_items`, `bulk_hide_ig_comments`, `bulk_register_media`, `bulk_remove_competitors`, `bulk_reply_ig_comments`, `bulk_reply_to_messages`, `bulk_reschedule_posts`, `bulk_schedule`, `bulk_schedule_groups`, `bulk_set_content_strategy`, `bulk_sync_accounts`, `bulk_toggle_evergreen`, `bulk_toggle_ig_comments`, `bulk_update_group_configs`, `claim_beta_spot`, `create_account_group`, `create_collab`, `create_composer_diff`, `create_developer_api_key`, `create_draft_folder`, `create_ig_auto_responder`, `create_ig_dm_template`, `create_inbox_rule`, `create_link_page`, `create_listening_alert`, `create_saved_view`, `create_smart_link`, `create_tag`, `create_template`, `create_user_webhook`, `decline_ig_collaboration`, `delete_account_group`, `delete_account_override`, `delete_agent_note`, `delete_auto_post_config`, `delete_bio_link`, `delete_collab`, `delete_developer_api_key`, `delete_draft_folder`, `delete_ig_auto_responder`, `delete_ig_comment`, `delete_ig_dm_template`, `delete_ig_ice_breakers`, `delete_ig_media`, `delete_ig_persistent_menu`, `delete_ig_welcome_message`, `delete_inbox_rule`, `delete_link_page`, `delete_listening_alert`, `delete_post`, `delete_queue_item`, `delete_saved_view`, `delete_smart_link`, `delete_tag`, `delete_template`, `delete_user_webhook`, `dismiss_recommendation`, `enhance_smart_link`, `execute_operator_action`, `generate_composer_variants`, `generate_report`, `generate_saved_report`, `growth_journal_create`, `hide_ig_comment`, `import_posts`, `like_ig_media_or_comment`, `lock_high_risk_actions`, `log_composer_ai_action`, `log_revenue_snapshot`, `mark_inbox_message_read`, `move_drafts_to_folder`, `override_account_state`, `private_reply_ig_comment`, `promote_auto_post_variant`, `promote_composer_variant`, `promote_variant`, `publish_instagram_post`, `publish_threads_post`, `purge_dead_letters`, `refresh_media_urls`, `refresh_threads_post_metrics`, `reject_post`, `remove_competitor`, `reorder_bio_links`, `reply_to_ig_comment`, `reply_to_message`, `repost_threads_post`, `request_human_approval`, `request_operator_approval`, `request_typed_approval`, `request_user_data_export`, `reschedule_post`, `resolve_composer_diff`, `retry_dead_letter`, `retry_queue_item`, `run_onboarding_instant_analysis`, `save_agent_note`, `save_draft`, `schedule_instagram_post`, `schedule_threads_post`, `send_ig_generic_template`, `send_ig_media_message`, `send_ig_message`, `send_ig_message_reaction`, `send_ig_quick_replies`, `send_ig_typing_indicator`, `send_saved_report`, `send_team_invite`, `set_agent_paused`, `set_agent_policy`, `set_business_goals`, `set_content_strategy`, `set_data_contribution_preference`, `set_ig_ice_breakers`, `set_ig_persistent_menu`, `set_ig_welcome_message`, `set_trending_config`, `share_media_folder`, `shorten_url`, `submit_beta_feedback`, `subscribe_push_notifications`, `sync_auto_post_engagement`, `sync_instagram_account`, `sync_threads_account`, `test_user_webhook`, `toggle_auto_post`, `toggle_auto_reply`, `toggle_evergreen`, `toggle_ig_auto_responder`, `toggle_ig_comments`, `toggle_inbox_rule`, `trigger_queue_fill`, `unassign_inbox_message`, `unassign_tag_from_posts`, `unlike_ig_media_or_comment`, `unsubscribe_push_notifications`, `update_account_group`, `update_agency_branding`, `update_bio_link`, `update_collab`, `update_developer_api_key`, `update_draft`, `update_draft_folder`, `update_evergreen_settings`, `update_ig_auto_responder`, `update_ig_dm_template`, `update_inbox_ai_suggestion`, `update_link_page`, `update_listening_alert`, `update_operator_task`, `update_saved_report`, `update_smart_link`, `update_voice_context_file`, `upload_media`, `upsert_account_override`, `upsert_ai_config`, `upsert_auto_post_config`, `upsert_workspace_config`, `use_inspiration_idea`
