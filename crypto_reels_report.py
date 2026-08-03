"""
گزارش روزانه ریل‌های برتر کریپتو/ترید فارسی در اینستاگرام
اجزا: Apify (داده اینستاگرام) + Google Gemini (تحلیل رایگان) + Telegram (ارسال)

نحوه اجرا:
    python crypto_reels_report.py

متغیرهای محیطی لازم (به‌صورت GitHub Secrets یا در .env محلی):
    APIFY_TOKEN
    GEMINI_API_KEY
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
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
    "fasttraderofficial",
    "kahangi_arash1",
]

HASHTAGS = ["ترید", "کریپتو", "ارزدیجیتال", "تحلیل_تکنیکال", "بیتکوین"]

MAX_RESULTS_IN_REPORT = 8
LOOKBACK_HOURS = 48

# ---------------------------------------------------------------------------
# متغیرهای محیطی
# ---------------------------------------------------------------------------

APIFY_TOKEN = os.environ["APIFY_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

APIFY_ACTOR = "apify~instagram-scraper"


# ---------------------------------------------------------------------------
# قدم ۱: گرفتن داده از Apify
# ---------------------------------------------------------------------------

def fetch_instagram_data():
    """ریل‌های اکانت‌های ثابت + هشتگ‌ها را از Apify می‌گیرد."""
    url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items"

    lookback_days = max(1, LOOKBACK_HOURS // 24)

    run_input = {
        "directUrls": [f"https://www.instagram.com/{u}/" for u in SEED_ACCOUNTS]
        + [f"https://www.instagram.com/explore/tags/{h}/" for h in HASHTAGS],
        "resultsType": "reels",
        "resultsLimit": 15,
        "onlyPostsNewerThan": f"{lookback_days} days",
    }

    resp = requests.post(
        url,
        params={"token": APIFY_TOKEN},
        json=run_input,
        timeout=600,
    )
    resp.raise_for_status()
    return resp.json()


def filter_and_rank(items):
    """فقط ریل‌ها را نگه می‌دارد، بر اساس بازدید مرتب می‌کند و N تای برتر را برمی‌گرداند."""
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


# ---------------------------------------------------------------------------
# قدم ۲: تحلیل هر ریل با Gemini (رایگان)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# قدم ۳: ساخت متن گزارش و ارسال به تلگرام
# ---------------------------------------------------------------------------

def build_report(ranked_reels_with_analysis):
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"📊 *گزارش روزانه ریل‌های برتر کریپتو* — {today}\n"]

    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 10
    for i, reel in enumerate(ranked_reels_with_analysis):
        a = reel["analysis"]
        lines.append(
            f"{medals[i]} *@{reel['account']}*\n"
            f"👁 {reel['views']:,} | ❤️ {reel['likes']:,} | 💬 {reel['comments']:,}\n"
            f"🎣 هوک: {a['hook']}\n"
            f"💡 چرا وایرال شد: {a['why_viral']}\n"
            f"✨ ایده پیشنهادی: {a['idea']}\n"
            f"🔗 {reel['url']}\n"
        )

    return "\n".join(lines)


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
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        resp.raise_for_status()
        time.sleep(1)


# ---------------------------------------------------------------------------
# اجرای اصلی
# ---------------------------------------------------------------------------

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

    report_text = build_report(top_reels)

    print("در حال ارسال به تلگرام...")
    send_to_telegram(report_text)
    print("گزارش با موفقیت ارسال شد.")


if __name__ == "__main__":
    main()
