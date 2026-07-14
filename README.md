# hudu-keeper-sync

Two-way password sync between [Hudu](https://hudu.com) (IT documentation
platform, passwords resource) and [Keeper Security](https://keepersecurity.com)
(via Keeper Secrets Manager).

It's a scheduled batch job, not a service: run it on a timer (cron/systemd
timer) and it reconciles both sides on every run. There's no daemon, no
webhooks, no open ports.

## How it works

- Hudu passwords live under a **company**; Keeper records live in a
  **shared folder**. `scope_map.json` pairs each Hudu company with the
  Keeper folder that should hold its passwords.
- A local SQLite file (`STATE_DB_PATH`) tracks which Hudu password is
  linked to which Keeper record, plus a content hash of each side as of
  the last successful sync. That's how the tool tells "this side changed"
  apart from "this differs because I haven't synced it yet."
- Each run, per scope:
  1. **Linked pairs**: compare each side's current content hash to the
     hash recorded at last sync. Whichever side changed gets pushed to the
     other. If *both* changed since last sync, `CONFLICT_WINNER` decides
     (see [Conflict handling](#conflict-handling) below).
  2. **Unlinked records**: anything with no counterpart gets created on
     the other side and linked, so future runs treat it as a tracked pair.
     Pass `--bootstrap-match-title` on a first run against two systems
     that already hold overlapping data, and it will pair up entries with
     matching titles (same scope, case-insensitive) instead of creating
     duplicates -- it only links them, it never overwrites either side
     when doing this, so you can review any content mismatch it logs.
  3. **Deletions are never propagated.** If one side of a linked pair is
     deleted, the tool leaves the other side alone, logs it as an
     "orphaned link", and reports a count -- it does not guess which side
     was "right" and delete a live credential out from under you.
- If you edit `scope_map.json` to point a company at a different Keeper
  folder, existing links for records that moved with it are re-attached to
  the new scope automatically on the next run rather than being silently
  orphaned and duplicated.
- Every record's push/create/link is isolated in a try/except: one bad
  record (a transient API error, a duplicate title colliding during
  `--bootstrap-match-title`, a state-DB write failure) is logged and counted
  in the run's error total without aborting the rest of the scope. A create
  that fails to persist its link is logged loudly, naming both sides, since
  that's the one case that can leave a live, untracked duplicate credential
  behind for a human to reconcile.

## Conflict handling

Hudu's API returns a real `updated_at` timestamp, but Keeper Secrets
Manager records don't expose a comparable wall-clock modification time --
only an internal revision counter that isn't meaningfully comparable
across systems. So true cross-system last-write-wins-by-timestamp isn't
possible with this API surface. When both sides changed since the last
sync (an actual edit conflict, which should be rare if the job runs
frequently), the tool falls back to a configured winner (`CONFLICT_WINNER`,
default `hudu`) and logs a warning naming the record. If that's not
acceptable for your use case, run the job more often to shrink the window
in which real conflicts can occur, or watch the logs for `Conflict on`
lines.

## Setup

### 1. Hudu

Admin > API in your Hudu instance to generate an API key. The key's
permissions determine what the sync tool can read/write; it needs access
to the Passwords resource for whichever companies you map.

### 2. Keeper Secrets Manager

Create a KSM Application and share the folder(s) you want synced with it,
**with edit permission** (KSM apps default to read-only folder shares;
create/update will fail with read-only access):

```
keeper secrets-manager app create hudu-sync
keeper secrets-manager share add --app hudu-sync --secret <shared-folder-uid> --editable true
keeper secrets-manager client add --app hudu-sync --config-init json
```

Save the resulting config JSON somewhere the job can read and point
`KEEPER_CONFIG_PATH` at it. Treat that file like a credential -- it's a
one-time bootstrap token that decrypts to full API access for that
application's shared folders.

### 3. Scope map

Copy `scope_map.example.json` to `scope_map.json` and list each Hudu
company ID you want synced next to the Keeper shared-folder UID it maps
to.

### 4. Environment

Copy `.env.example` to `.env` and fill in `HUDU_BASE_URL`, `HUDU_API_KEY`,
`KEEPER_CONFIG_PATH`, `SCOPE_MAP_PATH`. The CLI reads plain environment
variables -- load `.env` however your scheduler does that (`env_file=` in
systemd, `source .env` in a cron wrapper, etc.). Nothing reads `.env`
automatically.

### 5. Install and run

```
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Preview first -- no writes to Hudu, Keeper, or the state DB:
hudu-keeper-sync --dry-run -v

# First real run against systems with pre-existing overlapping data:
hudu-keeper-sync --bootstrap-match-title

# Normal scheduled run:
hudu-keeper-sync
```

## Scheduling

Systemd timer (recommended over cron for logging/retry behavior):

```ini
# /etc/systemd/system/hudu-keeper-sync.service
[Service]
Type=oneshot
WorkingDirectory=/opt/hudu-keeper-sync
EnvironmentFile=/opt/hudu-keeper-sync/.env
ExecStart=/opt/hudu-keeper-sync/.venv/bin/hudu-keeper-sync
```

```ini
# /etc/systemd/system/hudu-keeper-sync.timer
[Timer]
OnCalendar=*:0/15
Persistent=true

[Install]
WantedBy=timers.target
```

Or cron:

```
*/15 * * * * cd /opt/hudu-keeper-sync && . .env && .venv/bin/hudu-keeper-sync >> /var/log/hudu-keeper-sync.log 2>&1
```

## Security notes

- Both API credentials grant read/write access to live passwords. Store
  `.env` and the Keeper config JSON with restrictive file permissions
  (`chmod 600`) and keep them out of version control (`.gitignore` already
  excludes them).
- The tool never logs secret values -- only titles/IDs, for traceability.
- Run it as a dedicated, minimally-privileged service account, not
  interactively as a personal user.
- The state DB (`STATE_DB_PATH`) is not a backup and doesn't store plaintext
  secrets, only content hashes and IDs, but it should still be treated as
  operational data worth backing up so re-linking isn't required after a
  disk loss (a lost state DB just means the next run falls back to
  `--bootstrap-match-title`-style matching or creates fresh duplicates,
  it doesn't lose credentials).

## Development

```
pip install -e ".[dev]"
pytest
```

`tests/` cover the state store and sync engine against fake Hudu/Keeper
clients -- no network access or live credentials required.
