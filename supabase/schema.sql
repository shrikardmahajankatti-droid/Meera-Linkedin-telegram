-- Run this once in the Supabase SQL editor (or via `supabase db push`) before
-- deploying. Nothing here ever deletes a row: notes, drafts and gate_decisions
-- are append-only and only ever change specific fields in place (see each
-- table's comment). RLS is enabled with no anon/authenticated policies on
-- every table — this backend only ever uses the service_role/secret key,
-- which bypasses RLS regardless.

create table if not exists notes (
    id bigint generated always as identity primary key,
    telegram_update_id bigint not null unique,
    chat_id bigint not null,
    text text not null,
    score smallint,
    score_reason text,
    created_at timestamptz not null default now()
);

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
    -- Only these three fields, plus draft_id/telegram_message_id below, are
    -- ever updated in place, when Meera overrides a skip/blocked decision.
    override_status text check (override_status in ('overridden', 'dropped', 'cancelled')),
    override_reason text,
    overridden_at timestamptz,
    draft_id bigint,
    telegram_message_id bigint,
    created_at timestamptz not null default now()
);

create table if not exists drafts (
    id bigint generated always as identity primary key,
    note_id bigint not null references notes(id),
    draft_text text not null,
    news_headline text,
    news_source text,
    news_date text,
    news_link text,
    model text not null,
    status text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
    gate_decision_id bigint references gate_decisions(id),
    is_override boolean not null default false,
    created_at timestamptz not null default now(),
    decided_at timestamptz
);

alter table gate_decisions add constraint gate_decisions_draft_id_fkey foreign key (draft_id) references drafts(id);

create table if not exists voice_skill (
    id bigint generated always as identity primary key,
    content text not null,
    updated_at timestamptz not null default now()
);

-- Dedup for updates that never become notes: /topic, /draft, /override,
-- callback queries. Kept separate from `notes` so that table stays real
-- captured fragments only, while every update type still gets idempotent
-- dedup on telegram_update_id.
create table if not exists processed_updates (
    telegram_update_id bigint primary key,
    created_at timestamptz not null default now()
);

create index if not exists drafts_note_id_idx on drafts (note_id);
create index if not exists drafts_status_idx on drafts (status);
create index if not exists gate_decisions_created_at_idx on gate_decisions (created_at);
create index if not exists gate_decisions_override_status_idx on gate_decisions (override_status);

alter table notes enable row level security;
alter table gate_decisions enable row level security;
alter table drafts enable row level security;
alter table voice_skill enable row level security;
alter table processed_updates enable row level security;
