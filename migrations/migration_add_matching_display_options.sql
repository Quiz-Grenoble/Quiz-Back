-- Migration: Add display options for matching questions
-- Date: 2026-10-12
-- Description:
--   1. Add randomize_on_play column to question table (BOOLEAN, default 0/false)
--   2. Add custom_display_order column to question table (TEXT/JSON, nullable)
--      Stores per-list display order as JSON: [[pos, pos, ...], [pos, pos, ...], ...]

-- ============================================================================
-- STEP 1: Add randomize_on_play column
-- ============================================================================

ALTER TABLE question
ADD COLUMN randomize_on_play BOOLEAN NOT NULL DEFAULT 0;

-- ============================================================================
-- STEP 2: Add custom_display_order column (stored as JSON text)
-- ============================================================================

ALTER TABLE question
ADD COLUMN custom_display_order TEXT DEFAULT NULL;
