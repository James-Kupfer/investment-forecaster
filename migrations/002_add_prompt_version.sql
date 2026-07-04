-- Add prompt_version column to prompt_registry if it is missing.
-- Needed when the table was created from an earlier schema that lacked this column.
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dbo.prompt_registry') AND name = 'prompt_version'
)
BEGIN
    ALTER TABLE dbo.prompt_registry ADD prompt_version VARCHAR(20) NOT NULL DEFAULT 'v1.0';
END
GO
