# VPS Cron Range Refetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增强现有 `run-fetch.sh`，让它支持默认昨天、单天补跑和日期范围补跑，同时保持现有 cron 默认行为不变。

**Architecture:** 保持现有 `run-fetch.sh -> fetch.php -> Python API -> MySQL` 路径不变，只增强 shell 参数解析、日期范围遍历和范围汇总输出。成功标准仍然是单天触发被系统成功“受理”，不等待最终 `report.php success`。

**Tech Stack:** Bash, cron, curl, Python 3 (用于 JSON 校验), Markdown docs

---

## File Structure

- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh`
  - 增加参数解析、日期校验、范围遍历、失败汇总
- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/README.md`
  - 增加单日补跑与范围补跑命令示例
- Modify: `D:/code/adx-account-isolated-collector/docs/operator-notes.md`
  - 增加范围补跑语义和失败处理说明

### Task 1: Enhance run-fetch.sh for single-date and date-range refetch

**Files:**
- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh`
- Test: VPS shell syntax + manual single-day/range execution

- [ ] **Step 1: Verify the current script does not yet support explicit dates**

Run on VPS:

```bash
/bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh 2026-06-07
```

Expected before implementation:
- output still uses yesterday instead of the provided date, or
- behavior does not distinguish single-date mode from default mode

- [ ] **Step 2: Replace the top-level single-date flow with argument-aware date selection**

Update `run-fetch.sh` so it includes these helper functions:

```bash
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
```

- [ ] **Step 3: Refactor the existing curl request into a per-date function**

Use this exact function body in `run-fetch.sh`:

```bash
run_single_date() {
  local report_date="$1"
  local started_at response_file http_code response_body

  started_at="$(date '+%Y-%m-%d %H:%M:%S %Z')"
  response_file="$(mktemp)"

  http_code="$(
    curl -sS \
      --get \
      --data-urlencode "account_key=${ADX_FETCH_ACCOUNT_KEY}" \
      --data-urlencode "report_date=${report_date}" \
      --data-urlencode "token=${ADX_FETCH_TOKEN}" \
      -o "${response_file}" \
      -w '%{http_code}' \
      "${ADX_FETCH_BASE_URL%/}/ke/fetch.php"
  )"
  response_body="$(cat "${response_file}")"
  rm -f "${response_file}"

  echo "[${started_at}] account_key=${ADX_FETCH_ACCOUNT_KEY} report_date=${report_date} http_code=${http_code} body=${response_body}"

  if [[ "${http_code}" != "200" ]]; then
    return 1
  fi

  python3 - "${response_body}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
if not payload.get("ok"):
    raise SystemExit(1)
if payload.get("status") != "accepted":
    raise SystemExit(1)
PY
}
```

- [ ] **Step 4: Add range iteration and summary output**

Finish the script with this main execution block:

```bash
mapfile -t report_dates < <(build_date_list "$@")

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
  echo "[adx-fetch-cron] range summary start=${report_dates[0]} end=${report_dates[-1]} success_count=${#success_dates[@]} failed_count=${#failed_dates[@]}"
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
```

- [ ] **Step 5: Run shell syntax verification on VPS**

Run:

```bash
bash -n /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh
```

Expected: no output and exit code `0`

- [ ] **Step 6: Verify single-date mode on VPS**

Run:

```bash
/bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh 2026-06-07
```

Expected:
- output contains `report_date=2026-06-07`
- output contains `http_code=200`
- response body contains `"status":"accepted"`
- script exits `0`

- [ ] **Step 7: Verify range mode on VPS**

Run:

```bash
/bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh 2026-06-06 2026-06-07
```

Expected:
- one line for `report_date=2026-06-06`
- one line for `report_date=2026-06-07`
- one summary line with `success_count=` and `failed_count=`
- script exits `0` when both dates are accepted

- [ ] **Step 8: Commit**

```bash
git add deploy/vps/cron/run-fetch.sh
git commit -m "feat: support date range refetch in cron script"
```

### Task 2: Document single-day and range refetch usage

**Files:**
- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/README.md`
- Modify: `D:/code/adx-account-isolated-collector/docs/operator-notes.md`
- Test: doc content review only

- [ ] **Step 1: Add single-day and range examples to the VPS README**

Append to the cron section in `D:/code/adx-account-isolated-collector/deploy/vps/README.md`:

```md
### 手工补跑示例

拉昨天：
```bash
/bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh
```

补跑单天：
```bash
/bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh 2026-06-07
```

补跑范围：
```bash
/bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh 2026-06-01 2026-06-07
```
```

- [ ] **Step 2: Add range failure semantics to operator notes**

Append to `D:/code/adx-account-isolated-collector/docs/operator-notes.md`:

```md
补跑范围时：
- 脚本会按天逐个调用现有 `fetch.php`
- 某一天失败不会中断后续日期
- 执行结束后会输出 success/failed 汇总
- 只要范围内存在失败日期，脚本整体 exit code 就是非 0
```

- [ ] **Step 3: Review the updated docs for consistency**

Run:

```bash
Get-Content deploy/vps/README.md | Select-Object -Last 80
Get-Content docs/operator-notes.md | Select-Object -Last 40
```

Expected:
- README contains yesterday / single-day / range examples
- operator notes clearly say range failures continue and summarize later
- no wording suggests a backend multi-date task exists

- [ ] **Step 4: Commit**

```bash
git add deploy/vps/README.md docs/operator-notes.md
git commit -m "docs: add cron refetch range usage"
```

## Self-Review

- Spec coverage: the plan covers parameter parsing, date validation, per-day triggering, range summary, continued execution on failures, and doc updates.
- Placeholder scan: no TODO/TBD placeholders remain; all commands, code blocks, and file paths are explicit.
- Type consistency: the script always treats success as `ok=true` and `status=accepted`; range mode remains a client-side loop over existing single-date tasks.
