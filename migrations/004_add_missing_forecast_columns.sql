-- Add all agent output columns to forecasts that may be missing on pre-migration tables.
-- Each block is idempotent via sys.columns check.

-- question_definition
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq3_definition')
    ALTER TABLE dbo.forecasts ADD invq3_definition NVARCHAR(MAX) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq3_definition_confidence')
    ALTER TABLE dbo.forecasts ADD invq3_definition_confidence VARCHAR(10) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq3_definition_rationale')
    ALTER TABLE dbo.forecasts ADD invq3_definition_rationale NVARCHAR(1000) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq3_def_model')
    ALTER TABLE dbo.forecasts ADD invq3_def_model VARCHAR(100) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq3_def_prompt_version')
    ALTER TABLE dbo.forecasts ADD invq3_def_prompt_version INT NULL;
GO

-- macroq
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='macroq_node_id')
    ALTER TABLE dbo.forecasts ADD macroq_node_id VARCHAR(50) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='macroq_p')
    ALTER TABLE dbo.forecasts ADD macroq_p DECIMAL(5,4) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='macroq_confidence')
    ALTER TABLE dbo.forecasts ADD macroq_confidence VARCHAR(10) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='macroq_rationale')
    ALTER TABLE dbo.forecasts ADD macroq_rationale NVARCHAR(1000) NULL;
GO

-- risk_judge
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='risk_judge_output')
    ALTER TABLE dbo.forecasts ADD risk_judge_output NVARCHAR(MAX) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq2_floor')
    ALTER TABLE dbo.forecasts ADD invq2_floor DECIMAL(5,4) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='risk_judge_confidence')
    ALTER TABLE dbo.forecasts ADD risk_judge_confidence VARCHAR(10) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='risk_judge_rationale')
    ALTER TABLE dbo.forecasts ADD risk_judge_rationale NVARCHAR(1000) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='risk_judge_model')
    ALTER TABLE dbo.forecasts ADD risk_judge_model VARCHAR(100) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='risk_judge_prompt_version')
    ALTER TABLE dbo.forecasts ADD risk_judge_prompt_version INT NULL;
GO

-- earnings
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='earnings_signal')
    ALTER TABLE dbo.forecasts ADD earnings_signal VARCHAR(200) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='earnings_confidence')
    ALTER TABLE dbo.forecasts ADD earnings_confidence VARCHAR(10) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='earnings_rationale')
    ALTER TABLE dbo.forecasts ADD earnings_rationale NVARCHAR(1000) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='earnings_model')
    ALTER TABLE dbo.forecasts ADD earnings_model VARCHAR(100) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='earnings_prompt_version')
    ALTER TABLE dbo.forecasts ADD earnings_prompt_version INT NULL;
GO

-- primary_source
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='primary_signal')
    ALTER TABLE dbo.forecasts ADD primary_signal VARCHAR(200) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='primary_confidence')
    ALTER TABLE dbo.forecasts ADD primary_confidence VARCHAR(10) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='primary_rationale')
    ALTER TABLE dbo.forecasts ADD primary_rationale NVARCHAR(1000) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='primary_model')
    ALTER TABLE dbo.forecasts ADD primary_model VARCHAR(100) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='primary_prompt_version')
    ALTER TABLE dbo.forecasts ADD primary_prompt_version INT NULL;
GO

-- momentum
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='momentum_rsi')
    ALTER TABLE dbo.forecasts ADD momentum_rsi DECIMAL(6,2) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='momentum_macd')
    ALTER TABLE dbo.forecasts ADD momentum_macd VARCHAR(50) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='momentum_roc')
    ALTER TABLE dbo.forecasts ADD momentum_roc DECIMAL(6,2) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='momentum_signal')
    ALTER TABLE dbo.forecasts ADD momentum_signal VARCHAR(50) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='momentum_confidence')
    ALTER TABLE dbo.forecasts ADD momentum_confidence VARCHAR(10) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='momentum_rationale')
    ALTER TABLE dbo.forecasts ADD momentum_rationale NVARCHAR(1000) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='momentum_model')
    ALTER TABLE dbo.forecasts ADD momentum_model VARCHAR(100) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='momentum_prompt_version')
    ALTER TABLE dbo.forecasts ADD momentum_prompt_version INT NULL;
GO

-- trend
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='trend_signal')
    ALTER TABLE dbo.forecasts ADD trend_signal VARCHAR(50) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='trend_ma_alignment')
    ALTER TABLE dbo.forecasts ADD trend_ma_alignment VARCHAR(200) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='trend_confidence')
    ALTER TABLE dbo.forecasts ADD trend_confidence VARCHAR(10) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='trend_rationale')
    ALTER TABLE dbo.forecasts ADD trend_rationale NVARCHAR(1000) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='trend_model')
    ALTER TABLE dbo.forecasts ADD trend_model VARCHAR(100) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='trend_prompt_version')
    ALTER TABLE dbo.forecasts ADD trend_prompt_version INT NULL;
GO

-- volume
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='volume_signal')
    ALTER TABLE dbo.forecasts ADD volume_signal VARCHAR(50) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='volume_confidence')
    ALTER TABLE dbo.forecasts ADD volume_confidence VARCHAR(10) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='volume_rationale')
    ALTER TABLE dbo.forecasts ADD volume_rationale NVARCHAR(1000) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='volume_model')
    ALTER TABLE dbo.forecasts ADD volume_model VARCHAR(100) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='volume_prompt_version')
    ALTER TABLE dbo.forecasts ADD volume_prompt_version INT NULL;
GO

-- pattern
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='pattern_signal')
    ALTER TABLE dbo.forecasts ADD pattern_signal VARCHAR(50) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='pattern_key_level')
    ALTER TABLE dbo.forecasts ADD pattern_key_level DECIMAL(12,4) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='pattern_confidence')
    ALTER TABLE dbo.forecasts ADD pattern_confidence VARCHAR(10) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='pattern_rationale')
    ALTER TABLE dbo.forecasts ADD pattern_rationale NVARCHAR(1000) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='pattern_model')
    ALTER TABLE dbo.forecasts ADD pattern_model VARCHAR(100) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='pattern_prompt_version')
    ALTER TABLE dbo.forecasts ADD pattern_prompt_version INT NULL;
GO

-- tech_judge
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='technical_signal')
    ALTER TABLE dbo.forecasts ADD technical_signal VARCHAR(50) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='technical_key_level')
    ALTER TABLE dbo.forecasts ADD technical_key_level DECIMAL(12,4) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='technical_confidence')
    ALTER TABLE dbo.forecasts ADD technical_confidence VARCHAR(10) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='technical_rationale')
    ALTER TABLE dbo.forecasts ADD technical_rationale NVARCHAR(1000) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='technical_judge_model')
    ALTER TABLE dbo.forecasts ADD technical_judge_model VARCHAR(100) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='technical_judge_prompt_version')
    ALTER TABLE dbo.forecasts ADD technical_judge_prompt_version INT NULL;
GO

-- elicitation
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq3_p')
    ALTER TABLE dbo.forecasts ADD invq3_p DECIMAL(5,4) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq3_confidence')
    ALTER TABLE dbo.forecasts ADD invq3_confidence VARCHAR(10) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq3_rationale')
    ALTER TABLE dbo.forecasts ADD invq3_rationale NVARCHAR(1000) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq3_model')
    ALTER TABLE dbo.forecasts ADD invq3_model VARCHAR(100) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq3_prompt_version')
    ALTER TABLE dbo.forecasts ADD invq3_prompt_version INT NULL;
GO

-- review
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='review_flag')
    ALTER TABLE dbo.forecasts ADD review_flag BIT NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='review_rationale')
    ALTER TABLE dbo.forecasts ADD review_rationale NVARCHAR(1000) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='review_confidence')
    ALTER TABLE dbo.forecasts ADD review_confidence VARCHAR(10) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='review_model')
    ALTER TABLE dbo.forecasts ADD review_model VARCHAR(100) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='review_prompt_version')
    ALTER TABLE dbo.forecasts ADD review_prompt_version INT NULL;
GO

-- confidence_judge
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='sizing_haircut')
    ALTER TABLE dbo.forecasts ADD sizing_haircut DECIMAL(5,4) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='confidence_rationale')
    ALTER TABLE dbo.forecasts ADD confidence_rationale NVARCHAR(1000) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='confidence_confidence')
    ALTER TABLE dbo.forecasts ADD confidence_confidence VARCHAR(10) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='confidence_judge_model')
    ALTER TABLE dbo.forecasts ADD confidence_judge_model VARCHAR(100) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='confidence_prompt_version')
    ALTER TABLE dbo.forecasts ADD confidence_prompt_version INT NULL;
GO

-- aggregation
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq1_p')
    ALTER TABLE dbo.forecasts ADD invq1_p DECIMAL(5,4) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq1_confidence')
    ALTER TABLE dbo.forecasts ADD invq1_confidence VARCHAR(10) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq1_rationale')
    ALTER TABLE dbo.forecasts ADD invq1_rationale NVARCHAR(1000) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq1_model')
    ALTER TABLE dbo.forecasts ADD invq1_model VARCHAR(100) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq1_prompt_version')
    ALTER TABLE dbo.forecasts ADD invq1_prompt_version INT NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq2_p')
    ALTER TABLE dbo.forecasts ADD invq2_p DECIMAL(5,4) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq2_confidence')
    ALTER TABLE dbo.forecasts ADD invq2_confidence VARCHAR(10) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq2_rationale')
    ALTER TABLE dbo.forecasts ADD invq2_rationale NVARCHAR(1000) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq2_model')
    ALTER TABLE dbo.forecasts ADD invq2_model VARCHAR(100) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='invq2_prompt_version')
    ALTER TABLE dbo.forecasts ADD invq2_prompt_version INT NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='compound_conviction')
    ALTER TABLE dbo.forecasts ADD compound_conviction DECIMAL(5,4) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='asymmetry_ratio')
    ALTER TABLE dbo.forecasts ADD asymmetry_ratio DECIMAL(8,4) NULL;
GO

-- resolution
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='resolved')
    ALTER TABLE dbo.forecasts ADD resolved BIT NOT NULL DEFAULT 0;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='resolved_outcome')
    ALTER TABLE dbo.forecasts ADD resolved_outcome NVARCHAR(MAX) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='brier_q1')
    ALTER TABLE dbo.forecasts ADD brier_q1 DECIMAL(8,6) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='brier_q2')
    ALTER TABLE dbo.forecasts ADD brier_q2 DECIMAL(8,6) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.forecasts') AND name='brier_q3')
    ALTER TABLE dbo.forecasts ADD brier_q3 DECIMAL(8,6) NULL;
GO
