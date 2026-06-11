-- Reset queue items that were incorrectly scheduled days in the future
-- due to the cascading scheduling bug (stacking on last scheduled item).
-- Move pending/queued items back to now so they publish in the current window.
-- Scheduled items (already claimed by QStash) get reset to pending for re-pickup.

UPDATE auto_post_queue
SET
  scheduled_for = NOW() + (random() * interval '30 minutes'),
  status = CASE WHEN status = 'scheduled' THEN 'pending' ELSE status END,
  schedule_nonce = NULL,
  qstash_message_id = NULL
WHERE status IN ('pending', 'queued', 'scheduled')
  AND scheduled_for > NOW() + interval '3 hours';
