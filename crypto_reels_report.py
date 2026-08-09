"""
گزارش روزانه ریل‌های برتر کریپتو/ترید فارسی در اینستاگرام
اجزا: Apify (داده اینستاگرام) + Google Gemini (تحلیل رایگان) + صفحه وب (GitHub Pages) + Telegram (اعلان)

نحوه اجرا:
    python crypto_reels_report.py

متغیرهای محیطی لازم (به‌صورت GitHub Secrets یا در .env محلی):
    APIFY_TOKEN
    GEMINI_API_KEY
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
    REPORT_URL   (اختیاری - آدرس صفحه گیت‌هاب پیجز، برای لینک در پیام تلگرام)
"""

import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# تنظیمات قابل ویرایش
# ---------------------------------------------------------------------------

SEED_ACCOUNTS = [
    "fasttraderofficial",   # محمدهادی بنابی
    "kahangi_arash1",       # آرش کهنگی
    # "your_verified_account",
]

HASHTAGS = ["ترید", "کریپتو", "ارزدیجیتال", "تحلیل_تکنیکال", "بیتکوین"]

MAX_RESULTS_IN_REPORT = 12
LOOKBACK_HOURS = 96

# ---------------------------------------------------------------------------
# متغیرهای محیطی
# ---------------------------------------------------------------------------

APIFY_TOKEN = os.environ["APIFY_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
REPORT_URL = os.environ.get("REPORT_URL", "")

APIFY_ACTOR = "apify~instagram-scraper"


def fetch_instagram_data():
    url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items"
    lookback_days = max(1, LOOKBACK_HOURS // 24)

    run_input = {
        "directUrls": [f"https://www.instagram.com/{u}/" for u in SEED_ACCOUNTS]
        + [f"https://www.instagram.com/explore/tags/{h}/" for h in HASHTAGS],
        "resultsType": "reels",
        "resultsLimit": 20,
        "onlyPostsNewerThan": f"{lookback_days} days",
    }

    resp = requests.post(url, params={"token": APIFY_TOKEN}, json=run_input, timeout=600)
    resp.raise_for_status()
    return resp.json()


def filter_and_rank(items):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    reels = []

    for item in items:
        ts = item.get("timestamp")
        if not ts:
            continue
        try:
            post_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if post_time < cutoff:
            continue

        views = item.get("videoViewCount") or item.get("videoPlayCount") or 0
        reels.append({
            "url": item.get("url"),
            "account": item.get("ownerUsername"),
            "caption": (item.get("caption") or "")[:500],
            "views": views,
            "likes": item.get("likesCount", 0),
            "comments": item.get("commentsCount", 0),
        })

    reels.sort(key=lambda r: r["views"], reverse=True)
    return reels[:MAX_RESULTS_IN_REPORT]


def analyze_with_gemini(reel, max_retries=4):
    prompt = f"""
این کپشن یک ریل اینستاگرامی پربازدید در حوزه ارز دیجیتال/ترید است:

کپشن: {reel['caption']}
بازدید: {reel['views']}
لایک: {reel['likes']}

به فارسی و خیلی مختصر (هرکدام حداکثر ۲ خط) پاسخ بده:
۱. هوک احتمالی ۳ ثانیه اول ویدیو (بر اساس کپشن حدس بزن) چیست؟
۲. چرا این ویدیو می‌تواند وایرال شده باشد؟ (نام الگو)
۳. یک ایده مشخص برای ساخت ویدیویی مشابه اما با محتوای فارسی و متفاوت پیشنهاد بده.

خروجی را دقیقاً به‌صورت JSON با کلیدهای hook, why_viral, idea بده. فقط JSON، بدون توضیح اضافه.
"""

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-flash-latest:generateContent?key={GEMINI_API_KEY}"
    )
    body = {"contents": [{"parts": [{"text": prompt}]}]}

    for attempt in range(max_retries):
        resp = requests.post(url, json=body, timeout=60)

        if resp.status_code in (503, 429) and attempt < max_retries - 1:
            wait = 10 * (attempt + 1)
            print(f"سرور Gemini موقتاً در دسترس نیست ({resp.status_code}). تلاش دوباره پس از {wait} ثانیه...")
            time.sleep(wait)
            continue

        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"hook": "—", "why_viral": "—", "idea": text[:200]}

    return {"hook": "—", "why_viral": "—", "idea": "سرور Gemini موقتاً در دسترس نبود."}


def build_html_report(ranked_reels_with_analysis, total_scanned):
    today_fa = datetime.now().strftime("%Y-%m-%d")

    rows = ""
    for i, reel in enumerate(ranked_reels_with_analysis):
        a = reel["analysis"]
        rank = i + 1
        rows += f"""
        <div class="card">
          <div class="rank">#{rank}</div>
          <div class="card-body">
            <div class="account">@{reel['account']}</div>
            <div class="stats">
              <span>👁 {reel['views']:,}</span>
              <span>❤️ {reel['likes']:,}</span>
              <span>💬 {reel['comments']:,}</span>
            </div>
            <div class="row"><b>🎣 هوک:</b> {a['hook']}</div>
            <div class="row"><b>💡 چرا وایرال شد:</b> {a['why_viral']}</div>
            <div class="row"><b>✨ ایده پیشنهادی:</b> {a['idea']}</div>
            <a class="link" href="{reel['url']}" target="_blank">مشاهده ریل اصلی ↗</a>
          </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>گزارش روزانه ریل‌های کریپتو - {today_fa}</title>
<style>
  body {{
    font-family: Tahoma, Vazirmatn, sans-serif;
    background: #0e1621;
    color: #e8ecf1;
    margin: 0;
    padding: 20px;
  }}
  .header {{
    max-width: 720px;
    margin: 0 auto 24px;
    text-align: center;
  }}
  .header h1 {{ font-size: 22px; color: #64b5f6; margin-bottom: 6px; }}
  .header p {{ color: #9db1c9; font-size: 13px; }}
  .card {{
    max-width: 720px;
    margin: 0 auto 16px;
    background: #182533;
    border-radius: 14px;
    padding: 16px 18px;
    display: flex;
    gap: 14px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
  }}
  .rank {{
    font-size: 20px;
    font-weight: bold;
    color: #ffb74d;
    min-width: 32px;
  }}
  .account {{ font-weight: bold; font-size: 16px; color: #fff; margin-bottom: 6px; }}
  .stats {{ font-size: 12px; color: #9db1c9; margin-bottom: 10px; }}
  .stats span {{ margin-left: 12px; }}
  .row {{ font-size: 13.5px; line-height: 1.9; margin-bottom: 4px; }}
  .link {{ display: inline-block; margin-top: 6px; font-size: 12px; color: #64b5f6; text-decoration: none; }}
  .footer {{ max-width: 720px; margin: 20px auto; text-align: center; color: #5a6b7d; font-size: 11px; }}
</style>
</head>
<body>
  <div class="header">
    <h1>📊 گزارش روزانه ریل‌های برتر کریپتو/ترید</h1>
    <p>{today_fa} | {total_scanned} پست بررسی شد | {len(ranked_reels_with_analysis)} ریل برتر</p>
  </div>
  {rows}
  <div class="footer">تولید خودکار توسط ربات گزارش‌گیری روزانه</div>
</body>
</html>"""

    return html


def save_html_report(html):
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)


def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        resp = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=30,
        )
        resp.raise_for_status()
        time.sleep(1)


def main():
    print("در حال گرفتن داده از اینستاگرام...")
    raw_items = fetch_instagram_data()

    print(f"{len(raw_items)} پست دریافت شد. در حال فیلتر و رتبه‌بندی...")
    top_reels = filter_and_rank(raw_items)

    if not top_reels:
        send_to_telegram("امروز ریل جدیدی در بازه زمانی مشخص‌شده پیدا نشد.")
        return

    print(f"{len(top_reels)} ریل برتر انتخاب شد. در حال تحلیل با Gemini...")
    for reel in top_reels:
        reel["analysis"] = analyze_with_gemini(reel)
        time.sleep(2)

    print("در حال ساخت صفحه وب گزارش...")
    html = build_html_report(top_reels, len(raw_items))
    save_html_report(html)

    best = top_reels[0]
    link_line = f"\n\n📄 گزارش کامل: {REPORT_URL}" if REPORT_URL else ""
    alert_text = (
        f"📊 *گزارش روزانه آماده شد*\n"
        f"🥇 برترین ریل امروز: @{best['account']} با {best['views']:,} بازدید"
        f"{link_line}"
    )

    print("در حال ارسال اعلان به تلگرام...")
    send_to_telegram(alert_text)
    print("گزارش با موفقیت ساخته و اعلان ارسال شد.")


if __name__ == "__main__":
    main()
