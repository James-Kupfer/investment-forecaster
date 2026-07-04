-- Widen rationale/summary columns that were created as NVARCHAR(1000).
-- LLM outputs regularly exceed 1000 chars; MAX avoids silent truncation.

IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq3_definition_rationale' AND max_length != -1)
    ALTER TABLE dbo.forecasts ALTER COLUMN invq3_definition_rationale NVARCHAR(MAX) NULL;
GO
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='macroq_rationale' AND max_length != -1)
    ALTER TABLE dbo.forecasts ALTER COLUMN macroq_rationale NVARCHAR(MAX) NULL;
GO
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='risk_judge_rationale' AND max_length != -1)
    ALTER TABLE dbo.forecasts ALTER COLUMN risk_judge_rationale NVARCHAR(MAX) NULL;
GO
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='earnings_rationale' AND max_length != -1)
    ALTER TABLE dbo.forecasts ALTER COLUMN earnings_rationale NVARCHAR(MAX) NULL;
GO
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='primary_rationale' AND max_length != -1)
    ALTER TABLE dbo.forecasts ALTER COLUMN primary_rationale NVARCHAR(MAX) NULL;
GO
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='momentum_rationale' AND max_length != -1)
    ALTER TABLE dbo.forecasts ALTER COLUMN momentum_rationale NVARCHAR(MAX) NULL;
GO
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='trend_rationale' AND max_length != -1)
    ALTER TABLE dbo.forecasts ALTER COLUMN trend_rationale NVARCHAR(MAX) NULL;
GO
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='volume_rationale' AND max_length != -1)
    ALTER TABLE dbo.forecasts ALTER COLUMN volume_rationale NVARCHAR(MAX) NULL;
GO
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='pattern_rationale' AND max_length != -1)
    ALTER TABLE dbo.forecasts ALTER COLUMN pattern_rationale NVARCHAR(MAX) NULL;
GO
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='technical_rationale' AND max_length != -1)
    ALTER TABLE dbo.forecasts ALTER COLUMN technical_rationale NVARCHAR(MAX) NULL;
GO
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq3_rationale' AND max_length != -1)
    ALTER TABLE dbo.forecasts ALTER COLUMN invq3_rationale NVARCHAR(MAX) NULL;
GO
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq1_rationale' AND max_length != -1)
    ALTER TABLE dbo.forecasts ALTER COLUMN invq1_rationale NVARCHAR(MAX) NULL;
GO
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq2_rationale' AND max_length != -1)
    ALTER TABLE dbo.forecasts ALTER COLUMN invq2_rationale NVARCHAR(MAX) NULL;
GO
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='review_rationale' AND max_length != -1)
    ALTER TABLE dbo.forecasts ALTER COLUMN review_rationale NVARCHAR(MAX) NULL;
GO
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='confidence_rationale' AND max_length != -1)
    ALTER TABLE dbo.forecasts ALTER COLUMN confidence_rationale NVARCHAR(MAX) NULL;
GO
