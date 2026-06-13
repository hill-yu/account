# OAuth 回调 JSON 导入工作流

日期：2026-06-12

这份文档定义新的节点授权流程。目标是让每个账号使用自己的站点域名作为 `redirect_uri`，授权完成后由站点侧脚本把回调参数下载成 JSON 文件，再由中台手动导入，最后在中台服务端完成 `code -> refresh_token` 兑换。

## 1. 方案概览

标准链路：

`Google OAuth -> 账号站点 callback 脚本 -> 下载 callback JSON -> 中台导入 JSON -> 中台服务端换 refresh_token -> collector 使用 refresh_token 拉数`

这套方案的关键点：

1. 每个账号都可以绑定自己的 `redirect_uri`
2. 网站侧不保存 `client_secret`
3. 真正的 token 兑换仍然在中台后端完成
4. 用户只需要下载 JSON 并上传到中台

## 2. 网站侧需要部署的文件

当前标准文件：

- [oauth-callback-download.php](/D:/code/adx-account-isolated-collector/deploy/vps/php/oauth-callback-download.php)

推荐站点路径示例：

- `https://loshiny.com/oauth/google/callback`
- `https://jwtnx.com/oauth/google/callback`

如果站点使用宝塔 + Nginx，可以把这个 PHP 文件映射到对应站点的 callback 路径。

## 3. callback 脚本行为

当 Google 授权完成后，浏览器会跳到站点 callback 地址，例如：

`https://example.com/oauth/google/callback?state=...&code=...&scope=...`

脚本会自动做这些事：

1. 读取 `state`、`code`、`scope`、`iss`
2. 生成 `redirect_uri`
3. 生成完整 `callback_url`
4. 生成下载时间 `downloaded_at`
5. 直接下载一个 JSON 文件

JSON 示例：

```json
{
  "state": "xxx",
  "code": "4/0Ad...",
  "redirect_uri": "https://example.com/oauth/google/callback",
  "callback_url": "https://example.com/oauth/google/callback?state=xxx&code=4/0Ad...",
  "scope": "https://www.googleapis.com/auth/admanager",
  "iss": "https://accounts.google.com",
  "error": null,
  "downloaded_at": "2026-06-12T10:00:00+00:00"
}
```

## 4. 中台侧要求

中台 OAuth App 配置中，`redirect_uri` 必须和网站 callback 地址完全一致。

例如：

- 账号站点：`jwtnx.com`
- OAuth App `redirect_uri`：`https://jwtnx.com/oauth/google/callback`

中台已经支持导入 JSON：

- `POST /api/v1/operator/oauth-apps/import-callback-json`

导入后，中台会：

1. 按 `state` 找到待授权的 OAuth app
2. 校验 JSON 中的 `redirect_uri` 或 `callback_url`
3. 用中台保存的 `client_id`、`client_secret`、`redirect_uri`、`code` 去 Google 兑换 token
4. 将 `refresh_token` 保存到 `oauth_app_configs`

## 5. 实际操作步骤

### 步骤 1：在中台创建 OAuth app

填写：

- `account_id`
- `client_id`
- `client_secret`
- `redirect_uri`
- `scopes`

其中 `redirect_uri` 必须写成该账号自己的站点 callback 地址。

### 步骤 2：生成授权链接

在中台点击 `Generate Authorization URL`。

中台会记录：

- `authorization_state`
- `authorization_requested_at`
- `authorization_state_expires_at`

### 步骤 3：打开 Google 授权页

使用中台生成的链接完成 Google 授权。

Google 会跳回该账号站点的 callback 页面。

### 步骤 4：下载 callback JSON

站点侧脚本会自动下载一个 JSON 文件。

这个 JSON 文件就是后续导入中台所需的材料。

### 步骤 5：在中台上传 JSON

在 user system 的 `OAuth Setup` 页面里选择对应账号，上传 JSON 文件。

上传成功后，应看到：

- `authorization_status = authorized`
- `refresh_token_present = true`

## 6. 验收标准

满足下面 4 条才算成功：

1. 站点 callback 能正常下载 JSON
2. 中台导入 JSON 返回 200
3. OAuth app 状态变成 `authorized`
4. collector runtime config 中能读到 `google_oauth_refresh_token`

## 7. 常见错误

### `OAuth authorization state is invalid or expired`

说明：

- 授权超过有效期
- 上传了旧 JSON
- state 对不上当前待授权记录

处理：

1. 重新生成授权链接
2. 重新授权
3. 重新下载新 JSON

### `redirect_uri mismatch`

说明：

- JSON 里的 callback 地址和中台 OAuth app 配置不一致

处理：

1. 核对站点 callback 路径
2. 核对 OAuth app 里的 `redirect_uri`
3. 两边必须完全一致

### Google 授权后没有下载 JSON

说明：

- callback 脚本未部署
- Nginx/PHP 路由未指向正确文件

处理：

1. 检查站点 PHP 文件是否存在
2. 检查站点 callback 路径是否能命中该文件
3. 检查宝塔站点 PHP 配置

## 8. 与旧流程的区别

旧流程是人工从 callback URL 里抠 `code`，再手工换 token。

新流程改成：

1. 回调页自动把参数打包成 JSON
2. 用户手动上传 JSON
3. 中台自动完成 token 兑换

这样以后新增节点时，OAuth 这段流程会更稳定，也更容易复用。
