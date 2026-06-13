# VPS Cron Auto Fetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为当前已跑通的单账号 VPS 拉数链路补一个最小可用的 cron 自动触发能力，每天北京时间 09:00 和 21:00 自动触发“昨天”的拉数任务。

**Architecture:** 保持现有 `fetch.php` / `report.php` 和 Python API 主链路不变，只新增一个 VPS 本机 shell 脚本和一份 cron env 样板。cron 负责按时执行脚本，脚本负责计算“昨天”的日期并调用现有 `fetch.php`，成功返回 `accepted` 视为本次触发成功。

**Tech Stack:** Bash, cron, curl, Linux env file, existing PHP public endpoint

---

## File Structure

- Create: `D:/code/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh`
  - VPS cron 实际执行脚本
  - 负责加载 env、固定时区、计算昨天日期、调用 `fetch.php`、输出日志、返回 exit code
- Create: `D:/code/adx-account-isolated-collector/deploy/vps/cron/adx-fetch-cron.env.example`
  - cron 配置样板
  - 供 VPS 复制为 `adx-fetch-cron.env`
- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/README.md`
  - 增补 cron 部署步骤、crontab 示例、日志查看方式、手工 smoke test
- Modify: `D:/code/adx-account-isolated-collector/docs/operator-notes.md`
  - 增补 cron 运维说明、常见排查命令

### Task 1: Add cron env template and executable fetch script

**Files:**
- Create: `D:/code/adx-account-isolated-collector/deploy/vps/cron/adx-fetch-cron.env.example`
- Create: `D:/code/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh`
- Test: shell syntax and local dry-run command

- [ ] **Step 1: Create the cron env example with the minimum supported settings**

Create `D:/code/adx-account-isolated-collector/deploy/vps/cron/adx-fetch-cron.env.example` with:

```bash
ADX_FETCH_BASE_URL=https://api.wangmengmeng.fun
ADX_FETCH_ACCOUNT_KEY=a1
ADX_FETCH_TOKEN=change-me
ADX_FETCH_TIMEZONE=Asia/Shanghai
```

- [ ] **Step 2: Verify the example file was created and contains the expected keys**

Run:

```bash
Get-Content deploy/vps/cron/adx-fetch-cron.env.example
```

Expected: output contains exactly these keys:
- `ADX_FETCH_BASE_URL`
- `ADX_FETCH_ACCOUNT_KEY`
- `ADX_FETCH_TOKEN`
- `ADX_FETCH_TIMEZONE`

- [ ] **Step 3: Write the fetch script with strict mode, env loading, timezone handling, date calculation, and curl trigger**

Create `D:/code/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh` with:

```bash
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
REPORT_DATE="$(date -d 'yesterday' +%F)"
URL="${ADX_FETCH_BASE_URL%/}/ke/fetch.php?account_key=${ADX_FETCH_ACCOUNT_KEY}&report_date=${REPORT_DATE}&token=${ADX_FETCH_TOKEN}"

started_at="$(date '+%Y-%m-%d %H:%M:%S %Z')"
response_file="$(mktemp)"
http_code="$((curl -sS -o "${response_file}" -w '%{http_code}' "${URL}") 2>/dev/null)"
response_body="$(cat "${response_file}")"
rm -f "${response_file}"

echo "[${started_at}] account_key=${ADX_FETCH_ACCOUNT_KEY} report_date=${REPORT_DATE} http_code=${http_code} body=${response_body}"

if [[ "${http_code}" != "200" ]]; then
  echo "[adx-fetch-cron] unexpected http status: ${http_code}" >&2
  exit 1
fi

python3 - <<'PY' "${response_body}"
import json
import sys
payload = json.loads(sys.argv[1])
if not payload.get("ok"):
    raise SystemExit(1)
if payload.get("status") != "accepted":
    raise SystemExit(1)
PY
```

- [ ] **Step 4: Fix the curl capture bug before first verification**

Update the `http_code` line in `D:/code/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh` to the correct command substitution form:

```bash
http_code="$(curl -sS -o "${response_file}" -w '%{http_code}' "${URL}")"
```

This step exists so the final script is syntactically and functionally correct before verification.

- [ ] **Step 5: Run bash syntax verification**

Run:

```bash
bash -n deploy/vps/cron/run-fetch.sh
```

Expected: no output and exit code `0`

- [ ] **Step 6: Create a local env file for dry-run verification**

Create a temporary local test env file at `D:/code/adx-account-isolated-collector/deploy/vps/cron/adx-fetch-cron.env` with:

```bash
ADX_FETCH_BASE_URL=https://api.wangmengmeng.fun
ADX_FETCH_ACCOUNT_KEY=a1
ADX_FETCH_TOKEN=4IQ5_cwbUQlN9GNryquhjm64SnGd1-Wo
ADX_FETCH_TIMEZONE=Asia/Shanghai
```

- [ ] **Step 7: Run the script once manually to verify it returns accepted**

Run from a Linux-compatible environment or on VPS after sync:

```bash
/bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh
```

Expected output contains:
- `account_key=a1`
- `http_code=200`
- response JSON with `"ok":true`
- response JSON with `"status":"accepted"`

- [ ] **Step 8: Commit**

```bash
git add deploy/vps/cron/adx-fetch-cron.env.example deploy/vps/cron/run-fetch.sh
git commit -m "feat: add vps cron fetch trigger"
```

### Task 2: Document cron deployment and operations

**Files:**
- Modify: `D:/code/adx-account-isolated-collector/deploy/vps/README.md`
- Modify: `D:/code/adx-account-isolated-collector/docs/operator-notes.md`
- Test: review docs for exact commands and paths

- [ ] **Step 1: Add a cron deployment section to the VPS README**

Append a new section to `D:/code/adx-account-isolated-collector/deploy/vps/README.md` covering:

```md
## Cron 自动拉数

1. 复制配置样板：
   `cp /srv/adx-account-isolated-collector/deploy/vps/cron/adx-fetch-cron.env.example /srv/adx-account-isolated-collector/deploy/vps/cron/adx-fetch-cron.env`
2. 填写真实值：
   - `ADX_FETCH_BASE_URL`
   - `ADX_FETCH_ACCOUNT_KEY`
   - `ADX_FETCH_TOKEN`
   - `ADX_FETCH_TIMEZONE`
3. 赋予脚本执行权限：
   `chmod +x /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh`
4. 手工 smoke test：
   `/bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh`
5. 安装 crontab：
   `crontab -e`
6. 写入：
   `0 9 * * * /bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh >> /var/log/adx-fetch-cron.log 2>&1`
   `0 21 * * * /bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh >> /var/log/adx-fetch-cron.log 2>&1`
```

- [ ] **Step 2: Add log inspection and failure triage commands to the README**

Append these exact commands to the README section:

```md
### 常用检查命令

```bash
tail -n 50 /var/log/adx-fetch-cron.log
crontab -l
curl "https://api.wangmengmeng.fun/ke/report.php?account_key=a1&report_date=$(TZ=Asia/Shanghai date -d 'yesterday' +%F)&token=YOUR_TOKEN"
mysql -u adx_user -p -h 127.0.0.1 adx_data -e "SELECT id, account_id, report_date, status, row_count, request_id, error_message FROM adx_fetch_runs ORDER BY id DESC LIMIT 10;"
```
```

- [ ] **Step 3: Add an operator note section describing schedule semantics**

Append a new section to `D:/code/adx-account-isolated-collector/docs/operator-notes.md` with:

```md
## VPS cron 自动拉数

当前 cron 策略固定为：
- 每天北京时间 09:00 触发一次
- 每天北京时间 21:00 再触发一次
- 两次都默认拉取“昨天”的数据

当前策略只保证“受理触发”，即脚本成功标准是 `fetch.php` 返回 `ok=true` 且 `status=accepted`。
脚本本身不轮询 `report.php`，也不自动重试；如需确认最终结果，请再查询 `report.php` 或检查 `adx_fetch_runs`。
```

- [ ] **Step 4: Review the documentation for exact path and command consistency**

Run:

```bash
Get-Content deploy/vps/README.md
Get-Content docs/operator-notes.md
```

Expected:
- all paths use `/srv/adx-account-isolated-collector/deploy/vps/cron/...`
- crontab entries mention `09:00` and `21:00`
- docs clearly say the script validates `accepted`, not final success

- [ ] **Step 5: Commit**

```bash
git add deploy/vps/README.md docs/operator-notes.md
git commit -m "docs: add vps cron auto fetch guide"
```

### Task 3: Verify the cron workflow end-to-end on VPS

**Files:**
- Modify: none
- Test: deployed VPS files and live endpoint behavior

- [ ] **Step 1: Upload the new cron assets to the VPS**

From the local machine run:

```powershell
scp D:\code\adx-account-isolated-collector\deploy\vps\cron\run-fetch.sh root@97.64.83.11:/srv/adx-account-isolated-collector/deploy/vps/cron/
scp D:\code\adx-account-isolated-collector\deploy\vps\cron\adx-fetch-cron.env.example root@97.64.83.11:/srv/adx-account-isolated-collector/deploy/vps/cron/
```

Expected: both files transfer without errors

- [ ] **Step 2: Create the real VPS env file and make the script executable**

On VPS run:

```bash
mkdir -p /srv/adx-account-isolated-collector/deploy/vps/cron
cp /srv/adx-account-isolated-collector/deploy/vps/cron/adx-fetch-cron.env.example /srv/adx-account-isolated-collector/deploy/vps/cron/adx-fetch-cron.env
chmod +x /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh
nano /srv/adx-account-isolated-collector/deploy/vps/cron/adx-fetch-cron.env
```

Set:

```bash
ADX_FETCH_BASE_URL=https://api.wangmengmeng.fun
ADX_FETCH_ACCOUNT_KEY=a1
ADX_FETCH_TOKEN=4IQ5_cwbUQlN9GNryquhjm64SnGd1-Wo
ADX_FETCH_TIMEZONE=Asia/Shanghai
```

- [ ] **Step 3: Run a manual VPS smoke test before installing cron**

On VPS run:

```bash
/bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh
```

Expected:
- log line printed to stdout
- `http_code=200`
- response body contains `"status":"accepted"`

- [ ] **Step 4: Install the production crontab entries**

On VPS run:

```bash
( crontab -l 2>/dev/null; echo "0 9 * * * /bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh >> /var/log/adx-fetch-cron.log 2>&1"; echo "0 21 * * * /bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh >> /var/log/adx-fetch-cron.log 2>&1" ) | crontab -
crontab -l
```

Expected output contains exactly the two new lines for `09:00` and `21:00`

- [ ] **Step 5: Verify that a manually triggered run still produces a latest successful snapshot**

After Step 3, run:

```bash
sleep 3
curl "https://api.wangmengmeng.fun/ke/report.php?account_key=a1&report_date=$(TZ=Asia/Shanghai date -d 'yesterday' +%F)&token=4IQ5_cwbUQlN9GNryquhjm64SnGd1-Wo"
```

Expected JSON contains:
- `"ok":true`
- `"has_run":true`
- `"run_status":"success"`
- `"row_count":` greater than `0`

- [ ] **Step 6: Verify the cron log file is usable for operations**

On VPS run:

```bash
tail -n 20 /var/log/adx-fetch-cron.log
```

Expected: at least one line with:
- timestamp
- `account_key=a1`
- `http_code=200`
- accepted response JSON

- [ ] **Step 7: Commit**

```bash
git add deploy/vps/cron/run-fetch.sh deploy/vps/cron/adx-fetch-cron.env.example deploy/vps/README.md docs/operator-notes.md
git commit -m "feat: add vps cron auto fetch workflow"
```

## Self-Review

- Spec coverage: all cron requirements are covered by Task 1-3: new script, env sample, README, operator notes, crontab entries, manual verification, and logging.
- Placeholder scan: no TODO/TBD placeholders remain; all paths, commands, and file contents are explicit.
- Type consistency: env keys use the same names throughout (`ADX_FETCH_BASE_URL`, `ADX_FETCH_ACCOUNT_KEY`, `ADX_FETCH_TOKEN`, `ADX_FETCH_TIMEZONE`); success condition consistently means `ok=true` and `status=accepted`.
