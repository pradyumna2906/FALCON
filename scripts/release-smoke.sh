#!/usr/bin/env bash
# Destructive only to an isolated CI Compose project; never run against production.
set -euo pipefail
[[ "${CI:-}" == "true" ]] || { echo "Run this drill only in an isolated CI runner."; exit 1; }
root=$(cd "$(dirname "$0")/.." && pwd)
scratch=$(mktemp -d)
chmod 700 "$scratch"
export FALCON_RELEASE_ENV="$scratch/release.env"
export FALCON_TLS_DIR="$scratch/tls"
export FALCON_CLASSIFIER_DIR="$scratch/models"
export FALCON_REDIS_CONFIG="$scratch/redis.conf"
export FALCON_HTTP_PORT=18080 FALCON_HTTPS_PORT=18443
export FALCON_DB_NAME=falcon_release FALCON_DB_USER=falcon_release
FALCON_DB_PASSWORD=$(openssl rand -hex 24)
export FALCON_DB_PASSWORD
mkdir "$FALCON_TLS_DIR" "$FALCON_CLASSIFIER_DIR"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=localhost \
  -addext subjectAltName=DNS:localhost,IP:127.0.0.1 \
  -keyout "$FALCON_TLS_DIR/privkey.pem" -out "$FALCON_TLS_DIR/fullchain.pem" 2>/dev/null
# Synthetic CI-only certificate is readable by the non-root proxy.
chmod 644 "$FALCON_TLS_DIR/privkey.pem"
python - <<'PY'
import os, secrets
from pathlib import Path
from cryptography.fernet import Fernet
redis_password = secrets.token_hex(24)
values = {
    'FALCON_AUTH_SIGNING_SECRET': secrets.token_hex(32),
    'FALCON_AUTH_DELIVERY_ENCRYPTION_KEY': Fernet.generate_key().decode(),
    'FALCON_ASSISTANT_HISTORY_ENCRYPTION_KEYS': '["' + Fernet.generate_key().decode() + '"]',
    'FALCON_REDIS_URL': f'redis://:{redis_password}@redis:6379/0',
    'FALCON_SMTP_HOST': 'smtp.invalid',
    'FALCON_SMTP_SENDER': 'synthetic@example.com',
    'FALCON_ASSISTANT_PROVIDER': 'disabled',
    'FALCON_PUBLIC_ORIGIN': 'https://localhost',
}
for name in ('FALCON_DB_NAME', 'FALCON_DB_USER', 'FALCON_DB_PASSWORD'):
    values[name] = os.environ[name]
path = Path(os.environ['FALCON_RELEASE_ENV'])
path.write_text('\n'.join(f'{key}={value}' for key, value in values.items()) + '\n')
path.chmod(0o600)
Path(os.environ['FALCON_REDIS_CONFIG']).write_text(
    f'requirepass {redis_password}\nappendonly yes\nmaxmemory 128mb\nmaxmemory-policy noeviction\n')
PY
compose=(docker compose --project-name "falcon-release-${GITHUB_RUN_ID:-local}" -f "$root/deployment/compose.production.yaml")
cleanup() {
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$scratch"
}
trap cleanup EXIT
"${compose[@]}" config --quiet
"${compose[@]}" build api web
"${compose[@]}" up -d --wait postgres redis
"${compose[@]}" --profile maintenance run --rm migrate
"${compose[@]}" up -d --wait api web worker
curl --fail --silent --cacert "$FALCON_TLS_DIR/fullchain.pem" https://localhost:18443/health/ready
curl --fail --silent --cacert "$FALCON_TLS_DIR/fullchain.pem" -D "$scratch/headers" https://localhost:18443/sign-in > "$scratch/index"
grep -qi 'content-security-policy:.*frame-ancestors' "$scratch/headers"
grep -qi 'strict-transport-security:' "$scratch/headers"
grep -qi 'x-content-type-options: nosniff' "$scratch/headers"
grep -q '<div id="root"' "$scratch/index"
[[ $(curl --silent --output /dev/null --write-out '%{http_code}' http://localhost:18080/) == 308 ]]
# Generate a synthetic marker, take a real PostgreSQL archive, encrypt it, then
# authenticate/decrypt and restore into a separate disposable database.
"${compose[@]}" exec -T postgres psql -U falcon_release -d falcon_release -v ON_ERROR_STOP=1 \
  -c "CREATE TABLE release_probe (value text); INSERT INTO release_probe VALUES ('verified');"
"${compose[@]}" exec -T postgres pg_dump -U falcon_release -d falcon_release -Fc > "$scratch/db.dump"
openssl rand 32 > "$scratch/backup.key"
python "$root/scripts/backup-archive.py" encrypt "$scratch/db.dump" "$scratch/db.enc" --key-file "$scratch/backup.key"
rm "$scratch/db.dump"
python "$root/scripts/backup-archive.py" decrypt "$scratch/db.enc" "$scratch/restored.dump" --key-file "$scratch/backup.key"
"${compose[@]}" exec -T postgres createdb -U falcon_release falcon_restored
"${compose[@]}" exec -T postgres pg_restore -U falcon_release -d falcon_restored --exit-on-error --no-owner < "$scratch/restored.dump"
[[ $("${compose[@]}" exec -T postgres psql -U falcon_release -d falcon_restored -Atc 'SELECT value FROM release_probe') == verified ]]
[[ $("${compose[@]}" exec -T postgres psql -U falcon_release -d falcon_restored -Atc 'SELECT version_num FROM alembic_version') == a3d9e6f8b215 ]]
# Short concurrent readiness probe: a regression signal, not a production load SLA.
export FALCON_SMOKE_CA="$FALCON_TLS_DIR/fullchain.pem"
python - <<'PY'
from concurrent.futures import ThreadPoolExecutor
import os, ssl, time, urllib.request
context = ssl.create_default_context(cafile=os.environ['FALCON_SMOKE_CA'])
def probe(_):
    start = time.monotonic()
    with urllib.request.urlopen('https://localhost:18443/health/ready', context=context, timeout=5) as response:
        assert response.status == 200
    return time.monotonic() - start
with ThreadPoolExecutor(max_workers=5) as pool:
    times = sorted(pool.map(probe, range(25)))
print(f'TLS readiness probe: 25/25 successful; p95={times[23]:.3f}s')
assert times[23] < 5
PY
echo "Release TLS, security headers, migration and encrypted backup/restore drill passed."
