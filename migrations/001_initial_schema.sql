-- Idempotent schema creation for DMS database.
-- Run via: python scripts/run_migrations.py

-- prompt_registry
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'prompt_registry')
BEGIN
    CREATE TABLE prompt_registry (
        id                INT           IDENTITY(1,1) PRIMARY KEY,
        agent_id          VARCHAR(50)   NOT NULL,
        prompt_version    VARCHAR(20)   NOT NULL,
        prompt_text       NVARCHAR(MAX) NOT NULL,
        authored_by_model VARCHAR(100)  NOT NULL,
        authored_at       DATETIME      NOT NULL DEFAULT GETDATE(),
        is_active         BIT           NOT NULL DEFAULT 1,
        notes             NVARCHAR(MAX) NULL,
        CONSTRAINT UQ_prompt_agent_version UNIQUE (agent_id, prompt_version)
    );
END
GO

-- positions
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'positions')
BEGIN
    CREATE TABLE positions (
        symbol                VARCHAR(20)    NOT NULL PRIMARY KEY,
        us_symbol             VARCHAR(20)    NULL,
        primary_exchange      VARCHAR(20)    NOT NULL,
        name                  VARCHAR(200)   NOT NULL,
        label                 VARCHAR(200)   NULL,
        tags                  VARCHAR(500)   NULL,
        status                VARCHAR(50)    NOT NULL,
        position_direction    VARCHAR(10)    NOT NULL,
        hedge_target_symbol   VARCHAR(20)    NULL,
        type                  VARCHAR(50)    NULL,
        sector                VARCHAR(100)   NULL,
        industry              VARCHAR(100)   NULL,
        macro_node_id         VARCHAR(50)    NULL,
        business              NVARCHAR(MAX)  NULL,
        competitive_landscape NVARCHAR(MAX)  NULL,
        investment_thesis     NVARCHAR(MAX)  NULL,
        risks                 NVARCHAR(MAX)  NULL,
        asymmetric            BIT            NOT NULL DEFAULT 0,
        asymmetric_horizon_cap VARCHAR(20)   NULL,
        horizon               VARCHAR(100)   NULL,
        risk_level            VARCHAR(20)    NULL,
        risk_level_rationale  NVARCHAR(MAX)  NULL,
        profile_confidence    VARCHAR(10)    NULL,
        profile_rationale     NVARCHAR(1000) NULL,
        profile_model         VARCHAR(100)   NULL,
        target_weight         DECIMAL(10,4)  NULL,
        effective_exposure    DECIMAL(10,4)  NULL,
        upside_threshold      DECIMAL(5,4)   NOT NULL DEFAULT 0.20,
        drawdown_threshold    DECIMAL(5,4)   NOT NULL DEFAULT 0.20,
        source_name           VARCHAR(200)   NULL,
        source_link           VARCHAR(500)   NULL,
        change_log            NVARCHAR(MAX)  NULL,
        last_synced_at        DATETIME       NULL
    );
END
GO

-- macro_state
-- parent_node_id is a logical hierarchy ref; no physical FK because node_id is not unique across dates.
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'macro_state')
BEGIN
    CREATE TABLE macro_state (
        id                   INT            IDENTITY(1,1) PRIMARY KEY,
        node_id              VARCHAR(50)    NOT NULL,
        parent_node_id       VARCHAR(50)    NULL,
        macro_date           DATE           NOT NULL,
        composite_score      DECIMAL(5,4)   NOT NULL,
        composite_confidence VARCHAR(10)    NOT NULL,
        composite_rationale  NVARCHAR(1000) NOT NULL,
        rates_signal         VARCHAR(50)    NULL,
        rates_confidence     VARCHAR(10)    NULL,
        dxy_signal           VARCHAR(50)    NULL,
        dxy_confidence       VARCHAR(10)    NULL,
        vix_signal           VARCHAR(50)    NULL,
        vix_confidence       VARCHAR(10)    NULL,
        sector_signal        VARCHAR(50)    NULL,
        sector_confidence    VARCHAR(10)    NULL,
        node_rationale       NVARCHAR(1000) NULL,
        executing_model      VARCHAR(100)   NOT NULL,
        prompt_version_id    INT            NOT NULL,
        CONSTRAINT FK_macro_state_prompt FOREIGN KEY (prompt_version_id)
            REFERENCES prompt_registry(id),
        CONSTRAINT UQ_macro_state_node_date UNIQUE (node_id, macro_date)
    );
END
GO

-- position_catalysts
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'position_catalysts')
BEGIN
    CREATE TABLE position_catalysts (
        id             INT           IDENTITY(1,1) PRIMARY KEY,
        symbol         VARCHAR(20)   NOT NULL,
        catalyst_type  VARCHAR(30)   NOT NULL,
        description    VARCHAR(500)  NULL,
        expected_date  DATE          NULL,
        confidence     VARCHAR(10)   NULL,
        resolved       BIT           NOT NULL DEFAULT 0,
        actual_date    DATE          NULL,
        outcome        NVARCHAR(MAX) NULL,
        sort_order     INT           NULL,
        CONSTRAINT FK_catalysts_symbol FOREIGN KEY (symbol)
            REFERENCES positions(symbol)
    );
END
GO

-- position_sources
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'position_sources')
BEGIN
    CREATE TABLE position_sources (
        id          INT           IDENTITY(1,1) PRIMARY KEY,
        symbol      VARCHAR(20)   NOT NULL,
        source_type VARCHAR(30)   NOT NULL,
        url         VARCHAR(1000) NULL,
        filing_date DATE          NULL,
        ingested_at DATETIME      NOT NULL DEFAULT GETDATE(),
        summary     NVARCHAR(MAX) NULL,
        CONSTRAINT FK_sources_symbol FOREIGN KEY (symbol)
            REFERENCES positions(symbol)
    );
END
GO

-- forecasts
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'forecasts')
BEGIN
    CREATE TABLE forecasts (
        id                             INT            IDENTITY(1,1) PRIMARY KEY,
        symbol                         VARCHAR(20)    NOT NULL,
        forecast_date                  DATE           NOT NULL,
        resolution_date                DATE           NOT NULL,
        position_type                  VARCHAR(50)    NULL,
        invq3_definition               NVARCHAR(MAX)  NULL,
        invq3_definition_confidence    VARCHAR(10)    NULL,
        invq3_definition_rationale     NVARCHAR(1000) NULL,
        invq3_def_model                VARCHAR(100)   NULL,
        invq3_def_prompt_version       INT            NULL,
        macroq_node_id                 VARCHAR(50)    NULL,
        macroq_p                       DECIMAL(5,4)   NULL,
        macroq_confidence              VARCHAR(10)    NULL,
        macroq_rationale               NVARCHAR(1000) NULL,
        risk_judge_output              NVARCHAR(MAX)  NULL,
        invq2_floor                    DECIMAL(5,4)   NULL,
        risk_judge_confidence          VARCHAR(10)    NULL,
        risk_judge_rationale           NVARCHAR(1000) NULL,
        risk_judge_model               VARCHAR(100)   NULL,
        risk_judge_prompt_version      INT            NULL,
        earnings_signal                VARCHAR(200)   NULL,
        earnings_confidence            VARCHAR(10)    NULL,
        earnings_rationale             NVARCHAR(1000) NULL,
        earnings_model                 VARCHAR(100)   NULL,
        earnings_prompt_version        INT            NULL,
        primary_signal                 VARCHAR(200)   NULL,
        primary_confidence             VARCHAR(10)    NULL,
        primary_rationale              NVARCHAR(1000) NULL,
        primary_model                  VARCHAR(100)   NULL,
        primary_prompt_version         INT            NULL,
        momentum_rsi                   DECIMAL(6,2)   NULL,
        momentum_macd                  VARCHAR(50)    NULL,
        momentum_roc                   DECIMAL(6,2)   NULL,
        momentum_signal                VARCHAR(50)    NULL,
        momentum_confidence            VARCHAR(10)    NULL,
        momentum_rationale             NVARCHAR(1000) NULL,
        momentum_model                 VARCHAR(100)   NULL,
        momentum_prompt_version        INT            NULL,
        trend_signal                   VARCHAR(50)    NULL,
        trend_ma_alignment             VARCHAR(200)   NULL,
        trend_confidence               VARCHAR(10)    NULL,
        trend_rationale                NVARCHAR(1000) NULL,
        trend_model                    VARCHAR(100)   NULL,
        trend_prompt_version           INT            NULL,
        volume_signal                  VARCHAR(50)    NULL,
        volume_confidence              VARCHAR(10)    NULL,
        volume_rationale               NVARCHAR(1000) NULL,
        volume_model                   VARCHAR(100)   NULL,
        volume_prompt_version          INT            NULL,
        pattern_signal                 VARCHAR(50)    NULL,
        pattern_key_level              DECIMAL(12,4)  NULL,
        pattern_confidence             VARCHAR(10)    NULL,
        pattern_rationale              NVARCHAR(1000) NULL,
        pattern_model                  VARCHAR(100)   NULL,
        pattern_prompt_version         INT            NULL,
        technical_signal               VARCHAR(50)    NULL,
        technical_key_level            DECIMAL(12,4)  NULL,
        technical_confidence           VARCHAR(10)    NULL,
        technical_rationale            NVARCHAR(1000) NULL,
        technical_judge_model          VARCHAR(100)   NULL,
        technical_judge_prompt_version INT            NULL,
        invq3_p                        DECIMAL(5,4)   NULL,
        invq3_confidence               VARCHAR(10)    NULL,
        invq3_rationale                NVARCHAR(1000) NULL,
        invq3_model                    VARCHAR(100)   NULL,
        invq3_prompt_version           INT            NULL,
        invq1_p                        DECIMAL(5,4)   NULL,
        invq1_confidence               VARCHAR(10)    NULL,
        invq1_rationale                NVARCHAR(1000) NULL,
        invq1_model                    VARCHAR(100)   NULL,
        invq1_prompt_version           INT            NULL,
        invq2_p                        DECIMAL(5,4)   NULL,
        invq2_confidence               VARCHAR(10)    NULL,
        invq2_rationale                NVARCHAR(1000) NULL,
        invq2_model                    VARCHAR(100)   NULL,
        invq2_prompt_version           INT            NULL,
        review_flag                    BIT            NULL,
        review_rationale               NVARCHAR(1000) NULL,
        review_confidence              VARCHAR(10)    NULL,
        review_model                   VARCHAR(100)   NULL,
        review_prompt_version          INT            NULL,
        sizing_haircut                 DECIMAL(5,4)   NULL,
        confidence_rationale           NVARCHAR(1000) NULL,
        confidence_confidence          VARCHAR(10)    NULL,
        confidence_judge_model         VARCHAR(100)   NULL,
        confidence_prompt_version      INT            NULL,
        compound_conviction            DECIMAL(5,4)   NULL,
        asymmetry_ratio                DECIMAL(8,4)   NULL,
        chain_breaker                  BIT            NOT NULL DEFAULT 0,
        catalyst_id                    INT            NULL,
        resolved                       BIT            NOT NULL DEFAULT 0,
        resolved_outcome               NVARCHAR(MAX)  NULL,
        brier_q1                       DECIMAL(8,6)   NULL,
        brier_q2                       DECIMAL(8,6)   NULL,
        brier_q3                       DECIMAL(8,6)   NULL,
        CONSTRAINT FK_forecasts_symbol   FOREIGN KEY (symbol)      REFERENCES positions(symbol),
        CONSTRAINT FK_forecasts_catalyst FOREIGN KEY (catalyst_id) REFERENCES position_catalysts(id)
    );
END
GO

-- llm_call_log
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'llm_call_log')
BEGIN
    CREATE TABLE llm_call_log (
        id                INT           IDENTITY(1,1) PRIMARY KEY,
        forecast_id       INT           NULL,
        macro_state_id    INT           NULL,
        agent_id          VARCHAR(50)   NOT NULL,
        prompt_version_id INT           NOT NULL,
        executing_model   VARCHAR(100)  NOT NULL,
        tokens_in         INT           NOT NULL DEFAULT 0,
        tokens_out        INT           NOT NULL DEFAULT 0,
        tokens_cached     INT           NOT NULL DEFAULT 0,
        call_cost_usd     DECIMAL(10,6) NOT NULL DEFAULT 0,
        called_at         DATETIME      NOT NULL DEFAULT GETDATE(),
        duration_ms       INT           NULL,
        error             VARCHAR(500)  NULL,
        CONSTRAINT FK_log_forecast FOREIGN KEY (forecast_id)       REFERENCES forecasts(id),
        CONSTRAINT FK_log_macro    FOREIGN KEY (macro_state_id)    REFERENCES macro_state(id),
        CONSTRAINT FK_log_prompt   FOREIGN KEY (prompt_version_id) REFERENCES prompt_registry(id)
    );
END
GO

-- agent_weights
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'agent_weights')
BEGIN
    CREATE TABLE agent_weights (
        agent_id         VARCHAR(50)  NOT NULL,
        question_type    VARCHAR(50)  NOT NULL,
        model_id         VARCHAR(100) NOT NULL,
        rolling_accuracy DECIMAL(5,4) NULL,
        sample_size      INT          NOT NULL DEFAULT 0,
        last_updated     DATETIME     NOT NULL DEFAULT GETDATE(),
        CONSTRAINT PK_agent_weights PRIMARY KEY (agent_id, question_type, model_id)
    );
END
GO

-- sync_log
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'sync_log')
BEGIN
    CREATE TABLE sync_log (
        id            INT           IDENTITY(1,1) PRIMARY KEY,
        synced_at     DATETIME      NOT NULL DEFAULT GETDATE(),
        rows_upserted INT           NOT NULL DEFAULT 0,
        source_file   VARCHAR(500)  NULL,
        status        VARCHAR(50)   NOT NULL,
        notes         NVARCHAR(MAX) NULL
    );
END
GO
