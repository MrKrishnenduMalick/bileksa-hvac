#!/usr/bin/env bash
# Fails if anything that looks like a real secret or an .env file is tracked by git.
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
tracked_env=$(git ls-files | grep -E '(^|/)\.env($|\.)' | grep -vE '\.env(\.demo)?\.example$' || true)
if [ -n "$tracked_env" ]; then echo "Tracked env files:"; echo "$tracked_env"; fail=1; fi
patterns='(sk_live_[0-9A-Za-z]{10,}|rk_live_[0-9A-Za-z]{10,}|whsec_[0-9A-Za-z]{20,}|eyJhbGciOi[0-9A-Za-z_-]{30,}\.[0-9A-Za-z_-]{30,}|-----BEGIN (RSA |EC )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|xox[baprs]-[0-9A-Za-z-]{10,}|postgres(ql)?(\+asyncpg)?://[^:@/ ]+:[^@/ ]{12,}@[a-z0-9.-]+\.supabase\.(co|com))'
hits=$(git ls-files -z | xargs -0 grep -InE "$patterns" -- 2>/dev/null | grep -v '^scripts/check_secrets.sh' || true)
if [ -n "$hits" ]; then echo "Possible secrets:"; echo "$hits"; fail=1; fi
[ $fail -eq 0 ] && echo "PASS: no secrets or env files tracked"
exit $fail
