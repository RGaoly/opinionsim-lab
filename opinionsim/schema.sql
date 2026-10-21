CREATE TABLE IF NOT EXISTS projects (
 id uuid PRIMARY KEY, name text NOT NULL, notes text NOT NULL DEFAULT '', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS datasets (
 id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES projects(id), name text NOT NULL,
 manifest jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS participants (
 dataset_id uuid NOT NULL REFERENCES datasets(id), rid text NOT NULL, profile jsonb NOT NULL, truth jsonb NOT NULL,
 PRIMARY KEY(dataset_id,rid)
);
CREATE TABLE IF NOT EXISTS prompts (
 id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES projects(id), name text NOT NULL,
 version integer NOT NULL, body text NOT NULL, body_en text, sha256 text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(project_id,name,version)
);
CREATE TABLE IF NOT EXISTS credentials (
 id uuid PRIMARY KEY, label text NOT NULL UNIQUE, base_url text NOT NULL, ciphertext text NOT NULL,
 active boolean NOT NULL DEFAULT true, rpm integer NOT NULL CHECK(rpm BETWEEN 1 AND 600),
 next_allowed timestamptz NOT NULL DEFAULT now(), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS experiments (
 id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES projects(id), dataset_id uuid NOT NULL REFERENCES datasets(id),
 name text NOT NULL, config jsonb NOT NULL, config_sha256 text NOT NULL, status text NOT NULL DEFAULT 'draft',
 currency text NOT NULL CHECK(currency IN ('CNY','USD')), budget numeric(18,8) NOT NULL CHECK(budget>=0),
 spent numeric(18,8) NOT NULL DEFAULT 0, reserved numeric(18,8) NOT NULL DEFAULT 0,
 uncertain numeric(18,8) NOT NULL DEFAULT 0, total integer NOT NULL CHECK(total>0),
 authorized_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS tasks (
 id bigserial PRIMARY KEY, experiment_id uuid NOT NULL REFERENCES experiments(id), rid text NOT NULL,
 model_idx integer NOT NULL, language text NOT NULL, prompt_idx integer NOT NULL, question_idx integer NOT NULL,
 repetition integer NOT NULL, state text NOT NULL DEFAULT 'queued', attempts integer NOT NULL DEFAULT 0,
 available_at timestamptz NOT NULL DEFAULT now(), lease_until timestamptz, claim_token uuid,
 reservation numeric(18,8) NOT NULL DEFAULT 0, answer text, parse_error text,
 UNIQUE(experiment_id,rid,model_idx,language,prompt_idx,question_idx,repetition)
);
CREATE INDEX IF NOT EXISTS queue_idx ON tasks(experiment_id,available_at,id) WHERE state IN ('queued','retry');
CREATE INDEX IF NOT EXISTS lease_idx ON tasks(lease_until) WHERE state='running';
CREATE TABLE IF NOT EXISTS attempts (
 id bigserial PRIMARY KEY, task_id bigint NOT NULL REFERENCES tasks(id), number integer NOT NULL,
 claim_token uuid NOT NULL UNIQUE, status text NOT NULL, request jsonb NOT NULL,
 response jsonb, error_code text, input_tokens integer, output_tokens integer,
 cost numeric(18,8), reservation numeric(18,8) NOT NULL,
 started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
 UNIQUE(task_id,number)
);
CREATE TABLE IF NOT EXISTS events (
 id bigserial PRIMARY KEY, experiment_id uuid REFERENCES experiments(id), kind text NOT NULL,
 detail jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS workers (
 id text PRIMARY KEY, heartbeat timestamptz NOT NULL DEFAULT now(), mode text NOT NULL
);
