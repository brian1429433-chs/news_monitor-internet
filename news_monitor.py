#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高雄警察 / 高雄治安 即時新聞監控（雲端版 / GitHub Actions）
監控自由時報、東森新聞，比對關鍵字後透過 LINE Messaging API 傳送通知。

與本機版差異：
  - 設定優先讀「環境變數」，找不到才 fallback 讀 config.json（方便本機測試）。
  - 適合在 GitHub Actions 排程執行，機密放 repo Secrets。
"""

import base64
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import urllib3
import requests
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# ── 路徑 ──
BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
SENT_IDS_FILE = BASE_DIR / "sent_news_ids.json"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
LOG_FILE = BASE_DIR / "monitor.log"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

# 高雄 + 中間最多 3 個任意字 + 目標詞
KEYWORD_PATTERN = re.compile(r"高雄")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9",
}


# ── 工具函式 ──

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_config() -> dict:
    """
    設定來源優先序：
      1. 環境變數（雲端 / GitHub Actions Secrets）
      2. config.json（本機測試用 fallback）
    """
    # 先讀環境變數
    cfg = {
        "line_channel_access_token": os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""),
        "line_user_id":              os.environ.get("LINE_USER_ID", ""),
        "imgbb_api_key":             os.environ.get("IMGBB_API_KEY", ""),
    }

    # 環境變數缺漏時，fallback 讀 config.json
    if not cfg["line_channel_access_token"] or not cfg["line_user_id"]:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, encoding="utf-8") as f:
                file_cfg = json.load(f)
            for key in cfg:
                if not cfg[key]:
                    cfg[key] = file_cfg.get(key, "")

    # 必填欄位檢查
    required = ["line_channel_access_token", "line_user_id"]
    for key in required:
        val = cfg.get(key, "")
        if not val or val.startswith("YOUR_"):
            print(f"[ERROR] 缺少必填設定：{key}")
            print("請設定環境變數 LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID，"
                  "或在 config.json 填入。")
            sys.exit(1)
    return cfg


def load_sent_ids() -> set:
    if SENT_IDS_FILE.exists():
        with open(SENT_IDS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return set(data[-1000:])
    return set()


def save_sent_ids(sent_ids: set):
    with open(SENT_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(sent_ids)[-1000:], f, ensure_ascii=False)


def news_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


# ── 新聞爬取 ──

def scrape_ltn() -> list:
    """自由時報即時新聞（HTML 版）"""
    articles = []
    try:
        resp = requests.get(
            "https://news.ltn.com.tw/list/breakingnews",
            headers=HEADERS, timeout=15
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.select(".cont_news_list ul li a, ul.list li a"):
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not href.startswith("http"):
                href = "https://news.ltn.com.tw" + href
            if title and href and "/news/" in href:
                articles.append({"title": title, "url": href, "source": "自由時報"})
    except Exception as e:
        log(f"[ERROR] 自由時報抓取失敗：{e}")
    return articles


def scrape_ettoday() -> list:
    """東森新聞即時新聞（SSL verify=False 繞過伺服器憑證缺漏 SKI 欄位問題）"""
    articles = []
    try:
        resp = requests.get(
            "https://www.ettoday.net/news/breakingnews/",
            headers=HEADERS, timeout=15, verify=False
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        seen = set()
        for a in soup.select(".block_content .title a, .text_ticker_1_v4 a[href]"):
            href = a.get("href", "")
            title = a.get_text(strip=True)
            if not href.startswith("http"):
                href = "https://www.ettoday.net" + href
            if title and href not in seen and re.search(r"/news/\d+", href):
                seen.add(href)
                articles.append({"title": title, "url": href, "source": "東森新聞"})
    except Exception as e:
        log(f"[ERROR] 東森新聞抓取失敗：{e}")
    return articles


# ── 關鍵字過濾 ──

def filter_by_keywords(articles: list) -> list:
    matched = []
    for art in articles:
        m = KEYWORD_PATTERN.search(art.get("title", ""))
        if m:
            art["matched_keyword"] = m.group(0)
            matched.append(art)
    return matched


# ── 截圖 ──

def take_screenshot(url: str, output_path: Path) -> bool:
    if not PLAYWRIGHT_AVAILABLE:
        log("[WARN] Playwright 未安裝，略過截圖")
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 800},
                locale="zh-TW",
            )
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(output_path), full_page=False)
            browser.close()
        return True
    except Exception as e:
        log(f"[WARN] 截圖失敗 {url}：{e}")
        return False


# ── 圖片上傳 ──

def upload_imgbb(image_path: Path, api_key: str) -> str | None:
    """上傳截圖到 imgbb（免費），回傳公開 URL"""
    if not api_key or api_key.startswith("YOUR_"):
        return None
    try:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode()
        resp = requests.post(
            "https://api.imgbb.com/1/upload",
            data={"key": api_key, "image": image_b64, "expiration": 604800},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["data"]["url"]
    except Exception as e:
        log(f"[WARN] imgbb 上傳失敗：{e}")
        return None


# ── LINE 推播 ──

def send_line_message(config: dict, article: dict, image_url: str | None) -> bool:
    token = config["line_channel_access_token"]
    target_id = config["line_user_id"]

    text = (
        f"【即時新聞警報】\n"
        f"來源：{article['source']}\n"
        f"關鍵字：#{article['matched_keyword']}\n\n"
        f"📰 {article['title']}\n\n"
        f"🔗 {article['url']}"
    )
    messages = [{"type": "text", "text": text}]

    if image_url:
        messages.append({
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": image_url,
        })

    payload = {"to": target_id, "messages": messages}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers=headers,
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        body = getattr(resp, "text", "")
        log(f"[ERROR] LINE 推播失敗：{e} | {body}")
        return False


# ── 主程式 ──

def main():
    log("=== 開始新聞監控 ===")
    config = load_config()
    sent_ids = load_sent_ids()

    # 抓取新聞
    all_articles = scrape_ltn() + scrape_ettoday()
    log(f"共抓取 {len(all_articles)} 則新聞（自由時報 + 東森）")

    # 關鍵字比對
    matched = filter_by_keywords(all_articles)
    log(f"比對到 {len(matched)} 則符合關鍵字")

    new_count = 0
    for art in matched:
        nid = news_id(art["url"])
        if nid in sent_ids:
            log(f"  (已推播過，跳過) {art['title'][:40]}")
            continue

        log(f"→ {art['source']} | {art['matched_keyword']} | {art['title'][:50]}")

        # 截圖
        image_url = None
        shot_path = SCREENSHOTS_DIR / f"{nid}.png"
        if take_screenshot(art["url"], shot_path):
            imgbb_key = config.get("imgbb_api_key", "")
            image_url = upload_imgbb(shot_path, imgbb_key)
            if shot_path.exists():
                shot_path.unlink()

        # 推播
        if send_line_message(config, art, image_url):
            sent_ids.add(nid)
            new_count += 1
            log(f"  ✓ 已推播")
        else:
            log(f"  ✗ 推播失敗")

    save_sent_ids(sent_ids)
    log(f"=== 完成，本次推播 {new_count} 則 ===\n")


if __name__ == "__main__":
    main()
