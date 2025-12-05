-- ===========================================
-- AI WORKFORCE PLATFORM - INITIAL SCHEMA
-- Version: 2.0 (10x Enhanced Edition)
-- ===========================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For fuzzy text search
CREATE EXTENSION IF NOT EXISTS "vector";   -- For ML embeddings (pgvector)

-- ===========================================
-- ENUMS
-- ===========================================

CREATE TYPE agent_status AS ENUM (
    'active',
    'paused',
    'suspended',
    'training',
    'retired'
);

CREATE TYPE job_status AS ENUM (
    'discovered',
    'scored',
    'queued',
    'applied',
    'interviewing',
    'won',
    'in_progress',
    'delivered',
    'completed',
    'rejected',
    'expired',
    'cancelled',
    'disputed'
);

CREATE TYPE proposal_status AS ENUM (
    'draft',
    'submitted',
    'viewed',
    'shortlisted',
    'accepted',
    'rejected',
    'withdrawn'
);

CREATE TYPE message_direction AS ENUM (
    'incoming',
    'outgoing'
);

CREATE TYPE message_intent AS ENUM (
    'greeting',
    'question',
    'clarification',
    'negotiation',
    'acceptance',
    'rejection',
    'revision_request',
    'feedback',
    'complaint',
    'payment_discussion',
    'other'
);

CREATE TYPE payment_status AS ENUM (
    'pending',
    'processing',
    'completed',
    'disputed',
    'refunded',
    'cancelled'
);

CREATE TYPE qa_status AS ENUM (
    'pending',
    'passed',
    'failed',
    'needs_revision'
);

-- ===========================================
-- AGENTS TABLE
-- ===========================================

CREATE TABLE agents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Identity
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    persona_description TEXT,
    avatar_url TEXT,

    -- Capabilities (stored as JSONB for flexibility)
    capabilities JSONB NOT NULL DEFAULT '[]',
    specializations JSONB DEFAULT '[]',

    -- Performance metrics
    hourly_rate DECIMAL(8,2) DEFAULT 25.00,
    min_project_value DECIMAL(10,2) DEFAULT 50.00,
    success_rate DECIMAL(5,4) DEFAULT 0.0,
    average_rating DECIMAL(3,2) DEFAULT 0.0,
    total_ratings INTEGER DEFAULT 0,
    total_earnings DECIMAL(14,2) DEFAULT 0.00,
    jobs_completed INTEGER DEFAULT 0,
    jobs_failed INTEGER DEFAULT 0,

    -- Behavior configuration
    timezone VARCHAR(50) DEFAULT 'UTC',
    working_hours JSONB DEFAULT '{"start": 9, "end": 17, "days": [1,2,3,4,5]}',
    response_delay_range JSONB DEFAULT '{"min": 60, "max": 300}',
    writing_style JSONB DEFAULT '{}',

    -- Status
    status agent_status DEFAULT 'active',
    status_reason TEXT,

    -- ML/Learning
    embedding vector(1536),  -- For similarity matching
    learning_data JSONB DEFAULT '{}',

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_active_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    is_deleted BOOLEAN DEFAULT FALSE,

    -- Versioning
    version INTEGER DEFAULT 1,
    metadata_json JSONB
);

CREATE INDEX idx_agents_status ON agents(status) WHERE NOT is_deleted;
CREATE INDEX idx_agents_capabilities ON agents USING GIN(capabilities);
CREATE INDEX idx_agents_success_rate ON agents(success_rate DESC) WHERE status = 'active';
CREATE INDEX idx_agents_embedding ON agents USING ivfflat (embedding vector_cosine_ops);

-- ===========================================
-- AGENT PLATFORM PROFILES
-- ===========================================

CREATE TABLE agent_platform_profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,

    -- Platform info
    platform VARCHAR(50) NOT NULL,
    platform_user_id VARCHAR(255),
    username VARCHAR(100),
    profile_url TEXT,

    -- Platform-specific data
    profile_data JSONB DEFAULT '{}',
    credentials_encrypted BYTEA,  -- Encrypted with pgcrypto

    -- Performance on this platform
    earnings_on_platform DECIMAL(12,2) DEFAULT 0.00,
    jobs_on_platform INTEGER DEFAULT 0,
    rating_on_platform DECIMAL(3,2),
    reviews_count INTEGER DEFAULT 0,

    -- Status
    status VARCHAR(20) DEFAULT 'active',
    verified BOOLEAN DEFAULT FALSE,
    last_login_at TIMESTAMPTZ,

    -- Risk tracking
    warning_count INTEGER DEFAULT 0,
    last_warning_at TIMESTAMPTZ,
    restriction_level INTEGER DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(agent_id, platform)
);

CREATE INDEX idx_platform_profiles_platform ON agent_platform_profiles(platform);
CREATE INDEX idx_platform_profiles_agent ON agent_platform_profiles(agent_id);

-- ===========================================
-- AGENT PORTFOLIO
-- ===========================================

CREATE TABLE agent_portfolio (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,

    -- Portfolio item details
    title VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100),
    skills_demonstrated JSONB DEFAULT '[]',

    -- Files
    file_url TEXT,
    thumbnail_url TEXT,
    file_type VARCHAR(50),

    -- Generated or real
    is_generated BOOLEAN DEFAULT FALSE,
    generation_prompt TEXT,

    -- Display settings
    display_order INTEGER DEFAULT 0,
    is_featured BOOLEAN DEFAULT FALSE,
    is_public BOOLEAN DEFAULT TRUE,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_portfolio_agent ON agent_portfolio(agent_id);
CREATE INDEX idx_portfolio_category ON agent_portfolio(category);

-- ===========================================
-- DISCOVERED JOBS
-- ===========================================

CREATE TABLE discovered_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Source info
    platform VARCHAR(50) NOT NULL,
    platform_job_id VARCHAR(255) NOT NULL,
    source_url TEXT,

    -- Job details
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category VARCHAR(100),
    subcategory VARCHAR(100),

    -- Budget
    budget_min DECIMAL(10,2),
    budget_max DECIMAL(10,2),
    budget_type VARCHAR(20),  -- 'fixed', 'hourly', 'monthly'
    currency VARCHAR(3) DEFAULT 'USD',

    -- Requirements
    skills_required JSONB DEFAULT '[]',
    experience_level VARCHAR(50),
    estimated_hours DECIMAL(6,2),
    estimated_duration VARCHAR(50),

    -- Client info
    client_id VARCHAR(255),
    client_name VARCHAR(255),
    client_country VARCHAR(100),
    client_rating DECIMAL(3,2),
    client_reviews_count INTEGER,
    client_total_spent DECIMAL(14,2),
    client_jobs_posted INTEGER,
    client_hire_rate DECIMAL(5,4),

    -- Competition
    applicant_count INTEGER DEFAULT 0,
    interview_count INTEGER DEFAULT 0,

    -- Scoring
    score DECIMAL(5,4),
    score_breakdown JSONB,
    ml_success_probability DECIMAL(5,4),
    estimated_profit_margin DECIMAL(5,4),

    -- Matching
    matched_capabilities JSONB DEFAULT '[]',
    embedding vector(1536),

    -- Status
    status job_status DEFAULT 'discovered',
    assigned_agent_id UUID REFERENCES agents(id),

    -- Timing
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    posted_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    applied_at TIMESTAMPTZ,
    won_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Metadata
    raw_data JSONB,
    metadata_json JSONB,

    UNIQUE(platform, platform_job_id)
);

CREATE INDEX idx_jobs_status ON discovered_jobs(status);
CREATE INDEX idx_jobs_platform ON discovered_jobs(platform);
CREATE INDEX idx_jobs_score ON discovered_jobs(score DESC) WHERE status IN ('discovered', 'scored', 'queued');
CREATE INDEX idx_jobs_assigned_agent ON discovered_jobs(assigned_agent_id);
CREATE INDEX idx_jobs_category ON discovered_jobs(category);
CREATE INDEX idx_jobs_skills ON discovered_jobs USING GIN(skills_required);
CREATE INDEX idx_jobs_embedding ON discovered_jobs USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_jobs_discovered_at ON discovered_jobs(discovered_at DESC);

-- ===========================================
-- PROPOSALS
-- ===========================================

CREATE TABLE proposals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID NOT NULL REFERENCES discovered_jobs(id),
    agent_id UUID NOT NULL REFERENCES agents(id),

    -- Proposal content
    cover_letter TEXT NOT NULL,
    bid_amount DECIMAL(10,2) NOT NULL,
    bid_type VARCHAR(20),  -- 'fixed', 'hourly'
    estimated_duration VARCHAR(100),
    milestones JSONB DEFAULT '[]',

    -- Questions/answers
    questions_answered JSONB DEFAULT '[]',
    attachments JSONB DEFAULT '[]',

    -- A/B Testing
    variant_id VARCHAR(50),
    template_used VARCHAR(100),

    -- Status
    status proposal_status DEFAULT 'draft',
    client_viewed_at TIMESTAMPTZ,
    client_response TEXT,

    -- Performance tracking
    response_time_seconds INTEGER,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    submitted_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Metadata
    generation_metadata JSONB,

    UNIQUE(job_id, agent_id)
);

CREATE INDEX idx_proposals_job ON proposals(job_id);
CREATE INDEX idx_proposals_agent ON proposals(agent_id);
CREATE INDEX idx_proposals_status ON proposals(status);
CREATE INDEX idx_proposals_variant ON proposals(variant_id);

-- ===========================================
-- ACTIVE JOBS (Jobs we've won and are working on)
-- ===========================================

CREATE TABLE active_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    discovered_job_id UUID NOT NULL REFERENCES discovered_jobs(id),
    agent_id UUID NOT NULL REFERENCES agents(id),
    proposal_id UUID REFERENCES proposals(id),

    -- Contract details
    contract_id VARCHAR(255),
    contract_type VARCHAR(50),
    agreed_amount DECIMAL(10,2) NOT NULL,
    agreed_hours DECIMAL(6,2),

    -- Progress
    progress_percentage DECIMAL(5,2) DEFAULT 0,
    current_milestone INTEGER DEFAULT 0,
    milestones JSONB DEFAULT '[]',

    -- Deliverables
    deliverables JSONB DEFAULT '[]',

    -- Time tracking
    hours_logged DECIMAL(8,2) DEFAULT 0,

    -- Status
    status job_status DEFAULT 'in_progress',
    client_satisfied BOOLEAN,

    -- Revisions
    revision_count INTEGER DEFAULT 0,
    max_revisions INTEGER DEFAULT 3,

    -- Timestamps
    started_at TIMESTAMPTZ DEFAULT NOW(),
    deadline_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Execution data
    execution_log JSONB DEFAULT '[]',
    metadata_json JSONB
);

CREATE INDEX idx_active_jobs_agent ON active_jobs(agent_id);
CREATE INDEX idx_active_jobs_status ON active_jobs(status);
CREATE INDEX idx_active_jobs_deadline ON active_jobs(deadline_at) WHERE status = 'in_progress';

-- ===========================================
-- MESSAGES
-- ===========================================

CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Participants
    agent_id UUID NOT NULL REFERENCES agents(id),
    job_id UUID REFERENCES discovered_jobs(id),
    active_job_id UUID REFERENCES active_jobs(id),

    -- Platform info
    platform VARCHAR(50) NOT NULL,
    platform_message_id VARCHAR(255),
    platform_conversation_id VARCHAR(255),

    -- Message content
    direction message_direction NOT NULL,
    content TEXT NOT NULL,
    attachments JSONB DEFAULT '[]',

    -- Analysis
    intent message_intent,
    sentiment_score DECIMAL(4,3),  -- -1 to 1
    urgency_level INTEGER DEFAULT 0,  -- 0-10

    -- Response tracking
    response_to_id UUID REFERENCES messages(id),
    response_time_seconds INTEGER,

    -- Status
    is_read BOOLEAN DEFAULT FALSE,
    requires_response BOOLEAN DEFAULT FALSE,
    responded_at TIMESTAMPTZ,

    -- Timestamps
    sent_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Metadata
    raw_data JSONB,
    metadata_json JSONB
);

CREATE INDEX idx_messages_agent ON messages(agent_id);
CREATE INDEX idx_messages_job ON messages(job_id);
CREATE INDEX idx_messages_conversation ON messages(platform_conversation_id);
CREATE INDEX idx_messages_requires_response ON messages(requires_response) WHERE requires_response = TRUE;
CREATE INDEX idx_messages_sent_at ON messages(sent_at DESC);

-- ===========================================
-- QUALITY CHECKS
-- ===========================================

CREATE TABLE quality_checks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    active_job_id UUID NOT NULL REFERENCES active_jobs(id),

    -- Check type
    check_type VARCHAR(50) NOT NULL,  -- 'plagiarism', 'ai_detection', 'grammar', 'completeness', etc.

    -- Results
    status qa_status DEFAULT 'pending',
    score DECIMAL(5,4),
    passed BOOLEAN,

    -- Details
    issues JSONB DEFAULT '[]',
    suggestions JSONB DEFAULT '[]',

    -- Service used
    service_used VARCHAR(100),
    service_response JSONB,

    -- Timestamps
    checked_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_qa_checks_job ON quality_checks(active_job_id);
CREATE INDEX idx_qa_checks_status ON quality_checks(status);

-- ===========================================
-- EARNINGS & PAYMENTS
-- ===========================================

CREATE TABLE earnings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id UUID NOT NULL REFERENCES agents(id),
    active_job_id UUID REFERENCES active_jobs(id),

    -- Platform info
    platform VARCHAR(50) NOT NULL,
    platform_transaction_id VARCHAR(255),

    -- Amounts
    gross_amount DECIMAL(12,2) NOT NULL,
    platform_fee DECIMAL(12,2) DEFAULT 0,
    processing_fee DECIMAL(12,2) DEFAULT 0,
    net_amount DECIMAL(12,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',

    -- Status
    status payment_status DEFAULT 'pending',

    -- Timing
    earned_at TIMESTAMPTZ,
    available_at TIMESTAMPTZ,
    paid_at TIMESTAMPTZ,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Metadata
    metadata_json JSONB
);

CREATE INDEX idx_earnings_agent ON earnings(agent_id);
CREATE INDEX idx_earnings_platform ON earnings(platform);
CREATE INDEX idx_earnings_status ON earnings(status);
CREATE INDEX idx_earnings_earned_at ON earnings(earned_at DESC);

-- ===========================================
-- COSTS
-- ===========================================

CREATE TABLE costs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id UUID REFERENCES agents(id),
    active_job_id UUID REFERENCES active_jobs(id),

    -- Cost type
    cost_type VARCHAR(50) NOT NULL,  -- 'llm_api', 'captcha', 'proxy', 'tool', 'platform_fee'
    cost_subtype VARCHAR(100),

    -- Details
    description TEXT,
    quantity DECIMAL(12,4),
    unit_cost DECIMAL(10,6),
    total_amount DECIMAL(12,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',

    -- Provider info
    provider VARCHAR(100),
    provider_reference VARCHAR(255),

    -- Timestamps
    incurred_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Metadata
    metadata_json JSONB
);

CREATE INDEX idx_costs_agent ON costs(agent_id);
CREATE INDEX idx_costs_type ON costs(cost_type);
CREATE INDEX idx_costs_incurred_at ON costs(incurred_at DESC);

-- ===========================================
-- PLATFORM ACCOUNTS (Balance tracking)
-- ===========================================

CREATE TABLE platform_accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id UUID NOT NULL REFERENCES agents(id),
    platform VARCHAR(50) NOT NULL,

    -- Balances
    available_balance DECIMAL(12,2) DEFAULT 0,
    pending_balance DECIMAL(12,2) DEFAULT 0,
    total_earned DECIMAL(14,2) DEFAULT 0,
    total_withdrawn DECIMAL(14,2) DEFAULT 0,

    -- Withdrawal settings
    withdrawal_method VARCHAR(50),
    withdrawal_details_encrypted BYTEA,
    auto_withdraw BOOLEAN DEFAULT FALSE,
    auto_withdraw_threshold DECIMAL(10,2),

    -- Last sync
    last_synced_at TIMESTAMPTZ,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(agent_id, platform)
);

CREATE INDEX idx_platform_accounts_agent ON platform_accounts(agent_id);

-- ===========================================
-- A/B TESTING
-- ===========================================

CREATE TABLE ab_experiments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Experiment info
    name VARCHAR(255) NOT NULL,
    description TEXT,
    experiment_type VARCHAR(50) NOT NULL,  -- 'proposal', 'message', 'pricing', 'timing'

    -- Variants
    variants JSONB NOT NULL,  -- Array of variant configs

    -- Status
    status VARCHAR(20) DEFAULT 'draft',  -- 'draft', 'running', 'paused', 'completed'

    -- Traffic allocation
    traffic_percentage DECIMAL(5,2) DEFAULT 100,

    -- Results
    winner_variant_id VARCHAR(50),
    statistical_significance DECIMAL(5,4),

    -- Timing
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE ab_experiment_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    experiment_id UUID NOT NULL REFERENCES ab_experiments(id),
    variant_id VARCHAR(50) NOT NULL,

    -- Metrics
    impressions INTEGER DEFAULT 0,
    conversions INTEGER DEFAULT 0,
    conversion_rate DECIMAL(7,6),
    revenue DECIMAL(12,2) DEFAULT 0,

    -- Additional metrics
    metrics JSONB DEFAULT '{}',

    -- Timestamps
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===========================================
-- MARKET INTELLIGENCE
-- ===========================================

CREATE TABLE market_data (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Category/market
    platform VARCHAR(50) NOT NULL,
    category VARCHAR(100) NOT NULL,
    subcategory VARCHAR(100),
    region VARCHAR(100),

    -- Time period
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,

    -- Demand metrics
    job_count INTEGER,
    average_budget DECIMAL(10,2),
    median_budget DECIMAL(10,2),

    -- Supply metrics
    average_applicants DECIMAL(6,2),
    average_proposals INTEGER,

    -- Rate data
    average_hourly_rate DECIMAL(8,2),
    p25_hourly_rate DECIMAL(8,2),
    p75_hourly_rate DECIMAL(8,2),

    -- Competition
    competition_level DECIMAL(5,4),  -- 0-1

    -- Trends
    demand_trend DECIMAL(5,4),  -- Positive = growing
    rate_trend DECIMAL(5,4),

    -- Timestamps
    collected_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(platform, category, period_start)
);

CREATE INDEX idx_market_data_lookup ON market_data(platform, category, period_start DESC);

-- ===========================================
-- AGENT LEARNING DATA
-- ===========================================

CREATE TABLE agent_learning_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id UUID NOT NULL REFERENCES agents(id),

    -- Event type
    event_type VARCHAR(50) NOT NULL,  -- 'proposal_result', 'job_outcome', 'client_feedback'

    -- Context
    job_id UUID REFERENCES discovered_jobs(id),
    proposal_id UUID REFERENCES proposals(id),

    -- Input features (what led to the outcome)
    input_features JSONB NOT NULL,

    -- Outcome
    outcome VARCHAR(50) NOT NULL,  -- 'success', 'failure', 'neutral'
    outcome_value DECIMAL(10,4),  -- Numeric outcome if applicable

    -- Timestamps
    occurred_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_learning_agent ON agent_learning_events(agent_id);
CREATE INDEX idx_learning_event_type ON agent_learning_events(event_type);
CREATE INDEX idx_learning_occurred_at ON agent_learning_events(occurred_at DESC);

-- ===========================================
-- RATE LIMITING
-- ===========================================

CREATE TABLE rate_limit_counters (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Scope
    scope_type VARCHAR(50) NOT NULL,  -- 'agent', 'platform', 'global'
    scope_id VARCHAR(255) NOT NULL,
    limit_type VARCHAR(50) NOT NULL,  -- 'proposals', 'messages', 'api_calls'

    -- Counter
    counter INTEGER DEFAULT 0,

    -- Window
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,

    -- Timestamps
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(scope_type, scope_id, limit_type, window_start)
);

CREATE INDEX idx_rate_limits_lookup ON rate_limit_counters(scope_type, scope_id, limit_type, window_start DESC);

-- ===========================================
-- SYSTEM EVENTS / AUDIT LOG
-- ===========================================

CREATE TABLE system_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Event info
    event_type VARCHAR(100) NOT NULL,
    event_subtype VARCHAR(100),
    severity VARCHAR(20) DEFAULT 'info',  -- 'debug', 'info', 'warning', 'error', 'critical'

    -- Related entities
    agent_id UUID REFERENCES agents(id),
    job_id UUID REFERENCES discovered_jobs(id),

    -- Event data
    message TEXT,
    data JSONB,

    -- Source
    source VARCHAR(100),
    correlation_id UUID,

    -- Timestamps
    occurred_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_system_events_type ON system_events(event_type);
CREATE INDEX idx_system_events_severity ON system_events(severity) WHERE severity IN ('error', 'critical');
CREATE INDEX idx_system_events_occurred_at ON system_events(occurred_at DESC);
CREATE INDEX idx_system_events_correlation ON system_events(correlation_id);

-- ===========================================
-- FUNCTIONS & TRIGGERS
-- ===========================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply to all tables with updated_at
CREATE TRIGGER update_agents_updated_at BEFORE UPDATE ON agents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_jobs_updated_at BEFORE UPDATE ON discovered_jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_proposals_updated_at BEFORE UPDATE ON proposals
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_active_jobs_updated_at BEFORE UPDATE ON active_jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_earnings_updated_at BEFORE UPDATE ON earnings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Function to update agent stats after job completion
CREATE OR REPLACE FUNCTION update_agent_stats_on_job_complete()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'completed' AND OLD.status != 'completed' THEN
        UPDATE agents SET
            jobs_completed = jobs_completed + 1,
            last_active_at = NOW()
        WHERE id = NEW.agent_id;
    ELSIF NEW.status IN ('cancelled', 'disputed') AND OLD.status = 'in_progress' THEN
        UPDATE agents SET
            jobs_failed = jobs_failed + 1
        WHERE id = NEW.agent_id;
    END IF;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER trigger_update_agent_stats AFTER UPDATE ON active_jobs
    FOR EACH ROW EXECUTE FUNCTION update_agent_stats_on_job_complete();

-- ===========================================
-- VIEWS
-- ===========================================

-- Agent performance summary
CREATE VIEW agent_performance_summary AS
SELECT
    a.id,
    a.name,
    a.status,
    a.total_earnings,
    a.jobs_completed,
    a.jobs_failed,
    a.success_rate,
    a.average_rating,
    (SELECT COUNT(*) FROM active_jobs aj WHERE aj.agent_id = a.id AND aj.status = 'in_progress') as active_jobs,
    (SELECT COUNT(*) FROM proposals p WHERE p.agent_id = a.id AND p.status = 'submitted') as pending_proposals,
    (SELECT SUM(c.total_amount) FROM costs c WHERE c.agent_id = a.id) as total_costs,
    a.total_earnings - COALESCE((SELECT SUM(c.total_amount) FROM costs c WHERE c.agent_id = a.id), 0) as net_profit
FROM agents a
WHERE NOT a.is_deleted;

-- Job queue with scoring
CREATE VIEW job_queue AS
SELECT
    j.*,
    COALESCE(
        (SELECT COUNT(*) FROM proposals p WHERE p.job_id = j.id),
        0
    ) as our_proposals_count
FROM discovered_jobs j
WHERE j.status IN ('discovered', 'scored', 'queued')
    AND (j.expires_at IS NULL OR j.expires_at > NOW())
ORDER BY j.score DESC NULLS LAST, j.discovered_at DESC;

-- Daily earnings report
CREATE VIEW daily_earnings_report AS
SELECT
    DATE(e.earned_at) as date,
    e.platform,
    COUNT(*) as transaction_count,
    SUM(e.gross_amount) as gross_earnings,
    SUM(e.platform_fee) as platform_fees,
    SUM(e.net_amount) as net_earnings
FROM earnings e
WHERE e.status = 'completed'
GROUP BY DATE(e.earned_at), e.platform
ORDER BY date DESC, platform;
