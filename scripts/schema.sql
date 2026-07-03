-- ─────────────────────────────────────────────────────────────
--  Схема БД sales-agent для Supabase (Postgres).
--  Виконати один раз у Supabase → SQL Editor (крок 4 майстра /setup).
-- ─────────────────────────────────────────────────────────────

-- Аналіз кожного діалогу
CREATE TABLE IF NOT EXISTS dialog_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dialog_id TEXT NOT NULL,
    analyzed_at TIMESTAMP DEFAULT NOW(),
    dialog_date DATE NOT NULL,
    manager_name TEXT NOT NULL,
    has_order BOOLEAN DEFAULT FALSE,

    -- Метрики
    messages_count INT,
    avg_response_minutes FLOAT,
    max_response_minutes FLOAT,
    first_response_minutes FLOAT,
    duration_minutes FLOAT,

    -- Оцінки Claude (JSON)
    scores JSONB,
    alerts JSONB,
    strengths JSONB,
    improvements JSONB,
    recommendation TEXT,
    buying_intent TEXT,        -- low | medium | high
    client_sentiment TEXT,     -- positive | neutral | negative
    objections JSONB,          -- заперечення клієнта
    lost_reason TEXT,          -- чому не закрили (якщо немає замовлення)
    summary TEXT,

    raw_dialog JSONB
);
CREATE INDEX IF NOT EXISTS idx_manager_date ON dialog_analyses(manager_name, dialog_date);
CREATE INDEX IF NOT EXISTS idx_date ON dialog_analyses(dialog_date);

-- Щоденні агреговані звіти
CREATE TABLE IF NOT EXISTS daily_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_date DATE UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    aggregated_data JSONB,
    sent_to_telegram BOOLEAN DEFAULT FALSE
);

-- Критерії оцінки (можна міняти без редеплою)
CREATE TABLE IF NOT EXISTS criteria (
    id INT PRIMARY KEY DEFAULT 1,
    content TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT single_row CHECK (id = 1)
);
INSERT INTO criteria (content) VALUES ('Заповнити з клієнтом')
ON CONFLICT (id) DO NOTHING;

-- Самонавчання: виправлення оцінок від РОПа (👍/👎). Підмішуються у промпт як few-shot.
CREATE TABLE IF NOT EXISTS feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP DEFAULT NOW(),
    dialog_id TEXT,
    dialog_excerpt TEXT,
    agent_verdict JSONB,
    correct BOOLEAN,             -- TRUE = оцінка вірна, FALSE = РОП виправив
    correction TEXT              -- як мало бути
);

-- Тон-оф-войс / плейбук кращих менеджерів (насіння автопілота, Фаза 4)
CREATE TABLE IF NOT EXISTS tone_of_voice (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP DEFAULT NOW(),
    dialog_id TEXT,
    manager_name TEXT,
    voice JSONB,
    winning_moves JSONB,
    objection_playbook JSONB
);

-- Діалоги агента-продавця (памʼять розмов + дожими). Для продакшну/персистентності.
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id TEXT NOT NULL,
    channel TEXT NOT NULL,             -- telegram | instagram | sitniks
    turns JSONB,                       -- історія [{role, text}]
    stage TEXT DEFAULT 'contact',
    status TEXT DEFAULT 'active',      -- active | won | lost | escalated
    followups_sent INT DEFAULT 0,
    next_followup_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (channel, lead_id)
);
CREATE INDEX IF NOT EXISTS idx_conv_followup ON conversations(next_followup_at) WHERE status = 'active';

-- ── Фаза 2 (RAG): розкоментувати при підключенні бази знань по перепискам ──
-- CREATE EXTENSION IF NOT EXISTS vector;
-- ALTER TABLE dialog_analyses ADD COLUMN IF NOT EXISTS embedding vector(1536);
