# AdX VPS PHP Python 触发链路实施计划

> **给代理执行者：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务逐步执行本计划。步骤使用复选框 `- [ ]` 语法进行跟踪。

**目标：** 构建一套可部署到 VPS 的 AdX 拉数链路，由公网 PHP 入口触发本机 Python HTTP API，拉取真实 AdX 站点级数据并写入 MySQL。

**架构：** 复用现有 `AdxReportService` 作为拉数核心，在其外层补一层小型持久化层、一个 loopback-only 的 FastAPI 服务，以及一个很薄的 PHP 触发脚本。代理层作为显式抽象边界保留下来，后续可扩展为账号级固定 IP，而不需要改公网触发契约。

**技术栈：** Python 3.11、FastAPI、SQLAlchemy、Pydantic Settings、Uvicorn、pytest、httpx、PHP 8、MySQL、Google Ad Manager SOAP `ReportService`

---

## 文件结构

### 需要修改的文件

- `collector/requirements.txt`
  - 增加 VPS 本机 HTTP API 和 SQL 持久化层所需依赖
- `docs/operator-notes.md`
  - 增加 VPS 触发式部署与验证说明

### 需要创建的文件

- `collector/app/vps_config.py`
  - VPS API 配置与环境变量约定
- `collector/app/vps_database.py`
  - VPS 侧 SQLAlchemy 基类、engine 辅助函数和 session factory
- `collector/app/vps_models.py`
  - 账号、代理绑定、拉取运行记录、站点报表的 ORM 模型
- `collector/app/vps_repository.py`
  - 账号查找、运行记录生命周期、报表持久化等数据库操作
- `collector/app/vps_proxy_resolver.py`
  - 代理选择抽象与默认直连实现
- `collector/app/vps_service.py`
  - 编排服务：解析账号、执行拉取、保存结果、记录运行状态
- `collector/app/vps_api.py`
  - loopback-only FastAPI 应用，对外提供 `POST /internal/fetch`
- `collector/tests/test_vps_models.py`
  - 表结构与 schema 创建测试
- `collector/tests/test_vps_service.py`
  - 编排、持久化、重跑与错误路径测试
- `collector/tests/test_vps_api.py`
  - API 请求/响应与状态码测试
- `scripts/init_vps_schema.py`
  - VPS 数据库初始化脚本
- `deploy/vps/README.md`
  - PHP、Python、MySQL、Cloudflare 的部署说明
- `deploy/vps/php/fetch.php`
  - 公网触发脚本
- `deploy/vps/systemd/adx-fetch-api.service`
  - 本机 Python API 的 systemd 样板
- `deploy/vps/nginx/api.example.conf`
  - PHP 触发入口的 nginx 样板
- `deploy/vps/env/adx-fetch-api.env.example`
  - Python 服务环境变量示例文件

---

### 任务 1：补齐 VPS 持久化基础

**文件：**
- 修改：`collector/requirements.txt`
- 新建：`collector/app/vps_config.py`
- 新建：`collector/app/vps_database.py`
- 新建：`collector/app/vps_models.py`
- 新建：`collector/tests/test_vps_models.py`
- 新建：`scripts/init_vps_schema.py`

- [ ] **步骤 1：在 `collector/tests/test_vps_models.py` 中先写失败测试**

创建如下测试文件：

```python
from __future__ import annotations

from sqlalchemy import inspect

from app.vps_database import VpsBase, build_engine


def test_vps_schema_creates_expected_tables(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'vps.db').as_posix()}"
    engine = build_engine(database_url, sql_echo=False)

    from app import vps_models  # noqa: F401

    VpsBase.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {
        "adx_account_proxies",
        "adx_accounts",
        "adx_fetch_runs",
        "adx_site_daily_reports",
    }
```

- [ ] **步骤 2：运行新测试，确认它先失败**

执行：

```powershell
cd D:\code\adx-account-isolated-collector\collector
python -m pytest tests\test_vps_models.py -q
```

预期：

- 因为 `app.vps_database` 和 `app.vps_models` 还不存在而失败

- [ ] **步骤 3：在 `collector/requirements.txt` 中加入 VPS 依赖**

追加以下内容：

```text
fastapi>=0.115,<1.0
sqlalchemy>=2.0,<3.0
pydantic-settings>=2.2,<3.0
uvicorn>=0.30,<1.0
httpx>=0.27,<1.0
PyMySQL>=1.1,<2.0
```

- [ ] **步骤 4：创建 `collector/app/vps_config.py`**

```python
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class VpsApiSettings(BaseSettings):
    app_name: str = "ADX VPS Fetch API"
    bind_host: str = "127.0.0.1"
    bind_port: int = 9100
    database_url: str = "sqlite:///./vps_api.db"
    sql_echo: bool = False

    model_config = SettingsConfigDict(
        env_prefix="ADX_VPS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_vps_settings() -> VpsApiSettings:
    return VpsApiSettings()
```

- [ ] **步骤 5：创建 `collector/app/vps_database.py`**

```python
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.vps_config import get_vps_settings


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class VpsBase(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def build_engine(database_url: str, *, sql_echo: bool):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, echo=sql_echo, future=True, connect_args=connect_args)


def build_session_factory(database_url: str, *, sql_echo: bool):
    return sessionmaker(
        bind=build_engine(database_url, sql_echo=sql_echo),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )


def get_session_factory():
    settings = get_vps_settings()
    return build_session_factory(settings.database_url, sql_echo=settings.sql_echo)


def get_db() -> Generator[Session, None, None]:
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **步骤 6：创建 `collector/app/vps_models.py`**

```python
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.vps_database import VpsBase


class AdxAccount(VpsBase):
    __tablename__ = "adx_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    network_code: Mapped[str] = mapped_column(String(64), nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AdxAccountProxy(VpsBase):
    __tablename__ = "adx_account_proxies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("adx_accounts.id"), nullable=False)
    proxy_type: Mapped[str] = mapped_column(String(16), nullable=False, default="direct")
    proxy_host: Mapped[str | None] = mapped_column(String(255))
    proxy_port: Mapped[int | None] = mapped_column(Integer)
    proxy_username: Mapped[str | None] = mapped_column(String(255))
    proxy_password: Mapped[str | None] = mapped_column(String(255))
    expected_egress_ip: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AdxFetchRun(VpsBase):
    __tablename__ = "adx_fetch_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("adx_accounts.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)


class AdxSiteDailyReport(VpsBase):
    __tablename__ = "adx_site_daily_reports"
    __table_args__ = (
        UniqueConstraint("account_id", "report_date", "site_name", name="uq_adx_site_daily_account_date_site"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("adx_accounts.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    site_name: Mapped[str] = mapped_column(String(255), nullable=False)
    responses_served: Mapped[int] = mapped_column(Integer, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False)
    revenue: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    ecpm: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    fetch_run_id: Mapped[int] = mapped_column(ForeignKey("adx_fetch_runs.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

- [ ] **步骤 7：创建 `scripts/init_vps_schema.py`**

```python
from __future__ import annotations

from app import vps_models  # noqa: F401
from app.vps_database import VpsBase, get_session_factory


def main() -> int:
    session_factory = get_session_factory()
    engine = session_factory.kw["bind"]
    VpsBase.metadata.create_all(bind=engine)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **步骤 8：再次运行 schema 测试**

执行：

```powershell
cd D:\code\adx-account-isolated-collector\collector
python -m pytest tests\test_vps_models.py -q
```

预期：

- PASS

- [ ] **步骤 9：提交持久化基础层**

```powershell
cd D:\code\adx-account-isolated-collector
git add collector/requirements.txt collector/app/vps_config.py collector/app/vps_database.py collector/app/vps_models.py collector/tests/test_vps_models.py scripts/init_vps_schema.py
git commit -m "feat: add vps fetch persistence foundation"
```

---

### 任务 2：增加拉数编排服务和代理解析边界

**文件：**
- 新建：`collector/app/vps_repository.py`
- 新建：`collector/app/vps_proxy_resolver.py`
- 新建：`collector/app/vps_service.py`
- 新建：`collector/tests/test_vps_service.py`

- [ ] **步骤 1：在 `collector/tests/test_vps_service.py` 中先写失败测试**

创建如下测试文件：

```python
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.adx_report_service import AdxReportRow
from app.vps_database import VpsBase, build_session_factory


class FakeReportService:
    def fetch_site_daily_report(self, *, report_date, task_id=1):
        return [
            AdxReportRow(
                report_date=report_date.isoformat(),
                site_name="jane.ghfkl.com",
                responses_served=34,
                impressions=33,
                clicks=4,
                revenue="7.646800",
                ecpm="231.721203",
            )
        ]


def test_vps_fetch_service_persists_run_and_rows(tmp_path) -> None:
    from app.vps_models import AdxAccount
    from app.vps_service import VpsFetchService

    session_factory = build_session_factory(f"sqlite:///{(tmp_path / 'svc.db').as_posix()}", sql_echo=False)
    VpsBase.metadata.create_all(bind=session_factory.kw["bind"])

    with session_factory() as db:
        db.add(
            AdxAccount(
                account_key="a1",
                account_name="Account 1",
                network_code="23347208010",
                client_id="client-id",
                client_secret="client-secret",
                refresh_token="refresh-token",
                status="active",
            )
        )
        db.commit()

    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportService(),
    )

    result = service.run_fetch(
        account_key="a1",
        report_date=date(2026, 5, 14),
        trigger_source="php_manual",
        request_id="req-001",
    )

    assert result.status == "success"
    assert result.row_count == 1

    with session_factory() as db:
        from app.vps_models import AdxFetchRun, AdxSiteDailyReport

        run = db.query(AdxFetchRun).one()
        row = db.query(AdxSiteDailyReport).one()

        assert run.status == "success"
        assert run.request_id == "req-001"
        assert row.site_name == "jane.ghfkl.com"
        assert row.revenue == Decimal("7.646800")
        assert row.ecpm == Decimal("231.721203")
```

- [ ] **步骤 2：运行服务测试，确认它先失败**

执行：

```powershell
cd D:\code\adx-account-isolated-collector\collector
python -m pytest tests\test_vps_service.py::test_vps_fetch_service_persists_run_and_rows -q
```

预期：

- 因为 `app.vps_service` 还不存在而失败

- [ ] **步骤 3：创建 `collector/app/vps_repository.py`**

```python
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.adx_report_service import AdxReportRow
from app.vps_models import AdxAccount, AdxAccountProxy, AdxFetchRun, AdxSiteDailyReport


class VpsRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_active_account_by_key(self, account_key: str) -> AdxAccount | None:
        return (
            self._db.query(AdxAccount)
            .filter(AdxAccount.account_key == account_key, AdxAccount.status == "active")
            .one_or_none()
        )

    def get_active_proxy_for_account(self, account_id: int) -> AdxAccountProxy | None:
        return (
            self._db.query(AdxAccountProxy)
            .filter(AdxAccountProxy.account_id == account_id, AdxAccountProxy.is_active.is_(True))
            .one_or_none()
        )

    def create_fetch_run(self, *, account_id: int, report_date, trigger_source: str, request_id: str) -> AdxFetchRun:
        run = AdxFetchRun(
            account_id=account_id,
            report_date=report_date,
            trigger_source=trigger_source,
            request_id=request_id,
            status="running",
            row_count=0,
        )
        self._db.add(run)
        self._db.flush()
        return run

    def replace_site_rows(self, *, account_id: int, report_date, fetch_run_id: int, rows: list[AdxReportRow]) -> None:
        (
            self._db.query(AdxSiteDailyReport)
            .filter(AdxSiteDailyReport.account_id == account_id, AdxSiteDailyReport.report_date == report_date)
            .delete(synchronize_session=False)
        )
        for row in rows:
            self._db.add(
                AdxSiteDailyReport(
                    account_id=account_id,
                    report_date=report_date,
                    site_name=row.site_name,
                    responses_served=row.responses_served,
                    impressions=row.impressions,
                    clicks=row.clicks,
                    revenue=Decimal(row.revenue),
                    ecpm=Decimal(row.ecpm),
                    fetch_run_id=fetch_run_id,
                )
            )

    def mark_run_success(self, run: AdxFetchRun, *, row_count: int) -> None:
        run.status = "success"
        run.row_count = row_count
        run.finished_at = datetime.now(UTC)

    def mark_run_failed(self, run: AdxFetchRun, *, message: str) -> None:
        run.status = "failed"
        run.error_message = message
        run.finished_at = datetime.now(UTC)
```

- [ ] **步骤 4：创建 `collector/app/vps_proxy_resolver.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

from app.vps_models import AdxAccount, AdxAccountProxy


@dataclass(frozen=True)
class ProxyRoute:
    mode: str
    proxy_type: str | None = None
    proxy_host: str | None = None
    proxy_port: int | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None
    expected_egress_ip: str | None = None


class ProxyResolver:
    def resolve(self, *, account: AdxAccount, proxy_binding: AdxAccountProxy | None) -> ProxyRoute:
        if proxy_binding is None:
            return ProxyRoute(mode="direct")
        return ProxyRoute(
            mode="configured_proxy",
            proxy_type=proxy_binding.proxy_type,
            proxy_host=proxy_binding.proxy_host,
            proxy_port=proxy_binding.proxy_port,
            proxy_username=proxy_binding.proxy_username,
            proxy_password=proxy_binding.proxy_password,
            expected_egress_ip=proxy_binding.expected_egress_ip,
        )
```

- [ ] **步骤 5：创建 `collector/app/vps_service.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.adx_report_service import AdxApiCredentials, AdxReportService
from app.vps_proxy_resolver import ProxyResolver
from app.vps_repository import VpsRepository


class AccountConfigError(ValueError):
    pass


class FetchExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class VpsFetchResult:
    run_id: int
    account_key: str
    report_date: str
    row_count: int
    status: str


class VpsFetchService:
    def __init__(
        self,
        *,
        session_factory,
        report_service_factory=None,
        proxy_resolver: ProxyResolver | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._report_service_factory = report_service_factory or self._build_report_service
        self._proxy_resolver = proxy_resolver or ProxyResolver()

    def run_fetch(
        self,
        *,
        account_key: str,
        report_date: date,
        trigger_source: str,
        request_id: str,
    ) -> VpsFetchResult:
        with self._session_factory() as db:
            repo = VpsRepository(db)
            account = repo.get_active_account_by_key(account_key)
            if account is None:
                raise AccountConfigError(f"Unknown active account_key: {account_key}")

            proxy_binding = repo.get_active_proxy_for_account(account.id)
            proxy_route = self._proxy_resolver.resolve(account=account, proxy_binding=proxy_binding)
            run = repo.create_fetch_run(
                account_id=account.id,
                report_date=report_date,
                trigger_source=trigger_source,
                request_id=request_id,
            )

            try:
                report_service = self._report_service_factory(account, proxy_route)
                rows = report_service.fetch_site_daily_report(report_date=report_date, task_id=run.id)
                repo.replace_site_rows(
                    account_id=account.id,
                    report_date=report_date,
                    fetch_run_id=run.id,
                    rows=rows,
                )
                repo.mark_run_success(run, row_count=len(rows))
                db.commit()
            except Exception as exc:
                repo.mark_run_failed(run, message=str(exc))
                db.commit()
                raise FetchExecutionError(str(exc)) from exc

            return VpsFetchResult(
                run_id=run.id,
                account_key=account.account_key,
                report_date=report_date.isoformat(),
                row_count=len(rows),
                status="success",
            )

    @staticmethod
    def _build_report_service(account, proxy_route) -> AdxReportService:
        return AdxReportService(
            credentials=AdxApiCredentials(
                network_code=account.network_code,
                client_id=account.client_id,
                client_secret=account.client_secret,
                refresh_token=account.refresh_token,
            )
        )
```

- [ ] **步骤 6：再次运行服务测试**

执行：

```powershell
cd D:\code\adx-account-isolated-collector\collector
python -m pytest tests\test_vps_service.py::test_vps_fetch_service_persists_run_and_rows -q
```

预期：

- PASS

- [ ] **步骤 7：增加“同账号同日期重跑”测试**

将下面测试追加到 `collector/tests/test_vps_service.py`：

```python
def test_vps_fetch_service_replaces_existing_rows_for_same_account_and_date(tmp_path) -> None:
    from app.vps_models import AdxAccount, AdxSiteDailyReport
    from app.vps_service import VpsFetchService

    class FakeReportServiceTwo:
        def fetch_site_daily_report(self, *, report_date, task_id=1):
            return [
                AdxReportRow(
                    report_date=report_date.isoformat(),
                    site_name="jane.ghfkl.com",
                    responses_served=99,
                    impressions=88,
                    clicks=7,
                    revenue="9.000000",
                    ecpm="102.272727",
                )
            ]

    session_factory = build_session_factory(f"sqlite:///{(tmp_path / 'rerun.db').as_posix()}", sql_echo=False)
    VpsBase.metadata.create_all(bind=session_factory.kw["bind"])

    with session_factory() as db:
        db.add(
            AdxAccount(
                account_key="a1",
                account_name="Account 1",
                network_code="23347208010",
                client_id="client-id",
                client_secret="client-secret",
                refresh_token="refresh-token",
                status="active",
            )
        )
        db.commit()

    service = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportService(),
    )
    service.run_fetch(account_key="a1", report_date=date(2026, 5, 14), trigger_source="php_manual", request_id="req-1")

    service_two = VpsFetchService(
        session_factory=session_factory,
        report_service_factory=lambda account, proxy_route: FakeReportServiceTwo(),
    )
    service_two.run_fetch(account_key="a1", report_date=date(2026, 5, 14), trigger_source="php_manual", request_id="req-2")

    with session_factory() as db:
        rows = db.query(AdxSiteDailyReport).all()
        assert len(rows) == 1
        assert rows[0].responses_served == 99
```

- [ ] **步骤 8：运行完整服务测试文件**

执行：

```powershell
cd D:\code\adx-account-isolated-collector\collector
python -m pytest tests\test_vps_service.py -q
```

预期：

- PASS

- [ ] **步骤 9：提交编排服务**

```powershell
cd D:\code\adx-account-isolated-collector
git add collector/app/vps_repository.py collector/app/vps_proxy_resolver.py collector/app/vps_service.py collector/tests/test_vps_service.py
git commit -m "feat: add vps fetch orchestration service"
```

---

### 任务 3：增加 loopback-only Python HTTP API

**文件：**
- 新建：`collector/app/vps_api.py`
- 新建：`collector/tests/test_vps_api.py`

- [ ] **步骤 1：在 `collector/tests/test_vps_api.py` 中先写失败测试**

创建如下文件：

```python
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from app.vps_service import VpsFetchResult


class FakeFetchService:
    def run_fetch(self, *, account_key, report_date, trigger_source, request_id):
        assert account_key == "a1"
        assert report_date == date(2026, 6, 3)
        assert trigger_source == "php_manual"
        assert request_id == "req-001"
        return VpsFetchResult(
            run_id=17,
            account_key=account_key,
            report_date=report_date.isoformat(),
            row_count=8,
            status="success",
        )


def test_internal_fetch_endpoint_returns_success_payload() -> None:
    from app.vps_api import create_app

    app = create_app(fetch_service=FakeFetchService())
    client = TestClient(app)

    response = client.post(
        "/internal/fetch",
        json={
            "account_key": "a1",
            "report_date": "2026-06-03",
            "trigger_source": "php_manual",
            "request_id": "req-001",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "run_id": 17,
        "account_key": "a1",
        "report_date": "2026-06-03",
        "row_count": 8,
        "status": "success",
    }
```

- [ ] **步骤 2：运行 API 测试，确认它先失败**

执行：

```powershell
cd D:\code\adx-account-isolated-collector\collector
python -m pytest tests\test_vps_api.py::test_internal_fetch_endpoint_returns_success_payload -q
```

预期：

- 因为 `app.vps_api` 还不存在而失败

- [ ] **步骤 3：创建 `collector/app/vps_api.py`**

```python
from __future__ import annotations

from datetime import date

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.vps_database import get_session_factory
from app.vps_service import AccountConfigError, FetchExecutionError, VpsFetchService


class FetchRequest(BaseModel):
    account_key: str = Field(min_length=1)
    report_date: date
    trigger_source: str = Field(min_length=1)
    request_id: str = Field(min_length=1)


class FetchResponse(BaseModel):
    ok: bool
    run_id: int
    account_key: str
    report_date: str
    row_count: int
    status: str


def create_app(*, fetch_service: VpsFetchService | object | None = None) -> FastAPI:
    application = FastAPI(title="ADX VPS Fetch API")
    service = fetch_service or VpsFetchService(session_factory=get_session_factory())

    @application.get("/health")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/internal/fetch", response_model=FetchResponse)
    def internal_fetch(payload: FetchRequest) -> FetchResponse:
        try:
            result = service.run_fetch(
                account_key=payload.account_key,
                report_date=payload.report_date,
                trigger_source=payload.trigger_source,
                request_id=payload.request_id,
            )
        except AccountConfigError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FetchExecutionError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return FetchResponse(
            ok=True,
            run_id=result.run_id,
            account_key=result.account_key,
            report_date=result.report_date,
            row_count=result.row_count,
            status=result.status,
        )

    return application


app = create_app()
```

- [ ] **步骤 4：增加一个错误路径 API 测试**

将下面测试追加到 `collector/tests/test_vps_api.py`：

```python
def test_internal_fetch_endpoint_maps_account_config_errors_to_422() -> None:
    from app.vps_api import create_app
    from app.vps_service import AccountConfigError

    class FailingFetchService:
        def run_fetch(self, *, account_key, report_date, trigger_source, request_id):
            raise AccountConfigError("Unknown active account_key: bad")

    app = create_app(fetch_service=FailingFetchService())
    client = TestClient(app)

    response = client.post(
        "/internal/fetch",
        json={
            "account_key": "bad",
            "report_date": "2026-06-03",
            "trigger_source": "php_manual",
            "request_id": "req-002",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Unknown active account_key: bad"}
```

- [ ] **步骤 5：运行完整 API 测试文件**

执行：

```powershell
cd D:\code\adx-account-isolated-collector\collector
python -m pytest tests\test_vps_api.py -q
```

预期：

- PASS

- [ ] **步骤 6：提交 loopback API**

```powershell
cd D:\code\adx-account-isolated-collector
git add collector/app/vps_api.py collector/tests/test_vps_api.py
git commit -m "feat: add vps loopback fetch api"
```

---

### 任务 4：补齐 PHP 触发器、部署资产和验证文档

**文件：**
- 新建：`deploy/vps/php/fetch.php`
- 新建：`deploy/vps/systemd/adx-fetch-api.service`
- 新建：`deploy/vps/nginx/api.example.conf`
- 新建：`deploy/vps/env/adx-fetch-api.env.example`
- 新建：`deploy/vps/README.md`
- 修改：`docs/operator-notes.md`

- [ ] **步骤 1：创建公网触发脚本 `deploy/vps/php/fetch.php`**

```php
<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');

$token = $_GET['token'] ?? '';
$accountKey = $_GET['account_key'] ?? '';
$reportDate = $_GET['report_date'] ?? '';
$expectedToken = getenv('ADX_TRIGGER_TOKEN') ?: '';

if ($expectedToken === '' || !hash_equals($expectedToken, $token)) {
    http_response_code(401);
    echo json_encode(['ok' => false, 'error_code' => 'REQUEST_ERROR', 'message' => 'invalid token']);
    exit;
}

if ($accountKey === '' || $reportDate === '') {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error_code' => 'REQUEST_ERROR', 'message' => 'missing account_key or report_date']);
    exit;
}

$requestId = 'req_' . gmdate('Ymd_His') . '_' . bin2hex(random_bytes(4));
$payload = json_encode([
    'account_key' => $accountKey,
    'report_date' => $reportDate,
    'trigger_source' => 'php_manual',
    'request_id' => $requestId,
], JSON_UNESCAPED_SLASHES);

$ch = curl_init('http://127.0.0.1:9100/internal/fetch');
curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPHEADER => ['Content-Type: application/json'],
    CURLOPT_POSTFIELDS => $payload,
    CURLOPT_TIMEOUT => 120,
]);

$body = curl_exec($ch);
$status = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
$error = curl_error($ch);
curl_close($ch);

if ($body === false) {
    http_response_code(502);
    echo json_encode(['ok' => false, 'request_id' => $requestId, 'error_code' => 'FETCH_ERROR', 'message' => $error]);
    exit;
}

http_response_code($status > 0 ? $status : 502);
echo $body;
```

- [ ] **步骤 2：对 PHP 文件做语法检查**

执行：

```powershell
php -l D:\code\adx-account-isolated-collector\deploy\vps\php\fetch.php
```

预期：

- 输出 `No syntax errors detected`

- [ ] **步骤 3：创建 Python 服务环境变量示例文件**

路径：`deploy/vps/env/adx-fetch-api.env.example`

```text
ADX_VPS_DATABASE_URL=mysql+pymysql://adx_user:change_me@127.0.0.1:3306/adx_data
ADX_VPS_SQL_ECHO=false
ADX_VPS_BIND_HOST=127.0.0.1
ADX_VPS_BIND_PORT=9100
ADX_TRIGGER_TOKEN=change-me
```

- [ ] **步骤 4：创建 systemd 单元文件**

路径：`deploy/vps/systemd/adx-fetch-api.service`

```ini
[Unit]
Description=ADX VPS Fetch API
After=network.target

[Service]
Type=simple
WorkingDirectory=/srv/adx-account-isolated-collector/collector
EnvironmentFile=/srv/adx-account-isolated-collector/deploy/vps/env/adx-fetch-api.env
ExecStart=/usr/bin/python3 -m uvicorn app.vps_api:app --host 127.0.0.1 --port 9100
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

- [ ] **步骤 5：创建 nginx 示例配置**

路径：`deploy/vps/nginx/api.example.conf`

```nginx
server {
    listen 80;
    server_name api.example.com;
    root /srv/adx-account-isolated-collector/deploy/vps/php;
    index fetch.php;

    location /ke/fetch.php {
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root/fetch.php;
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
    }
}
```

- [ ] **步骤 6：创建 `deploy/vps/README.md`**

```markdown
# VPS Trigger Deployment

## Python API

1. Install Python dependencies from `collector/requirements.txt`.
2. Copy `deploy/vps/env/adx-fetch-api.env.example` to `deploy/vps/env/adx-fetch-api.env`.
3. Set a real MySQL URL and trigger token.
4. Run `python scripts/init_vps_schema.py`.
5. Start the API with `python -m uvicorn app.vps_api:app --host 127.0.0.1 --port 9100`.

## PHP Trigger

- Place `deploy/vps/php/fetch.php` under the public API site root.
- Ensure PHP has `curl` enabled.
- Set `ADX_TRIGGER_TOKEN` in the PHP-FPM environment.

## Cloudflare

- Point the API subdomain to the VPS origin.
- Keep Cloudflare as DNS/HTTPS ingress only.

## Smoke Test

Call:

`https://api.example.com/ke/fetch.php?account_key=a1&report_date=2026-05-14&token=change-me`
```

- [ ] **步骤 7：在 `docs/operator-notes.md` 中补充 VPS 触发链路说明**

在部署说明附近加入：

```markdown
## VPS Trigger Stack

The VPS deployment path uses:

- public PHP trigger: `GET /ke/fetch.php`
- local Python API: `POST http://127.0.0.1:9100/internal/fetch`
- result storage tables:
  - `adx_accounts`
  - `adx_account_proxies`
  - `adx_fetch_runs`
  - `adx_site_daily_reports`

The current production-style fetch still uses the verified site-level SOAP report semantics:

- `DATE_PT`
- `SITE_NAME`
- `AD_EXCHANGE_RESPONSES_SERVED`
- `AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS`
- `AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS`
- `AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE`
- `AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM`
```

- [ ] **步骤 8：运行 VPS 相关测试集**

执行：

```powershell
cd D:\code\adx-account-isolated-collector\collector
python -m pytest tests\test_vps_models.py tests\test_vps_service.py tests\test_vps_api.py -q
```

预期：

- PASS

- [ ] **步骤 9：提交部署资产和文档**

```powershell
cd D:\code\adx-account-isolated-collector
git add deploy/vps/php/fetch.php deploy/vps/systemd/adx-fetch-api.service deploy/vps/nginx/api.example.conf deploy/vps/env/adx-fetch-api.env.example deploy/vps/README.md docs/operator-notes.md
git commit -m "feat: add vps php trigger deployment assets"
```

---

## 自检

- 规格覆盖：
  - VPS 本机 Python API：任务 3
  - PHP 触发入口：任务 4
  - MySQL 持久化：任务 1 和任务 2
  - 代理扩展边界：任务 2 中的 `ProxyResolver`
  - 部署说明与冒烟测试：任务 4
- 占位符扫描：
  - 计划里不应留下 `TODO`、`TBD` 或“后续再补”这类空洞指令
- 类型一致性：
  - 结果表、路由对象和 API 负载统一使用 `account_key`、`report_date`、`request_id`、`row_count`

---

## 执行交接

计划已保存到 `docs/superpowers/plans/2026-06-04-adx-vps-php-python-trigger.md`。接下来有两种执行方式：

**1. 子代理驱动（推荐）** - 我为每个任务派发一个新的子代理，中间做复核，迭代更快

**2. 当前会话内执行** - 在这个会话里批量执行任务，并在关键节点检查

**请选择一种方式。**
