"""
============================================================================
collectors/service.py — 采集器业务逻辑层（Service Layer）
============================================================================

【这个文件是什么？】
这是广告中台（ADX Mid-Platform）的"采集器"模块的业务服务层代码。
它负责：
1. 管理广告账号（Account）、采集器实例（CollectorInstance）、代理绑定（ProxyBinding）的 CRUD 操作
2. 管理数据抓取调度的创建、更新和触发
3. 管理同步任务（CollectorSyncTask）的生命周期：创建、认领（claim）、状态更新
4. 构建各类报表数据（日报、小时报、站点报表）
5. 远程拉取数据的触发（调用 Node 端的 fetch.php、report.php）
6. 采集器运行时的配置构建（build_runtime_config）
7. 采集器实例的心跳记录（heartbeat）

【架构位置】
FastAPI 路由（routers/） → service.py（本文件，业务逻辑） → SQLAlchemy models（数据模型）

【关键概念】
- Account: 广告账号（如 Google Ad Manager 的一个 network）
- CollectorInstance: 采集器实例（一个账号下可以有多个实例，每个实例有自己的 token 和配置）
- ProxyBinding: 代理绑定（为采集器实例配置出国代理）
- CollectorSyncTask: 同步任务（每次数据抓取都是一个任务，有状态流转）
  - 任务类型：report_fetch（日报拉取）/ report_fetch_hourly（小时报拉取）
  - 状态流转：pending → in_progress → succeeded / failed / cancelled
- FetchSchedule: 抓取调度（定时触发数据抓取，支持按天定时或按小时间隔两种模式）
- AccountDailyReport / AccountHourlyReport: 账号级日报/小时报
- SiteDailyReport / SiteHourlyReport: 站点级日报/小时报
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from secrets import token_urlsafe
from zoneinfo import ZoneInfo

import httpx  # 异步 HTTP 客户端，用于调用远程 Node 端 API
from fastapi import HTTPException, status
from sqlalchemy import case, cast, distinct, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.types import Integer, Numeric

from app.collectors import schemas
from app.collectors.credential_crypto import CredentialCipher
from app.collectors.fetch_policy import assert_fetch_allowed
from app.config import get_settings
from app.models.account import Account
from app.models.account_daily_report import AccountDailyReport
from app.models.account_hourly_report import AccountHourlyReport
from app.models.account_report_day_status import AccountReportDayStatus
from app.models.collector_instance import CollectorInstance
from app.models.collector_account_policy import CollectorAccountPolicy
from app.models.collector_sync_log import CollectorSyncLog
from app.models.collector_sync_task import CollectorSyncTask
from app.models.fetch_schedule import FetchSchedule
from app.models.oauth_app_config import OAuthAppConfig
from app.models.oauth_credential import OAuthCredential
from app.models.oauth_event import OAuthEvent
from app.models.proxy_binding import ProxyBinding
from app.models.site_daily_report import SiteDailyReport
from app.models.site_hourly_report import SiteHourlyReport
from app.models.account_daily_dimension_report import AccountDailyDimensionReport
from app.models.site_daily_dimension_report import SiteDailyDimensionReport


# ============================================================================
# 常量定义区
# ============================================================================

# 终态任务状态集合 — 任务一旦进入这些状态，就不会再变化
TERMINAL_TASK_STATUSES = {"succeeded", "failed", "cancelled"}

# 活跃任务状态集合 — 还在进行中的任务
ACTIVE_SYNC_TASK_STATUSES = {"pending", "in_progress"}
ACTIVE_RECOVERY_TASK_STATUSES = {"pending", "in_progress"}
SAFE_OAUTH_FAILURE_CLASSES = {
    "oauth_code_invalid",
    "oauth_refresh_revoked",
    "oauth_session_expired",
    "oauth_client_invalid",
    "oauth_rate_limited",
    "oauth_provider_unavailable",
    "oauth_transport_timeout",
    "oauth_transport_error",
    "oauth_response_invalid",
    "oauth_request_rejected",
    "oauth_validation_failed",
    "oauth_health_check_succeeded",
}

# 默认报表时区（美国洛杉矶时区，即太平洋时间 PT）
DEFAULT_REPORT_TIMEZONE = "America/Los_Angeles"

# 日报数据的"安全等待时间"
# 含义：等到报告日期的次日凌晨后，再多等 2 小时，确保数据已完整生成
# 例如 7月20号的日报，要等到 7月21号凌晨 2:00（洛杉矶时间）才算"权威可用"
MID_PLATFORM_DAILY_SAFETY_DELTA = timedelta(hours=2)

# 需要定向回填（targeted backfill）的账号 key 列表
# 这些账号会被定时调度自动进行小时数据回填
TARGETED_BACKFILL_ACCOUNT_KEYS = (
    "bivajazz",
    "cpatobe",
    "cdqjsy",
    "coeurdazur",
    "cwpoole",
    "dddfdc",
    "ddgjcj",
    "domeband",
    "ldsjys",
    "learnclip",
    "liberatedu",
    "linkzclub",
    "mnewscast",
    "onlyfungogo",
    "reboroots",
    "rgtmozart",
    "sssnw",
    "stones-a1",
    "uragnv",
    "wxgenbo",
    "zilote",
)

# 以下两个元组合并后构成"自动日报拉取排除列表"
# ———— 授权失效，不拉取 ————
INVALID_GRANT_DO_NOT_FETCH_ACCOUNT_KEYS = (

)

# ———— 手动禁用，不拉取 ————
MANUAL_DO_NOT_FETCH_ACCOUNT_KEYS = (
    "a1",
    "arongtala",
    "dcrww",
    "exqutech",
    "lfmtmt",
    "loshiny",
    "sberesford",
)

# 合并所有排除账号 → 自动拉取时跳过这些账号
AUTOMATIC_DAILY_FETCH_EXCLUDED_ACCOUNT_KEYS = tuple(
    sorted({*INVALID_GRANT_DO_NOT_FETCH_ACCOUNT_KEYS, *MANUAL_DO_NOT_FETCH_ACCOUNT_KEYS})
)

# 任务状态转移白名单
# key: 当前状态, value: 允许转移到的目标状态集合
# 例如：pending 只能转到 in_progress / blocked / cancelled
# 空集合表示终态，不能再转移
ALLOWED_STATUS_TRANSITIONS = {
    "pending": {"in_progress", "blocked", "cancelled"},
    "in_progress": {"succeeded", "failed", "cancelled", "blocked"},
    "blocked": {"pending", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}


# ============================================================================
# 基础工具函数
# ============================================================================

def utcnow() -> datetime:
    """获取当前 UTC 时间（带时区信息）。

    项目中统一用这个函数获取"现在"，而不是直接调用 datetime.now()，
    方便后续做单元测试时 mock 时间。
    """
    return datetime.now(timezone.utc)


def allowed_source_statuses(target_status: str) -> set[str]:
    """反向查询：给定目标状态，返回可以从哪些状态转移过来。

    例如 target_status="in_progress" → 返回 {"pending", "blocked"}
    用于更新任务状态时做校验：只有当前状态在返回的集合内，才允许转移。
    """
    return {
        current_status
        for current_status, allowed_targets in ALLOWED_STATUS_TRANSITIONS.items()
        if target_status in allowed_targets
    }


def list_gray_daily_fetch_instances(db: Session) -> list[CollectorInstance]:
    """列出所有在"定向回填白名单"中的采集器实例。

    这些实例会被定时调度器选中，执行每日自动回填。
    """
    return list(
        db.scalars(
            select(CollectorInstance)
            .join(CollectorAccountPolicy, CollectorAccountPolicy.account_id == CollectorInstance.account_id)
            .where(
                CollectorAccountPolicy.lifecycle_status == "active",
                CollectorAccountPolicy.gray_enabled.is_(True),
                CollectorAccountPolicy.authoritative_daily_enabled.is_(True),
                CollectorAccountPolicy.exclusion_reason.is_(None),
            )
            .order_by(CollectorInstance.report_account_key.asc(), CollectorInstance.id.asc())
        )
    )


def should_skip_automatic_data_fetch(db: Session, instance: CollectorInstance, *, fetch_kind: str) -> bool:
    """判断一个采集器实例是否应该被自动数据拉取跳过。

    跳过条件（满足任一即跳过）：
    1. report_account_key 为空
    2. 账号在排除列表中
    3. 实例没有完整的运行时拉取配置（缺少 base_url / account_key / token）
    """
    account_key = (instance.report_account_key or "").strip()
    if not account_key:
        return True
    try:
        assert_fetch_allowed(db, account_id=instance.account_id, fetch_kind=fetch_kind)
    except HTTPException:
        return True
    return not _instance_has_runtime_fetch_config(instance)


# ============================================================================
# 时区和"权威日报"相关
# ============================================================================

def authoritative_daily_ready_at(*, report_date: date, timezone_name: str) -> datetime:
    """计算某个报告日期的"权威日报"最早可用时间（UTC）。

    逻辑：
    1. 取报告日期次日凌晨 0:00（指定时区）
    2. 加上安全等待时间（MID_PLATFORM_DAILY_SAFETY_DELTA = 2小时）
    3. 转为 UTC 时间返回

    例如：7月20号的日报，洛杉矶时区 → 7月21号 2:00 AM PT → UTC 7月21号 9:00 AM
    """
    zone = ZoneInfo(timezone_name or DEFAULT_REPORT_TIMEZONE)
    local_ready_at = datetime.combine(report_date + timedelta(days=1), datetime.min.time(), tzinfo=zone)
    local_ready_at += MID_PLATFORM_DAILY_SAFETY_DELTA
    return local_ready_at.astimezone(timezone.utc)


def is_authoritative_daily_ready(
    *,
    report_date: date,
    timezone_name: str,
    now: datetime | None = None,
) -> bool:
    """判断某个报告日期的日报数据是否已经"权威可用"。

    即：当前 UTC 时间 >= authoritative_daily_ready_at 计算出的时间
    """
    current_now = now or utcnow()
    return current_now.astimezone(timezone.utc) >= authoritative_daily_ready_at(
        report_date=report_date,
        timezone_name=timezone_name,
    )


def has_successful_authoritative_daily_fetch(
    db: Session,
    *,
    account_id: int,
    report_date: date,
) -> bool:
    """判断某个账号的某天日报是否已经成功拉取过。

    注意：即使拉取结果是 0 行数据也算成功，避免调度器每轮都重复入队同一天的任务。
    """
    return (
        db.scalar(
            select(CollectorSyncTask.id).where(
                CollectorSyncTask.account_id == account_id,
                CollectorSyncTask.task_type == "report_fetch",
                CollectorSyncTask.report_date == report_date,
                CollectorSyncTask.status == "succeeded",
            )
        )
        is not None
    )


# ============================================================================
# 超时任务处理
# ============================================================================

@dataclass(frozen=True)
class OAuthRecoveryGap:
    account_id: int
    collector_instance_id: int
    task_type: str
    report_date: date
    reason: str


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _has_complete_hourly_day(
    db: Session,
    *,
    account_id: int,
    report_date: date,
    timezone_name: str,
) -> bool:
    manifest = db.scalar(
        select(AccountReportDayStatus).where(
            AccountReportDayStatus.account_id == account_id,
            AccountReportDayStatus.report_date == report_date,
            AccountReportDayStatus.source_timezone == timezone_name,
        )
    )
    if manifest is not None and manifest.is_complete_day:
        return True
    coverage = build_hourly_coverage(db, account_id=account_id, report_date=report_date)
    return bool(coverage is not None and coverage.is_complete_day)


def _gap_task_exists(
    db: Session,
    *,
    account_id: int,
    task_type: str,
    report_date: date,
) -> bool:
    return (
        db.scalar(
            select(CollectorSyncTask.id).where(
                CollectorSyncTask.account_id == account_id,
                CollectorSyncTask.task_type == task_type,
                CollectorSyncTask.report_date == report_date,
                (
                    (CollectorSyncTask.run_reason == "oauth_recovery")
                    | CollectorSyncTask.status.in_(ACTIVE_RECOVERY_TASK_STATUSES)
                ),
            )
        )
        is not None
    )


def scan_oauth_recovery_gaps(
    db: Session,
    *,
    now: datetime | None = None,
    lookback_days: int = 3,
) -> list[OAuthRecoveryGap]:
    """Return real data gaps only for accounts that completed OAuth recovery."""
    if lookback_days < 1:
        raise ValueError("lookback_days must be positive")
    current_now = _as_aware_utc(now or utcnow())
    requested_account_ids = select(OAuthEvent.account_id).where(
        OAuthEvent.event_type == "oauth_gap_scan_requested"
    )
    rows = db.execute(
        select(Account, CollectorInstance, CollectorAccountPolicy, OAuthAppConfig)
        .join(CollectorInstance, CollectorInstance.account_id == Account.id)
        .join(CollectorAccountPolicy, CollectorAccountPolicy.account_id == Account.id)
        .join(OAuthAppConfig, OAuthAppConfig.account_id == Account.id)
        .where(
            Account.id.in_(requested_account_ids),
            Account.status == "active",
            CollectorAccountPolicy.lifecycle_status == "active",
            CollectorAccountPolicy.gray_enabled.is_(True),
            CollectorAccountPolicy.exclusion_reason.is_(None),
            OAuthAppConfig.runtime_status == "healthy",
        )
        .order_by(Account.id)
    ).all()
    hourly_gaps: list[OAuthRecoveryGap] = []
    for account, instance, policy, _oauth_app in rows:
        timezone_name = account.timezone or DEFAULT_REPORT_TIMEZONE
        local_date = current_now.astimezone(ZoneInfo(timezone_name)).date()
        candidate_dates = [local_date - timedelta(days=offset) for offset in range(0, lookback_days + 1)]

        if policy.hourly_fetch_enabled:
            for report_date in candidate_dates:
                if _gap_task_exists(
                    db,
                    account_id=account.id,
                    task_type="report_fetch_hourly",
                    report_date=report_date,
                ):
                    continue
                if report_date == local_date:
                    latest_watermark = db.scalar(
                        select(func.max(AccountHourlyReport.report_time_utc)).where(
                            AccountHourlyReport.account_id == account.id
                        )
                    )
                    if latest_watermark is not None and _as_aware_utc(latest_watermark) >= current_now - timedelta(hours=1):
                        continue
                    reason = "utc_watermark_lag"
                else:
                    if _has_complete_hourly_day(
                        db,
                        account_id=account.id,
                        report_date=report_date,
                        timezone_name=timezone_name,
                    ):
                        continue
                    reason = "incomplete_hourly_coverage"
                hourly_gaps.append(
                    OAuthRecoveryGap(
                        account_id=account.id,
                        collector_instance_id=instance.id,
                        task_type="report_fetch_hourly",
                        report_date=report_date,
                        reason=reason,
                    )
                )

    return hourly_gaps


def enqueue_next_oauth_recovery_gap(
    db: Session,
    *,
    now: datetime | None = None,
    lookback_days: int = 3,
) -> CollectorSyncTask | None:
    active_recovery = db.scalar(
        select(CollectorSyncTask.id).where(
            CollectorSyncTask.run_reason == "oauth_recovery",
            CollectorSyncTask.status.in_(ACTIVE_RECOVERY_TASK_STATUSES),
        )
    )
    if active_recovery is not None:
        return None
    gaps = scan_oauth_recovery_gaps(db, now=now, lookback_days=lookback_days)
    if not gaps:
        return None
    gap = gaps[0]
    credential_version = _active_credential_version_for_task(db, account_id=gap.account_id)
    task = CollectorSyncTask(
        account_id=gap.account_id,
        collector_instance_id=gap.collector_instance_id,
        task_type=gap.task_type,
        run_reason="oauth_recovery",
        report_date=gap.report_date,
        status="pending",
        credential_version=credential_version,
        external_request_id=f"oauth-recovery-{gap.task_type}-{gap.account_id}-{gap.report_date.isoformat()}",
    )
    if not _add_unique_active_task(db, task):
        return None
    return task


def _add_unique_active_task(db: Session, task: CollectorSyncTask) -> bool:
    try:
        with db.begin_nested():
            db.add(task)
            db.flush()
    except IntegrityError:
        return False
    return True


def _active_credential_version_for_task(db: Session, *, account_id: int) -> int | None:
    oauth_app = db.scalar(select(OAuthAppConfig).where(OAuthAppConfig.account_id == account_id))
    return oauth_app.active_credential_version if oauth_app is not None else None


def acquire_oauth_app_write_guard(db: Session, *, account_id: int) -> OAuthAppConfig | None:
    """Serialize task writes with credential activation on PostgreSQL and SQLite.

    PostgreSQL serializes this no-op row update with a row lock. SQLite ignores
    ``FOR UPDATE``, but this write takes its database write-intent lock before
    version validation. A competing rotation therefore waits or fails closed.
    """
    try:
        db.execute(
            update(OAuthAppConfig)
            .where(OAuthAppConfig.account_id == account_id)
            .values(updated_at=OAuthAppConfig.updated_at)
        )
    except OperationalError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "FETCH_CREDENTIAL_ROTATION_IN_PROGRESS", "message": "Credential rotation is in progress"},
        ) from exc
    # A writer that waited for an ACK commit must not retain the OAuth app or
    # task it loaded before waiting.  ``populate_existing`` reloads the locked
    # app even when it is present in the Session identity map; expiring the
    # rest also makes subsequent task/policy checks observe that same commit.
    db.expire_all()
    return db.scalar(
        select(OAuthAppConfig)
        .where(OAuthAppConfig.account_id == account_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )


def _assert_task_credential_is_current(
    db: Session,
    *,
    instance: CollectorInstance,
    task: CollectorSyncTask,
    supplied_version: int | None,
) -> OAuthAppConfig | None:
    # Every task write holds this guard until its commit. Credential activation
    # takes the identical guard before changing active version, so a check
    # cannot be separated from the subsequent batch/status write.
    oauth_app = acquire_oauth_app_write_guard(db, account_id=instance.account_id)
    if task.credential_version is None:
        # Legacy non-OAuth tasks retain their historical contract. In a
        # production OAuth account, fetch policy still rejects this route.
        assert_fetch_allowed(db, account_id=instance.account_id, fetch_kind="claim")
        return oauth_app
    if supplied_version is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "FETCH_CREDENTIAL_VERSION_REQUIRED", "message": "Collector credential version is required"},
        )
    if supplied_version != task.credential_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "FETCH_CREDENTIAL_VERSION_MISMATCH", "message": "Task credential version does not match collector runtime"},
        )
    fetch_kind = (
        "oauth_credential_validate"
        if task.task_type == "oauth_credential_validate"
        else "oauth_health_check"
        if task.task_type == "oauth_health_check"
        else "claim"
    )
    assert_fetch_allowed(
        db,
        account_id=instance.account_id,
        fetch_kind=fetch_kind,
        credential_version=task.credential_version,
    )
    return oauth_app


def fail_stale_in_progress_tasks(
    db: Session,
    *,
    stale_before: datetime,
    finished_at: datetime,
) -> int:
    """将长时间卡在 in_progress 状态的任务标记为失败。

    用于调度器的定时清理：如果某个任务 started_at 时间早于 stale_before，
    说明它已经"超时卡住了"，将其状态改为 failed。

    返回被标记为失败的任务数量。
    """
    tasks = list(
        db.scalars(
            select(CollectorSyncTask).where(
                CollectorSyncTask.status == "in_progress",
                CollectorSyncTask.started_at.is_not(None),
                CollectorSyncTask.started_at < stale_before,
            )
        )
    )
    for task in tasks:
        task.status = "failed"
        task.finished_at = finished_at
        task.updated_at = finished_at
    return len(tasks)


def commit_or_raise_conflict(db: Session, detail: str) -> None:
    """安全提交数据库事务：如果发生唯一约束冲突（IntegrityError），
    回滚事务并抛出 HTTP 409 Conflict。

    这是项目中处理并发创建的标准模式：
    try commit → catch IntegrityError → rollback → raise 409
    """
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from exc


# ============================================================================
# Account（广告账号）CRUD
# ============================================================================

def list_accounts(db: Session) -> list[Account]:
    """列出所有广告账号，按 id 排序。"""
    return list(db.scalars(select(Account).order_by(Account.id)))


def create_account(db: Session, payload: schemas.AccountCreate) -> Account:
    """创建新的广告账号。

    参数：
    - payload.name: 账号名称
    - payload.status: 账号状态
    - payload.external_account_id: 外部平台的账号 ID（如 GAM network code）
    - payload.currency: 货币类型（如 USD）
    """
    account = Account(
        name=payload.name,
        status=payload.status,
        external_account_id=payload.external_account_id,
        currency=payload.currency,
    )
    db.add(account)
    commit_or_raise_conflict(db, "Account already exists")
    db.refresh(account)
    return account


# ============================================================================
# CollectorInstance（采集器实例）CRUD
# ============================================================================

def list_instances(db: Session) -> list[CollectorInstance]:
    """列出所有采集器实例，按 id 排序。"""
    return list(db.scalars(select(CollectorInstance).order_by(CollectorInstance.id)))


def create_instance(db: Session, payload: schemas.InstanceCreate) -> CollectorInstance:
    """创建新的采集器实例。

    关键逻辑：
    1. 先验证关联的 Account 是否存在，不存在 → 404
    2. 如果未提供 instance_token，自动生成一个 24 字节的安全随机 token
    3. report_base_url 会自动去除末尾的 "/"

    实例的核心配置：
    - instance_token: 采集器运行时用来认证身份的令牌
    - report_base_url: Node 端的数据接口基础 URL
    - report_account_key: 在 Node 端的账号标识
    - report_token: 访问 Node 端 API 的 token
    """
    account = db.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    instance = CollectorInstance(
        account_id=payload.account_id,
        name=payload.name,
        instance_token=payload.instance_token or token_urlsafe(24),  # 自动生成安全 token
        status=payload.status,
        expected_egress_ip=payload.expected_egress_ip,
        report_base_url=payload.report_base_url.rstrip("/") if payload.report_base_url else None,
        report_account_key=payload.report_account_key,
        report_token=payload.report_token,
    )
    db.add(instance)
    commit_or_raise_conflict(db, "Collector instance already exists")
    db.refresh(instance)
    return instance


# ============================================================================
# ProxyBinding（代理绑定）CRUD
# ============================================================================

def list_proxies(db: Session) -> list[ProxyBinding]:
    """列出所有代理绑定。"""
    return list(db.scalars(select(ProxyBinding).order_by(ProxyBinding.id)))


def create_proxy_binding(db: Session, payload: schemas.ProxyBindingCreate) -> ProxyBinding:
    """创建代理绑定。

    校验链：
    1. Account 必须存在 → 否则 404
    2. CollectorInstance 必须存在 → 否则 404
    3. Account 和 CollectorInstance 的 account_id 必须匹配 → 否则 400

    代理绑定用于采集器通过海外代理访问 Google Ad Manager 等外部平台。
    """
    account = db.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    instance = db.get(CollectorInstance, payload.collector_instance_id)
    if instance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector instance not found")
    if instance.account_id != payload.account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Collector instance account does not match proxy binding account",
        )

    proxy_binding = ProxyBinding(
        account_id=payload.account_id,
        collector_instance_id=payload.collector_instance_id,
        provider_name=payload.provider_name,      # 代理服务商名称
        protocol=payload.protocol,                 # 代理协议: http / socks5
        host=payload.host,                         # 代理主机地址
        port=payload.port,                         # 代理端口
        username=payload.username,                 # 代理认证用户名
        password=payload.password,                 # 代理认证密码
        expected_egress_ip=payload.expected_egress_ip,  # 预期的出口 IP（用于验证代理生效）
        status=payload.status,
    )
    db.add(proxy_binding)
    commit_or_raise_conflict(db, "Proxy binding already exists for this account or instance")
    db.refresh(proxy_binding)
    return proxy_binding


# ============================================================================
# CollectorSyncTask（同步任务）基础 CRUD
# ============================================================================

def list_tasks(db: Session) -> list[CollectorSyncTask]:
    """列出所有同步任务。"""
    return list(db.scalars(select(CollectorSyncTask).order_by(CollectorSyncTask.id)))


# ============================================================================
# FetchSchedule（抓取调度）CRUD
# ============================================================================

def list_fetch_schedules(db: Session) -> list[schemas.FetchScheduleRead]:
    """列出所有抓取调度配置。"""
    schedules = list(db.scalars(select(FetchSchedule).order_by(FetchSchedule.id)))
    return [_build_fetch_schedule_read(schedule) for schedule in schedules]


def create_or_replace_fetch_schedule(db: Session, payload: schemas.FetchScheduleCreate) -> schemas.FetchScheduleRead:
    """创建抓取调度。

    支持两种调度模式：
    1. daily_times: 每天在指定时间点触发（如 ["08:00", "20:00"]）
    2. interval_hours: 每隔 N 小时触发一次（如每 6 小时）

    创建时自动计算下一次运行时间（next_run_at）。
    如果该实例已存在调度配置 → 返回 409 Conflict。
    """
    account = db.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    instance = db.get(CollectorInstance, payload.collector_instance_id)
    if instance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector instance not found")
    if instance.account_id != payload.account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Collector instance account does not match fetch schedule account",
        )

    # 检查是否已存在调度配置
    existing_schedule = db.scalar(
        select(FetchSchedule).where(FetchSchedule.collector_instance_id == payload.collector_instance_id)
    )
    if existing_schedule is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Fetch schedule already exists for this collector instance",
        )

    schedule = FetchSchedule(
        account_id=payload.account_id,
        collector_instance_id=payload.collector_instance_id,
    )
    db.add(schedule)

    # 设置调度参数
    schedule.enabled = payload.enabled
    schedule.mode = payload.mode
    schedule.daily_times_json = _dump_daily_times(payload.daily_times)  # 将列表序列化为 JSON 字符串
    schedule.interval_hours = payload.interval_hours
    schedule.timezone = payload.timezone
    schedule.next_run_at = _build_schedule_next_run_at(
        enabled=schedule.enabled,
        mode=schedule.mode,
        timezone_name=schedule.timezone,
        daily_times=payload.daily_times,
        interval_hours=payload.interval_hours,
        last_triggered_at=schedule.last_triggered_at,
    )

    commit_or_raise_conflict(db, "Fetch schedule already exists")
    db.refresh(schedule)
    return _build_fetch_schedule_read(schedule)


def update_fetch_schedule(db: Session, schedule_id: int, payload: schemas.FetchScheduleUpdate) -> schemas.FetchScheduleRead:
    """更新抓取调度。

    校验规则：
    - daily_times 字段只能在 mode="daily_times" 时更新
    - interval_hours 字段只能在 mode="interval_hours" 时更新
    - daily_times 不能为空（对于 daily_times 模式）
    - interval_hours 必须是正整数
    """
    schedule = db.get(FetchSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fetch schedule not found")

    # 校验更新参数与当前 mode 的兼容性
    if payload.mode is None:
        if payload.daily_times is not None and schedule.mode != "daily_times":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="daily_times update requires mode='daily_times'",
            )
        if payload.interval_hours is not None and schedule.mode != "interval_hours":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="interval_hours update requires mode='interval_hours'",
            )

    # 合并新旧值
    mode = payload.mode or schedule.mode
    current_daily_times = _load_daily_times(schedule.daily_times_json)
    daily_times = current_daily_times
    interval_hours = schedule.interval_hours

    # 根据模式调整 daily_times / interval_hours
    if mode == "daily_times":
        if payload.daily_times is not None:
            daily_times = payload.daily_times
        if payload.mode == "daily_times":
            interval_hours = None
    if mode == "interval_hours":
        if payload.interval_hours is not None:
            interval_hours = payload.interval_hours
        if payload.mode == "interval_hours":
            daily_times = None

    # 校验参数合法性
    if mode == "daily_times" and not daily_times:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="daily_times must not be empty for mode='daily_times'",
        )
    if mode == "interval_hours" and (interval_hours is None or interval_hours <= 0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="interval_hours must be a positive integer for mode='interval_hours'",
        )

    # 应用更新
    if payload.enabled is not None:
        schedule.enabled = payload.enabled
    if payload.timezone is not None:
        schedule.timezone = payload.timezone
    schedule.mode = mode
    schedule.daily_times_json = _dump_daily_times(daily_times) if mode == "daily_times" else None
    schedule.interval_hours = interval_hours if mode == "interval_hours" else None
    schedule.next_run_at = _build_schedule_next_run_at(
        enabled=schedule.enabled,
        mode=schedule.mode,
        timezone_name=schedule.timezone,
        daily_times=daily_times,
        interval_hours=schedule.interval_hours,
        last_triggered_at=schedule.last_triggered_at,
    )

    commit_or_raise_conflict(db, "Unable to update fetch schedule")
    db.refresh(schedule)
    return _build_fetch_schedule_read(schedule)


# ============================================================================
# 手动触发数据拉取（核心流程）
# ============================================================================

def trigger_manual_fetch(
    db: Session,
    payload: schemas.ManualFetchRequest,
    *,
    timeout_seconds: int,
    fetch_kind: str = "manual_hourly",
    direct_collector_only: bool = True,
    run_reason: str = "preview",
    external_request_id: str | None = None,
) -> schemas.ManualFetchResponse:
    """手动触发一次数据拉取。

    这是整个系统最核心的业务流程之一。完整流程：

    1. 【校验】确认 Account、CollectorInstance 存在且匹配
    2. 【校验】确认实例有完整的 report 配置（base_url、account_key、token）
    3. 【去重检查】如果该账号+日期已有活跃的小时报任务，直接复用，不重复创建
    4. 【远程调用】HTTP GET 请求 Node 端的 /ke/fetch.php 接口，触发远端数据抓取
    5. 【创建任务】根据返回的 request_id 创建或复用 CollectorSyncTask
    6. 【启动运行时】调用 _launch_hourly_sync_runtime 启动采集器 Python 进程
    7. 【返回】返回任务状态和是否新建等信息

    注意：
    - 如果远程返回的 ok 不为 true，抛出 502 Bad Gateway
    - 如果 JSON 解析失败，抛出 502
    """
    # ── 步骤1: 校验 Account ──
    account = db.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    assert_fetch_allowed(db, account_id=payload.account_id, fetch_kind=fetch_kind)

    # ── 步骤2: 校验 CollectorInstance ──
    instance = db.get(CollectorInstance, payload.collector_instance_id)
    if instance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector instance not found")
    if instance.account_id != payload.account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Collector instance account does not match manual fetch account",
        )
    if not direct_collector_only and (
        not instance.report_base_url or not instance.report_account_key or not instance.report_token
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Collector instance is missing report configuration",
        )

    # ── 步骤3: 去重检查 — 是否已有该日期的小时报活跃任务 ──
    existing_task = _find_active_hourly_sync_task(
        db,
        account_id=payload.account_id,
        report_date=payload.report_date,
        run_reason=run_reason if run_reason == "cross_day_finalize" else None,
    )
    if existing_task is not None:
        # 已有活跃任务，启动运行时并直接返回（不重复创建）
        _launch_hourly_sync_runtime(instance)
        return schemas.ManualFetchResponse(
            ok=True,
            status=existing_task.status,
            request_id=existing_task.external_request_id,
            message="Hourly sync task already active for this account and report date",
            hourly_sync_task_id=existing_task.id,
            hourly_sync_task_status=existing_task.status,
            hourly_sync_task_created=False,
        )

    if direct_collector_only:
        request_id = external_request_id or (
            f"direct-hourly-{payload.account_id}-{payload.report_date.isoformat()}-{token_urlsafe(8)}"
        )
        sync_task, created = _get_or_create_hourly_sync_task(
            db,
            account_id=payload.account_id,
            collector_instance_id=payload.collector_instance_id,
            report_date=payload.report_date,
            external_request_id=request_id,
            run_reason=run_reason,
        )
        _launch_hourly_sync_runtime(instance)
        return schemas.ManualFetchResponse(
            ok=True,
            status=sync_task.status,
            request_id=sync_task.external_request_id,
            message="queued for direct collector",
            hourly_sync_task_id=sync_task.id,
            hourly_sync_task_status=sync_task.status,
            hourly_sync_task_created=created,
        )

    # ── 步骤4: 远程调用 Node 端的 fetch.php 接口 ──
    # 这个接口会触发 Node 端去 Google Ad Manager 拉取数据
    try:
        response = httpx.get(
            f"{instance.report_base_url}/ke/fetch.php",
            params={
                "account_key": instance.report_account_key,
                "report_date": payload.report_date.isoformat(),
                "token": instance.report_token,
            },
            timeout=timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Remote fetch returned HTTP {response.status_code}",
        )

    # ── 步骤5: 解析远程响应 ──
    try:
        response_payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Remote fetch returned invalid JSON") from exc

    if response_payload.get("ok") is not True:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_optional_string(response_payload.get("message")) or "Remote fetch returned ok=false",
        )

    # ── 步骤6: 创建或复用同步任务 ──
    sync_task, created = _get_or_create_hourly_sync_task(
        db,
        account_id=payload.account_id,
        collector_instance_id=payload.collector_instance_id,
        report_date=payload.report_date,
        external_request_id=external_request_id or _optional_string(response_payload.get("request_id")),
        run_reason=run_reason,
    )

    # ── 步骤7: 启动采集器运行时进程 ──
    _launch_hourly_sync_runtime(instance)

    return schemas.ManualFetchResponse(
        ok=bool(response_payload.get("ok")),
        status=_optional_string(response_payload.get("status")),
        run_id=_optional_int(response_payload.get("run_id")),
        request_id=_optional_string(response_payload.get("request_id")),
        message=_optional_string(response_payload.get("message")),
        hourly_sync_task_id=sync_task.id,
        hourly_sync_task_status=sync_task.status,
        hourly_sync_task_created=created,
    )


def create_task(db: Session, payload: schemas.SyncTaskCreate) -> CollectorSyncTask:
    """直接创建一个同步任务（API 入口）。

    校验 Account 和 CollectorInstance 的匹配关系后创建任务。
    """
    account = db.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    assert_fetch_allowed(db, account_id=payload.account_id, fetch_kind="operator_task")

    instance = db.get(CollectorInstance, payload.collector_instance_id)
    if instance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collector instance not found")
    if instance.account_id != payload.account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Collector instance account does not match task account",
        )

    task = CollectorSyncTask(
        account_id=payload.account_id,
        collector_instance_id=payload.collector_instance_id,
        task_type=payload.task_type,
        report_date=payload.report_date,
        status=payload.status,
        credential_version=_active_credential_version_for_task(db, account_id=payload.account_id),
        external_request_id=payload.external_request_id,
    )
    db.add(task)
    commit_or_raise_conflict(db, "Sync task already exists")
    db.refresh(task)
    return task


# ============================================================================
# 内部任务查询和创建（私有函数 _xxx）
# ============================================================================

def _find_active_hourly_sync_task(
    db: Session,
    *,
    account_id: int,
    report_date: date,
    run_reason: str | None = None,
) -> CollectorSyncTask | None:
    """查找指定账号+日期的活跃小时报同步任务。

    "活跃"指状态为 pending 或 in_progress。
    如果没有找到则返回 None。
    """
    query = select(CollectorSyncTask).where(
            CollectorSyncTask.account_id == account_id,
            CollectorSyncTask.task_type == "report_fetch_hourly",
            CollectorSyncTask.report_date == report_date,
            CollectorSyncTask.status.in_(ACTIVE_SYNC_TASK_STATUSES),
        )
    if run_reason is not None:
        query = query.where(CollectorSyncTask.run_reason == run_reason)
    return db.scalar(query)


def list_cross_day_finalize_attempts(
    db: Session,
    *,
    account_id: int,
    report_date: date,
) -> list[CollectorSyncTask]:
    return list(
        db.scalars(
            select(CollectorSyncTask)
            .where(
                CollectorSyncTask.account_id == account_id,
                CollectorSyncTask.task_type == "report_fetch_hourly",
                CollectorSyncTask.report_date == report_date,
                CollectorSyncTask.run_reason == "cross_day_finalize",
            )
            .order_by(CollectorSyncTask.id.asc())
        )
    )


def record_cross_day_finalize_exhausted(
    db: Session,
    *,
    account_id: int,
    collector_instance_id: int,
    report_date: date,
) -> CollectorSyncTask:
    external_request_id = f"hourly-finalize-{account_id}-{report_date.isoformat()}-exhausted"
    existing = db.scalar(
        select(CollectorSyncTask).where(CollectorSyncTask.external_request_id == external_request_id)
    )
    if existing is not None:
        return existing
    task = CollectorSyncTask(
        account_id=account_id,
        collector_instance_id=collector_instance_id,
        task_type="report_fetch_hourly",
        run_reason="cross_day_finalize_exhausted",
        report_date=report_date,
        status="blocked",
        credential_version=_active_credential_version_for_task(db, account_id=account_id),
        external_request_id=external_request_id,
    )
    db.add(task)
    return task


def _find_active_daily_sync_task(
    db: Session,
    *,
    account_id: int,
    report_date: date,
) -> CollectorSyncTask | None:
    """查找指定账号+日期的活跃日报同步任务。"""
    return db.scalar(
        select(CollectorSyncTask).where(
            CollectorSyncTask.account_id == account_id,
            CollectorSyncTask.task_type == "report_fetch",
            CollectorSyncTask.report_date == report_date,
            CollectorSyncTask.status.in_(ACTIVE_SYNC_TASK_STATUSES),
        )
    )


def _raise_if_hourly_sync_task_active(
    db: Session,
    *,
    account_id: int,
    report_date: date,
) -> None:
    """如果已有活跃的小时报同步任务，直接抛出 409 Conflict。

    用于防止重复创建任务的场景。
    """
    existing = _find_active_hourly_sync_task(db, account_id=account_id, report_date=report_date)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Hourly sync task already active for this account and report date",
        )


def _get_or_create_hourly_sync_task(
    db: Session,
    *,
    account_id: int,
    collector_instance_id: int,
    report_date: date,
    external_request_id: str | None,
    run_reason: str = "preview",
) -> tuple[CollectorSyncTask, bool]:
    """获取或创建小时报同步任务（幂等操作）。

    返回 (task, created)：
    - 如果已有活跃任务 → 返回 (existing_task, False)
    - 如果不存在 → 创建新任务 → 返回 (new_task, True)
    """
    existing = _find_active_hourly_sync_task(
        db,
        account_id=account_id,
        report_date=report_date,
        run_reason=run_reason if run_reason == "cross_day_finalize" else None,
    )
    if existing is not None:
        return existing, False
    return (
        _create_hourly_sync_task(
            db,
            account_id=account_id,
            collector_instance_id=collector_instance_id,
            report_date=report_date,
            external_request_id=external_request_id,
            run_reason=run_reason,
        ),
        True,
    )


def _get_or_create_daily_sync_task(
    db: Session,
    *,
    account_id: int,
    collector_instance_id: int,
    report_date: date,
    authoritative_slot: int | None = None,
    external_request_id: str | None = None,
) -> tuple[CollectorSyncTask, bool]:
    """获取或创建日报同步任务（幂等操作）。

    与 _get_or_create_hourly_sync_task 同理，只是任务类型为 report_fetch。
    """
    existing = db.scalar(select(CollectorSyncTask).where(
        CollectorSyncTask.account_id == account_id,
        CollectorSyncTask.task_type == "report_fetch",
        CollectorSyncTask.report_date == report_date,
        CollectorSyncTask.authoritative_slot == authoritative_slot,
    ))
    if existing is not None:
        return existing, False
    return (
        _create_daily_sync_task(
            db,
            account_id=account_id,
            collector_instance_id=collector_instance_id,
            report_date=report_date,
            authoritative_slot=authoritative_slot,
            external_request_id=external_request_id,
        ),
        True,
    )


def _create_hourly_sync_task(
    db: Session,
    *,
    account_id: int,
    collector_instance_id: int,
    report_date: date,
    external_request_id: str | None,
    run_reason: str = "preview",
) -> CollectorSyncTask:
    """创建新的小时报同步任务。

    任务类型固定为 "report_fetch_hourly"，初始状态为 "pending"。
    如果没有提供 external_request_id，自动生成一个唯一标识。
    """
    task = CollectorSyncTask(
        account_id=account_id,
        collector_instance_id=collector_instance_id,
        task_type="report_fetch_hourly",
        run_reason=run_reason,
        report_date=report_date,
        status="pending",
        credential_version=_active_credential_version_for_task(db, account_id=account_id),
        external_request_id=external_request_id or f"hourly-{account_id}-{report_date.isoformat()}-{token_urlsafe(8)}",
    )
    db.add(task)
    commit_or_raise_conflict(db, "Hourly sync task already active for this account and report date")
    db.refresh(task)
    return task


def _create_daily_sync_task(
    db: Session,
    *,
    account_id: int,
    collector_instance_id: int,
    report_date: date,
    authoritative_slot: int | None = None,
    external_request_id: str | None = None,
) -> CollectorSyncTask:
    """创建新的日报同步任务。

    任务类型固定为 "report_fetch"，与小时报的 "report_fetch_hourly" 区分。
    """
    task = CollectorSyncTask(
        account_id=account_id,
        collector_instance_id=collector_instance_id,
        task_type="report_fetch",
        report_date=report_date,
        status="pending",
        credential_version=_active_credential_version_for_task(db, account_id=account_id),
        authoritative_slot=authoritative_slot,
        external_request_id=external_request_id or f"daily-{account_id}-{report_date.isoformat()}-{token_urlsafe(8)}",
    )
    db.add(task)
    commit_or_raise_conflict(db, "Daily sync task already active for this account and report date")
    db.refresh(task)
    return task


# ============================================================================
# 小时报覆盖度（Hourly Coverage）分析
# ============================================================================

def build_hourly_coverage(
    db: Session,
    *,
    account_id: int | None = None,
    report_date: date | None = None,
) -> schemas.HourlyCoverage | None:
    """构建某账号某天的小时报覆盖度分析数据。

    这是数据质量检查的核心函数，用于判断某天的小时报数据是否完整。

    分析维度：
    1. 覆盖小时数（hours_present）：哪些小时有数据
    2. 完整天数判定（is_complete_day）：是否 24 小时齐全（0-23 点都有数据）
    3. 值级校验（is_value_match）：小时聚合值 vs 日报值是否一致
       - revenue 差异 < 1% 且 impressions 差异 < 1% → 一致
       - 这个校验确保小时报数据聚合后能还原日报数据

    返回值：HourlyCoverage 对象，包含所有分析指标；无数据则返回 None。
    """
    if account_id is None or report_date is None:
        return None

    # ── 查询有数据的小时列表 ──
    hours = list(
        db.scalars(
            select(distinct(SiteHourlyReport.hour))
            .where(
                SiteHourlyReport.account_id == account_id,
                SiteHourlyReport.report_date == report_date,
            )
            .order_by(SiteHourlyReport.hour.asc())
        )
    )
    if not hours:
        return None

    # ── 查询最新的同步任务 ──
    latest_task = db.scalar(
        select(CollectorSyncTask)
        .where(
            CollectorSyncTask.account_id == account_id,
            CollectorSyncTask.report_date == report_date,
        )
        .order_by(CollectorSyncTask.created_at.desc(), CollectorSyncTask.id.desc())
        .limit(1)
    )
    min_hour = min(hours)
    max_hour = max(hours)

    # ── 值级校验：小时聚合 vs 日报表 ──
    daily_revenue = None
    hourly_revenue = None
    revenue_diff_percent = None
    daily_impressions = None
    hourly_impressions = None
    impressions_diff_percent = None
    is_value_match = None

    # 日报表数据（来自 Node 端拉取的日聚合数据）
    daily = db.scalar(
        select(AccountDailyReport).where(
            AccountDailyReport.account_id == account_id,
            AccountDailyReport.report_date == report_date,
        )
    )

    # 小时聚合数据（对所有小时报数据求和）
    hourly_agg = db.execute(
        select(
            cast(func.sum(AccountHourlyReport.impressions), Integer),
            cast(func.sum(AccountHourlyReport.revenue), Numeric),
        ).where(
            AccountHourlyReport.account_id == account_id,
            AccountHourlyReport.report_date == report_date,
        )
    ).one_or_none()

    # ── 计算差异百分比 ──
    if daily is not None and hourly_agg is not None and hourly_agg[0] is not None:
        daily_revenue = float(daily.revenue)
        hourly_revenue = float(hourly_agg[1]) if hourly_agg[1] is not None else 0.0
        daily_impressions = daily.impressions
        hourly_impressions = hourly_agg[0] if hourly_agg[0] is not None else 0

        if daily_revenue > 0:
            revenue_diff_percent = round(abs(hourly_revenue - daily_revenue) / daily_revenue * 100, 2)
        if daily_impressions > 0:
            impressions_diff_percent = round(abs(hourly_impressions - daily_impressions) / daily_impressions * 100, 2)

        # 值一致判定：revenue 差异 < 1% 且 impressions 差异 < 1%
        is_value_match = (
            (revenue_diff_percent is None or revenue_diff_percent < 1.0)
            and (impressions_diff_percent is None or impressions_diff_percent < 1.0)
        )

    return schemas.HourlyCoverage(
        account_id=account_id,
        report_date=report_date,
        hours_present=hours,
        hour_count=len(hours),
        min_hour=min_hour,
        max_hour=max_hour,
        is_complete_day=len(hours) == 24 and min_hour == 0 and max_hour == 23,
        latest_task_id=latest_task.id if latest_task is not None else None,
        daily_revenue=daily_revenue,
        hourly_revenue=hourly_revenue,
        revenue_diff_percent=revenue_diff_percent,
        daily_impressions=daily_impressions,
        hourly_impressions=hourly_impressions,
        impressions_diff_percent=impressions_diff_percent,
        is_value_match=is_value_match,
    )


# ============================================================================
# 定向小时回填（Targeted Hourly Backfill）
# ============================================================================

def trigger_targeted_recent_hourly_backfill(
    db: Session,
    payload: schemas.TargetedHourlyBackfillRequest,
) -> schemas.TargetedHourlyBackfillResponse:
    """定向回填最近 N 天的小时报数据。

    业务场景：当小时报数据不完整（缺小时或值不对），需要对最近 N 天进行回填。

    逻辑：
    1. 以 anchor_date（默认今天）为基准，向前推 N 天（days）
    2. 对每一天，检查 coverage（小时完整 + 值一致）
    3. 只对不完整的日期创建/复用回填任务
    4. 为每个有新建任务的实例启动采集器运行时

    参数：
    - account_keys: 要回填的账号列表（不传则从数据库 policy 查询已启用的灰度账号）
    - days: 回填天数
    - anchor_date: 基准日期（默认今天）
    """
    anchor_date = payload.anchor_date or utcnow().date()
    if payload.account_keys:
        requested_account_keys = sorted(set(payload.account_keys))
    else:
        requested_account_keys = sorted(
            {
                account_key
                for account_key in db.scalars(
                    select(CollectorInstance.report_account_key)
                    .join(CollectorAccountPolicy, CollectorAccountPolicy.account_id == CollectorInstance.account_id)
                    .where(
                        CollectorAccountPolicy.lifecycle_status == "active",
                        CollectorAccountPolicy.gray_enabled.is_(True),
                        CollectorAccountPolicy.hourly_fetch_enabled.is_(True),
                        CollectorAccountPolicy.exclusion_reason.is_(None),
                        CollectorInstance.report_account_key.is_not(None),
                    )
                )
                if account_key
            }
        )

    # 生成回填日期列表（从 anchor_date 往前推 days 天）
    target_dates = [anchor_date - timedelta(days=offset) for offset in range(payload.days, 0, -1)]
    items: list[schemas.TargetedHourlyBackfillItem] = []

    # 查询所有匹配的采集器实例
    instances = list(
        db.scalars(
            select(CollectorInstance)
            .where(CollectorInstance.report_account_key.in_(requested_account_keys))
            .order_by(CollectorInstance.report_account_key.asc(), CollectorInstance.id.asc())
        )
    )
    # 构建 account_key → instance 的映射（一个 key 只取第一个实例）
    instances_by_key: dict[str, CollectorInstance] = {}
    for instance in instances:
        if instance.report_account_key and instance.report_account_key not in instances_by_key:
            instances_by_key[instance.report_account_key] = instance

    for account_key in requested_account_keys:
        instance = instances_by_key.get(account_key)
        if instance is None:
            continue
        assert_fetch_allowed(db, account_id=instance.account_id, fetch_kind="targeted_recent")

        created_or_reused = False
        for report_date in target_dates:
            # 检查覆盖度：如果小时完整 + 值一致，跳过
            coverage = build_hourly_coverage(db, account_id=instance.account_id, report_date=report_date)
            if coverage is not None and coverage.is_complete_day and coverage.is_value_match:
                continue

            # 需要回填：创建或复用小时报同步任务
            task, created = _get_or_create_hourly_sync_task(
                db,
                account_id=instance.account_id,
                collector_instance_id=instance.id,
                report_date=report_date,
                external_request_id=f"targeted-backfill-{account_key}-{report_date.isoformat()}",
            )
            created_or_reused = True
            items.append(
                schemas.TargetedHourlyBackfillItem(
                    account_id=instance.account_id,
                    account_key=account_key,
                    collector_instance_id=instance.id,
                    report_date=report_date,
                    hourly_sync_task_id=task.id,
                    hourly_sync_task_status=task.status,
                    hourly_sync_task_created=created,
                )
            )

        # 如果本账号有任务被创建或复用，启动采集器运行时
        if created_or_reused:
            _launch_hourly_sync_runtime(instance)

    return schemas.TargetedHourlyBackfillResponse(
        anchor_date=anchor_date,
        days=payload.days,
        requested_account_keys=requested_account_keys,
        items=items,
    )


# ============================================================================
# 调度相关内部函数
# ============================================================================

def _build_schedule_next_run_at(
    *,
    enabled: bool,
    mode: str,
    timezone_name: str,
    daily_times: list[str] | None,
    interval_hours: int | None,
    last_triggered_at: datetime | None,
) -> datetime | None:
    """计算调度下次运行时间。

    如果调度被禁用（enabled=False），返回 None（表示不会自动运行）。
    否则调用 scheduler 模块的 compute_next_run_at 计算下次触发时间。

    延迟导入 scheduler 是为了避免循环导入问题。
    """
    if not enabled:
        return None
    from app.collectors.scheduler import compute_next_run_at, utcnow

    return compute_next_run_at(
        mode=mode,
        timezone_name=timezone_name,
        now=utcnow(),
        daily_times=daily_times,
        interval_hours=interval_hours,
        last_triggered_at=last_triggered_at,
    )


def _instance_has_runtime_fetch_config(instance: CollectorInstance) -> bool:
    """检查采集器实例是否具备完整的运行时拉取配置。

    三个必要条件缺一不可：
    - report_base_url: Node 端接口地址
    - report_account_key: Node 端账号标识
    - report_token: Node 端访问令牌
    """
    return bool(instance.report_base_url and instance.report_account_key and instance.report_token)


def _launch_hourly_sync_runtime(instance: CollectorInstance) -> None:
    """启动采集器运行时 Python 进程。

    这是一个独立子进程，负责：
    1. 从中台 API 拉取待处理的任务
    2. 通过代理访问 Google Ad Manager API
    3. 将拉取到的数据回传给中台

    启动方式：
    - 找到 collector 目录下的虚拟环境 Python
    - 设置环境变量 CONTROL_PLANE_BASE_URL（指向中台 API）
    - 设置环境变量 COLLECTOR_INSTANCE_TOKEN（实例认证令牌）
    - 以子进程方式启动：python -m app.main
    - 子进程独立于父进程（start_new_session=True），父进程结束不影响子进程

    注意：
    - 进程的 stdout/stderr 输出到 DEVNULL（不阻塞父进程）
    - 如果找不到 Python 解释器，抛出 502
    """
    # 找到项目根目录（service.py 向上 3 级）
    repo_root = Path(__file__).resolve().parents[3]

    # collector 子目录（采集器运行时代码）
    collector_dir = repo_root / "collector"

    # 查找 Python 解释器（优先 Linux .venv/bin/python，其次 Windows .venv/Scripts/python.exe）
    python_candidates = [
        collector_dir / ".venv" / "bin" / "python",
        collector_dir / ".venv" / "Scripts" / "python.exe",
    ]
    python_path = next((candidate for candidate in python_candidates if candidate.exists()), None)
    if python_path is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Collector runtime python not found")

    # 设置子进程环境变量
    env = os.environ.copy()
    env["CONTROL_PLANE_BASE_URL"] = "http://127.0.0.1:8000"  # 中台 API 地址
    env["COLLECTOR_INSTANCE_TOKEN"] = instance.instance_token   # 实例令牌，用于 API 认证

    try:
        subprocess.Popen(
            [str(python_path), "-m", "app.main"],
            cwd=str(collector_dir),
            env=env,
            stdout=subprocess.DEVNULL,   # 丢弃标准输出
            stderr=subprocess.DEVNULL,   # 丢弃标准错误
            start_new_session=True,      # 独立会话，脱离父进程
        )
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Unable to start collector runtime") from exc


# ============================================================================
# 各类报表查询
# ============================================================================

BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _beijing_date_range_utc(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    local_start = datetime.combine(start_date, datetime.min.time(), tzinfo=BEIJING_TIMEZONE)
    local_end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=BEIJING_TIMEZONE)
    return (
        local_start.astimezone(timezone.utc).replace(tzinfo=None),
        local_end.astimezone(timezone.utc).replace(tzinfo=None),
    )


def trigger_authoritative_daily_refresh(
    db: Session,
    *,
    account_id: int,
    payload: schemas.AuthoritativeDailyRefreshRequest,
) -> schemas.AuthoritativeDailyRefreshResponse:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    instance = db.scalar(
        select(CollectorInstance).where(
            CollectorInstance.account_id == account_id,
            CollectorInstance.status == "ready",
        )
    )
    if instance is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ready collector instance not found")

    external_request_id = (
        f"authoritative-refresh-{account_id}-{payload.report_date.isoformat()}-{payload.idempotency_key}"
    )
    existing = db.scalar(
        select(CollectorSyncTask).where(CollectorSyncTask.external_request_id == external_request_id)
    )
    created = False
    if existing is None:
        if _find_active_daily_sync_task(db, account_id=account_id, report_date=payload.report_date) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Daily sync task already active for this account and report date",
            )
        existing = _create_daily_sync_task(
            db,
            account_id=account_id,
            collector_instance_id=instance.id,
            report_date=payload.report_date,
            authoritative_slot=8,
            external_request_id=external_request_id,
        )
        existing.run_reason = "manual_authoritative"
        db.commit()
        db.refresh(existing)
        created = True
    return schemas.AuthoritativeDailyRefreshResponse(
        task_id=existing.id,
        account_id=existing.account_id,
        collector_instance_id=existing.collector_instance_id,
        report_date=existing.report_date,
        status=existing.status,
        authoritative_slot=8,
        external_request_id=external_request_id,
        created=created,
    )


def _beijing_report_parts(value: datetime) -> tuple[date, int]:
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    local = aware.astimezone(BEIJING_TIMEZONE)
    return local.date(), local.hour

def list_account_daily_reports(
    db: Session,
    *,
    account_id: int | None = None,
    report_date: date | None = None,
) -> list[AccountDailyReport]:
    """查询账号日报表。

    可选筛选：account_id、report_date。
    按 report_date 降序、account_id 升序排列。
    """
    query = select(AccountDailyReport).order_by(AccountDailyReport.report_date.desc(), AccountDailyReport.account_id.asc())
    if account_id is not None:
        query = query.where(AccountDailyReport.account_id == account_id)
    if report_date is not None:
        query = query.where(AccountDailyReport.report_date == report_date)
    return list(db.scalars(query))


def list_account_hourly_reports(
    db: Session,
    *,
    account_id: int | None = None,
    report_date: date | None = None,
) -> list[schemas.AccountHourlyReportRead]:
    """查询账号小时报表。

    按时间降序 → account_id → 国家代码 → 广告位 ID 排列。
    """
    query = select(AccountHourlyReport).order_by(
        AccountHourlyReport.report_time_utc.desc(),
        AccountHourlyReport.account_id.asc(),
        AccountHourlyReport.ad_country_code.asc(),
        AccountHourlyReport.ad_slot_id.asc(),
    )
    if account_id is not None:
        query = query.where(AccountHourlyReport.account_id == account_id)
    if report_date is not None:
        start_utc, end_utc = _beijing_date_range_utc(report_date, report_date)
        query = query.where(AccountHourlyReport.report_time_utc >= start_utc, AccountHourlyReport.report_time_utc < end_utc)
    rows = list(db.scalars(query))
    return [
        schemas.AccountHourlyReportRead.model_validate(row).model_copy(
            update=dict(zip(("report_date", "hour"), _beijing_report_parts(row.report_time_utc)))
        )
        for row in rows
    ]


def list_site_daily_reports(
    db: Session,
    *,
    account_id: int | None = None,
    report_date: date | None = None,
) -> list[SiteDailyReport]:
    """查询站点日报表。

    按 report_date 降序 → account_id → url 排列。
    """
    query = select(SiteDailyReport).order_by(
        SiteDailyReport.report_date.desc(),
        SiteDailyReport.account_id.asc(),
        SiteDailyReport.url.asc(),
    )
    if account_id is not None:
        query = query.where(SiteDailyReport.account_id == account_id)
    if report_date is not None:
        query = query.where(SiteDailyReport.report_date == report_date)
    return list(db.scalars(query))


def list_site_hourly_reports(
    db: Session,
    *,
    account_id: int | None = None,
    report_date: date | None = None,
) -> list[schemas.SiteHourlyReportRead]:
    """查询站点小时报表。

    按时间降序 → account_id → url → 国家代码 → 广告位 ID 排列。
    """
    query = select(SiteHourlyReport).order_by(
        SiteHourlyReport.report_time_utc.desc(),
        SiteHourlyReport.account_id.asc(),
        SiteHourlyReport.url.asc(),
        SiteHourlyReport.ad_country_code.asc(),
        SiteHourlyReport.ad_slot_id.asc(),
    )
    if account_id is not None:
        query = query.where(SiteHourlyReport.account_id == account_id)
    if report_date is not None:
        start_utc, end_utc = _beijing_date_range_utc(report_date, report_date)
        query = query.where(SiteHourlyReport.report_time_utc >= start_utc, SiteHourlyReport.report_time_utc < end_utc)
    rows = list(db.scalars(query))
    return [
        schemas.SiteHourlyReportRead.model_validate(row).model_copy(
            update=dict(zip(("report_date", "hour"), _beijing_report_parts(row.report_time_utc)))
        )
        for row in rows
    ]


# ============================================================================
# 时区解析
# ============================================================================

def resolve_report_timezone(
    db: Session,
    *,
    account_id: int | None = None,
    account_ids: set[int] | None = None,
) -> str:
    """解析报表时区。

    优先级：
    1. 如果指定单个 account_id，取该账号的 timezone
    2. 如果指定多个 account_ids，且它们时区一致，返回该时区
    3. 兜底返回默认时区 DEFAULT_REPORT_TIMEZONE（America/Los_Angeles）
    """
    if account_id is not None:
        account = db.get(Account, account_id)
        if account is not None and account.timezone:
            return account.timezone

    if account_ids:
        timezones = set(
            db.scalars(select(Account.timezone).where(Account.id.in_(account_ids)))
        )
        timezones.discard(None)
        if len(timezones) == 1:
            return next(iter(timezones))

    return DEFAULT_REPORT_TIMEZONE


# ============================================================================
# 中台（Mid-Platform）资源列表 API
# 这些函数用于构造前端展示的"中台资源"视图，将 Account + Instance + Report 关联
# ============================================================================

def list_mid_platform_link_resources(
    db: Session,
    *,
    account_id: int | None = None,
) -> list[schemas.MidPlatformLinkResource]:
    """列出中台 Link 资源（以 url + url_id 为维度）。

    从 Account → CollectorInstance → SiteDailyReport 三表联查，
    每个唯一的 (account_id, instance_id, site_name, link_key) 组合返回一条记录。
    """
    query = (
        select(Account, CollectorInstance, SiteDailyReport.url, SiteDailyReport.url_id)
        .join(CollectorInstance, CollectorInstance.account_id == Account.id)
        .join(SiteDailyReport, SiteDailyReport.account_id == Account.id)
        .order_by(Account.id, CollectorInstance.id, SiteDailyReport.url, SiteDailyReport.url_id)
    )
    if account_id is not None:
        query = query.where(Account.id == account_id)

    rows = db.execute(query).all()
    seen: set[tuple[int, int, str, str]] = set()
    items: list[schemas.MidPlatformLinkResource] = []
    for account, instance, site_name, link_key in rows:
        dedupe_key = (account.id, instance.id, str(site_name), str(link_key))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        items.append(
            schemas.MidPlatformLinkResource(
                account_id=account.id,
                account_name=account.name,
                instance_id=instance.id,
                instance_name=instance.name,
                node_base_url=instance.report_base_url or "",
                node_account_key=instance.report_account_key or instance.name,
                site_name=str(site_name),
                link_key=str(link_key),
                link_name=str(link_key),
                destination_url=None,
                currency=account.currency,
                default_display_timezone=account.timezone,
                status="active",
            )
        )
    return items


def list_mid_platform_account_resources(
    db: Session,
    *,
    account_id: int | None = None,
) -> list[schemas.MidPlatformAccountResource]:
    """列出中台 Account 资源（每个账号一条记录，去重）。"""
    query = (
        select(Account, CollectorInstance)
        .join(CollectorInstance, CollectorInstance.account_id == Account.id)
        .order_by(Account.id, CollectorInstance.id)
    )
    if account_id is not None:
        query = query.where(Account.id == account_id)

    rows = db.execute(query).all()
    items: list[schemas.MidPlatformAccountResource] = []
    seen: set[int] = set()
    for account, instance in rows:
        if account.id in seen:
            continue
        seen.add(account.id)
        items.append(
            schemas.MidPlatformAccountResource(
                account_id=account.id,
                account_name=account.name,
                external_account_key=instance.report_account_key or instance.name,
                network_code=account.external_account_id,
                timezone=account.timezone,
                default_display_timezone=account.timezone,
                currency=account.currency,
                status="active",
            )
        )
    return items


def list_mid_platform_node_resources(
    db: Session,
    *,
    account_id: int | None = None,
) -> list[schemas.MidPlatformNodeResource]:
    """列出中台 Node（采集器节点）资源。

    每个 (account, instance) 组合一条记录，不去重（一个账号可能有多个实例）。
    """
    query = (
        select(Account, CollectorInstance)
        .join(CollectorInstance, CollectorInstance.account_id == Account.id)
        .order_by(Account.id, CollectorInstance.id)
    )
    if account_id is not None:
        query = query.where(Account.id == account_id)

    rows = db.execute(query).all()
    return [
        schemas.MidPlatformNodeResource(
            account_id=account.id,
            account_name=account.name,
            instance_id=instance.id,
            instance_name=instance.name,
            node_base_url=instance.report_base_url or "",
            node_account_key=instance.report_account_key or instance.name,
            currency=account.currency,
            default_display_timezone=account.timezone,
            status="active",
        )
        for account, instance in rows
    ]


def list_mid_platform_site_resources(
    db: Session,
    *,
    account_id: int | None = None,
) -> list[schemas.MidPlatformSiteResource]:
    """列出中台 Site 资源（以 Account + Instance + site_name 为维度，去重）。"""
    query = (
        select(Account, CollectorInstance, SiteDailyReport.url)
        .join(CollectorInstance, CollectorInstance.account_id == Account.id)
        .join(SiteDailyReport, SiteDailyReport.account_id == Account.id)
        .order_by(Account.id, CollectorInstance.id, SiteDailyReport.url)
    )
    if account_id is not None:
        query = query.where(Account.id == account_id)

    rows = db.execute(query).all()
    items: list[schemas.MidPlatformSiteResource] = []
    seen: set[tuple[int, int, str]] = set()
    for account, instance, site_name in rows:
        dedupe_key = (account.id, instance.id, str(site_name))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        items.append(
            schemas.MidPlatformSiteResource(
                account_id=account.id,
                account_name=account.name,
                instance_id=instance.id,
                instance_name=instance.name,
                node_base_url=instance.report_base_url or "",
                node_account_key=instance.report_account_key or instance.name,
                site_name=str(site_name),
                currency=account.currency,
                default_display_timezone=account.timezone,
                status="active",
            )
        )
    return items


# ============================================================================
# 中台报表查询 — 将数据库原始报表数据组装为前端可用的结构化报表
# ============================================================================

DIMENSION_DATA_AVAILABLE_FROM = date(2026, 8, 2)


def _dimension_row(report: Any, *, site_name: str | None = None) -> schemas.DimensionReportRow:
    source_timezone = getattr(report, "source_timezone", None)
    is_hourly = hasattr(report, "hour")
    report_date = report.report_date
    hour = getattr(report, "hour", None)
    if is_hourly and getattr(report, "report_time_utc", None) is not None:
        report_date, hour = _beijing_report_parts(report.report_time_utc)
    return schemas.DimensionReportRow(account_id=report.account_id, report_date=report_date, site_name=site_name, ad_country_code=report.ad_country_code, ad_country_name=report.ad_country_name, ad_slot_id=report.ad_slot_id, ad_slot_name=report.ad_slot_name, source_kind=getattr(report, "source_kind", "hourly"), responses_served=report.responses_served, requests=report.requests, impressions=report.impressions, clicks=report.clicks, revenue=float(report.revenue), ecpm=float(report.ecpm), coverage_rate=(report.responses_served / report.requests if report.requests else 0.0), click_through_rate=(report.clicks / report.impressions if report.impressions else 0.0), impression_rate=(report.impressions / report.responses_served if report.responses_served else 0.0), coverage_hours=getattr(report, "coverage_hours", 1 if is_hourly else 0), expected_hours=getattr(report, "expected_hours", _expected_hours_for_timezone(report.report_date, source_timezone) if source_timezone else 24), is_complete=getattr(report, "is_complete", False), hour=hour, report_time_utc=getattr(report, "report_time_utc", None), source_timezone=source_timezone)


def _resolve_dimension_date_range(*, report_date: date | None, start_date: date | None, end_date: date | None) -> tuple[date, date]:
    if report_date is not None:
        if start_date is not None or end_date is not None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Use report_date or start_date/end_date, not both")
        return report_date, report_date
    if start_date is None or end_date is None or end_date < start_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="start_date and end_date must form a valid range")
    if (end_date - start_date).days > 30:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Dimension report date range cannot exceed 31 days")
    return start_date, end_date


def _dimension_response(*, start_date: date, end_date: date, total: int, items: list[schemas.DimensionReportRow], page: int, page_size: int) -> schemas.DimensionReportResponse:
    return schemas.DimensionReportResponse(report_date=start_date if start_date == end_date else None, start_date=start_date, end_date=end_date, dimension_data_available=end_date >= DIMENSION_DATA_AVAILABLE_FROM, available_from=DIMENSION_DATA_AVAILABLE_FROM, page=page, page_size=page_size, total=total, items=items)


def _finalized_daily_dimension_response(*, start_date: date, end_date: date, total: int, items: list[schemas.DimensionReportRow], page: int, page_size: int) -> schemas.FinalizedDailyDimensionReportResponse:
    return schemas.FinalizedDailyDimensionReportResponse(
        report_date=start_date if start_date == end_date else None,
        start_date=start_date,
        end_date=end_date,
        dimension_data_available=end_date >= DIMENSION_DATA_AVAILABLE_FROM,
        available_from=DIMENSION_DATA_AVAILABLE_FROM,
        page=page,
        page_size=page_size,
        total=total,
        items=[schemas.FinalizedDailyDimensionReportRow(**item.model_dump()) for item in items],
    )


def _page_dimension_query(db: Session, query: Any, *, page: int, page_size: int) -> tuple[int, list[Any]]:
    """Count and fetch only the requested stable page; never materialize all rows."""
    total = int(db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0)
    rows = list(db.scalars(query.offset((page - 1) * page_size).limit(page_size)))
    return total, rows


def list_mid_platform_account_daily_dimensions(db: Session, *, report_date: date | None = None, start_date: date | None = None, end_date: date | None = None, account_id: int | None = None, ad_country_code: str | None = None, ad_slot_id: str | None = None, page: int = 1, page_size: int = 100) -> schemas.FinalizedDailyDimensionReportResponse:
    start_date, end_date = _resolve_dimension_date_range(report_date=report_date, start_date=start_date, end_date=end_date)
    query = select(AccountDailyDimensionReport).where(AccountDailyDimensionReport.report_date.between(start_date, end_date)).order_by(AccountDailyDimensionReport.report_date, AccountDailyDimensionReport.account_id, AccountDailyDimensionReport.ad_country_code, AccountDailyDimensionReport.ad_slot_id)
    if account_id is not None: query = query.where(AccountDailyDimensionReport.account_id == account_id)
    if ad_country_code is not None: query = query.where(AccountDailyDimensionReport.ad_country_code == ad_country_code)
    if ad_slot_id is not None: query = query.where(AccountDailyDimensionReport.ad_slot_id == ad_slot_id)
    total, rows = _page_dimension_query(db, query, page=page, page_size=page_size)
    return _finalized_daily_dimension_response(start_date=start_date, end_date=end_date, total=total, items=[_dimension_row(row) for row in rows], page=page, page_size=page_size)


def list_mid_platform_site_daily_dimensions(db: Session, *, report_date: date | None = None, start_date: date | None = None, end_date: date | None = None, account_id: int | None = None, site_name: str | None = None, ad_country_code: str | None = None, ad_slot_id: str | None = None, page: int = 1, page_size: int = 100) -> schemas.FinalizedDailyDimensionReportResponse:
    start_date, end_date = _resolve_dimension_date_range(report_date=report_date, start_date=start_date, end_date=end_date)
    query = select(SiteDailyDimensionReport).where(SiteDailyDimensionReport.report_date.between(start_date, end_date)).order_by(SiteDailyDimensionReport.report_date, SiteDailyDimensionReport.account_id, SiteDailyDimensionReport.url_id, SiteDailyDimensionReport.ad_country_code, SiteDailyDimensionReport.ad_slot_id)
    if account_id is not None: query = query.where(SiteDailyDimensionReport.account_id == account_id)
    if site_name is not None: query = query.where(SiteDailyDimensionReport.url == site_name)
    if ad_country_code is not None: query = query.where(SiteDailyDimensionReport.ad_country_code == ad_country_code)
    if ad_slot_id is not None: query = query.where(SiteDailyDimensionReport.ad_slot_id == ad_slot_id)
    total, rows = _page_dimension_query(db, query, page=page, page_size=page_size)
    return _finalized_daily_dimension_response(start_date=start_date, end_date=end_date, total=total, items=[_dimension_row(row, site_name=row.url) for row in rows], page=page, page_size=page_size)


def _hourly_dimension_response(rows: list[Any], *, start_date: date, end_date: date, total: int, site: bool, page: int, page_size: int) -> schemas.DimensionReportResponse:
    items = [_dimension_row(row, site_name=row.url if site else None) for row in rows]
    return _dimension_response(start_date=start_date, end_date=end_date, total=total, items=items, page=page, page_size=page_size)


def _expected_hours_for_timezone(report_date: date, timezone_name: str) -> int:
    start = datetime(report_date.year, report_date.month, report_date.day, tzinfo=ZoneInfo(timezone_name))
    end = start + timedelta(days=1)
    return int((end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() // 3600)


def list_mid_platform_account_hourly_dimensions(db: Session, *, report_date: date | None = None, start_date: date | None = None, end_date: date | None = None, account_id: int | None = None, ad_country_code: str | None = None, ad_slot_id: str | None = None, page: int = 1, page_size: int = 100) -> schemas.DimensionReportResponse:
    start_date, end_date = _resolve_dimension_date_range(report_date=report_date, start_date=start_date, end_date=end_date)
    start_utc, end_utc = _beijing_date_range_utc(start_date, end_date)
    query = select(AccountHourlyReport).where(AccountHourlyReport.report_time_utc >= start_utc, AccountHourlyReport.report_time_utc < end_utc).order_by(AccountHourlyReport.report_time_utc, AccountHourlyReport.account_id, AccountHourlyReport.ad_country_code, AccountHourlyReport.ad_slot_id)
    if account_id is not None: query = query.where(AccountHourlyReport.account_id == account_id)
    if ad_country_code is not None: query = query.where(AccountHourlyReport.ad_country_code == ad_country_code)
    if ad_slot_id is not None: query = query.where(AccountHourlyReport.ad_slot_id == ad_slot_id)
    total, rows = _page_dimension_query(db, query, page=page, page_size=page_size)
    return _hourly_dimension_response(rows, start_date=start_date, end_date=end_date, total=total, site=False, page=page, page_size=page_size)


def list_mid_platform_site_hourly_dimensions(db: Session, *, report_date: date | None = None, start_date: date | None = None, end_date: date | None = None, account_id: int | None = None, site_name: str | None = None, ad_country_code: str | None = None, ad_slot_id: str | None = None, page: int = 1, page_size: int = 100) -> schemas.DimensionReportResponse:
    start_date, end_date = _resolve_dimension_date_range(report_date=report_date, start_date=start_date, end_date=end_date)
    start_utc, end_utc = _beijing_date_range_utc(start_date, end_date)
    query = select(SiteHourlyReport).where(SiteHourlyReport.report_time_utc >= start_utc, SiteHourlyReport.report_time_utc < end_utc).order_by(SiteHourlyReport.report_time_utc, SiteHourlyReport.account_id, SiteHourlyReport.url_id, SiteHourlyReport.ad_country_code, SiteHourlyReport.ad_slot_id)
    if account_id is not None: query = query.where(SiteHourlyReport.account_id == account_id)
    if site_name is not None: query = query.where(SiteHourlyReport.url == site_name)
    if ad_country_code is not None: query = query.where(SiteHourlyReport.ad_country_code == ad_country_code)
    if ad_slot_id is not None: query = query.where(SiteHourlyReport.ad_slot_id == ad_slot_id)
    total, rows = _page_dimension_query(db, query, page=page, page_size=page_size)
    return _hourly_dimension_response(rows, start_date=start_date, end_date=end_date, total=total, site=True, page=page, page_size=page_size)


def list_mid_platform_site_daily_report(
    db: Session,
    *,
    report_date: date,
    account_id: int | None = None,
    timeout_seconds: int = 15,
) -> schemas.MidPlatformSiteDailyReportResponse:
    """查询中台站点日报。

    从 Account → CollectorInstance → SiteDailyReport 三表联查，
    获取指定日期的所有站点日报数据，包括汇总信息（summary）和各节点结果（node_results）。
    """
    query = (
        select(Account, CollectorInstance, SiteDailyReport)
        .join(CollectorInstance, CollectorInstance.account_id == Account.id)
        .join(SiteDailyReport, SiteDailyReport.account_id == Account.id)
        .where(SiteDailyReport.report_date == report_date)
        .order_by(Account.id, CollectorInstance.id, SiteDailyReport.url, SiteDailyReport.url_id)
    )
    if account_id is not None:
        query = query.where(Account.id == account_id)

    rows = db.execute(query).all()
    items: list[schemas.MidPlatformSiteDailyRow] = []
    total_responses_served = 0
    total_requests = 0
    total_impressions = 0
    total_clicks = 0
    total_revenue = Decimal("0")

    node_index: dict[int, schemas.MidPlatformNodeResult] = {}

    for account, instance, site_report in rows:
        # 初始化该实例对应的节点结果
        if instance.id not in node_index:
            node_index[instance.id] = schemas.MidPlatformNodeResult(
                account_id=account.id,
                account_name=account.name,
                instance_id=instance.id,
                instance_name=instance.name,
                node_base_url=instance.report_base_url or "",
                node_account_key=instance.report_account_key or instance.name,
                source_state="success",
                source_http_status=200,
                source_run_id=None,
                row_count=0,
                message=None,
            )

        # 构建站点日报行
        site_row = schemas.MidPlatformSiteDailyRow(
            account_id=account.id,
            account_name=account.name,
            instance_id=instance.id,
            instance_name=instance.name,
            node_base_url=instance.report_base_url or "",
            node_account_key=instance.report_account_key or instance.name,
            report_date=site_report.report_date,
            site_name=site_report.url,
            responses_served=site_report.responses_served,
            requests=site_report.requests,
            impressions=site_report.impressions,
            clicks=site_report.clicks,
            revenue=float(site_report.revenue),
            ecpm=float(site_report.ecpm),
            source_run_id=None,
        )
        items.append(site_row)
        node_index[instance.id].row_count += 1

        # 累加汇总数据
        total_responses_served += site_row.responses_served
        total_requests += site_row.requests
        total_impressions += site_row.impressions
        total_clicks += site_row.clicks
        total_revenue += Decimal(str(site_row.revenue))

    node_results = list(node_index.values())

    # 构建汇总信息
    summary = _build_mid_platform_summary(
        report_date=report_date,
        node_results=node_results,
        row_count=len(items),
        total_responses_served=total_responses_served,
        total_requests=total_requests,
        total_impressions=total_impressions,
        total_clicks=total_clicks,
        total_revenue=total_revenue,
    )
    return schemas.MidPlatformSiteDailyReportResponse(
        report_date=report_date,
        timezone=resolve_report_timezone(
            db,
            account_id=account_id,
            account_ids={item.account_id for item in items},
        ),
        summary=summary,
        node_results=node_results,
        items=items,
    )


def list_mid_platform_link_daily_report(
    db: Session,
    *,
    report_date: date,
    account_id: int | None = None,
) -> schemas.MidPlatformLinkDailyReportResponse:
    """查询中台 Link 维度日报。

    与 site_daily_report 类似，但以 url_id 作为 link_key 维度。
    """
    query = (
        select(Account, CollectorInstance, SiteDailyReport)
        .join(CollectorInstance, CollectorInstance.account_id == Account.id)
        .join(SiteDailyReport, SiteDailyReport.account_id == Account.id)
        .where(SiteDailyReport.report_date == report_date)
        .order_by(Account.id, CollectorInstance.id, SiteDailyReport.url, SiteDailyReport.url_id)
    )
    if account_id is not None:
        query = query.where(Account.id == account_id)

    rows = db.execute(query).all()
    items: list[schemas.MidPlatformLinkDailyRow] = []
    total_responses_served = 0
    total_requests = 0
    total_impressions = 0
    total_clicks = 0
    total_revenue = Decimal("0")
    node_index: dict[int, schemas.MidPlatformNodeResult] = {}

    for account, instance, site_report in rows:
        if instance.id not in node_index:
            node_index[instance.id] = schemas.MidPlatformNodeResult(
                account_id=account.id,
                account_name=account.name,
                instance_id=instance.id,
                instance_name=instance.name,
                node_base_url=instance.report_base_url or "",
                node_account_key=instance.report_account_key or instance.name,
                source_state="success",
                source_http_status=200,
                source_run_id=None,
                row_count=0,
                message=None,
            )

        row = schemas.MidPlatformLinkDailyRow(
            account_id=account.id,
            account_name=account.name,
            instance_id=instance.id,
            instance_name=instance.name,
            node_base_url=instance.report_base_url or "",
            node_account_key=instance.report_account_key or instance.name,
            report_date=site_report.report_date,
            site_name=site_report.url,
            link_key=site_report.url_id,  # ← Link 维度使用 url_id
            responses_served=site_report.responses_served,
            requests=site_report.requests,
            impressions=site_report.impressions,
            clicks=site_report.clicks,
            revenue=float(site_report.revenue),
            ecpm=float(site_report.ecpm),
            source_run_id=None,
        )
        items.append(row)
        node_index[instance.id].row_count += 1
        total_responses_served += row.responses_served
        total_requests += row.requests
        total_impressions += row.impressions
        total_clicks += row.clicks
        total_revenue += Decimal(str(row.revenue))

    node_results = list(node_index.values())
    summary = _build_mid_platform_summary(
        report_date=report_date,
        node_results=node_results,
        row_count=len(items),
        total_responses_served=total_responses_served,
        total_requests=total_requests,
        total_impressions=total_impressions,
        total_clicks=total_clicks,
        total_revenue=total_revenue,
    )
    return schemas.MidPlatformLinkDailyReportResponse(
        report_date=report_date,
        timezone=resolve_report_timezone(
            db,
            account_id=account_id,
            account_ids={item.account_id for item in items},
        ),
        summary=summary,
        node_results=node_results,
        items=items,
    )


def list_mid_platform_account_daily_report(
    db: Session,
    *,
    report_date: date,
    account_id: int | None = None,
    timeout_seconds: int = 15,
) -> schemas.MidPlatformAccountDailyReportResponse:
    """查询中台账号日报。

    与 site/link 日报不同，这里连接的是 AccountDailyReport 表（账号级聚合），
    同时还会查询 site_count（该账号下有多少站点有数据）。
    """
    query = (
        select(Account, CollectorInstance, AccountDailyReport)
        .join(CollectorInstance, CollectorInstance.account_id == Account.id)
        .join(AccountDailyReport, AccountDailyReport.account_id == Account.id)
        .where(AccountDailyReport.report_date == report_date)
        .order_by(Account.id, CollectorInstance.id)
    )
    # 子查询：统计每个账号在该日期的站点数量
    site_count_query = (
        select(SiteDailyReport.account_id, func.count(SiteDailyReport.id))
        .where(SiteDailyReport.report_date == report_date)
        .group_by(SiteDailyReport.account_id)
    )
    if account_id is not None:
        query = query.where(Account.id == account_id)
        site_count_query = site_count_query.where(SiteDailyReport.account_id == account_id)

    rows = db.execute(query).all()
    site_counts = dict(db.execute(site_count_query).all())
    items: list[schemas.MidPlatformAccountDailyRow] = []
    total_responses_served = 0
    total_requests = 0
    total_impressions = 0
    total_clicks = 0
    total_revenue = Decimal("0")

    node_results: list[schemas.MidPlatformNodeResult] = []
    for account, instance, account_report in rows:
        account_row = schemas.MidPlatformAccountDailyRow(
            account_id=account.id,
            account_name=account.name,
            instance_id=instance.id,
            instance_name=instance.name,
            node_base_url=instance.report_base_url or "",
            node_account_key=instance.report_account_key or instance.name,
            report_date=account_report.report_date,
            site_count=site_counts.get(account.id, 0),
            responses_served=account_report.responses_served,
            requests=account_report.requests,
            impressions=account_report.impressions,
            clicks=account_report.clicks,
            revenue=float(account_report.revenue),
            ecpm=float(account_report.ecpm),
            source_run_id=None,
        )
        items.append(account_row)
        node_results.append(
            schemas.MidPlatformNodeResult(
                account_id=account.id,
                account_name=account.name,
                instance_id=instance.id,
                instance_name=instance.name,
                node_base_url=instance.report_base_url or "",
                node_account_key=instance.report_account_key or instance.name,
                source_state="success",
                source_http_status=200,
                source_run_id=None,
                row_count=1,  # 账号级日报每个账号只有一条
                message=None,
            )
        )
        total_responses_served += account_row.responses_served
        total_requests += account_row.requests
        total_impressions += account_row.impressions
        total_clicks += account_row.clicks
        total_revenue += Decimal(str(account_row.revenue))

    summary = _build_mid_platform_summary(
        report_date=report_date,
        node_results=node_results,
        row_count=len(items),
        total_responses_served=total_responses_served,
        total_requests=total_requests,
        total_impressions=total_impressions,
        total_clicks=total_clicks,
        total_revenue=total_revenue,
    )
    return schemas.MidPlatformAccountDailyReportResponse(
        report_date=report_date,
        timezone=resolve_report_timezone(
            db,
            account_id=account_id,
            account_ids={item.account_id for item in items},
        ),
        summary=summary,
        node_results=node_results,
        items=items,
    )


def list_mid_platform_account_hourly_report(
    db: Session,
    *,
    report_date: date,
    account_id: int | None = None,
) -> schemas.MidPlatformAccountHourlyReportResponse:
    """查询中台账号小时报表。

    连接 AccountHourlyReport 表，按时间升序排列。
    每条记录包含小时维度的广告数据（国家、广告位、收入等）。
    """
    query = (
        select(Account, CollectorInstance, AccountHourlyReport)
        .join(CollectorInstance, CollectorInstance.account_id == Account.id)
        .join(AccountHourlyReport, AccountHourlyReport.account_id == Account.id)
        .where(
            AccountHourlyReport.report_time_utc >= _beijing_date_range_utc(report_date, report_date)[0],
            AccountHourlyReport.report_time_utc < _beijing_date_range_utc(report_date, report_date)[1],
        )
        .order_by(
            Account.id,
            AccountHourlyReport.report_time_utc.asc(),
            AccountHourlyReport.ad_country_code.asc(),
            AccountHourlyReport.ad_slot_id.asc(),
        )
    )
    if account_id is not None:
        query = query.where(Account.id == account_id)

    rows = db.execute(query).all()
    items = [
        schemas.MidPlatformAccountHourlyRow(
            account_id=account.id,
            account_name=account.name,
            instance_id=instance.id,
            instance_name=instance.name,
            node_base_url=instance.report_base_url or "",
            node_account_key=instance.report_account_key or instance.name,
            report_date=_beijing_report_parts(hourly.report_time_utc)[0],
            hour=_beijing_report_parts(hourly.report_time_utc)[1],
            report_time_utc=_serialize_utc_datetime(hourly.report_time_utc),
            source_timezone=hourly.source_timezone,
            currency=hourly.currency,
            ad_country_code=hourly.ad_country_code,
            ad_country_name=hourly.ad_country_name,
            ad_slot_id=hourly.ad_slot_id,
            ad_slot_name=hourly.ad_slot_name,
            responses_served=hourly.responses_served,
            requests=hourly.requests,
            impressions=hourly.impressions,
            clicks=hourly.clicks,
            revenue=float(hourly.revenue),
            ecpm=float(hourly.ecpm),
            source_run_id=None,
        )
        for account, instance, hourly in rows
    ]
    return schemas.MidPlatformAccountHourlyReportResponse(
        report_date=report_date,
        timezone="Asia/Shanghai",
        items=items,
    )


def list_mid_platform_site_hourly_report(
    db: Session,
    *,
    report_date: date,
    account_id: int | None = None,
) -> schemas.MidPlatformSiteHourlyReportResponse:
    """查询中台站点小时报表。

    与 account_hourly 类似，但以站点（site_name）为维度。
    连接 SiteHourlyReport 表。
    """
    query = (
        select(Account, CollectorInstance, SiteHourlyReport)
        .join(CollectorInstance, CollectorInstance.account_id == Account.id)
        .join(SiteHourlyReport, SiteHourlyReport.account_id == Account.id)
        .where(
            SiteHourlyReport.report_time_utc >= _beijing_date_range_utc(report_date, report_date)[0],
            SiteHourlyReport.report_time_utc < _beijing_date_range_utc(report_date, report_date)[1],
        )
        .order_by(
            Account.id,
            SiteHourlyReport.report_time_utc.asc(),
            SiteHourlyReport.url.asc(),
            SiteHourlyReport.ad_country_code.asc(),
            SiteHourlyReport.ad_slot_id.asc(),
        )
    )
    if account_id is not None:
        query = query.where(Account.id == account_id)

    rows = db.execute(query).all()
    items = [
        schemas.MidPlatformSiteHourlyRow(
            account_id=account.id,
            account_name=account.name,
            instance_id=instance.id,
            instance_name=instance.name,
            node_base_url=instance.report_base_url or "",
            node_account_key=instance.report_account_key or instance.name,
            report_date=_beijing_report_parts(hourly.report_time_utc)[0],
            hour=_beijing_report_parts(hourly.report_time_utc)[1],
            report_time_utc=_serialize_utc_datetime(hourly.report_time_utc),
            source_timezone=hourly.source_timezone,
            currency=hourly.currency,
            site_name=hourly.url,
            ad_country_code=hourly.ad_country_code,
            ad_country_name=hourly.ad_country_name,
            ad_slot_id=hourly.ad_slot_id,
            ad_slot_name=hourly.ad_slot_name,
            responses_served=hourly.responses_served,
            requests=hourly.requests,
            impressions=hourly.impressions,
            clicks=hourly.clicks,
            revenue=float(hourly.revenue),
            ecpm=float(hourly.ecpm),
            source_run_id=None,
        )
        for account, instance, hourly in rows
    ]
    return schemas.MidPlatformSiteHourlyReportResponse(
        report_date=report_date,
        timezone="Asia/Shanghai",
        items=items,
    )


# ============================================================================
# 远端节点快照采集（远程拉取 Node 端的数据）
# ============================================================================

def _configured_mid_platform_instances(db: Session, *, account_id: int | None = None) -> list[CollectorInstance]:
    """获取所有已完整配置的采集器实例。

    条件：report_base_url、report_account_key、report_token 三者都不能为空。
    """
    query = (
        select(CollectorInstance)
        .where(
            CollectorInstance.report_base_url.is_not(None),
            CollectorInstance.report_account_key.is_not(None),
            CollectorInstance.report_token.is_not(None),
        )
        .order_by(CollectorInstance.id)
    )
    if account_id is not None:
        query = query.where(CollectorInstance.account_id == account_id)
    return list(db.scalars(query))


def _collect_remote_node_snapshots(
    db: Session,
    *,
    report_date: date,
    account_id: int | None,
    timeout_seconds: int,
) -> tuple[list[dict[str, object]], list[schemas.MidPlatformNodeResult]]:
    """从远端 Node（采集器节点）拉取报表快照数据。

    调用每个已配置实例的 /ke/report.php 接口，获取该日期的报表数据。

    对每个实例：
    1. HTTP GET 请求 report.php
    2. 校验返回的 account_key 和 report_date 是否匹配
    3. 检查 has_run 和 run_status 是否为成功
    4. 提取 items 列表和 run_id

    返回：
    - 成功的快照列表（每个元素包含 account_id, instance_id, run_id, items）
    - 所有节点的结果列表（包括成功和失败的）
    """
    successful_snapshots: list[dict[str, object]] = []
    node_results: list[schemas.MidPlatformNodeResult] = []

    for instance in _configured_mid_platform_instances(db, account_id=account_id):
        account = db.get(Account, instance.account_id)
        if account is None or not instance.report_base_url or not instance.report_account_key or not instance.report_token:
            continue

        # 初始化节点结果为 error（后续被成功覆盖）
        node_result = schemas.MidPlatformNodeResult(
            account_id=account.id,
            account_name=account.name,
            instance_id=instance.id,
            instance_name=instance.name,
            node_base_url=instance.report_base_url,
            node_account_key=instance.report_account_key,
            source_state="error",
            source_http_status=None,
            source_run_id=None,
            row_count=0,
            message=None,
        )
        try:
            # ── 请求远端 report.php ──
            response = httpx.get(
                f"{instance.report_base_url}/ke/report.php",
                params={
                    "account_key": instance.report_account_key,
                    "report_date": report_date.isoformat(),
                    "token": instance.report_token,
                },
                timeout=timeout_seconds,
            )
            node_result.source_http_status = response.status_code

            # 非 200 → 记录错误，跳过
            if response.status_code != 200:
                node_result.message = f"remote report returned HTTP {response.status_code}"
                node_results.append(node_result)
                continue

            payload = response.json()

            # ok 不为 true → 记录错误，跳过
            if payload.get("ok") is not True:
                node_result.message = str(
                    payload.get("message") or payload.get("error_message") or "remote report returned ok=false"
                )
                node_results.append(node_result)
                continue

            # account_key 不匹配 → 记录错误，跳过（防止数据串号）
            if payload.get("account_key") != instance.report_account_key:
                node_result.message = "remote report account_key mismatch"
                node_results.append(node_result)
                continue

            # report_date 不匹配 → 记录错误，跳过
            if payload.get("report_date") != report_date.isoformat():
                node_result.message = "remote report report_date mismatch"
                node_results.append(node_result)
                continue

            # 远端还没有成功跑过 → 记录为 no_snapshot
            if payload.get("has_run") is not True or payload.get("run_status") != "success":
                node_result.source_state = "no_snapshot"
                node_result.row_count = int(payload.get("row_count") or 0)
                node_results.append(node_result)
                continue

            # ── 校验数据结构 ──
            rows = payload.get("items")
            run_id = payload.get("run_id")
            if not isinstance(rows, list):
                node_result.message = "remote report items is not a list"
                node_results.append(node_result)
                continue
            if run_id is None:
                node_result.message = "remote report run_id is missing"
                node_results.append(node_result)
                continue

            # ── 成功：记录快照数据 ──
            successful_snapshots.append(
                {
                    "account_id": account.id,
                    "account_name": account.name,
                    "instance_id": instance.id,
                    "instance_name": instance.name,
                    "node_base_url": instance.report_base_url,
                    "node_account_key": instance.report_account_key,
                    "run_id": int(run_id),
                    "items": rows,
                }
            )
            node_result.source_state = "success"
            node_result.source_run_id = int(run_id)
            node_result.row_count = int(payload.get("row_count") or len(rows))
            node_results.append(node_result)

        except (httpx.HTTPError, ValueError, TypeError, InvalidOperation) as exc:
            # 网络错误、JSON 解析错误等统一捕获
            node_result.message = str(exc)
            node_results.append(node_result)

    return successful_snapshots, node_results


# ============================================================================
# 汇总信息构建
# ============================================================================

def _build_mid_platform_summary(
    *,
    report_date: date,
    node_results: list[schemas.MidPlatformNodeResult],
    row_count: int,
    total_responses_served: int,
    total_requests: int,
    total_impressions: int,
    total_clicks: int,
    total_revenue: Decimal,
) -> schemas.MidPlatformSummary:
    """构建中台报表的汇总信息（Summary）。

    包含：
    - 请求的节点总数
    - 成功的节点数 / 无快照的节点数 / 出错的节点数
    - 总行数、总广告响应数、总请求数、总展示数、总点击数、总收入
    """
    return schemas.MidPlatformSummary(
        report_date=report_date,
        requested_node_count=len(node_results),
        success_node_count=sum(1 for item in node_results if item.source_state == "success"),
        no_snapshot_node_count=sum(1 for item in node_results if item.source_state == "no_snapshot"),
        error_node_count=sum(1 for item in node_results if item.source_state == "error"),
        row_count=row_count,
        total_responses_served=total_responses_served,
        total_requests=total_requests,
        total_impressions=total_impressions,
        total_clicks=total_clicks,
        total_revenue=float(total_revenue),
    )


# ============================================================================
# FetchSchedule 的序列化 / 反序列化工具
# ============================================================================

def _build_fetch_schedule_read(schedule: FetchSchedule) -> schemas.FetchScheduleRead:
    """将数据库模型 FetchSchedule 转换为 API 响应模型 FetchScheduleRead。

    主要转换：将 JSON 字符串格式的 daily_times_json 反序列化为 Python 列表。
    """
    return schemas.FetchScheduleRead(
        id=schedule.id,
        account_id=schedule.account_id,
        collector_instance_id=schedule.collector_instance_id,
        enabled=schedule.enabled,
        mode=schedule.mode,
        daily_times=_load_daily_times(schedule.daily_times_json),
        interval_hours=schedule.interval_hours,
        timezone=schedule.timezone,
        last_triggered_at=schedule.last_triggered_at,
        next_run_at=schedule.next_run_at,
        last_trigger_status=schedule.last_trigger_status,
        last_trigger_message=schedule.last_trigger_message,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )


def _dump_daily_times(daily_times: list[str] | None) -> str | None:
    """将 daily_times 列表序列化为 JSON 字符串（存入数据库）。

    例如：["08:00", "20:00"] → '["08:00", "20:00"]'
    """
    if daily_times is None:
        return None
    return json.dumps(daily_times)


def _load_daily_times(daily_times_json: str | None) -> list[str] | None:
    """从 JSON 字符串反序列化 daily_times 列表（从数据库读出）。

    例如：'["08:00", "20:00"]' → ["08:00", "20:00"]
    """
    if daily_times_json is None:
        return None
    loaded = json.loads(daily_times_json)
    return [str(item) for item in loaded]


# ============================================================================
# 数据转换小工具
# ============================================================================

def _parse_decimal(value: object, label: str) -> Decimal:
    """安全地将任意值解析为 6 位小数的 Decimal。

    用于处理收入等金额数据。
    """
    try:
        return Decimal(str(value)).quantize(Decimal("0.000001"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {label}") from exc


def _optional_string(value: object) -> str | None:
    """安全转换为字符串：None → None，其他 → str(value)。"""
    if value is None:
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    """安全转换为整数：None → None，其他 → int(value)。"""
    if value is None:
        return None
    return int(value)


def build_report_time_utc(*, report_date: date, hour: int, source_timezone: str) -> datetime:
    """根据报告日期、小时和源时区，构建 UTC 时间。

    例如：report_date=7月20号, hour=14, source_timezone="America/Los_Angeles"
    → 洛杉矶时间 7月20号 14:00 → UTC 7月20号 21:00
    """
    local_time = datetime(report_date.year, report_date.month, report_date.day, hour, tzinfo=ZoneInfo(source_timezone))
    return local_time.astimezone(timezone.utc)


def _serialize_utc_datetime(value: datetime) -> datetime:
    """将 datetime 统一转换为带 UTC 时区信息的 datetime。

    如果 value 没有时区信息（naive datetime），默认视为 UTC。
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ============================================================================
# 采集器运行时配置（build_runtime_config）
# ============================================================================

def build_runtime_config(
    db: Session,
    instance: CollectorInstance,
    *,
    control_plane_base_url: str,
    egress_check_url: str = "https://api.ipify.org",
    request_timeout_seconds: int = 30,
    allow_stub_runtime_with_managed_credentials: bool = False,
) -> schemas.CollectorRuntimeConfigResponse:
    """构建采集器运行时所需的完整配置。

    这是采集器启动前调用的关键 API，返回采集器运行所需的一切：
    - 代理配置（proxy_host, proxy_port, proxy_username, proxy_password）
    - 出口 IP 校验地址（用于确认代理生效）
    - Google OAuth 凭据（用于访问 Google Ad Manager API）

    Google 认证有两种模式：
    1. "stub" — 没有 OAuth 配置时使用（实际上不会真正调用 GAM API）
    2. "admanager_soap" — 有完整 OAuth 配置时，提供 SOAP 调用所需的凭据

    校验：
    - 实例必须有代理绑定 → 否则 409
    - 如果有 OAuth 配置，必须已授权且 refresh_token 存在
    - account.external_account_id 必须是 GAM 的 network code
    """
    # 获取代理绑定
    proxy_binding = db.scalar(
        select(ProxyBinding).where(
            ProxyBinding.collector_instance_id == instance.id,
            ProxyBinding.account_id == instance.account_id,
        )
    )
    if proxy_binding is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Collector instance has no proxy binding")

    # 获取 OAuth 配置
    oauth_app = db.scalar(select(OAuthAppConfig).where(OAuthAppConfig.account_id == instance.account_id))
    google_runtime = schemas.CollectorGoogleRuntimeCredentials(fetch_mode="stub")

    validation_task = db.scalar(
        select(CollectorSyncTask).where(
            CollectorSyncTask.collector_instance_id == instance.id,
            CollectorSyncTask.task_type == "oauth_credential_validate",
            CollectorSyncTask.status.in_(ACTIVE_SYNC_TASK_STATUSES),
        )
    )
    if oauth_app is not None and validation_task is not None and oauth_app.pending_credential_version is not None:
        assert_fetch_allowed(
            db,
            account_id=instance.account_id,
            fetch_kind="oauth_credential_validate",
            credential_version=oauth_app.pending_credential_version,
        )
        staged = db.scalar(
            select(OAuthCredential).where(
                OAuthCredential.oauth_app_id == oauth_app.id,
                OAuthCredential.version == oauth_app.pending_credential_version,
                OAuthCredential.status == "staged",
            )
        )
        account = db.get(Account, instance.account_id)
        if staged is None or account is None or not account.external_account_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Staged OAuth credential is not runnable")
        settings = get_settings()
        cipher = CredentialCipher(
            encryption_key=settings.credential_encryption_key,
            fingerprint_key=settings.credential_fingerprint_key,
        )
        google_runtime = schemas.CollectorGoogleRuntimeCredentials(
            fetch_mode="admanager_soap",
            operation="oauth_credential_validate",
            credential_version=staged.version,
            credential_fingerprint=staged.token_fingerprint,
            granted_scopes=staged.granted_scopes,
            admanager_network_code=account.external_account_id,
            google_oauth_client_id=oauth_app.client_id,
            google_oauth_client_secret=cipher.decrypt(staged.client_secret_ciphertext),
            google_oauth_refresh_token=cipher.decrypt(staged.refresh_token_ciphertext),
        )
        oauth_app = None

    if (
        oauth_app is not None
        and allow_stub_runtime_with_managed_credentials
        and oauth_app.runtime_status == "healthy"
        and oauth_app.active_credential_version is not None
    ):
        google_runtime = schemas.CollectorGoogleRuntimeCredentials(
            fetch_mode="stub",
            credential_version=oauth_app.active_credential_version,
        )
        oauth_app = None

    if oauth_app is not None and oauth_app.active_credential_version is not None:
        health_task = db.scalar(
            select(CollectorSyncTask).where(
                CollectorSyncTask.collector_instance_id == instance.id,
                CollectorSyncTask.task_type == "oauth_health_check",
                CollectorSyncTask.status.in_(ACTIVE_SYNC_TASK_STATUSES),
            )
        )
        fetch_kind = "oauth_health_check" if health_task is not None else "claim"
        assert_fetch_allowed(
            db,
            account_id=instance.account_id,
            fetch_kind=fetch_kind,
            credential_version=oauth_app.active_credential_version,
        )
        active = db.scalar(
            select(OAuthCredential).where(
                OAuthCredential.oauth_app_id == oauth_app.id,
                OAuthCredential.version == oauth_app.active_credential_version,
                OAuthCredential.status == "active",
            )
        )
        account = db.get(Account, instance.account_id)
        if active is None or account is None or not account.external_account_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Active OAuth credential is not runnable")
        settings = get_settings()
        cipher = CredentialCipher(
            encryption_key=settings.credential_encryption_key,
            fingerprint_key=settings.credential_fingerprint_key,
        )
        google_runtime = schemas.CollectorGoogleRuntimeCredentials(
            fetch_mode="admanager_soap",
            operation="oauth_health_check" if health_task is not None else "fetch",
            credential_version=active.version,
            credential_fingerprint=active.token_fingerprint,
            granted_scopes=active.granted_scopes,
            admanager_network_code=account.external_account_id,
            google_oauth_client_id=oauth_app.client_id,
            google_oauth_client_secret=cipher.decrypt(active.client_secret_ciphertext),
            google_oauth_refresh_token=cipher.decrypt(active.refresh_token_ciphertext),
        )
        oauth_app = None

    if oauth_app is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Managed OAuth credential is required for runtime fetch",
        )

    return schemas.CollectorRuntimeConfigResponse(
        control_plane_base_url=control_plane_base_url.rstrip("/"),
        instance_id=instance.id,
        account_id=instance.account_id,
        expected_egress_ip=proxy_binding.expected_egress_ip,
        proxy_protocol=proxy_binding.protocol,
        proxy_host=proxy_binding.host,
        proxy_port=proxy_binding.port,
        proxy_username=proxy_binding.username,
        proxy_password=proxy_binding.password,
        egress_check_url=egress_check_url,
        request_timeout_seconds=request_timeout_seconds,
        google=google_runtime,
    )


# ============================================================================
# 心跳（Heartbeat）和任务认领（Claim）
# ============================================================================

def record_heartbeat(
    db: Session,
    instance: CollectorInstance,
    payload: schemas.HeartbeatRequest,
) -> tuple[CollectorInstance, str | None]:
    """记录采集器实例的心跳。

    采集器运行时定期发送心跳，用于：
    1. 更新 last_heartbeat_at（用于监控实例是否在线）
    2. 更新实例状态（如 payload.status）
    3. 返回观察到的出口 IP（用于校验代理是否生效）

    返回 (更新后的实例, 观察到的出口IP)。
    """
    instance.last_heartbeat_at = utcnow()
    if payload.status is not None:
        instance.status = payload.status
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return instance, payload.observed_egress_ip


def claim_next_task(
    db: Session,
    instance: CollectorInstance,
    *,
    credential_version: int | None,
) -> CollectorSyncTask | None:
    """采集器运行时认领下一个待执行的任务。

    认领策略（优先级）：
    1. 优先认领小时报任务（report_fetch_hourly），选 report_date 最新 + created_at 最新 + id 最大的
    2. 如果没有小时报任务，认领最早创建的任意任务
    3. 使用原子 UPDATE（带 status='pending' 条件）防止并发认领同一个任务

    返回认领成功的任务；如果没有可认领的任务则返回 None。

    这个函数使用了乐观锁模式：
    - UPDATE ... WHERE status='pending' + RETURNING
    - 如果 UPDATE 影响 0 行（被其他进程抢先），返回 None
    - rollback 释放行锁
    """
    claimed_at = utcnow()

    # 查询该实例所有 pending 任务
    pending_tasks = list(
        db.scalars(
            select(CollectorSyncTask).where(
                CollectorSyncTask.collector_instance_id == instance.id,
                CollectorSyncTask.status == "pending",
            )
        )
    )
    if not pending_tasks:
        return None

    validation_tasks = [task for task in pending_tasks if task.task_type == "oauth_credential_validate"]
    health_tasks = [task for task in pending_tasks if task.task_type == "oauth_health_check"]
    # 优先凭据验证，其次健康检查，再处理小时报任务。
    hourly_tasks = [task for task in pending_tasks if task.task_type == "report_fetch_hourly"]
    next_task = (
        min(validation_tasks, key=lambda task: (task.created_at, task.id))
        if validation_tasks
        else min(health_tasks, key=lambda task: (task.created_at, task.id))
        if health_tasks
        else max(hourly_tasks, key=lambda task: (task.report_date, task.created_at, task.id))
        if hourly_tasks
        else min(pending_tasks, key=lambda task: (task.created_at, task.id))
    )
    _assert_task_credential_is_current(
        db,
        instance=instance,
        task=next_task,
        supplied_version=credential_version,
    )

    # 原子认领（CAS 操作）
    claimed = db.execute(
        update(CollectorSyncTask)
        .where(
            CollectorSyncTask.id == next_task.id,
            CollectorSyncTask.status == "pending",  # ← 条件：只有 pending 状态才能认领
        )
        .values(status="in_progress", started_at=claimed_at)
        .returning(CollectorSyncTask)
    ).scalar_one_or_none()

    if claimed is None:
        # 并发冲突：任务已被其他进程认领
        db.rollback()
        return None

    db.commit()
    return claimed


def update_task_status(
    db: Session,
    instance: CollectorInstance,
    task_id: int,
    payload: schemas.TaskStatusUpdate,
) -> CollectorSyncTask:
    """更新任务状态（由采集器运行时调用）。

    校验：
    1. 状态转移合法性（根据 ALLOWED_STATUS_TRANSITIONS）
    2. 任务属于该实例
    3. 任务当前状态在允许的源状态集合中

    自动处理：
    - 如果目标状态是终态，自动设置 finished_at
    - 如果 started_at 为空且状态变为 in_progress，自动设置 started_at
    - 如果 payload 中有 message，自动写入 CollectorSyncLog
    """
    task_before_update = db.scalar(
        select(CollectorSyncTask).where(
            CollectorSyncTask.id == task_id,
            CollectorSyncTask.collector_instance_id == instance.id,
        )
    )
    if task_before_update is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    oauth_app = _assert_task_credential_is_current(
        db,
        instance=instance,
        task=task_before_update,
        supplied_version=payload.credential_version,
    )
    if task_before_update.status == payload.status:
        return task_before_update
    # 反向查询：当前允许的源状态
    source_statuses = allowed_source_statuses(payload.status)
    if not source_statuses:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invalid task status transition")

    finished_at = utcnow() if payload.status in TERMINAL_TASK_STATUSES else None

    # 原子更新（带状态条件 + 返回更新后的行）
    updated_task = db.execute(
        update(CollectorSyncTask)
        .where(
            CollectorSyncTask.id == task_id,
            CollectorSyncTask.collector_instance_id == instance.id,
            CollectorSyncTask.status.in_(source_statuses),  # ← 只有当前状态合法才能更新
        )
        .values(
            status=payload.status,
            started_at=case(
                # 如果 started_at 为空，自动设为当前时间；否则保持原值
                (CollectorSyncTask.started_at.is_(None), utcnow()),
                else_=CollectorSyncTask.started_at,
            ),
            finished_at=finished_at,
            updated_at=utcnow(),
        )
        .returning(CollectorSyncTask)
    ).scalar_one_or_none()

    if updated_task is None:
        # 更新失败：要么任务不存在，要么状态转移不合法
        task = db.scalar(
            select(CollectorSyncTask).where(
                CollectorSyncTask.id == task_id,
                CollectorSyncTask.collector_instance_id == instance.id,
            )
        )
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invalid task status transition")

    safe_failure_class = (
        payload.failure_class
        if payload.failure_class in SAFE_OAUTH_FAILURE_CLASSES | {"collector_task_failed"}
        else None
    )
    safe_message = payload.message
    if payload.status == "failed":
        safe_message = safe_failure_class or "collector_task_failed"
    if updated_task.task_type in {"oauth_credential_validate", "oauth_health_check"}:
        safe_message = _sanitize_oauth_task_message(safe_failure_class or payload.message)
    # 如果有消息，写入任务日志
    if safe_message:
        db.add(
            CollectorSyncLog(
                task_id=updated_task.id,
                account_id=updated_task.account_id,
                collector_instance_id=instance.id,
                level="error" if payload.status == "failed" else "info",
                message=safe_message,
            )
        )

    if updated_task.task_type == "oauth_credential_validate" and payload.status == "failed" and oauth_app is not None:
        failed_version = oauth_app.pending_credential_version
        if failed_version is not None:
            db.execute(
                update(OAuthCredential)
                .where(
                    OAuthCredential.oauth_app_id == oauth_app.id,
                    OAuthCredential.version == failed_version,
                    OAuthCredential.status == "staged",
                )
                .values(status="rejected", retired_at=utcnow())
            )
            oauth_app.pending_credential_version = None
            oauth_app.flow_status = "validation_failed"
            oauth_app.authorization_status = "authorization_failed"
            oauth_app.failure_class = safe_message or "oauth_validation_failed"
            oauth_app.failure_count += 1
            oauth_app.next_action = "reauthorize"
            db.add(
                OAuthEvent(
                    account_id=oauth_app.account_id,
                    oauth_app_id=oauth_app.id,
                    event_type="credential_validation_failed",
                    credential_version=failed_version,
                    failure_class=oauth_app.failure_class,
                    metadata_json='{"flow_status":"validation_failed"}',
                )
            )

    if oauth_app is not None and payload.status == "failed" and safe_failure_class == "oauth_refresh_revoked":
        if updated_task.task_type == "oauth_health_check":
            _open_oauth_circuit(db, oauth_app=oauth_app, account_id=instance.account_id)
        elif updated_task.task_type in {"report_fetch", "report_fetch_hourly"}:
            _request_oauth_revalidation(
                db,
                oauth_app=oauth_app,
                instance=instance,
                report_date=updated_task.report_date,
            )

    if oauth_app is not None and payload.status == "failed" and safe_failure_class == "oauth_session_expired":
        _open_oauth_circuit(
            db,
            oauth_app=oauth_app,
            account_id=instance.account_id,
            failure_class="oauth_session_expired",
            runtime_status="revoked",
            exclusion_reason="invalid_grant",
            next_action="reauthorize",
        )

    if oauth_app is not None and payload.status == "failed" and safe_failure_class == "oauth_client_invalid":
        _open_oauth_circuit(
            db,
            oauth_app=oauth_app,
            account_id=instance.account_id,
            failure_class="oauth_client_invalid",
            runtime_status="policy_blocked",
            exclusion_reason="oauth_client_invalid",
            next_action="fix_oauth_client_configuration",
        )

    if oauth_app is not None and updated_task.task_type == "oauth_health_check" and payload.status == "succeeded":
        _recover_oauth_after_health_check(db, oauth_app=oauth_app, account_id=instance.account_id)

    commit_or_raise_conflict(db, "Unable to update task status")
    db.refresh(updated_task)
    return updated_task


def _sanitize_oauth_task_message(message: str | None) -> str:
    return message if message in SAFE_OAUTH_FAILURE_CLASSES else "oauth_validation_failed"


def _request_oauth_revalidation(
    db: Session,
    *,
    oauth_app: OAuthAppConfig,
    instance: CollectorInstance,
    report_date: date,
) -> None:
    oauth_app.failure_class = "oauth_refresh_revoked"
    oauth_app.failure_count += 1
    if oauth_app.runtime_status == "degraded":
        return
    oauth_app.runtime_status = "degraded"
    oauth_app.next_action = "controlled_oauth_revalidation"
    existing = db.scalar(
        select(CollectorSyncTask).where(
            CollectorSyncTask.account_id == instance.account_id,
            CollectorSyncTask.task_type == "oauth_health_check",
            CollectorSyncTask.status.in_(ACTIVE_SYNC_TASK_STATUSES),
        )
    )
    if existing is None:
        _add_unique_active_task(
            db,
            CollectorSyncTask(
                account_id=instance.account_id,
                collector_instance_id=instance.id,
                task_type="oauth_health_check",
                report_date=report_date,
                status="pending",
                credential_version=_active_credential_version_for_task(db, account_id=instance.account_id),
                external_request_id=(
                    f"oauth-revalidate-{oauth_app.id}-v{oauth_app.active_credential_version}-{token_urlsafe(6)}"
                ),
            ),
        )
    db.add(
        OAuthEvent(
            account_id=instance.account_id,
            oauth_app_id=oauth_app.id,
            event_type="oauth_revalidation_requested",
            credential_version=oauth_app.active_credential_version,
            failure_class="oauth_refresh_revoked",
            metadata_json='{"runtime_status":"degraded"}',
        )
    )


def _open_oauth_circuit(
    db: Session,
    *,
    oauth_app: OAuthAppConfig,
    account_id: int,
    failure_class: str = "oauth_refresh_revoked",
    runtime_status: str = "revoked",
    exclusion_reason: str = "invalid_grant",
    next_action: str = "reauthorize",
) -> None:
    policy = db.scalar(select(CollectorAccountPolicy).where(CollectorAccountPolicy.account_id == account_id))
    if policy is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Collector account policy is missing")
    oauth_app.failure_class = failure_class
    oauth_app.failure_count += 1
    if oauth_app.runtime_status == runtime_status and policy.exclusion_reason == exclusion_reason:
        return
    if policy.resume_gray_enabled is None:
        policy.resume_gray_enabled = policy.gray_enabled
    if policy.resume_hourly_fetch_enabled is None:
        policy.resume_hourly_fetch_enabled = policy.hourly_fetch_enabled
    if policy.resume_authoritative_daily_enabled is None:
        policy.resume_authoritative_daily_enabled = policy.authoritative_daily_enabled
    policy.gray_enabled = False
    policy.hourly_fetch_enabled = False
    policy.authoritative_daily_enabled = False
    policy.exclusion_reason = exclusion_reason
    policy.exclusion_note = failure_class
    policy.policy_version += 1
    oauth_app.runtime_status = runtime_status
    oauth_app.revoked_at = utcnow()
    oauth_app.next_action = next_action
    schedule = db.scalar(select(FetchSchedule).where(FetchSchedule.account_id == account_id))
    if schedule is not None:
        schedule.enabled = False
        schedule.next_run_at = None
        schedule.last_trigger_status = "blocked"
        schedule.last_trigger_message = failure_class
    db.execute(
        update(CollectorSyncTask)
        .where(
            CollectorSyncTask.account_id == account_id,
            CollectorSyncTask.status == "pending",
        )
        .values(status="blocked", updated_at=utcnow())
    )
    db.add(
        OAuthEvent(
            account_id=account_id,
            oauth_app_id=oauth_app.id,
            event_type="oauth_circuit_opened",
            credential_version=oauth_app.active_credential_version,
            failure_class=failure_class,
            metadata_json=json.dumps({"runtime_status": runtime_status}, separators=(",", ":")),
        )
    )


def _recover_oauth_after_health_check(db: Session, *, oauth_app: OAuthAppConfig, account_id: int) -> None:
    policy = db.scalar(select(CollectorAccountPolicy).where(CollectorAccountPolicy.account_id == account_id))
    if policy is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Collector account policy is missing")
    oauth_app.runtime_status = "healthy"
    oauth_app.failure_class = None
    oauth_app.failure_count = 0
    oauth_app.last_verified_at = utcnow()
    oauth_app.revoked_at = None
    oauth_app.next_action = None
    if policy.exclusion_reason == "invalid_grant":
        policy.exclusion_reason = None
        policy.exclusion_note = None
        policy.gray_enabled = bool(policy.resume_gray_enabled)
        policy.hourly_fetch_enabled = bool(policy.resume_hourly_fetch_enabled)
        policy.authoritative_daily_enabled = bool(policy.resume_authoritative_daily_enabled)
        policy.resume_gray_enabled = None
        policy.resume_hourly_fetch_enabled = None
        policy.resume_authoritative_daily_enabled = None
        policy.policy_version += 1
    schedule = db.scalar(select(FetchSchedule).where(FetchSchedule.account_id == account_id))
    if schedule is not None and policy.gray_enabled and policy.hourly_fetch_enabled:
        now = utcnow()
        schedule.enabled = True
        schedule.mode = "interval_hours"
        schedule.daily_times_json = None
        schedule.interval_hours = 4
        schedule.next_run_at = now + timedelta(minutes=5 + (account_id * 17) % 50)
        schedule.last_trigger_status = "recovered"
        schedule.last_trigger_message = "oauth_health_check_succeeded"
    db.add_all(
        [
            OAuthEvent(
                account_id=account_id,
                oauth_app_id=oauth_app.id,
                event_type="oauth_health_recovered",
                credential_version=oauth_app.active_credential_version,
                metadata_json='{"runtime_status":"healthy"}',
            ),
            OAuthEvent(
                account_id=account_id,
                oauth_app_id=oauth_app.id,
                event_type="oauth_gap_scan_requested",
                credential_version=oauth_app.active_credential_version,
                metadata_json='{"reason":"oauth_recovered"}',
            ),
        ]
    )
