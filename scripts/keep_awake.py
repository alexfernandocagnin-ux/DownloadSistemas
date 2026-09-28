"""Abre o portal de downloads num navegador sem tela e acorda o app se o Streamlit Cloud o colocou para dormir."""

import os
import sys

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

URL = os.environ.get("DOWNLOAD_APP_URL", "https://downloadsistemas.streamlit.app/")
WAKE_BUTTON = "Yes, get this app back up!"
READY_TEXT = "DownloadSistemas"


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(15_000)
        button = page.get_by_role("button", name=WAKE_BUTTON)
        if button.count():
            print("App dormindo: acordando.")
            button.first.click()
            page.wait_for_timeout(90_000)
        else:
            print("App acordado.")
        try:
            page.frame_locator("iframe").get_by_text(READY_TEXT).first.wait_for(timeout=120_000)
            print("Portal carregado.")
        except PlaywrightTimeout:
            print("Aviso: o portal não respondeu a tempo; confira manualmente.")
            browser.close()
            return 1
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
