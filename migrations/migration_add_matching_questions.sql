-- Migration: Add matching questions feature support
-- Date: 2026-07-13
-- Description: 
--   1. Add question_type column to question table (TEXT, values: 'classic', 'matching')
--   2. Migrate existing questions to question_type='classic'
--   3. Create matching_element table for matching question elements (text or media)
--   4. Create matching_correct_pair table for correct associations

-- ============================================================================
-- STEP 1: Add question_type column to question table
-- ============================================================================

ALTER TABLE question
ADD COLUMN question_type TEXT DEFAULT 'classic';

-- Update existing records to have question_type='classic'
UPDATE question
SET question_type = 'classic'
WHERE question_type IS NULL;

-- ============================================================================
-- STEP 2: Create matching_element table
-- ============================================================================
-- Stores elements for matching questions. Each element belongs to a specific list
-- (identified by list_index) and position within that list.
-- Element content is either text OR media (image/audio/video), enforced by CHECK constraint.

CREATE TABLE matching_element (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    list_index INTEGER NOT NULL,  -- 0-based index of the list this element belongs to
    position INTEGER NOT NULL,     -- 0-based position within the list
    text TEXT DEFAULT NULL,        -- Element text content (mutually exclusive with media)
    media_id INTEGER DEFAULT NULL, -- Foreign key to Image/Audio/Video table
    media_type TEXT DEFAULT NULL,  -- Type of media: 'image', 'audio', or 'video'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Foreign key constraints
    FOREIGN KEY (question_id) REFERENCES question(id) ON DELETE CASCADE,
    
    -- Check constraints
    -- Ensure either text OR media is provided (mutually exclusive)
    CHECK (
        (text IS NOT NULL AND media_id IS NULL AND media_type IS NULL) OR
        (text IS NULL AND media_id IS NOT NULL AND media_type IS NOT NULL)
    ),
    -- Ensure media_type is valid if provided
    CHECK (media_type IS NULL OR media_type IN ('image', 'audio', 'video'))
);

-- Create indexes for performance
CREATE INDEX idx_matching_element_question_id ON matching_element(question_id);
CREATE INDEX idx_matching_element_list_index ON matching_element(question_id, list_index);

-- ============================================================================
-- STEP 3: Create matching_correct_pair table
-- ============================================================================
-- Stores the correct associations between elements for matching questions.
-- Each pair identifies two elements that should be matched together.

CREATE TABLE matching_correct_pair (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    list_index_1 INTEGER NOT NULL,      -- List index of first element
    element_position_1 INTEGER NOT NULL, -- Position of first element in its list
    list_index_2 INTEGER NOT NULL,      -- List index of second element
    element_position_2 INTEGER NOT NULL, -- Position of second element in its list
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Foreign key constraints
    FOREIGN KEY (question_id) REFERENCES question(id) ON DELETE CASCADE
);

-- Create indexes for performance
CREATE INDEX idx_matching_correct_pair_question_id ON matching_correct_pair(question_id);

-- Create unique constraint to prevent duplicate pairs
-- Note: (A,B) and (B,A) are considered different in this schema, 
-- but application logic should ensure consistency
CREATE UNIQUE INDEX idx_matching_correct_pair_unique ON matching_correct_pair(
    question_id, 
    list_index_1, 
    element_position_1, 
    list_index_2, 
    element_position_2
);

-- ============================================================================
-- Migration complete
-- ============================================================================
-- To verify:
--   SELECT id, question_type FROM question LIMIT 5;
--   SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'matching%';
