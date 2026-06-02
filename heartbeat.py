#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日心跳：發一則 LINE 訊息報平安，確認新聞監控系統仍正常運作。
由 GitHub Actions 每天定時觸發（見 .github/workflows/heartbeat.yml）。
設定來源：環境變數（GitHub Secrets）優先，找不到才 fallback 讀 config.json。
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"

# 台灣時區 UTC+8（GitHub runner 為 UTC，需自行換算顯示）
TW_TZ = timezone(timedelta(hours=8))


def load_line_config() -> dict:
    cfg = {
        "line_channel_access_token": os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""),
        "line_user_id":              os.environ.get("LINE_USER_ID", ""),
    }
    if (not cfg["line_channel_access_token"] or not cfg["line_user_id"]) and CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            file_cfg = json.load(f)
        for key in cfg:
            if not cfg[key]:
                cfg[key] = file_cfg.get(key, "")

    for key, val in cfg.items():
        if not val or val.startswith("YOUR_"):
            print(f"[ERROR] 缺少必填設定：{key}")
            sys.exit(1)
    return cfg


def main():
    cfg = load_line_config()
    now_tw = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M")

    text = (
        "✅【新聞監控心跳】\n"
        "系統運作正常，雲端排程持續監控中。\n"
        f"時間：{now_tw}（台灣時間）"
    )

    payload = {"to": cfg["line_user_id"], "messages": [{"type": "text", "text": text}]}
    headers = {
        "Authorization": f"Bearer {cfg['line_channel_access_token']}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers=headers, json=payload, timeout=15,
    )
    if resp.status_code == 200:
        print(f"[OK] 心跳已送出：{now_tw}")
    else:
        print(f"[ERROR] 心跳推播失敗：{resp.status_code} | {resp.text}")
        sys.exit(1)


if __name__ == "__main__":
    main()
