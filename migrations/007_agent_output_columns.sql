-- Add per-agent full JSON output columns to forecasts.
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='earnings_output')
    ALTER TABLE dbo.forecasts ADD earnings_output NVARCHAR(MAX) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='primary_output')
    ALTER TABLE dbo.forecasts ADD primary_output NVARCHAR(MAX) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='elicitation_output')
    ALTER TABLE dbo.forecasts ADD elicitation_output NVARCHAR(MAX) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='momentum_output')
    ALTER TABLE dbo.forecasts ADD momentum_output NVARCHAR(MAX) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='trend_output')
    ALTER TABLE dbo.forecasts ADD trend_output NVARCHAR(MAX) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='volume_output')
    ALTER TABLE dbo.forecasts ADD volume_output NVARCHAR(MAX) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='pattern_output')
    ALTER TABLE dbo.forecasts ADD pattern_output NVARCHAR(MAX) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='technical_judge_output')
    ALTER TABLE dbo.forecasts ADD technical_judge_output NVARCHAR(MAX) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='review_output')
    ALTER TABLE dbo.forecasts ADD review_output NVARCHAR(MAX) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='confidence_judge_output')
    ALTER TABLE dbo.forecasts ADD confidence_judge_output NVARCHAR(MAX) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='aggregation_output')
    ALTER TABLE dbo.forecasts ADD aggregation_output NVARCHAR(MAX) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='macroq_output')
    ALTER TABLE dbo.forecasts ADD macroq_output NVARCHAR(MAX) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='question_def_output')
    ALTER TABLE dbo.forecasts ADD question_def_output NVARCHAR(MAX) NULL;
GO

-- Dedicated probability and recommendation columns.
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='ci_low')
    ALTER TABLE dbo.forecasts ADD ci_low DECIMAL(5,4) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='ci_high')
    ALTER TABLE dbo.forecasts ADD ci_high DECIMAL(5,4) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='base_case_p')
    ALTER TABLE dbo.forecasts ADD base_case_p DECIMAL(5,4) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='recommendation')
    ALTER TABLE dbo.forecasts ADD recommendation VARCHAR(20) NULL;
GO

-- Widen macro_state rationale columns (truncated in _persist_tree).
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.macro_state') AND name='composite_rationale' AND max_length != -1)
    ALTER TABLE dbo.macro_state ALTER COLUMN composite_rationale NVARCHAR(MAX) NULL;
GO
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.macro_state') AND name='node_rationale' AND max_length != -1)
    ALTER TABLE dbo.macro_state ALTER COLUMN node_rationale NVARCHAR(MAX) NULL;
GO
