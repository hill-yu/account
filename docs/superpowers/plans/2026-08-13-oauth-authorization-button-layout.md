# OAuth 授权按钮布局修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将 OAuth 授权操作移动到应用身份信息旁，并确保长 client ID/redirect URI 和窄屏布局下按钮无需滚动到最右侧即可看见。

**架构：** 保留 `OAuthAppsSection` 的状态机、错误处理和 API 调用，仅调整表格 DOM 并增加 OAuth 专用 CSS。Vitest/jsdom 精确验证 DOM 归属、状态矩阵和 CSS 契约；本地临时验收页复用静态组件标记和项目 CSS，在可用浏览器中验证 1440px/768px bounding box。所有实现保持未提交，定向/全量验证和两阶段独立审阅通过后才提交。

**技术栈：** React 19、TypeScript、Vitest、jsdom、CSS、Vite。

---

## 文件结构

- 修改：`frontend/src/features/oauth/OAuthAppsSection.tsx` — 将授权按钮移入应用信息单元格，删除 Action 列并调整空状态列数。
- 修改：`frontend/src/styles.css` — 增加 OAuth 专用列宽、滚动、长文本换行和按钮尺寸规则。
- 修改：`frontend/src/__tests__/oauthHealth.test.tsx` — 增加 DOM、状态矩阵和 CSS 契约测试。
- 修改：`docs/system-maintainer-onboarding-guide.md` — 更新第 22 节现有记录中的实现、测试、审阅、Git 和未发布状态。
- 条件修改：`docs/问题记录.md` — 仅在实施发生实际命令、代码或操作错误时追加脱敏记录。

## 任务 1：一次性建立完整红灯

**文件：**
- 修改：`frontend/src/__tests__/oauthHealth.test.tsx`

- [ ] **步骤 1：增加 DOM 与 CSS 读取辅助函数**

```tsx
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

function renderAppsDocument(apps: OAuthAppRead[]): Document {
  return new DOMParser().parseFromString(renderApps(apps), "text/html");
}

function getColumnIndex(document: Document, label: string): number {
  return Array.from(document.querySelectorAll("thead th")).findIndex(
    (header) => header.textContent?.trim() === label,
  );
}

function readStyles(): string {
  return readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");
}
```

- [ ] **步骤 2：增加按钮归属、列数和布局 hook 测试**

```tsx
it("renders the authorization action inside the Account / App cell", () => {
  const document = renderAppsDocument([{ ...baseApp, flow_status: "draft", runtime_status: "unknown" }]);
  const accountColumn = getColumnIndex(document, "Account / App");
  const accountCell = document.querySelectorAll("tbody tr")[0]?.children.item(accountColumn);

  expect(accountColumn).toBeGreaterThanOrEqual(0);
  expect(accountCell?.querySelector("button")?.textContent).toBe("Generate URL");
  expect(getColumnIndex(document, "Action")).toBe(-1);
  expect(document.querySelector(".oauth-apps-table-shell")).not.toBeNull();
  expect(document.querySelector(".oauth-apps-table")).not.toBeNull();
  expect(accountCell?.classList.contains("oauth-app-identity-cell")).toBe(true);
  expect(accountCell?.querySelector(".oauth-app-redirect-uri")).not.toBeNull();
  expect(accountCell?.querySelector(".oauth-app-authorization-action")).not.toBeNull();
});

it("spans the OAuth empty state across the eight visible columns", () => {
  const document = renderAppsDocument([]);
  expect(document.querySelectorAll("thead th")).toHaveLength(8);
  expect(document.querySelector("tbody .empty-cell")?.getAttribute("colspan")).toBe("8");
});
```

- [ ] **步骤 3：增加 CSS 契约测试**

```tsx
it("defines the OAuth table overflow and long-value wrapping contract", () => {
  const css = readStyles();
  expect(css).toMatch(/\.oauth-apps-table-shell\s*\{[^}]*overflow-x:\s*auto/s);
  expect(css).toMatch(/\.oauth-apps-table\s*\{[^}]*table-layout:\s*fixed/s);
  expect(css).toMatch(/\.oauth-app-identity-value[\s\S]*overflow-wrap:\s*anywhere/s);
  expect(css).toMatch(/\.oauth-app-redirect-uri[\s\S]*overflow-wrap:\s*anywhere/s);
  expect(css).toMatch(/\.oauth-app-authorization-action\s*\{[^}]*flex:\s*0\s+0\s+auto/s);
});
```

这些断言只锁定本功能要求的局部契约，不解析整个 CSS 语义。

- [ ] **步骤 4：运行红灯并核对失败原因**

```powershell
npm test -- --run src/__tests__/oauthHealth.test.tsx
```

工作目录：`frontend`。预期：FAIL，原因必须同时包含按钮仍在 Action 列、表头/colspan 仍为 9、专用 class/CSS 不存在；不得因模块导入或 fixture 错误失败。

## 任务 2：最小 JSX 和 CSS 绿灯

**文件：**
- 修改：`frontend/src/features/oauth/OAuthAppsSection.tsx:307-367`
- 修改：`frontend/src/styles.css:392-395`
- 测试：`frontend/src/__tests__/oauthHealth.test.tsx`

- [ ] **步骤 1：修改容器和表格 class**

```tsx
<div className="table-card oauth-apps-table-shell">
  <table className="data-table oauth-apps-table">
```

- [ ] **步骤 2：将按钮移入 Account / App 单元格**

```tsx
<td className="oauth-app-identity-cell">
  <div className="oauth-app-identity">
    <div className="oauth-app-identity-value">
      {oauthApp.account_id} / {oauthApp.client_id}
    </div>
    <div className="token-meta oauth-app-redirect-uri">{oauthApp.redirect_uri}</div>
    <button
      type="button"
      className="secondary-button oauth-app-authorization-action"
      onClick={() => void handleGenerate(oauthApp)}
      disabled={action.disabled || generatingId === oauthApp.id}
    >
      {generatingId === oauthApp.id ? "Generating..." : action.label}
    </button>
  </div>
</td>
```

删除 `<th>Action</th>` 和每行最后的 Action `<td>`，把空状态改为 `colSpan={8}`。

- [ ] **步骤 3：增加局部 CSS**

```css
.oauth-apps-table-shell {
  overflow-x: auto;
  overflow-y: hidden;
}

.oauth-apps-table {
  table-layout: fixed;
  min-width: 920px;
}

.oauth-apps-table th:nth-child(1) { width: 52px; }
.oauth-apps-table th:nth-child(2) { width: 280px; }
.oauth-apps-table th:nth-child(3),
.oauth-apps-table th:nth-child(4) { width: 104px; }
.oauth-apps-table th:nth-child(5) { width: 112px; }
.oauth-apps-table th:nth-child(6) { width: 128px; }
.oauth-apps-table th:nth-child(7) { width: 132px; }
.oauth-apps-table th:nth-child(8) { width: 148px; }

.oauth-app-identity {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
}

.oauth-app-identity-value,
.oauth-app-redirect-uri {
  max-width: 100%;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.oauth-app-authorization-action {
  flex: 0 0 auto;
  max-width: 100%;
  white-space: normal;
}
```

- [ ] **步骤 4：运行定向测试和构建**

```powershell
npm test -- --run src/__tests__/oauthHealth.test.tsx
npm run build
```

预期：全部 PASS。此时仍不提交 Git。

## 任务 3：锁定授权状态矩阵

**文件：**
- 修改：`frontend/src/__tests__/oauthHealth.test.tsx`

- [ ] **步骤 1：增加按钮查询辅助函数**

```tsx
function getAuthorizationButton(app: OAuthAppRead): HTMLButtonElement {
  const button = renderAppsDocument([app]).querySelector<HTMLButtonElement>(
    ".oauth-app-authorization-action",
  );
  if (!button) throw new Error("authorization button not rendered");
  return button;
}
```

- [ ] **步骤 2：增加四类状态测试**

```tsx
it.each([
  [{ ...baseApp, flow_status: "draft", runtime_status: "unknown" }, "Generate URL", false],
  [baseApp, "Reauthorize", false],
  [{ ...baseApp, runtime_status: "revoked" }, "Restore authorization", false],
  [{ ...baseApp, flow_status: "validation_pending", runtime_status: "unknown" }, "Validation pending", true],
] as const)("renders the expected authorization action", (app, label, disabled) => {
  const button = getAuthorizationButton(app as OAuthAppRead);
  expect(button.textContent).toBe(label);
  expect(button.disabled).toBe(disabled);
});
```

- [ ] **步骤 3：运行定向测试**

```powershell
npm test -- --run src/__tests__/oauthHealth.test.tsx
```

预期：PASS；现有 `getOAuthAuthorizationAction` 无需修改。仍不提交 Git。

## 任务 4：可重复的 1440/768 布局验收

**文件：**
- 不提交临时验收文件；临时目录使用 PowerShell/.NET 创建并在验收后保留到当前任务结束，便于审阅复核。

- [ ] **步骤 1：用现有 Vitest runner 生成脱敏静态验收页**

在 `frontend/src/__tests__/oauthLayoutAcceptance.generate.test.tsx` 临时创建一个生成器测试（验收结束前删除，不提交）。该测试复用 `baseApp` 等价的脱敏 fixture、`ToastContext` 和 `renderToStaticMarkup`，把包含 160 字符 client ID/redirect URI 的 `OAuthAppsSection` 标记与 `styles.css` 内联写入由环境变量 `OAUTH_LAYOUT_ACCEPTANCE_HTML` 指定的绝对临时路径。fixture 仅使用 `example.test` 和重复字符，不包含生产数据。

生成器核心输入为：

```tsx
const longApp = {
  ...baseApp,
  client_id: "x".repeat(160),
  redirect_uri: `https://example.test/oauth/google/callback/${"r".repeat(160)}`,
};
```

输出路径必须位于 `[System.IO.Path]::GetTempPath()` 下，不能写进仓库。

执行命令：

```powershell
$acceptanceRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'adx-oauth-layout-acceptance'
New-Item -ItemType Directory -Force -Path $acceptanceRoot | Out-Null
$env:OAUTH_LAYOUT_ACCEPTANCE_HTML = Join-Path $acceptanceRoot 'index.html'
npm test -- --run src/__tests__/oauthLayoutAcceptance.generate.test.tsx
if ($LASTEXITCODE -ne 0) { throw 'acceptance fixture generation failed' }
if (-not (Test-Path -LiteralPath $env:OAUTH_LAYOUT_ACCEPTANCE_HTML -PathType Leaf)) {
  throw 'acceptance HTML was not generated'
}
```

生成失败是验收阻塞，不得用手写近似 DOM 替代组件输出。

- [ ] **步骤 2：用现有 Vite 提供临时验收页**

```powershell
npm exec -- vite --host 127.0.0.1 --port 4174 $acceptanceRoot
```

打开固定本地 URL `http://127.0.0.1:4174/`。验收结束后停止 Vite，删除临时生成器测试，并运行 `git status --short` 确认该测试没有进入最终差异。

- [ ] **步骤 3：确定本机可用浏览器驱动**

优先使用工作区已有浏览器自动化依赖；若无依赖，检查系统 Edge/Chrome 的明确安装路径并使用其 headless 模式。不得联网安装新依赖。若当前环境没有可调用浏览器，记录为布局人工验收阻塞并请求用户选择，不得伪造 bounding-box 结果。

- [ ] **步骤 4：执行 1440px 验收**

在 `1440x900`、初始 `scrollLeft=0` 下读取：

```js
const shell = document.querySelector('.oauth-apps-table-shell');
const button = document.querySelector('.oauth-app-authorization-action');
const identity = document.querySelector('.oauth-app-identity-cell');
const shellRect = shell.getBoundingClientRect();
const buttonRect = button.getBoundingClientRect();
({
  visible: buttonRect.left >= shellRect.left && buttonRect.right <= shellRect.right,
  scrollLeft: shell.scrollLeft,
  wrapped: identity.scrollWidth <= identity.clientWidth,
});
```

预期：`visible=true`、`scrollLeft=0`、`wrapped=true`。

- [ ] **步骤 5：执行 768px 验收**

在 `768x900` 重复相同脚本。允许 `shell.scrollWidth > shell.clientWidth`，但上述三个预期必须保持成立。

- [ ] **步骤 6：记录证据并清理临时资源**

记录浏览器名称/版本、两档视口、脱敏 fixture 和三个断言结果；停止临时 Vite，删除 `frontend/src/__tests__/oauthLayoutAcceptance.generate.test.tsx` 和临时 HTML 目录。不提交临时资源，不连接生产 API。清理后重跑定向测试并确认 `git status` 只含计划允许文件。

## 任务 5：全量验证与两阶段独立审阅

**文件：**
- 当前不修改文档或提交。

- [ ] **步骤 1：运行全量验证**

```powershell
npm test
npm run build
git diff --check
git status --short --branch
git -c core.quotepath=false diff --name-only
git diff -- frontend/src/features/oauth/OAuthAppsSection.tsx frontend/src/styles.css frontend/src/__tests__/oauthHealth.test.tsx
```

预期：测试和构建成功；未提交实现差异仅限三个前端文件，计划文件另行存在；没有构建产物或秘密。

- [ ] **步骤 2：规格符合性独立审阅**

审阅规格、计划和未提交差异，确认按钮 DOM 归属、八列结构、状态矩阵、专用 CSS、1440/768 证据及安全边界全部满足。发现问题交回同一实现者修复并复审，直到 P0/P1=0。

- [ ] **步骤 3：代码质量独立审阅**

规格审阅通过后，另派审阅者检查测试有效性、CSS 作用域、响应式行为、可维护性、无关改动和错误处理。发现问题交回实现者修复并复审，直到 P0/P1=0。

## 任务 6：台账闭环与提交

**文件：**
- 修改：`docs/system-maintainer-onboarding-guide.md`
- 条件修改：`docs/问题记录.md`
- 新增：`docs/superpowers/plans/2026-08-13-oauth-authorization-button-layout.md`

- [ ] **步骤 1：更新第 22 节现有记录**

把状态写为“实现与独立审阅完成，待提交；未发布”，补充定向/全量测试、构建、1440/768 验收、两阶段审阅结论和回滚。Git 字段先写分支及“本次提交自身为准”，不得在提交前声称已有实现提交号。

- [ ] **步骤 2：按需更新问题记录**

仅当实施中出现实际错误时追加现象、原因、正确替代和验证结果；没有错误则不修改。

- [ ] **步骤 3：提交前最终范围与敏感信息检查**

```powershell
git diff --check
git -c core.quotepath=false status --short
git diff
```

精确允许：三个前端文件、计划、维护台账，以及仅在确有错误时的问题记录。扫描并拒绝私钥、密码、Token、OAuth code/state、client secret、refresh/access token 或完整代理凭据。

- [ ] **步骤 4：最终完整差异独立复核**

将任务 6 更新后的完整未提交 diff（包括三个前端文件、计划、维护台账和条件性问题记录）交给独立审阅者。审阅者须确认：实现与已通过规格一致；测试、构建和视口证据真实；台账准确记录审阅结论与未发布状态；没有敏感信息或无关差异。只有最终复核 P0/P1=0 后才能 stage/commit；发现问题须修复并再次复核。

- [ ] **步骤 5：一次性提交已审阅实现和文档**

```powershell
git add frontend/src/features/oauth/OAuthAppsSection.tsx frontend/src/styles.css frontend/src/__tests__/oauthHealth.test.tsx docs/superpowers/plans/2026-08-13-oauth-authorization-button-layout.md docs/system-maintainer-onboarding-guide.md
git add docs/问题记录.md  # 仅在步骤 2 实际修改时执行
git diff --cached --check
git commit -m "fix: surface OAuth authorization actions"
```

- [ ] **步骤 6：提交后核验**

```powershell
git status --short --branch
git log --oneline origin/master..HEAD
```

预期：工作区干净；历史包含规格提交与实现提交。台账 Git 字段所说“本次提交自身为准”由提交历史闭环。保持未发布，不 push、不合并 `master`、不连接生产，除非用户另行授权。
