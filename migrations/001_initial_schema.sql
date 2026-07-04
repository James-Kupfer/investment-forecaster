-- Create InvestmentForecaster database if it does not exist.
-- Executed with autocommit=True by scripts/run_migrations.py.
IF NOT EXISTS (SELECT 1 FROM sys.databases WHERE name = 'InvestmentForecaster')
    CREATE DATABASE InvestmentForecaster;
GO

USE InvestmentForecaster;
GO

-- prompt_registry: one active prompt per agent_id at a time
IF OBJECT_ID('dbo.prompt_registry', 'U') IS NULL
CREATE TABLE dbo.prompt_registry (
    id                  INT             IDENTITY(1,1)   PRIMARY KEY,
    agent_id            NVARCHAR(100)   NOT NULL,
    version             NVARCHAR(20)    NOT NULL,
    prompt_text         NVARCHAR(MAX)   NOT NULL,
    is_active           BIT             NOT NULL        DEFAULT 0,
    authored_by_model   NVARCHAR(100),
    created_at          DATETIME2                       DEFAULT GETDATE()
);
GO

-- macro_state: tree of macro regime nodes from MacroQAgent
IF OBJECT_ID('dbo.macro_state', 'U') IS NULL
CREATE TABLE dbo.macro_state (
    id                      INT             IDENTITY(1,1)   PRIMARY KEY,
    node_id                 NVARCHAR(100)   NOT NULL        UNIQUE,
    parent_node_id          NVARCHAR(100),
    macro_date              DATE            NOT NULL,
    composite_score         FLOAT,
    composite_confidence    NVARCHAR(20),
    composite_rationale     NVARCHAR(1000),
    rates_signal            NVARCHAR(50),
    rates_confidence        NVARCHAR(20),
    dxy_signal              NVARCHAR(50),
    dxy_confidence          NVARCHAR(20),
    vix_signal              NVARCHAR(50),
    vix_confidence          NVARCHAR(20),
    sector_signal           NVARCHAR(50),
    sector_confidence       NVARCHAR(20),
    node_rationale          NVARCHAR(1000),
    executing_model         NVARCHAR(100),
    prompt_version_id       INT,
    created_at              DATETIME2                       DEFAULT GETDATE()
);
GO

-- forecasts: partial row inserted at pipeline start; columns filled incrementally
IF OBJECT_ID('dbo.forecasts', 'U') IS NULL
CREATE TABLE dbo.forecasts (
    id                  INT             IDENTITY(1,1)   PRIMARY KEY,
    symbol              NVARCHAR(20)    NOT NULL,
    forecast_date       DATE            NOT NULL,
    resolution_date     DATE,
    -- MacroQ
    macroq_node_id      NVARCHAR(50),
    macroq_p            FLOAT,
    macroq_confidence   NVARCHAR(20),
    macroq_rationale    NVARCHAR(1000),
    -- Aggregation (invq1 = upside, invq2 = downside)
    invq1_p                 FLOAT,
    invq1_confidence        NVARCHAR(20),
    invq1_rationale         NVARCHAR(1000),
    invq1_model             NVARCHAR(100),
    invq1_prompt_version    INT,
    invq2_p                 FLOAT,
    invq2_confidence        NVARCHAR(20),
    invq2_rationale         NVARCHAR(1000),
    invq2_model             NVARCHAR(100),
    invq2_prompt_version    INT,
    compound_conviction     FLOAT,
    asymmetry_ratio         FLOAT,
    -- Resolution / Brier
    resolution_price        FLOAT,
    brier_score             FLOAT,
    created_at              DATETIME2   DEFAULT GETDATE()
);
GO

-- llm_call_log: every Anthropic API call logged immediately (never batched)
IF OBJECT_ID('dbo.llm_call_log', 'U') IS NULL
CREATE TABLE dbo.llm_call_log (
    id                  INT             IDENTITY(1,1)   PRIMARY KEY,
    forecast_id         INT,
    macro_state_id      INT,
    agent_id            NVARCHAR(100)   NOT NULL,
    prompt_version_id   INT,
    executing_model     NVARCHAR(100),
    tokens_in           INT             DEFAULT 0,
    tokens_out          INT             DEFAULT 0,
    tokens_cached       INT             DEFAULT 0,
    call_cost_usd       FLOAT,
    duration_ms         INT,
    error               NVARCHAR(MAX),
    created_at          DATETIME2       DEFAULT GETDATE()
);
GO

-- agent_weights: calibration weights updated by Brier scoring
IF OBJECT_ID('dbo.agent_weights', 'U') IS NULL
CREATE TABLE dbo.agent_weights (
    agent_id    NVARCHAR(100)   NOT NULL    PRIMARY KEY,
    weight      FLOAT           NOT NULL    DEFAULT 1.0,
    updated_at  DATETIME2                   DEFAULT GETDATE()
);
GO

-- position_catalysts: catalysts tracked per symbol
IF OBJECT_ID('dbo.position_catalysts', 'U') IS NULL
CREATE TABLE dbo.position_catalysts (
    id              INT             IDENTITY(1,1)   PRIMARY KEY,
    symbol          NVARCHAR(20)    NOT NULL,
    catalyst        NVARCHAR(MAX)   NOT NULL,
    catalyst_date   DATE,
    created_at      DATETIME2                       DEFAULT GETDATE()
);
GO

-- position_sources: research sources per symbol
IF OBJECT_ID('dbo.position_sources', 'U') IS NULL
CREATE TABLE dbo.position_sources (
    id          INT             IDENTITY(1,1)   PRIMARY KEY,
    symbol      NVARCHAR(20)    NOT NULL,
    source_name NVARCHAR(200),
    url         NVARCHAR(500),
    summary     NVARCHAR(MAX),
    created_at  DATETIME2                       DEFAULT GETDATE()
);
GO

-- sync_log: tracks pipeline sync runs
IF OBJECT_ID('dbo.sync_log', 'U') IS NULL
CREATE TABLE dbo.sync_log (
    id                  INT             IDENTITY(1,1)   PRIMARY KEY,
    source              NVARCHAR(100)   NOT NULL,
    records_processed   INT             DEFAULT 0,
    records_inserted    INT             DEFAULT 0,
    records_updated     INT             DEFAULT 0,
    records_errors      INT             DEFAULT 0,
    run_at              DATETIME2       DEFAULT GETDATE()
);
GO
