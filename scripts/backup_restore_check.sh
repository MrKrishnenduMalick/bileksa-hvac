#!/usr/bin/env bash
# Backup and restore rehearsal: dump a database, restore it into a fresh database and
# prove every table's row count and the RLS settings survived.
#   usage: scripts/backup_restore_check.sh <source-db-url> <admin-db-url>
# In production, run it against a Supabase backup restored to a scratch project.
set -euo pipefail
SRC="${1:-postgresql://bileksa:bileksa@localhost:5432/bileksa_e2e}"
ADMIN="${2:-postgresql://bileksa:bileksa@localhost:5432/postgres}"
TARGET_DB="bileksa_restore_check"
TARGET="${ADMIN%/*}/${TARGET_DB}"
DUMP="$(mktemp -d)/bileksa.dump"

pg_dump --format=custom --no-owner --file "$DUMP" "$SRC"
echo "dump: $(du -h "$DUMP" | cut -f1)"
psql "$ADMIN" -qc "DROP DATABASE IF EXISTS ${TARGET_DB} WITH (FORCE)" -qc "CREATE DATABASE ${TARGET_DB}"
pg_restore --no-owner --exit-on-error --dbname "$TARGET" "$DUMP"

COUNTS_SQL="SELECT string_agg(t || '=' || n, ' ' ORDER BY t) FROM (
  SELECT c.relname AS t, (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM public.%I', c.relname), false, true, '')))[1]::text AS n
  FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r') s"
RLS_SQL="SELECT count(*) FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r' AND NOT relrowsecurity"
POLICY_SQL="SELECT count(*) FROM pg_policies WHERE schemaname='public'"

src_counts=$(psql "$SRC" -Atc "$COUNTS_SQL"); dst_counts=$(psql "$TARGET" -Atc "$COUNTS_SQL")
echo "source:   $src_counts"
echo "restored: $dst_counts"
[ "$src_counts" = "$dst_counts" ] || { echo "FAIL: row counts differ"; exit 1; }
[ "$(psql "$TARGET" -Atc "$RLS_SQL")" = "0" ] || { echo "FAIL: a restored table lost RLS"; exit 1; }
[ "$(psql "$SRC" -Atc "$POLICY_SQL")" = "$(psql "$TARGET" -Atc "$POLICY_SQL")" ] || { echo "FAIL: policies differ"; exit 1; }
psql "$ADMIN" -qc "DROP DATABASE ${TARGET_DB} WITH (FORCE)"
echo "PASS: backup restored with identical row counts, RLS and policies"
