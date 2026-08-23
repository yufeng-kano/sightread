# Database

PostgreSQL 16+. Schema changes **only** via Alembic migrations under `apps/api/migrations/`, this doc updated first. Never edit production schema by hand.

## Tables

```text
users            id PK, google_sub UNIQUE, email, name, created_at
sessions         id PK, user_id FK, token_hash UNIQUE, created_at, expires_at
api_keys         id PK, user_id FK, name, key_hash UNIQUE, prefix, created_at,
                 last_used_at, revoked_at NULL
openrouter_keys  user_id PK/FK, ciphertext BYTEA, masked, updated_at        -- one per user
provider_connections
                 id PK, user_id FK, name, base_url,
                 ciphertext BYTEA, masked,        -- the connection's API key, AES-GCM
                 created_at, updated_at
                 UNIQUE (user_id, name)
                 -- user-defined OpenAI-compatible endpoints (e.g. a kano-proxy
                 -- /openai/v1 base); the built-in OpenRouter upstream is NOT a row here
prompt_presets   id PK, user_id FK, name, text TEXT, created_at, updated_at
                 UNIQUE (user_id, name)
                 -- named transcription prompts; selecting one replaces the template
                 -- entirely (docs/parsing.md § Prompts)
user_settings    user_id PK/FK, default_model, default_profile,
                 default_connection_id FK NULL,   -- provider_connections; NULL = OpenRouter
                 prompt_preset_id FK NULL         -- prompt_presets; NULL = default prompt
                 -- both FKs ON DELETE SET NULL: deleting a connection/preset falls back
                 -- to OpenRouter / the default prompt
jobs             id UUID PK, user_id FK, kind pdf|image, filename, media_type,
                 size_bytes, sha256, pages_spec, model, profile, profile_version,
                 pipeline_version, bbox_format,
                 connection_id NULL,              -- provider connection; NULL = OpenRouter.
                                                  -- deliberately NO FK: immutable history
                                                  -- (see Rules)
                 prompt TEXT NULL,                -- effective prompt template, verbatim
                 prompt_sha256,                   -- its hash; part of the dedup key
                 status queued|running|succeeded|failed, error,
                 page_count, pages_done, source_path NULL, source_deleted_at NULL,
                 created_at, started_at, finished_at
                 INDEX (status, created_at)                                  -- queue claim
                 INDEX (user_id, sha256, model, connection_id, profile, profile_version,
                        pages_spec, prompt_sha256, pipeline_version)
                        WHERE status='succeeded'                             -- dedup
job_pages        (job_id FK, page_no) PK, method NULL, status, error NULL
results          job_id PK/FK, markdown TEXT, pages JSONB, figures JSONB,
                 errors JSONB, meta JSONB, created_at
usage_log        id PK, user_id FK, job_id FK, model, prompt_tokens,
                 completion_tokens, cost NUMERIC(12,6), created_at
                 INDEX (user_id, created_at)
upload_tickets   id PK, user_id FK, token_hash UNIQUE, prefix, job_id FK NULL,
                 created_at, expires_at, spent_at NULL
                 INDEX (user_id, created_at)                                 -- mint rate limit
                 -- single-use upload credential minted by the MCP `parse` tool
                 -- (auth.md § 5); job_id set when the upload spends the ticket
oauth_clients    client_id PK, client_name, redirect_uris JSONB, created_at
oauth_grants     id PK, client_id FK, user_id FK, kind code|access|refresh,
                 token_hash UNIQUE, pkce_challenge NULL, redirect_uri NULL,
                 scope, expires_at, revoked_at NULL, created_at
                 -- redirect_uri is set on `code` rows only: the token endpoint
                 -- checks a code came back from the URI it was issued for
```

## Rules

- All credentials at rest follow [auth.md](./auth.md): hashes for anything we only verify, AES-GCM ciphertext for what we must replay upstream (the OpenRouter key and every provider connection's key). No plaintext secrets in any column.
- `user_settings.system_prompt` no longer exists: the migration turned each stored custom prompt into a `prompt_presets` row named "Custom prompt" and pointed `prompt_preset_id` at it, so behavior did not change for anyone.
- `jobs.connection_id` carries **no foreign key** on purpose: the upstream a job ran on is immutable history. A FK with SET NULL would relabel a deleted connection's jobs as OpenRouter jobs — a still-queued one would then run against OpenRouter billing the wrong key, and a succeeded one would answer OpenRouter dedup lookups with another upstream's output; RESTRICT would make a connection undeletable once any job exists. Instead the id simply outlives the row: the worker fails a queued job whose connection is gone ("the provider connection for this job no longer exists"), and dedup keys keep matching only their own upstream (connection ids are never reused).
- `results` holds parsed **output** (kept indefinitely); `jobs.source_path` points at a temp file that is deleted at terminal state — the DB never stores document bytes.
- Job claiming and per-user caps: exact queries in [jobs.md](./jobs.md).
- Timestamps are `timestamptz`, UTC.
