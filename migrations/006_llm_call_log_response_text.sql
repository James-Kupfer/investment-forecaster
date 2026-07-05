-- Store the full raw response text from every LLM call.
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dbo.llm_call_log') AND name = 'response_text'
)
    ALTER TABLE dbo.llm_call_log ADD response_text NVARCHAR(MAX) NULL;
GO
