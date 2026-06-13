# Second Account Manual OAuth Callback Implementation Plan

> **面向 AI 代理的工作者：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。
**目标：** 在不修改后端数据模型的前提下，让第二个账号接入流程明确支持手动填写该账号自己的网站 OAuth 回调地址，并降低误填风险。

**架构：** 通过前端辅助文案和列表展示补足当前多账号运营可见性，保持后端 `redirect_uri` 手动输入模式不变，再用 README 把第二账号接入步骤写清楚。

**技术栈：** React 19、TypeScript、Vite、Vitest、Markdown

---

### 任务 1：为第二账号接入提示提取可测试文案

**文件：**
- 创建：`frontend/src/lib/operatorGuidance.ts`
- 创建：`frontend/src/__tests__/operatorGuidance.test.ts`

- [ ] **步骤 1：编写失败的测试**

```ts
import { describe, expect, it } from "vitest";

import {
  buildInstanceOnboardingNote,
  buildOAuthRedirectUriHint,
  buildSecondAccountChecklist,
} from "../lib/operatorGuidance";

describe("buildOAuthRedirectUriHint", () => {
  it("mentions that each account should use its own website callback", () => {
    const text = buildOAuthRedirectUriHint();

    expect(text).toContain("current account");
    expect(text).toContain("own website");
    expect(text).toContain("Do not reuse");
  });
});

describe("buildInstanceOnboardingNote", () => {
  it("explains that the second node belongs under a second account", () => {
    expect(buildInstanceOnboardingNote()).toContain("Create a second account first");
  });
});

describe("buildSecondAccountChecklist", () => {
  it("returns the five-step second-account onboarding checklist", () => {
    expect(buildSecondAccountChecklist()).toEqual([
      "Create the second account.",
      "Create the second account's instance.",
      "Create the second account's OAuth app.",
      "Set redirect_uri to the second account website callback.",
      "Generate the authorization URL and complete authorization.",
    ]);
  });
});
```

- [ ] **步骤 2：运行测试验证失败**

运行：`npm test -- src/__tests__/operatorGuidance.test.ts`
预期：FAIL，提示找不到 `../lib/operatorGuidance`

- [ ] **步骤 3：编写最小实现代码**

```ts
export function buildOAuthRedirectUriHint(): string {
  return "Set the redirect URI to the current account's own website callback. Different accounts can use different website addresses. Do not reuse another account's callback URL.";
}

export function buildInstanceOnboardingNote(): string {
  return "Create a second account first, then create that account's own instance instead of attaching a second node under the first account.";
}

export function buildSecondAccountChecklist(): string[] {
  return [
    "Create the second account.",
    "Create the second account's instance.",
    "Create the second account's OAuth app.",
    "Set redirect_uri to the second account website callback.",
    "Generate the authorization URL and complete authorization.",
  ];
}
```

- [ ] **步骤 4：运行测试验证通过**

运行：`npm test -- src/__tests__/operatorGuidance.test.ts`
预期：PASS

### 任务 2：把提示与展示接入 Operations 页面和 OAuth 列表

**文件：**
- 修改：`frontend/src/features/oauth/OAuthAppsSection.tsx`
- 修改：`frontend/src/features/instances/InstancesSection.tsx`

- [ ] **步骤 1：编写失败的测试**

```ts
import { describe, expect, it } from "vitest";

import {
  buildInstanceOnboardingNote,
  buildOAuthRedirectUriHint,
  buildSecondAccountChecklist,
} from "../lib/operatorGuidance";

describe("operator guidance copy", () => {
  it("provides redirect guidance and second-account steps for the UI", () => {
    expect(buildOAuthRedirectUriHint()).toContain("Do not reuse");
    expect(buildInstanceOnboardingNote()).toContain("second account");
    expect(buildSecondAccountChecklist()).toHaveLength(5);
  });
});
```

- [ ] **步骤 2：运行测试验证失败**

运行：`npm test -- src/__tests__/operatorGuidance.test.ts`
预期：如果 UI 依赖的 copy 尚未实现或与测试不一致，则 FAIL

- [ ] **步骤 3：编写最小实现代码**

```tsx
import {
  buildInstanceOnboardingNote,
  buildOAuthRedirectUriHint,
  buildSecondAccountChecklist,
} from "../../lib/operatorGuidance";

// Instances section
<SectionCard
  title="Instances"
  description="..."
>
  <p>{buildInstanceOnboardingNote()}</p>
</SectionCard>

// OAuth section redirect field
<Field
  label="Redirect URI"
  hint={buildOAuthRedirectUriHint()}
  ...
/>

// OAuth section checklist + redirect_uri table column
<ul>
  {buildSecondAccountChecklist().map((item) => (
    <li key={item}>{item}</li>
  ))}
</ul>
```

- [ ] **步骤 4：运行测试验证通过**

运行：`npm test -- src/__tests__/operatorGuidance.test.ts`
预期：PASS

### 任务 3：更新 README 的第二账号操作说明

**文件：**
- 修改：`README.md`

- [ ] **步骤 1：编写失败的测试**

本仓库当前没有 README 自动化测试。
改为先定义必须出现的文案检查目标：

```text
Second account onboarding
Create the second account
Set redirect_uri to the second account website callback
```

- [ ] **步骤 2：运行文本检查验证失败**

运行：`rg -n "Second account onboarding|Set redirect_uri to the second account website callback" README.md`
预期：FAIL，无匹配

- [ ] **步骤 3：编写最小实现代码**

```md
## Second Account Onboarding

1. Create the second account.
2. Create the second account's instance.
3. Create the second account's OAuth app.
4. Set `redirect_uri` to the second account website callback.
5. Generate the authorization URL and complete authorization.
```

- [ ] **步骤 4：运行文本检查验证通过**

运行：`rg -n "Second Account Onboarding|Set \`redirect_uri\` to the second account website callback" README.md`
预期：PASS

### 任务 4：运行回归验证

**文件：**
- 验证：`frontend/src/__tests__/operatorGuidance.test.ts`
- 验证：`frontend/src/__tests__/oauth.test.ts`
- 验证：`frontend/`

- [ ] **步骤 1：运行新增测试**

运行：`npm test -- src/__tests__/operatorGuidance.test.ts`
预期：PASS

- [ ] **步骤 2：运行相关现有测试**

运行：`npm test -- src/__tests__/oauth.test.ts`
预期：PASS

- [ ] **步骤 3：运行完整前端测试**

运行：`npm test`
预期：PASS

- [ ] **步骤 4：运行前端构建**

运行：`npm run build`
预期：PASS，Vite 构建成功
