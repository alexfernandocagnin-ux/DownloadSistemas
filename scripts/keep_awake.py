"""Visita o portal e solicita seu despertar quando a tela de suspensão aparece."""
import os
import sys
import time
from urllib.parse import urlsplit

DEFAULT_URL = "https://downloadsistemas.streamlit.app/"
WAKE_BUTTON = "Yes, get this app back up!"
READY_HEADING = "Downloads sem rodeios."
LOAD_TIMEOUT_SECONDS = 240


def inspect_frames(page):
    """Procura os controles na página principal e nos iframes do Community Cloud."""
    wake_button = None
    for frame in page.frames:
        try:
            error = frame.locator('[data-testid="stException"]').first
            if error.is_visible():
                raise RuntimeError("O portal exibiu uma exceção do Streamlit.")
            if frame.get_by_role("heading", name=READY_HEADING, exact=True).is_visible():
                return True, None
            button = frame.get_by_role("button", name=WAKE_BUTTON, exact=True).first
            if button.is_visible():
                wake_button = button
        except RuntimeError:
            raise
        except Exception:
            if not frame.is_detached():
                raise
    return False, wake_button


def wake_portal(page, url, timeout=LOAD_TIMEOUT_SECONDS):
    print(f"Abrindo {url}", flush=True)
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    deadline = time.monotonic() + timeout
    clicked = False
    while time.monotonic() < deadline:
        ready, button = inspect_frames(page)
        if ready:
            print("SUCESSO: portal carregado" + (" após despertar." if clicked else "; já estava disponível."), flush=True)
            return
        if button is not None and not clicked:
            print("Página de suspensão detectada; solicitando despertar.", flush=True)
            button.click(timeout=30_000)
            clicked = True
        page.wait_for_timeout(1_000)
    raise TimeoutError(f"Portal não carregou em {timeout}s após a navegação. URL final: {page.url}")


def main():
    url = os.environ.get("DOWNLOAD_APP_URL", "").strip() or DEFAULT_URL
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        print("::error::DOWNLOAD_APP_URL deve ser uma URL HTTP(S) válida.", flush=True)
        return 1
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_default_timeout(5_000)
                wake_portal(page, url)
            finally:
                browser.close()
    except Exception as exc:
        print(f"::error::Falha ao visitar/acordar o portal: {type(exc).__name__}: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
