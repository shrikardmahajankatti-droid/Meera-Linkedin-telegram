-- Adds the decision gate: gate_decisions table, drafts.gate_decision_id /
-- is_override, and processed_updates for dedup on triggers/commands/callbacks
-- that are never stored as notes. Append-only style, matching schema.sql: the
-- only rows ever updated in place are the override fields, draft_id and
-- telegram_message_id on gate_decisions. Nothing is deleted.

create table if not exists gate_decisions (
    id bigint generated always as identity primary key,
    note_id bigint references notes(id),
    topic text not null,
    decision text not null check (decision in ('draft', 'draft_with_warning', 'skip', 'blocked')),
    total_score smallint not null,
    scores jsonb not null,
    reasons jsonb not null,
    hard_blocks jsonb not null default '[]'::jsonb,
    news_items jsonb not null default '[]'::jsonb,
    suggested_angle text,
    gate_error text,
    override_status text check (override_status in ('overridden', 'dropped', 'cancelled')),
    override_reason text,
    overridden_at timestamptz,
    draft_id bigint references drafts(id),
    telegram_message_id bigint,
    created_at timestamptz not null default now()
);

create index if not exists gate_decisions_created_at_idx on gate_decisions (created_at);
create index if not exists gate_decisions_override_status_idx on gate_decisions (override_status);

alter table drafts add column if not exists gate_decision_id bigint references gate_decisions(id);
alter table drafts add column if not exists is_override boolean not null default false;

-- Dedup for updates that never become notes: triggers, /override, callbacks.
-- Kept separate from `notes` so that table stays real captured fragments only.
create table if not exists processed_updates (
    telegram_update_id bigint primary key,
    created_at timestamptz not null default now()
);

alter table gate_decisions enable row level security;
alter table processed_updates enable row level security;
-- No policies added: this backend only ever uses the service_role/secret key,
-- which bypasses RLS regardless. Matches notes/drafts/voice_skill already in
-- schema.sql.
