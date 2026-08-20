from playwright.sync_api import sync_playwright
import time, os

BASE = "http://127.0.0.1:8000"

def find_chrome_executable():
    # Common locations for Chrome on Windows
    candidates = [
        os.environ.get("CHROME_PATH"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for p in candidates:
        if not p:
            continue
        if os.path.exists(p):
            return p
    return None

with sync_playwright() as pw:
    chrome_path = find_chrome_executable()
    if chrome_path:
        print("Using system Chrome at:", chrome_path)
        browser = pw.chromium.launch(headless=True, executable_path=chrome_path)
    else:
        print("No system Chrome found. Attempting to use Playwright-managed browser.")
        # This will fail if browsers are not installed; let the exception surface with guidance
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception as e:
            print("Playwright browser launch failed:", e)
            print("If you are behind a corporate proxy or your network intercepts TLS, install browsers manually or set up proxy/CA trust.\n")
            print("Options:\n 1) Run 'python -m playwright install' on a machine with internet access and copy the browsers folder.\n 2) Set environment variables HTTPS_PROXY/HTTP_PROXY or NODE_EXTRA_CA_CERTS to allow download.\n 3) Install Chrome and set CHROME_PATH env var to its executable path.")
            raise
    page = browser.new_page()
    page.goto(BASE)

    # login
    page.fill('#username', 'admin')
    page.fill('#password', 'adminpass')
    page.click('#login')

    # wait for app area
    page.wait_for_selector('#app', timeout=5000)

    # ensure company field present
    page.wait_for_selector('#company')

    # set inputs
    page.fill('#company', '이지메디컴')
    page.fill('#operating_income', '1000000')
    page.fill('#corporate_tax', '0')
    page.fill('#total_sales', '1000000')
    page.fill('#related_sales', '{"대웅제약":900000}')

    # click evaluate
    page.click('#evaluate')

    # wait for result to update
    page.wait_for_selector('#result', timeout=5000)
    content = page.inner_text('#result')
    print('E2E result:', content[:200])

    if 'gift_tax_total' in content:
        print('E2E: PASS')
        browser.close()
        raise SystemExit(0)
    else:
        print('E2E: FAIL')
        browser.close()
        raise SystemExit(2)
