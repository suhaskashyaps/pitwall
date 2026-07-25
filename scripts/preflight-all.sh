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

PRICES="${PITWALL_PRICES:-$PLUGIN_ROOT/config/prices.json}"

# A lane whose model has no price entry ingests as unattributable cost: the
# harness may report nothing and there is no table to impute from. Catch it
# here rather than after a paid run.
price_status() {
  local model="$1"
  [[ -f "$PRICES" ]] || { echo "NO-TABLE"; return; }
  [[ -n "$model" ]] || { echo "n/a"; return; }
  if jq -e --arg m "$model" '.models[$m]' "$PRICES" >/dev/null 2>&1; then
    echo "ok"
  else
    echo "NO-PRICE"
  fi
}

# Cheap, free reachability probe. Only lanes routed through a local proxy can be
# probed without spending money; native CLIs report auth/config presence only.
# S7 lost a whole leg to an upstream outage that a 5-second probe would have caught.
# Probed ONCE, before the lane loop. Calling a probe from inside a command
# substitution would run it in a subshell, so any cache set there is lost and
# every proxy lane re-probes: 6 lanes against a dead proxy meant 6 x 5s of
# timeout. The answer is identical for every proxy lane, so compute it up front.
probe_proxy() {
  local base="${CLIPROXY_BASE_URL:-http://127.0.0.1:8317}" code
  command -v curl >/dev/null || { echo "NO-CURL"; return; }
  # Take curl's EXIT STATUS for the failure case, never its stdout: on a refused
  # connection curl prints 000 AND exits nonzero, so `|| echo 000` would append a
  # second 000 and yield "000000", which no case arm matches.
  code="$(curl -s -o /dev/null -m 5 -w '%{http_code}' \
    -H "Authorization: Bearer ${CLIPROXY_API_KEY:-}" "$base/v1/models" 2>/dev/null)" \
    || code="000"
  case "$code" in
    200) echo "ok" ;;
    ""|000*) echo "DOWN" ;;
    401|403) echo "AUTH($code)" ;;
    *) echo "HTTP($code)" ;;
  esac
}

PROXY_REACH=""
if grep -q 'CLIPROXY_API_KEY' "$CONFIG" 2>/dev/null; then
  PROXY_REACH="$(probe_proxy)"
fi

reach_status() {
  [[ "$1" == *CLIPROXY_API_KEY* ]] || { echo "skip"; return; }
  echo "${PROXY_REACH:-DOWN}"
}

printf '%-14s %-8s %-22s %-8s %-10s %-9s %s\n' \
  "LANE" "HARNESS" "MODEL" "BINARY" "PRICE" "REACH" "ENV"
printf '%-14s %-8s %-22s %-8s %-10s %-9s %s\n' \
  "----" "-------" "-----" "------" "-----" "-----" "---"

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

  price_st="$(price_status "$model")"
  reach_st="$(reach_status "$envvars")"

  # Ready means dispatchable AND attributable. Anything other than a clean
  # probe (AUTH/HTTP/DOWN) or a usable price entry blocks the lane: a lane whose
  # proxy rejects its key, or whose model has no price, cannot produce a receipt.
  [[ "$bin_status" == "ok" && "$env_status" == "ok" \
     && ( "$reach_st" == "ok" || "$reach_st" == "skip" ) \
     && ( "$price_st" == "ok" || "$price_st" == "n/a" ) ]] \
    && ready_count=$((ready_count + 1))

  printf '%-14s %-8s %-22s %-8s %-10s %-9s %s\n' \
    "$lane_id" "$harness" "${model:-(default)}" "$bin_status" \
    "$price_st" "$reach_st" "$env_status"
done < <(jq -r '.lanes | to_entries[] | [.key, .value.harness, (.value.model // ""), (.value.env // null | if . == null then "" else to_entries | map(.value) | @json end)] | @tsv' "$CONFIG")

echo
echo "$ready_count/$total_count lanes ready"
