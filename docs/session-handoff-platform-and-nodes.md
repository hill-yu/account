# 中台与节点会话交接文档

这份文档用于给另一个独立会话窗口接管“中台 + 节点”相关工作。

## 1. 这个会话负责什么

只处理下面范围：

- 中台主 backend / control plane
- collector / VPS 抓数链路
- 新节点接入
- `fetch.php` / `report.php`
- 多节点部署
- OAuth / refresh token / 代理 / 节点 MySQL

不处理下面范围：

- `user_system` 页面布局、登录页、报表 UI、小交互

## 2. 启动前必须先读的文件

按这个顺序读：

1. [docs/new-node-onboarding-sop-template.md](D:/code/adx-account-isolated-collector/docs/new-node-onboarding-sop-template.md)
2. [docs/2026-06-08-single-account-node-template.md](D:/code/adx-account-isolated-collector/docs/2026-06-08-single-account-node-template.md)
3. [docs/2026-06-08-mid-platform-api-examples.md](D:/code/adx-account-isolated-collector/docs/2026-06-08-mid-platform-api-examples.md)
4. [docs/operator-notes.md](D:/code/adx-account-isolated-collector/docs/operator-notes.md)
5. [docs/2026-06-11-prod-data-sync-to-local.md](D:/code/adx-account-isolated-collector/docs/2026-06-11-prod-data-sync-to-local.md)

## 3. 当前已知部署形态

- 中台 VPS：`97.64.83.11`
- `user_system` / 对外站点 VPS：`97.64.83.22`
- 当前已接入多节点模式
- 新节点推荐沿用“中台单 VPS 多节点”方案：
  - 中台新增独立 collector 实例
  - 独立端口
  - 独立 MySQL 库
  - 独立 env
  - 独立 systemd
  - 独立 cron

## 4. 当前已知业务状态

- 第三个节点 `loshiny` 已按多节点方案接入过
- 节点侧可以只负责触发，不必整套采集后端都落在节点机
- 新节点通常沿用：
  - 节点域名 `/ke/fetch.php`
  - 节点域名 `/ke/report.php`
  - 反代到中台对应 collector 端口

## 5. 新节点接入最少需要准备的信息

- 节点名称
- `account_key`
- `report_token`
- 域名
- 节点 VPS IP
- Google OAuth 信息
- `refresh_token`
- 代理信息
- network code
- 是否只做代理触发

## 6. 进入工作时建议使用的提示词

把下面这段直接发给新会话：

```text
你只负责中台与节点。
先阅读：
1. docs/session-handoff-platform-and-nodes.md
2. docs/new-node-onboarding-sop-template.md
3. docs/2026-06-08-single-account-node-template.md
4. docs/2026-06-08-mid-platform-api-examples.md
5. docs/operator-notes.md

然后基于当前仓库继续处理中台、collector、fetch/report.php、多节点接入、OAuth、代理、节点部署问题。
不要主动接管 user_system 页面 UI，除非我明确要求。
```

## 7. 会话结束前要回写什么

离开前把这些补到本文件：

- 当前接入到第几个节点
- 每个节点大概状态
- 哪些部署已完成
- 哪些 token / OAuth / 代理还缺
- 下一步操作顺序
