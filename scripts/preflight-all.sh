#!/usr/bin/env bash
# preflight-all.sh — lane health matrix for pitwall.
# Reads ~/.claude/pitwall/lanes.json and reports, per lane:
# harness binary present / env vars set / ready to dispatch.
# Run after install and after any edit to lanes.json.

set -u

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Lane credentials live in ~/.claude/.env, not the ambient shell. Load them here so
# preflight sees exactly what a dispatch will see. set -a exports every assignment;
# the subshell-free source keeps values in this process only.
ENV_FILE="${PITWALL_ENV_FILE:-$HOME/.claude/.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

CONFIG="${PITWALL_CONFIG:-$HOME/.claude/pitwall/lanes.json}"

if [[ ! -f "$CONFIG" ]]; then
  echo "config not found: $CONFIG"
  echo "run any lane dispatch once to auto-copy the example, or:"
  echo "  mkdir -p ~/.claude/pitwall && cp \"$PLUGIN_ROOT/config/lanes.example.json\" \"$CONFIG\""
  exit 1
fi

if ! command -v jq >/dev/null; then
  echo "jq is required (brew install jq)" >&2
  exit 1
fi

harness_binary() {
  case "$1" in
    grok)   echo "grok"   ;;
    codex)  echo "codex"  ;;
    claude) echo "claude" ;;
    groq)   echo "curl"   ;;
    *)      echo ""       ;;
  esac
}

printf '%-14s %-8s %-22s %-8s %s\n' "LANE" "HARNESS" "MODEL" "BINARY" "ENV"
printf '%-14s %-8s %-22s %-8s %s\n' "----" "-------" "-----" "------" "---"

ready_count=0
total_count=0

while IFS=$'\t' read -r lane_id harness model envvars; do
  total_count=$((total_count + 1))

  bin="$(harness_binary "$harness")"
  if [[ -z "$bin" ]]; then
    bin_status="UNKNOWN HARNESS"
  elif command -v "$bin" >/dev/null; then
    bin_status="ok"
  else
    bin_status="MISSING($bin)"
  fi

  env_status="ok"
  if [[ -n "$envvars" && "$envvars" != "null" ]]; then
    missing=()
    while IFS= read -r var; do
      [[ -z "${!var:-}" ]] && missing+=("$var")
    done < <(echo "$envvars" | jq -r '.[]')
    if (( ${#missing[@]} > 0 )); then
      env_status="MISSING(${missing[*]})"
    fi
  fi

  [[ "$bin_status" == "ok" && "$env_status" == "ok" ]] && ready_count=$((ready_count + 1))

  printf '%-14s %-8s %-22s %-8s %s\n' "$lane_id" "$harness" "${model:-(default)}" "$bin_status" "$env_status"
done < <(jq -r '.lanes | to_entries[] | [.key, .value.harness, (.value.model // ""), (.value.env // null | if . == null then "" else to_entries | map(.value) | @json end)] | @tsv' "$CONFIG")

echo
echo "$ready_count/$total_count lanes ready"
