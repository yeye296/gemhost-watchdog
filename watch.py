#!/usr/bin/env python3
"""GemHost 免费 MC 服看门狗（btppgem / id 5655947）。

背景：免费服是 6 小时会话制，到点平台自动 power stop；hy2 节点和哪吒 v1
都寄生在 Paper 的 JVM 里，MC 一停就全断。本脚本定时查状态，停了就拉起。

外部定时腿：cron-job.org -> workflow_dispatch（GA 原生 schedule 在本账号不 fire）。
通知：定时腿成功静默；失败或手动触发推一条 Telegram（含本仓 URL）。

环境变量（全部走 Actions secrets / dispatch inputs）：
  GH_EMAIL / GH_PW   面板登录邮箱与密码（必需）
  TG_BOT_TOKEN / TG_CHAT_ID  可选，告警推送
  INPUT_SOURCE        cron = 定时腿（成功静默），其他 = 手动（推结果）
  GH_SID             可选，默认 5655947
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import http.cookiejar
from datetime import datetime, timedelta, timezone

PANEL = "https://panel.gemhost.pl"
REPO_URL = "https://github.com/btpp03/gemhost-watchdog"
SID = int(os.environ.get("GH_SID", "5655947"))
EMAIL = os.environ.get("GH_EMAIL", "").strip()
PW = os.environ.get("GH_PW", "").strip()
SOURCE = (os.environ.get("INPUT_SOURCE", "manual") or "manual").strip()
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/145.0 Safari/537.36")
BJ = timezone(timedelta(hours=8))


def log(*a):
    print(datetime.now(BJ).strftime("%H:%M:%S"), *a, flush=True)


def tg(text):
    tok = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat = os.environ.get("TG_CHAT_ID", "").strip()
    if not tok or not chat:
        log("tg skipped (no creds)")
        return
    data = json.dumps({"chat_id": chat, "text": text,
                       "disable_web_page_preview": True}).encode()
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % tok,
                                 data=data, headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            log("tg ok", r.status)
    except Exception as e:
        log("tg failed:", e)


cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def csrf():
    return next((c.value for c in cj if c.name == "gemhost_csrf"), "")


def req(path, body=None):
    h = {"User-Agent": UA, "Accept": "application/json"}
    if body is not None:
        h.update({"Content-Type": "application/json", "X-CSRF-Token": csrf(),
                  "Origin": PANEL, "Referer": PANEL + "/console/" + str(SID)})
    r = urllib.request.Request(PANEL + path,
                               data=json.dumps(body).encode() if body is not None else None,
                               headers=h)
    try:
        with op.open(r, timeout=40) as x:
            return x.status, x.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return -1, repr(e)


def get_status():
    st, b = req("/api/servers/%s/status" % SID)
    if st != 200:
        return None
    try:
        return json.loads(b)
    except Exception:
        return None


def session_text(d):
    fs = (d or {}).get("free_session") or {}
    if not fs.get("active"):
        return "会话未激活"
    ms = fs.get("remaining_ms") or 0
    return "会话剩余 %d 分钟" % int(ms / 60000)


def main():
    if not EMAIL or not PW:
        log("FATAL: GH_EMAIL / GH_PW 未配置")
        sys.exit(2)

    req("/api/auth/registration-status")
    st, b = req("/api/auth/login", {"email": EMAIL, "password": PW, "rememberMe": False})
    if st != 200:
        log("login failed", st, b[:200])
        tg("❌ GemHost 看门狗登录失败 (HTTP %s) | 保活无法进行 | 来源:%s | %s"
           % (st, SOURCE, REPO_URL))
        sys.exit(1)

    d = get_status()
    if d is None:
        log("status read failed")
        tg("❌ GemHost 状态读取失败 | 保活无法判断 | 来源:%s | %s" % (SOURCE, REPO_URL))
        sys.exit(1)

    s = d.get("status")
    log("status", s, "|", session_text(d), "| source", SOURCE)

    if s == "running":
        if SOURCE != "cron":
            tg("✅ GemHost | 在线 running | 保活：无需动作 | %s | 来源:%s | %s"
               % (session_text(d), SOURCE, REPO_URL))
        else:
            log("online, silent (cron)")
        return 0

    log("not running -> power start")
    recovered = False
    for attempt in range(2):
        st, b = req("/api/servers/%s/power" % SID, {"action": "start"})
        log("start attempt", attempt, "->", st, b[:120])
        for i in range(12):
            time.sleep(10)
            d2 = get_status()
            if not d2:
                continue
            s2 = d2.get("status")
            mem = (d2.get("resources") or {}).get("memory_bytes") or 0
            log("poll", i, s2, "mem", mem)
            if s2 == "running":
                recovered = True
                break
            if s2 == "starting" and mem == 0 and i >= 3:
                log("wedged (starting/mem=0) -> kill + start")
                req("/api/servers/%s/power" % SID, {"action": "kill"})
                time.sleep(10)
                req("/api/servers/%s/power" % SID, {"action": "start"})
        if recovered:
            break

    if recovered:
        d3 = get_status() or {}
        log("recovered |", session_text(d3))
        if SOURCE != "cron":
            tg("✅ GemHost | 已自动拉起 running | 保活：已发 start 并复验 | %s | 来源:%s | %s"
               % (session_text(d3), SOURCE, REPO_URL))
        return 0

    tg("❌ GemHost 保活失败 | 两轮 start 后仍非 running | 来源:%s | %s" % (SOURCE, REPO_URL))
    sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())
