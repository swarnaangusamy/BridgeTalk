-- ============================================================================
-- Migration 001 — Interview Mode enforcement
--
-- Run against an existing BridgeTalk database:
--     mysql -u bridgetalk -p bridgetalk < database/migrations/001_interview_mode_enforcement.sql
--
-- Additive only. No column is dropped and no data is rewritten, so running it
-- on a database that already holds meetings and transcripts is safe.
-- Every statement is guarded, so re-running it is a no-op rather than an error.
-- ============================================================================

-- --------------------------------------------------------------------------
-- focus_events.duration_away_ms
--
-- The table previously recorded only THAT focus was lost, as separate
-- 'blur' / 'hidden' / 'return' rows. The host needs to know HOW LONG someone
-- was away: a 300 ms notification stealing focus and a two-minute absence are
-- not the same event, and treating them alike makes the log useless.
--
-- Stored on the 'return' row, because that is the first moment the duration is
-- known. Null on 'blur' and 'hidden' rows, and null on a 'return' whose
-- matching departure was never recorded (a reload mid-absence).
-- --------------------------------------------------------------------------
SET @exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'focus_events'
    AND COLUMN_NAME = 'duration_away_ms'
);
SET @sql := IF(@exists = 0,
  'ALTER TABLE focus_events ADD COLUMN duration_away_ms INT NULL AFTER event_type',
  'DO 0');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- --------------------------------------------------------------------------
-- An index on (meeting_id, user_id) — the host's violation view groups by
-- participant, and counting violations per person is the query that decides
-- whether to prompt for removal.
-- --------------------------------------------------------------------------
SET @exists := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'focus_events'
    AND INDEX_NAME = 'ix_focus_meeting_user'
);
SET @sql := IF(@exists = 0,
  'CREATE INDEX ix_focus_meeting_user ON focus_events (meeting_id, user_id)',
  'DO 0');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- --------------------------------------------------------------------------
-- meetings.interview_mode_started_at
--
-- Interview mode can now be switched on DURING a meeting, not only chosen at
-- creation. Recording when it started is what makes the violation log
-- interpretable: a focus event from before the mode was switched on is not a
-- violation, and without this timestamp there is no way to tell them apart.
-- --------------------------------------------------------------------------
SET @exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'meetings'
    AND COLUMN_NAME = 'interview_mode_started_at'
);
SET @sql := IF(@exists = 0,
  'ALTER TABLE meetings ADD COLUMN interview_mode_started_at DATETIME NULL AFTER is_interview_mode',
  'DO 0');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SELECT 'migration 001 applied' AS result;
