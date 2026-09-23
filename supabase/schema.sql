-- Run this once in the Supabase SQL editor (or via `supabase db push`) before
-- deploying. Nothing here ever deletes a row: notes and drafts are append-only
-- and only ever change status/score in place.

create table if not exists notes (
    id bigint generated always as identity primary key,
    telegram_update_id bigint not null unique,
    chat_id bigint not null,
    text text not null,
    score smallint,
    score_reason text,
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
    created_at timestamptz not null default now(),
    decided_at timestamptz
);

create table if not exists voice_skill (
    id bigint generated always as identity primary key,
    content text not null,
    updated_at timestamptz not null default now()
);

create index if not exists drafts_note_id_idx on drafts (note_id);
create index if not exists drafts_status_idx on drafts (status);
