-- Migration: Add pawns feature support
-- Date: 2026-02-01
-- Description: 
--   1. Add with_pawns column to game table (boolean, default false)
--   2. Add pawn_row, pawn_col, allowed_steps columns to player table
--   3. Update username lengletsalome@gmail.com to Salomé in user table

-- Add with_pawns column to game table
ALTER TABLE game
ADD COLUMN with_pawns BOOLEAN DEFAULT FALSE;

-- Update existing records to have with_pawns = false
UPDATE game
SET with_pawns = FALSE
WHERE with_pawns IS NULL;

-- Add pawn columns to player table
ALTER TABLE player
ADD COLUMN pawn_row INTEGER DEFAULT NULL;

ALTER TABLE player
ADD COLUMN pawn_col INTEGER DEFAULT NULL;

ALTER TABLE player
ADD COLUMN allowed_steps INTEGER DEFAULT 1;

-- Update existing records
UPDATE player
SET allowed_steps = 1
WHERE allowed_steps IS NULL;

-- Update username in user table
UPDATE "user"
SET username = 'Salomé'
WHERE username = 'lengletsalome@gmail.com';
