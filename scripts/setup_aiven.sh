#!/usr/bin/env bash
# ============================================================================
# BridgeTalk — load the schema into a managed Aiven MySQL service.
#
#   ./scripts/setup_aiven.sh
#
# Reads DATABASE_URL from .env, so no credential is written here or passed on
# the command line (where it would land in your shell history).
#
# Two things differ from a local MySQL, and both are handled below:
#
#   1. Aiven is managed, so `avnadmin` cannot CREATE USER, GRANT, or FLUSH
#      PRIVILEGES. schema.sql does all three (lines 34-36) to make a local
#      least-privilege user. Those are stripped; on Aiven you connect as
#      avnadmin and Aiven manages users itself.
#
#   2. Aiven requires TLS, and its certificate is signed by a per-project CA
#      rather than a public one, so the CA file has to be supplied.
# ============================================================================
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

CA="database/aiven-ca.pem"
[ -f .env ] || { echo "✗ No .env found." >&2; exit 1; }

if [ ! -f "$CA" ]; then
  cat >&2 <<MSG
✗ Missing $CA

  In the Aiven console, open your MySQL service, and on the Overview tab
  click Download next to "CA Certificate". Save it as exactly:

      $(pwd)/$CA

MSG
  exit 1
fi

# Pull the pieces out of DATABASE_URL. Done in Python because a URL-encoded
# password would break a shell regex.
eval "$(python3 - <<'PY'
import re, urllib.parse as u
line = next(l for l in open('.env') if l.startswith('DATABASE_URL='))
url = u.urlparse(line.split('=', 1)[1].strip().replace('mysql+pymysql://', 'mysql://'))
print(f'DB_HOST={u.unquote(url.hostname)}')
print(f'DB_PORT={url.port}')
print(f'DB_USER={u.unquote(url.username)}')
print(f'DB_PASS={u.quote(u.unquote(url.password))}')   # safe for eval
print(f'DB_NAME={url.path.lstrip("/")}')
PY
)"
DB_PASS=$(python3 -c "import urllib.parse,sys;print(urllib.parse.unquote(sys.argv[1]))" "$DB_PASS")

# Refuse to run against a local server. Pointed at localhost, the VERIFY_CA
# below checks your LOCAL MySQL's certificate against Aiven's CA and fails
# with "certificate verify failed" — which reads like a TLS problem and is
# really just the wrong DATABASE_URL being active.
case "$DB_HOST" in
  localhost|127.0.0.1|::1)
    cat >&2 <<MSG
✗ DATABASE_URL in .env points at $DB_HOST, not Aiven.

  This script sets up the REMOTE database. Edit .env and swap the two
  DATABASE_URL lines so the aivencloud.com one is active, then re-run.

MSG
    exit 1 ;;
esac

echo "  host     : $DB_HOST:$DB_PORT"
echo "  user     : $DB_USER"
echo "  database : $DB_NAME"
echo

# MYSQL_PWD keeps the password out of the process list and the history file.
export MYSQL_PWD="$DB_PASS"
MY=(mysql --host="$DB_HOST" --port="$DB_PORT" --user="$DB_USER"
    --ssl-mode=VERIFY_CA --ssl-ca="$CA")

echo "→ creating the database and tables…"
sed '/CREATE USER/d; /^GRANT /d; /^FLUSH PRIVILEGES/d' database/schema.sql | "${MY[@]}"
echo "  done"

echo "→ adding the demo accounts…"
"${MY[@]}" < database/seed.sql
echo "  done"

echo
echo "→ checking what is actually there:"
"${MY[@]}" --table "$DB_NAME" <<'SQL'
SELECT VERSION() AS mysql_version, DATABASE() AS db;
SHOW STATUS LIKE 'Ssl_cipher';
SELECT TABLE_NAME AS tables_created FROM information_schema.TABLES
 WHERE TABLE_SCHEMA = DATABASE() ORDER BY TABLE_NAME;
SELECT email, role FROM users ORDER BY id;
SQL

echo
echo "✓ Aiven is ready. Ssl_cipher above must NOT be empty — that is your proof"
echo "  the connection is encrypted. Now restart the backend:"
echo "      ./scripts/run_backend.sh"
