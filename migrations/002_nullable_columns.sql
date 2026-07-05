-- Make primary_exchange and position_direction nullable.
-- primary_exchange is only used for Yahoo Finance lookups (not yet active).
-- position_direction is agent-generated, not sourced from Excel.

IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('positions')
      AND name = 'primary_exchange'
      AND is_nullable = 0
)
BEGIN
    ALTER TABLE positions ALTER COLUMN primary_exchange VARCHAR(20) NULL;
END
GO

IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('positions')
      AND name = 'position_direction'
      AND is_nullable = 0
)
BEGIN
    ALTER TABLE positions ALTER COLUMN position_direction VARCHAR(10) NULL;
END
GO
