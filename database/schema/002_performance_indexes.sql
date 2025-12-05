-- ===========================================
-- AI WORKFORCE PLATFORM - PERFORMANCE INDEXES
-- Version: 2.0.1
-- Purpose: Add missing indexes for common query patterns
-- ===========================================

-- ===========================================
-- AGENTS TABLE INDEXES
-- ===========================================

-- Composite index for agent status queries with soft delete
CREATE INDEX IF NOT EXISTS idx_agents_status_not_deleted
    ON agents (status, is_deleted)
    WHERE is_deleted = FALSE;

-- Index for agent capability matching (GIN for JSONB containment)
CREATE INDEX IF NOT EXISTS idx_agents_capabilities_gin
    ON agents USING GIN (capabilities);

-- Index for agent specializations
CREATE INDEX IF NOT EXISTS idx_agents_specializations_gin
    ON agents USING GIN (specializations);

-- Index for finding available agents by platform
CREATE INDEX IF NOT EXISTS idx_agents_active_platform
    ON agents (status, created_at DESC)
    WHERE status IN ('active', 'available') AND is_deleted = FALSE;

-- Index for agent success rate queries
CREATE INDEX IF NOT EXISTS idx_agents_success_rate
    ON agents (success_rate DESC)
    WHERE jobs_completed > 0 AND is_deleted = FALSE;

-- ===========================================
-- DISCOVERED_JOBS TABLE INDEXES
-- ===========================================

-- Composite index for duplicate job detection (critical for scanning)
CREATE INDEX IF NOT EXISTS idx_jobs_platform_external_id
    ON discovered_jobs (platform, platform_job_id);

-- Index for job scoring queries
CREATE INDEX IF NOT EXISTS idx_jobs_score_status
    ON discovered_jobs (score DESC, status)
    WHERE is_deleted = FALSE;

-- Index for finding jobs by status
CREATE INDEX IF NOT EXISTS idx_jobs_status_created
    ON discovered_jobs (status, created_at DESC)
    WHERE is_deleted = FALSE;

-- GIN index for job skills/tags matching
CREATE INDEX IF NOT EXISTS idx_jobs_required_skills_gin
    ON discovered_jobs USING GIN (required_skills);

-- Index for budget range queries
CREATE INDEX IF NOT EXISTS idx_jobs_budget_range
    ON discovered_jobs (budget_min, budget_max)
    WHERE status IN ('discovered', 'scored', 'queued');

-- ===========================================
-- ACTIVE_JOBS TABLE INDEXES
-- ===========================================

-- Index for finding jobs by agent
CREATE INDEX IF NOT EXISTS idx_active_jobs_agent_status
    ON active_jobs (agent_id, status)
    WHERE is_deleted = FALSE;

-- Index for deadline monitoring
CREATE INDEX IF NOT EXISTS idx_active_jobs_deadline
    ON active_jobs (deadline)
    WHERE status = 'in_progress';

-- ===========================================
-- PROPOSALS TABLE INDEXES
-- ===========================================

-- Index for finding proposals by job
CREATE INDEX IF NOT EXISTS idx_proposals_job_status
    ON proposals (job_id, status);

-- Index for finding proposals by agent
CREATE INDEX IF NOT EXISTS idx_proposals_agent_created
    ON proposals (agent_id, created_at DESC);

-- Index for A/B testing analysis
CREATE INDEX IF NOT EXISTS idx_proposals_variant
    ON proposals (variant_id, status)
    WHERE variant_id IS NOT NULL;

-- ===========================================
-- MESSAGES TABLE INDEXES
-- ===========================================

-- Composite index for conversation message retrieval
CREATE INDEX IF NOT EXISTS idx_messages_conversation_direction_created
    ON messages (conversation_id, direction, created_at DESC);

-- Index for unread messages
CREATE INDEX IF NOT EXISTS idx_messages_unread
    ON messages (conversation_id, is_read)
    WHERE is_read = FALSE;

-- Index for sentiment analysis queries
CREATE INDEX IF NOT EXISTS idx_messages_sentiment
    ON messages (sentiment_score)
    WHERE sentiment_score IS NOT NULL;

-- ===========================================
-- CONVERSATIONS TABLE INDEXES
-- ===========================================

-- Index for finding active conversations by agent
CREATE INDEX IF NOT EXISTS idx_conversations_agent_status
    ON conversations (agent_id, status)
    WHERE status IN ('active', 'waiting_agent', 'waiting_client');

-- Index for client lookup
CREATE INDEX IF NOT EXISTS idx_conversations_client_platform
    ON conversations (client_id, client_platform);

-- Index for priority conversations
CREATE INDEX IF NOT EXISTS idx_conversations_priority
    ON conversations (is_priority, last_message_at DESC)
    WHERE requires_attention = TRUE;

-- ===========================================
-- SAFETY_INCIDENTS TABLE INDEXES
-- ===========================================

-- Index for agent incident history
CREATE INDEX IF NOT EXISTS idx_safety_incidents_agent_created
    ON safety_incidents (agent_id, created_at DESC)
    WHERE is_resolved = FALSE;

-- Index for unresolved incidents by risk level
CREATE INDEX IF NOT EXISTS idx_safety_incidents_risk_unresolved
    ON safety_incidents (risk_level, created_at DESC)
    WHERE is_resolved = FALSE;

-- ===========================================
-- QUALITY_REPORTS TABLE INDEXES
-- ===========================================

-- Index for job quality reports
CREATE INDEX IF NOT EXISTS idx_quality_reports_job
    ON quality_reports (job_id, created_at DESC);

-- Index for reports requiring review
CREATE INDEX IF NOT EXISTS idx_quality_reports_review
    ON quality_reports (manual_review_required, status)
    WHERE manual_review_required = TRUE;

-- ===========================================
-- PARTIAL INDEXES FOR COMMON FILTERS
-- ===========================================

-- Partial index for non-deleted agents
CREATE INDEX IF NOT EXISTS idx_agents_active_not_deleted
    ON agents (id)
    WHERE is_deleted = FALSE;

-- Partial index for pending jobs
CREATE INDEX IF NOT EXISTS idx_jobs_pending
    ON discovered_jobs (created_at DESC)
    WHERE status = 'pending' AND is_deleted = FALSE;

-- Partial index for in-progress jobs
CREATE INDEX IF NOT EXISTS idx_jobs_in_progress
    ON active_jobs (agent_id, deadline)
    WHERE status = 'in_progress';

-- ===========================================
-- FULL TEXT SEARCH INDEXES
-- ===========================================

-- Full text search on job titles and descriptions
CREATE INDEX IF NOT EXISTS idx_jobs_fulltext
    ON discovered_jobs USING GIN (to_tsvector('english', title || ' ' || COALESCE(description, '')));

-- Full text search on message content
CREATE INDEX IF NOT EXISTS idx_messages_fulltext
    ON messages USING GIN (to_tsvector('english', content));

-- ===========================================
-- ANALYZE TABLES FOR QUERY PLANNER
-- ===========================================

ANALYZE agents;
ANALYZE discovered_jobs;
ANALYZE active_jobs;
ANALYZE proposals;
ANALYZE messages;
ANALYZE conversations;
ANALYZE safety_incidents;
ANALYZE quality_reports;
