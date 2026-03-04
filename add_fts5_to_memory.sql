-- Add FTS5 to conversation logs
CREATE VIRTUAL TABLE conversation_logs_fts USING fts5(
    content, 
    agent_name,
    content=conversation_logs,
    tokenize='porter unicode61'
);

-- Populate existing data
INSERT INTO conversation_logs_fts(rowid, content, agent_name)
SELECT id, content, agent_name FROM conversation_logs;

-- Trigger for new conversations
CREATE TRIGGER conv_fts_insert AFTER INSERT ON conversation_logs BEGIN
    INSERT INTO conversation_logs_fts(rowid, content, agent_name)
    VALUES (new.id, new.content, new.agent_name);
END;
