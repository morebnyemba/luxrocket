#!/usr/bin/env bash
# Probes the per-service database boundaries set by roles.sql (ADR-019). Exits non-zero on any
# unexpected result. Usage: DB=luxrocket PLATFORM_PW=... REALTIME_PW=... check-roles.sh
set -uo pipefail
DB=${DB:-luxrocket}
HOST=${PGHOST:-localhost}
fail=0

run() { PGPASSWORD=$2 psql -h "$HOST" -U "$1" -d "$DB" -tAqc "$3" 2>&1 | head -1; }

expect() { # expect <allowed|denied> <label> <user> <password> <sql>
  local out; out=$(run "$3" "$4" "$5")
  if [[ $1 == denied && $out == *"permission denied"* ]] || [[ $1 == allowed && $out != *ERROR* ]]; then
    printf '  ok    %-48s %s\n' "$2" "$1"
  else
    printf '  FAIL  %-48s expected %s, got: %s\n' "$2" "$1" "$out"; fail=1
  fi
}

P=lr_platform; R=lr_realtime
expect allowed "platform reads round facts"            $P "$PLATFORM_PW" "SELECT count(*) FROM rt.round"
expect denied  "platform writes round facts"           $P "$PLATFORM_PW" "DELETE FROM rt.round"
expect denied  "platform reads encrypted seeds"        $P "$PLATFORM_PW" "SELECT root_seed_ct FROM rt.seed_chain"
expect denied  "platform reads seed checkpoints"       $P "$PLATFORM_PW" "SELECT 1 FROM rt.seed_checkpoint"
expect allowed "platform reads public chain facts"     $P "$PLATFORM_PW" "SELECT terminal_hash FROM rt.seed_chain"
expect denied  "platform creates in public"            $P "$PLATFORM_PW" "CREATE TABLE public.lr_probe(i int)"
expect denied  "realtime reads platform data"          $R "$REALTIME_PW" "SELECT 1 FROM platform.gaming_bet"
expect denied  "realtime creates in platform"          $R "$REALTIME_PW" "CREATE TABLE platform.lr_probe(i int)"
expect allowed "platform tables under RLS (count)"     $P "$PLATFORM_PW" \
  "SELECT count(*) FROM pg_tables WHERE schemaname = 'platform' AND rowsecurity"
exit $fail
