"""
capture_overview_to_teams.py
=============================
Chụp tab "Overview" của dashboard, nén ảnh, gửi base64 lên webhook Power
Automate. Flow bên Teams sẽ tự lo phần: lưu ảnh vào SharePoint (OneDrive for
Business "Create file"), tạo link chia sẻ, rồi dựng Adaptive Card dùng link
đó -> né được giới hạn 28KB của Teams, ảnh vẫn tự hiện trong khung chat.

Chạy 1 lần thử:  python capture_overview_to_teams.py
Chạy tự động 20:00 hàng ngày: dùng Task Scheduler (xem setup_scheduler.ps1)

Yêu cầu cài đặt (1 lần):
  pip install playwright pillow requests
  playwright install chromium
"""

import base64
import io
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image
from playwright.sync_api import sync_playwright

# ══════════════════════════════════════════════
# CẤU HÌNH — chỉnh ở đây khi cần
# ══════════════════════════════════════════════
DASHBOARD_URL = "https://polarium-energy.github.io/Manufacturing-Execution-System/"
TAB_NAME      = "overview"                       # khớp data-tab="overview" trong dashboard.html
TAB_BUTTON_SELECTOR = f'.tab-btn[data-tab="{TAB_NAME}"]'
PANEL_SELECTOR       = f'.tabpanel[data-tab="{TAB_NAME}"]'

# Trigger "Who can trigger the flow?" = Anyone -> URL tự chứa chữ ký (sig=...)
# Lấy từ biến môi trường WEBHOOK_URL (GitHub Actions secret) để không lộ chữ ký khi public code.
# Chạy local: set biến môi trường trước, hoặc tạm gán thẳng chuỗi vào đây để test 1 lần.
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
if not WEBHOOK_URL:
    print("❌ Thiếu WEBHOOK_URL. Set biến môi trường WEBHOOK_URL trước khi chạy.")
    sys.exit(1)

MAX_WIDTH    = 1600     # px, đủ nét để đọc số liệu nhưng ảnh nhẹ
JPEG_QUALITY = 80        # flow tự lo lưu trữ nên không còn giới hạn 28KB -> nén nhẹ tay hơn
VIEWPORT     = {"width": 1920, "height": 1080}

LOG_FILE = Path(__file__).parent / "capture_teams.log"


def log(msg: str):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def capture_overview_png() -> bytes:
    """Mở dashboard bằng headless Chromium, chuyển sang tab Overview, chụp panel đó."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport=VIEWPORT)
        page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=30000)
        page.click(TAB_BUTTON_SELECTOR)
        page.wait_for_timeout(2000)  # chờ chart/số liệu render xong
        panel = page.locator(PANEL_SELECTOR)
        panel.wait_for(state="visible", timeout=10000)
        png_bytes = panel.screenshot()
        browser.close()
        return png_bytes


def compress_to_jpeg_base64(png_bytes: bytes) -> str:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    if img.width > MAX_WIDTH:
        ratio = MAX_WIDTH / img.width
        img = img.resize((MAX_WIDTH, int(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    log(f"Ảnh sau nén: {img.width}x{img.height}, {buf.tell()//1024} KB")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def send_to_teams(image_b64: str):
    """Gửi base64 + thời gian chụp lên webhook. Flow tự lưu SharePoint + tạo card."""
    payload = {
        "capturedAt": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "imageBase64": image_b64,
    }
    resp = requests.post(WEBHOOK_URL, json=payload, timeout=60)
    if resp.status_code in (200, 202):
        log(f"✅ Đã gửi thành công (status {resp.status_code})")
    else:
        log(f"❌ Gửi thất bại: {resp.status_code} — {resp.text[:300]}")
        sys.exit(1)


def main():
    log("=== Bắt đầu chụp Overview ===")
    try:
        png = capture_overview_png()
        b64 = compress_to_jpeg_base64(png)
        send_to_teams(b64)
    except Exception as e:
        log(f"❌ LỖI: {e}")
        sys.exit(1)
    log("=== Hoàn tất ===\n")


if __name__ == "__main__":
    main()
