#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ADX_FETCH_ENV_FILE:-${SCRIPT_DIR}/adx-fetch-cron.env}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[adx-fetch-cron] missing env file: ${ENV_FILE}" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

: "${ADX_FETCH_BASE_URL:?ADX_FETCH_BASE_URL is required}"
: "${ADX_FETCH_ACCOUNT_KEY:?ADX_FETCH_ACCOUNT_KEY is required}"
: "${ADX_FETCH_TOKEN:?ADX_FETCH_TOKEN is required}"

export TZ="${ADX_FETCH_TIMEZONE:-Asia/Shanghai}"

validate_date() {
  local value="$1"
  date -d "${value}" +%F >/dev/null 2>&1 || return 1
  [[ "$(date -d "${value}" +%F)" == "${value}" ]]
}

build_date_list() {
  if [[ $# -eq 0 ]]; then
    date -d 'yesterday' +%F
    return 0
  fi

  if [[ $# -eq 1 ]]; then
    if ! validate_date "$1"; then
      echo "[adx-fetch-cron] invalid date: $1" >&2
      return 1
    fi
    printf '%s\n' "$1"
    return 0
  fi

  if [[ $# -eq 2 ]]; then
    local start_date="$1"
    local end_date="$2"

    if ! validate_date "${start_date}"; then
      echo "[adx-fetch-cron] invalid start_date: ${start_date}" >&2
      return 1
    fi

    if ! validate_date "${end_date}"; then
      echo "[adx-fetch-cron] invalid end_date: ${end_date}" >&2
      return 1
    fi

    if [[ "$(date -d "${start_date}" +%s)" -gt "$(date -d "${end_date}" +%s)" ]]; then
      echo "[adx-fetch-cron] start_date must be <= end_date" >&2
      return 1
    fi

    local current_date="${start_date}"
    while [[ "$(date -d "${current_date}" +%s)" -le "$(date -d "${end_date}" +%s)" ]]; do
      printf '%s\n' "${current_date}"
      current_date="$(date -d "${current_date} +1 day" +%F)"
    done
    return 0
  fi

  echo "[adx-fetch-cron] usage: run-fetch.sh [YYYY-MM-DD] [YYYY-MM-DD]" >&2
  return 1
}

run_single_date() {
  local report_date="$1"
  local started_at response_file error_file http_code response_body curl_error

  started_at="$(date '+%Y-%m-%d %H:%M:%S %Z')"
  response_file="$(mktemp)"
  error_file="$(mktemp)"

  if ! http_code="$(
    curl -sS \
      --get \
      --data-urlencode "account_key=${ADX_FETCH_ACCOUNT_KEY}" \
      --data-urlencode "report_date=${report_date}" \
      --data-urlencode "token=${ADX_FETCH_TOKEN}" \
      -o "${response_file}" \
      -w '%{http_code}' \
      "${ADX_FETCH_BASE_URL%/}/ke/fetch.php" \
      2>"${error_file}"
  )"; then
    curl_error="$(tr '\n' ' ' < "${error_file}")"
    echo "[${started_at}] account_key=${ADX_FETCH_ACCOUNT_KEY} report_date=${report_date} http_code=curl_error body=${curl_error}"
    rm -f "${response_file}" "${error_file}"
    return 1
  fi

  response_body="$(cat "${response_file}")"
  rm -f "${response_file}" "${error_file}"

  echo "[${started_at}] account_key=${ADX_FETCH_ACCOUNT_KEY} report_date=${report_date} http_code=${http_code} body=${response_body}"

  if [[ "${http_code}" != "200" ]]; then
    echo "[adx-fetch-cron] unexpected http status for ${report_date}: ${http_code}" >&2
    return 1
  fi

  if ! python3 - "${response_body}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
if not payload.get("ok"):
    raise SystemExit(1)
if payload.get("status") != "accepted":
    raise SystemExit(1)
PY
  then
    echo "[adx-fetch-cron] unexpected response payload for ${report_date}" >&2
    return 1
  fi
}

date_list_output="$(build_date_list "$@")"
mapfile -t report_dates <<< "${date_list_output}"

success_dates=()
failed_dates=()

for report_date in "${report_dates[@]}"; do
  if run_single_date "${report_date}"; then
    success_dates+=("${report_date}")
  else
    failed_dates+=("${report_date}")
  fi
done

if [[ ${#report_dates[@]} -gt 1 ]]; then
  last_index=$((${#report_dates[@]} - 1))
  echo "[adx-fetch-cron] range summary start=${report_dates[0]} end=${report_dates[$last_index]} success_count=${#success_dates[@]} failed_count=${#failed_dates[@]}"
  if [[ ${#success_dates[@]} -gt 0 ]]; then
    echo "[adx-fetch-cron] success_dates=$(IFS=,; echo "${success_dates[*]}")"
  fi
  if [[ ${#failed_dates[@]} -gt 0 ]]; then
    echo "[adx-fetch-cron] failed_dates=$(IFS=,; echo "${failed_dates[*]}")"
  fi
fi

if [[ ${#failed_dates[@]} -gt 0 ]]; then
  exit 1
fi
