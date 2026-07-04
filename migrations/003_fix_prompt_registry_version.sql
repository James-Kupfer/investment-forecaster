-- The prompt_registry table was created before migrations with a 'version' column
-- (NOT NULL, no default) that differs from the 'prompt_version' column added in 002.
-- Make 'version' nullable so seed inserts that omit it do not fail.
IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dbo.prompt_registry')
      AND name = 'version'
      AND is_nullable = 0
)
BEGIN
    ALTER TABLE dbo.prompt_registry ALTER COLUMN version VARCHAR(20) NULL;
END
GO
