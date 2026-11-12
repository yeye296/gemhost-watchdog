# gemhost-watchdog

GemHost.pl 免费 Minecraft 服（`btppgem`，server id `5655947`）的保活。

## 为什么需要
免费服是 **6 小时会话制**，到点平台自动关机；hy2 代理节点和哪吒 v1 探针都跑在
Paper 的 JVM 里（老王 java 插件），MC 一停，节点和探针一起掉。

## 链路（大白话）
```
cron-job.org 每 15 分钟
   → POST GitHub Actions workflow_dispatch（外部腿，唯一定时器）
      → watch.py 用面板账号登录 → 查 /api/servers/5655947/status
         → running：什么都不做（静默）
         → offline：POST /power {"action":"start"} → 轮询到 running
            → 僵在 starting 且内存 0：kill 再 start
            → 两轮拉不起：推 Telegram + run 变红
```

## 凭据（Actions secrets）
| Secret | 内容 |
|---|---|
| `GH_EMAIL` | 面板登录邮箱 |
| `GH_PW` | 面板登录密码 |
| `TG_BOT_TOKEN` / `TG_CHAT_ID` | 告警用 Telegram bot |

## 通知规则
- 定时腿成功 = **静默**（不刷屏）；
- 失败、登录失效、手动触发 = 推一条 Telegram（含本仓 URL）；
- `source=cron` 由 cron-job.org 的 dispatch body 传入。

## 触发
- 自动：cron-job.org job `gemhost-watchdog-dispatch`（UTC 每 15 分钟）。
- 手动：Actions → Run workflow（不填 source 会推一条结果通知）。

## 注意
- 平台「延长会话」接口要 hCaptcha 真人点，本看门狗走的是**重开**（power start），
  不是官方续期；到期后能否无验证码重开，由第一次真实到期时自动验证。
- 免费会话到期会自动 stop，所以最长断线 ≈ 一个巡检间隔（15 分钟）。
