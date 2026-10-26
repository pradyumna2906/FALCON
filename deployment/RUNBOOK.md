# Phase 13 release operations

This is a single-host deployment package, not evidence of a live deployment.
Only the proxy publishes host ports. PostgreSQL and Redis are on a private
Docker network; this configuration assumes a trusted dedicated host. A managed
remote database/Redis deployment requires verified TLS and a separate reviewed
network configuration. No paid resources are provisioned by this repository.

## Owner activation decisions

Before a public release, record the hosting region and capacity, domain, valid
TLS certificate/renewal process, SMTP account and verified sender, OpenAI model
and current token prices, monthly provider spending cap, backup destination,
retention and recovery objectives, and the reviewed classification artifact.
These have not been selected or activated. The model is explicitly configurable;
there is no guessed model or price. Set provider account budget alerts separately.
Automated tests use synthetic users, injected email delivery and provider stubs;
they do not demonstrate actual email deliverability or live model compatibility.

## Build and start

1. Copy `release.env.example` outside the checkout, fill every placeholder, and
   restrict it to the deployment operator (`chmod 600`). Never paste its output
   into an issue or log. `FALCON_RELEASE_ENV` must be its absolute path.
2. Generate independent signing, delivery, history and backup keys. Delivery and
   history keys use `Fernet.generate_key()`; the signing secret needs at least
   32 random characters. Keep the backup encryption key outside the host backup.
3. Mount the domain certificate and private key as `fullchain.pem` and
   `privkey.pem`. Make the key readable by the proxy UID 101 using a dedicated
   group/ACL, never world-readable. Renew before expiry and reload the proxy.
4. Create the private Redis configuration with `requirepass`, `appendonly yes`,
   `maxmemory 128mb` and `maxmemory-policy noeviction`. URL-encode its password in
   `FALCON_REDIS_URL`. Do not expose port 6379. Redis loss fails protected actions
   closed; restarting Redis can reset the rolling rate window, so preserve AOF.
5. Supply the approved classifier bundle in `FALCON_CLASSIFIER_DIR` and set
   `FALCON_CLASSIFICATION_MODEL_VERSION`. Missing bundles retain the explicit
   rule-based fallback; they do not imply a trained production ML model exists.
6. Export the variables for Compose via its `--env-file` option and run:

   ```sh
   docker compose --env-file /private/release.env -f deployment/compose.production.yaml config --quiet
   docker compose --env-file /private/release.env -f deployment/compose.production.yaml build api web
   docker compose --env-file /private/release.env -f deployment/compose.production.yaml up -d --wait postgres redis
   docker compose --env-file /private/release.env -f deployment/compose.production.yaml --profile maintenance run --rm migrate
   docker compose --env-file /private/release.env -f deployment/compose.production.yaml up -d --wait api web worker
   ```

   Migrations are an explicit maintenance action, never an API startup side
   effect. Serialize releases and back up before a migration. The database
   credential owns this dedicated database; a managed least-privilege migration
   role/runtime role split must be configured for a shared database platform.
7. Record final API/web image digests and dependency audit results. Base image
   maintenance tags must be resolved/pinned to reviewed digests in the release
   record before live activation. The Python/PostgreSQL bases are already pinned.
8. Check `/health/live` and `/health/ready` over the real domain, then explicitly
   authorize a synthetic email verification/reset and an assistant request.
   Verify no financial access before verification and no unverified AI output.

The backend container installs forecasting, classification and optimization
extras for this manifest. The proxy serves the SPA and `/api` from one origin.
CSP permits inline styles because MUI/Emotion inserts runtime style elements;
scripts remain same-origin with no inline script permission. Authentication
endpoints have proxy IP limits; assistant and privacy actions additionally use
atomic Redis owner limits shared across API replicas. Deploy one edge proxy;
multiple independent proxies require shared edge abuse protection.

## Jobs, failures and rotation

`python -m falcon_api.worker` runs bounded outbox and retention batches every
five seconds, uses PostgreSQL `FOR UPDATE SKIP LOCKED`, and commits one delivery
at a time. SMTP uses certificate-verified SSL or STARTTLS before credentials.
Successful sends erase the encrypted payload; expired/consumed/invalidated
challenges cannot be sent. Five failed attempts become a dead letter, with a
stable safe error code and exponential backoff. Inspect counts, not contents:

```sql
SELECT status, last_error_code, count(*)
FROM authentication_delivery_outbox GROUP BY status, last_error_code;
SELECT min(available_at) FROM authentication_delivery_outbox
WHERE status IN ('pending', 'failed') AND attempt_count < 5;
```

Fix the delivery configuration before asking the user to request a fresh token;
do not blindly replay expired dead letters. SMTP is at-least-once: a crash after
acceptance but before commit can duplicate a message with the same Message-ID.
No exactly-once external delivery claim is made. Failed payloads remain encrypted
until challenge retention removes them seven days after expiry. Assistant
retention purges at most 100 expired conversations per cycle. Import notifications
remain the persisted, deduplicated in-app inbox from Batch 4, refreshed on demand;
email marketing/push notification delivery is not enabled.

For delivery key rotation, put the previous key in `FALCON_DELIVERY_PREVIOUS_KEYS`
as a JSON map of key ID to Fernet key, change the active key and ID, and restart
API and worker. Retain previous keys until old pending deliveries expire. For
assistant history, prepend the new key to the existing ring; keep old keys for
the retention period and backup recovery window. Signing-secret rotation logs
out current access-token users; coordinate session revocation and user notice.
Rotate provider/SMTP credentials by replacing the private environment and
recreating containers. Never rebuild secrets into an image.

Monitor redacted request duration/error/status logs, Redis readiness, worker
`worker_cycle_completed` heartbeat, backlog age, dead-letter counts, certificate
expiry, disk space, DB pool saturation and provider spend. Alert if no worker
heartbeat for two minutes, backlog age exceeds five minutes, readiness fails or
disk free space drops below 20%. Connect these signals to the owner's chosen
monitoring system; no external alert destination has yet been configured.

## Backups and restore

Use a private encrypted host volume for temporary files (`umask 077`). Take a
PostgreSQL custom-format dump using a `.pgpass`/secret file, never a password in
command history. Encrypt with the repository streaming AES-256-GCM utility:

```sh
pg_dump --format=custom --file=/private/current.dump falcon
python scripts/backup-archive.py encrypt /private/current.dump /private/current.enc --key-file /private/backup.key
rm /private/current.dump
```

Store the encrypted archive off-host, separated from its 32-byte random key.
Schedule daily backups and rehearse restore monthly. Proposed retention is 7
daily/4 weekly backups; the owner must approve retention/RPO/RTO and ensure
deleted-user data ages out of backups. An archived database includes encrypted
assistant data and credentials; preserve required encryption keys separately.

Restore only to a new isolated database, with application/worker stopped:

```sh
python scripts/backup-archive.py decrypt /private/current.enc /private/restore.dump --key-file /private/backup.key
createdb falcon_restore
pg_restore --exit-on-error --no-owner --dbname=falcon_restore /private/restore.dump
```

Authentication is checked before the plaintext destination is published. Wrong
keys, truncated archives and tampering fail without exposing a restore file.
Compare schema revision, table counts and synthetic record values, then run
API ownership/verification checks before switching traffic. Delete temporary
plaintext. CI rehearses encrypted backup/restore against real PostgreSQL.

## Rollback and release evidence

Keep previous immutable API/web images and a pre-migration archive. Roll back
images only while the schema remains backward compatible. For incompatible
migrations, stop writes and restore the archive into a new database; validate
before switching connections. Do not downgrade or overwrite the live database
as an automatic recovery action. This batch adds no schema migration.

Required PR checks: backend regression/coverage, PostgreSQL lifecycle and end-to-end
financial workflows, Redis replica limits, frontend tests/contracts/build budget,
Chromium/Firefox/WebKit workflows, automated WCAG AA public-form scans, dependency
audit, API/dev Compose smoke, production TLS/security-header/migration/restore
drill. CI's 25-request readiness probe is a small regression test, not evidence
of production throughput for simulations or forecasting. Record an actual-host
financial workload benchmark, human screen-reader review, live delivery/model
checks and recovery timings before claiming production acceptance.
