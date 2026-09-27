"""Streamlit Community Cloud のスリープ防止.

ヘッドレスブラウザでアプリを開き、スリープ画面なら「起動」ボタンを押す。
使い方: python etl/keep_alive.py https://jal-lsp.streamlit.app/
"""
import re
import sys
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://jal-lsp.streamlit.app/"
WAKE = re.compile(r"get this app back up|wake", re.I)


def find_wake_button(page):
    for fr in page.frames:
        btn = fr.get_by_role("button", name=WAKE)
        if btn.count():
            return btn.first
    return None


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(8_000)
    btn = find_wake_button(page)
    if btn:
        print("sleeping -> waking up")
        btn.click()
        page.wait_for_timeout(90_000)   # 起動完了まで待つ
    else:
        print("awake")
        page.wait_for_timeout(15_000)   # 接続を維持してアクセスとして記録させる
    print("title:", page.title())
    browser.close()
