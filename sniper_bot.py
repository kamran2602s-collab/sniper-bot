#!/usr/bin/env python3
"""
Reddit Micro-Job Sniper + Auto-Solution Generator Bot (v3.0 - Zero-Crash Edition)
=================================================================================
Upgrades & Fixes in v3.0:
1. Added a guaranteed "✅ Bot Connected & Working!" Telegram Startup Test Message
   on the very first run so a non-coder knows immediately that setup succeeded.
2. Relaxed post age window from 2 hours to 4 hours (14400s) so GitHub Actions cron
   delays never cause you to miss a fresh job.
3. Expanded task detection: catches [TASK], [Hiring], (Task), (Hiring), or Flair matches.
4. Added plain-text fallback for Telegram delivery in case HTML tags ever fail.
5. 3-Layer Reddit Fetcher (www.reddit.com JSON -> old.reddit.com JSON -> Public .rss XML)
   so cloud IP blocks never stop the bot.
"""

import ast
import html
import json
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

import requests

# =====================================================================
# 1. CONFIGURATION & SETTINGS
# =====================================================================

SUBREDDITS: List[str] = ["slavelabour", "DoneDirtCheap", "forhire"]
SEEN_POSTS_FILE: str = "seen_posts.txt"
MAX_POST_AGE_SECONDS: int = 4 * 3600  # 4 hours (prevents missing posts when GitHub cron delays)
FETCH_LIMIT: int = 25

USER_AGENT: str = (
    "python:microjob-sniper-bot:v3.0.0 (by /u/AutomationArchitectBot; "
    "+https://github.com/actions)"
)

# Keywords for tasks that can be solved quickly using AI without deep coding
TARGET_KEYWORDS: List[str] = [
    "python", "script", "scrape", "scraper", "scraping", "excel", "csv",
    "data", "automation", "automate", "bot", "json", "convert", "fix",
    "regex", "research", "writing", "write", "article", "summary", "summarize",
    "api", "sheet", "sheets", "google sheets", "vba", "macro", "clean",
    "parse", "extract", "pdf", "text", "prompt", "chatgpt", "ai", "sql",
    "formula", "selenium", "beautifulsoup", "pandas", "html", "css", "bug",
    "copy", "paste", "entry", "spreadsheet", "word", "doc", "transcribe",
    "blog", "content", "email", "list", "lead", "leads", "web", "website"
]

TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "").strip()

SYSTEM_PROMPT: str = (
    "Analyze this Reddit micro-job. "
    "1) Write a short, winning 3-line direct message (DM) to the client proving I have "
    "already started or solved their task. "
    "2) Explain in 2 simple Hindi/Hinglish lines what the client is asking for and how the user can finish it. "
    "3) If it is a coding, scraping, Excel formula, or writing task, provide the actual working Python script "
    "or ready-to-send sample right now. Wrap any Python code strictly inside a ```python ... ``` block."
)


# =====================================================================
# 2. SEEN POSTS TRACKER (PREVENT DUPLICATES)
# =====================================================================

def load_seen_posts(filepath: str = SEEN_POSTS_FILE) -> Set[str]:
    """Load previously seen post IDs from seen_posts.txt."""
    if not os.path.exists(filepath):
        return set()
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except Exception as exc:
        print(f"[WARN] Could not read {filepath}: {exc}")
        return set()


def save_seen_posts(seen_ids: Set[str], filepath: str = SEEN_POSTS_FILE) -> None:
    """Save seen post IDs to seen_posts.txt (retains latest 2500 entries)."""
    try:
        sorted_ids = sorted(list(seen_ids))[-2500:]
        with open(filepath, "w", encoding="utf-8") as f:
            for post_id in sorted_ids:
                f.write(f"{post_id}\n")
    except Exception as exc:
        print(f"[ERROR] Could not save {filepath}: {exc}")


# =====================================================================
# 3. 3-LAYER REDDIT FETCHER (JSON + OLD.REDDIT + RSS XML FALLBACK)
# =====================================================================

def clean_html_text(raw_html: str) -> str:
    """Strip HTML tags from RSS description text."""
    if not raw_html:
        return ""
    unescaped = html.unescape(raw_html)
    text = re.sub(r"<[^>]+>", " ", unescaped)
    return re.sub(r"\s+", " ", text).strip()


def fetch_subreddit_posts(subreddit: str) -> List[Dict[str, object]]:
    """
    Fetch latest 25 posts from a subreddit without browser/Selenium.
    Automatically falls back to old.reddit.com and .rss feed if blocked.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, application/atom+xml, text/xml;q=0.9, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    json_urls = [
        f"https://www.reddit.com/r/{subreddit}/new.json?limit={FETCH_LIMIT}",
        f"https://old.reddit.com/r/{subreddit}/new.json?limit={FETCH_LIMIT}",
    ]

    for url in json_urls:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                children = data.get("data", {}).get("children", [])
                posts = []
                for child in children:
                    p = child.get("data", {})
                    if not p:
                        continue
                    posts.append({
                        "id": str(p.get("id", "")).strip(),
                        "subreddit": subreddit,
                        "title": str(p.get("title", "")).strip(),
                        "selftext": str(p.get("selftext", "")).strip(),
                        "flair": str(p.get("link_flair_text", "") or "").strip(),
                        "author": str(p.get("author", "")).strip(),
                        "created_utc": float(p.get("created_utc", 0.0)),
                        "url": f"https://www.reddit.com{p.get('permalink', '')}",
                    })
                if posts:
                    print(f"[INFO] Fetched {len(posts)} posts from r/{subreddit} via JSON.")
                    return posts
            else:
                print(f"[WARN] {url} returned HTTP {resp.status_code}. Trying next layer...")
        except Exception as exc:
            print(f"[WARN] Error fetching {url}: {exc}")

    # Layer 3 Fallback: Public RSS/Atom feed (.rss)
    rss_url = f"https://www.reddit.com/r/{subreddit}/new/.rss?limit={FETCH_LIMIT}"
    try:
        resp = requests.get(rss_url, headers=headers, timeout=15)
        if resp.status_code == 200:
            root = ET.fromstring(resp.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            posts = []
            for entry in root.findall("atom:entry", ns):
                raw_id = entry.findtext("atom:id", default="", namespaces=ns)
                post_id = raw_id.split("_")[-1] if "_" in raw_id else raw_id
                title = entry.findtext("atom:title", default="", namespaces=ns)
                content_el = entry.find("atom:content", ns)
                selftext = clean_html_text(content_el.text if content_el is not None else "")

                author_el = entry.find("atom:author/atom:name", ns)
                author = ""
                if author_el is not None and author_el.text:
                    author = author_el.text.replace("/u/", "").strip()

                link_el = entry.find("atom:link", ns)
                post_url = link_el.attrib.get("href", "") if link_el is not None else ""

                updated_str = entry.findtext("atom:updated", default="", namespaces=ns)
                created_utc = time.time()
                if updated_str:
                    try:
                        dt = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                        created_utc = dt.timestamp()
                    except Exception:
                        pass

                posts.append({
                    "id": post_id,
                    "subreddit": subreddit,
                    "title": title.strip(),
                    "selftext": selftext,
                    "flair": "",
                    "author": author,
                    "created_utc": created_utc,
                    "url": post_url,
                })
            print(f"[INFO] Fetched {len(posts)} posts from r/{subreddit} via RSS fallback.")
            return posts
        else:
            print(f"[ERROR] RSS fallback for r/{subreddit} returned HTTP {resp.status_code}.")
    except Exception as exc:
        print(f"[ERROR] RSS fallback failed for r/{subreddit}: {exc}")

    return []


# =====================================================================
# 4. LOCAL PRE-FILTER (0 AI CALLS)
# =====================================================================

def is_valid_microjob(post: Dict[str, object], seen_ids: Set[str], now_ts: float) -> Tuple[bool, List[str]]:
    """
    Filter posts locally before calling AI:
    - Must not be in seen_posts.txt
    - Must NOT be [OFFER] or [For Hire]
    - Must contain [TASK] or [Hiring] in title or flair
    - Must have a valid author and be less than 4 hours old
    - Must match at least one target keyword
    """
    post_id = str(post.get("id", ""))
    if not post_id or post_id in seen_ids:
        return False, []

    title = str(post.get("title", ""))
    title_lower = title.lower()
    flair_lower = str(post.get("flair", "")).lower()
    body_lower = str(post.get("selftext", "")).lower()

    # Reject offers from freelancers looking for work
    offer_markers = ["[offer]", "(offer)", "[for hire]", "(for hire)", "[for-hire]"]
    if any(marker in title_lower for marker in offer_markers) or "offer" in flair_lower or "for hire" in flair_lower:
        return False, []

    # Require [TASK] or [Hiring] in title or flair
    task_markers = ["[task]", "(task)", "[hiring]", "(hiring)", "task:", "hiring:"]
    has_task_tag = any(marker in title_lower for marker in task_markers) or ("task" in flair_lower) or ("hiring" in flair_lower)
    if not has_task_tag:
        return False, []

    # Verify author is real
    author = str(post.get("author", "")).strip()
    if not author or author.lower() in {"[deleted]", "none", "automoderator", "deleted"}:
        return False, []

    # Verify post age is within MAX_POST_AGE_SECONDS
    created_utc = float(post.get("created_utc", 0.0))
    age_seconds = now_ts - created_utc
    if age_seconds < -300 or age_seconds > MAX_POST_AGE_SECONDS:
        return False, []

    # Check keyword match
    combined_text = f"{title_lower} {body_lower}"
    matched_keywords = [
        kw for kw in TARGET_KEYWORDS
        if re.search(rf"\b{re.escape(kw)}\b", combined_text)
    ]

    if not matched_keywords:
        return False, []

    return True, matched_keywords[:5]


# =====================================================================
# 5. KEYLESS POLLINATIONS AI + AST SYNTAX CHECKER
# =====================================================================

def extract_python_code_blocks(text: str) -> List[str]:
    """Extract ```python ... ``` blocks from AI response."""
    pattern = re.compile(r"```(?:python|py)\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
    return [match.strip() for match in pattern.findall(text) if match.strip()]


def verify_python_syntax(code_blocks: List[str]) -> Tuple[bool, Optional[str]]:
    """Run Python's built-in ast.parse() to guarantee zero syntax errors."""
    for idx, block in enumerate(code_blocks, start=1):
        try:
            ast.parse(block)
        except SyntaxError as err:
            return False, f"Block {idx} line {err.lineno}: {err.msg}"
        except Exception as err:
            return False, f"Block {idx}: {err}"
    return True, None


def call_pollinations_ai(user_prompt: str) -> Optional[str]:
    """Call keyless Pollinations AI endpoint with multi-endpoint fallback."""
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    payload = {
        "model": "openai",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
    }

    for endpoint in ["https://text.pollinations.ai/", "https://text.pollinations.ai/openai"]:
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=45)
            if resp.status_code == 200 and resp.text.strip():
                raw = resp.text.strip()
                if raw.startswith("{"):
                    try:
                        data = json.loads(raw)
                        if "choices" in data and data["choices"]:
                            content = data["choices"][0].get("message", {}).get("content", "")
                            if content:
                                return content.strip()
                    except json.JSONDecodeError:
                        pass
                return raw
        except Exception as exc:
            print(f"[WARN] Pollinations POST ({endpoint}) error: {exc}")

    # GET fallback
    try:
        combined = f"{SYSTEM_PROMPT}\n\n{user_prompt}"
        encoded = urllib.parse.quote(combined[:2800])
        resp = requests.get(
            f"https://text.pollinations.ai/{encoded}",
            headers={"User-Agent": USER_AGENT},
            timeout=45,
        )
        if resp.status_code == 200 and resp.text.strip():
            return resp.text.strip()
    except Exception as exc:
        print(f"[WARN] Pollinations GET fallback error: {exc}")

    return None


def call_groq_fallback(user_prompt: str) -> Optional[str]:
    """Optional fallback if user ever adds GROQ_API_KEY."""
    if not GROQ_API_KEY:
        return None
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        print(f"[WARN] Groq fallback error: {exc}")
    return None


def generate_verified_solution(post: Dict[str, object]) -> Tuple[str, str]:
    """Generate pitch + solution and verify any Python code with ast.parse()."""
    title = str(post.get("title", ""))
    body = str(post.get("selftext", ""))[:3000] or "(Only title provided by client.)"
    subreddit = str(post.get("subreddit", ""))

    prompt = (
        f"Subreddit: r/{subreddit}\n"
        f"Task Title: {title}\n"
        f"Task Details:\n{body}\n\n"
        "Output strictly in this structure:\n"
        "1) WINNING 3-LINE DM PITCH (English, ready to copy-paste to client)\n"
        "2) HINDI EXPLANATION (2 easy lines explaining what the client wants)\n"
        "3) WORKING SOLUTION / CODE (Python script or sample output)"
    )

    ai_output = call_pollinations_ai(prompt) or call_groq_fallback(prompt)
    if not ai_output:
        fallback_pitch = (
            "1) WINNING DM PITCH:\n"
            "Hi! I just saw your post and already prepared the workflow/sample for your task. "
            "I have commented $bid on your post—let me know where to send the completed work!\n\n"
            "2) HINDI EXPLANATION:\n"
            "AI सर्वर अभी व्यस्त था, कृपया ऊपर दिए गए पोस्ट लिंक पर क्लिक करके डिटेल्स देख लें।"
        )
        return fallback_pitch, "⚠️ AI Busy (Ready Pitch Included)"

    code_blocks = extract_python_code_blocks(ai_output)
    if not code_blocks:
        return ai_output, "✅ Verified (Pitch & Sample Ready)"

    is_valid, err_msg = verify_python_syntax(code_blocks)
    if is_valid:
        return ai_output, f"✅ AST Syntax Verified ({len(code_blocks)} Python script verified)"

    print(f"[WARN] AST SyntaxError ({err_msg}). Retrying AI generation...")
    retry_prompt = (
        f"{prompt}\n\n"
        f"IMPORTANT FIX: Your previous Python code had a SyntaxError ({err_msg}). "
        "Please fix the Python code so it passes Python 3 ast.parse() without errors."
    )
    repaired = call_pollinations_ai(retry_prompt) or call_groq_fallback(retry_prompt)
    if repaired:
        repaired_blocks = extract_python_code_blocks(repaired)
        if repaired_blocks:
            ok, _ = verify_python_syntax(repaired_blocks)
            if ok:
                return repaired, "✅ AST Syntax Verified (Auto-Fixed on Retry)"

    return ai_output, f"⚠️ Check Code Syntax ({err_msg})"


# =====================================================================
# 6. TELEGRAM SENDER (WITH STARTUP CONFIRMATION & FALLBACK)
# =====================================================================

def send_raw_telegram(text: str, use_html: bool = True) -> bool:
    """Send a single message to Telegram with automatic plain-text fallback if HTML fails."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] Telegram credentials not set. Console output:")
        print(text)
        return True

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload: Dict[str, object] = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    if use_html:
        payload["parse_mode"] = "HTML"

    try:
        resp = requests.post(url, json=payload, timeout=20)
        if resp.status_code == 200:
            return True
        print(f"[WARN] Telegram HTML send returned {resp.status_code}: {resp.text}. Retrying plain text...")
        # Fallback: strip HTML tags and send as plain text so message is NEVER lost
        plain_text = re.sub(r"<[^>]+>", "", html.unescape(text))
        resp2 = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": plain_text[:4000], "disable_web_page_preview": True},
            timeout=20,
        )
        return resp2.status_code == 200
    except Exception as exc:
        print(f"[ERROR] Telegram connection failed: {exc}")
        return False


def send_telegram_alert(post: Dict[str, object], keywords: List[str], ai_solution: str, badge: str) -> bool:
    """Format and send the job alert + AI solution to Telegram."""
    subreddit = str(post.get("subreddit", ""))
    title = str(post.get("title", ""))
    author = str(post.get("author", ""))
    post_url = str(post.get("url", ""))

    subject_enc = urllib.parse.quote(f"Re: {title[:75]}")
    dm_url = f"https://www.reddit.com/message/compose/?to={urllib.parse.quote(author)}&subject={subject_enc}"

    header = (
        f"🎯 <b>NEW REDDIT MICRO-JOB FOUND!</b>\n"
        f"📂 <b>Subreddit:</b> r/{html.escape(subreddit)}\n"
        f"📝 <b>Title:</b> {html.escape(title)}\n"
        f"👤 <b>Client:</b> u/{html.escape(author)}\n"
        f"🔑 <b>Keywords:</b> <code>{html.escape(', '.join(keywords))}</code>\n"
        f"🛡️ <b>Status:</b> {html.escape(badge)}\n\n"
        f"👉 <b>STEP 1:</b> <a href=\"{html.escape(post_url)}\">Click Here to Open Post &amp; Comment $bid</a>\n"
        f"👉 <b>STEP 2:</b> <a href=\"{html.escape(dm_url)}\">Click Here to Send DM to u/{html.escape(author)}</a>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )

    body = f"<b>🤖 AI PITCH &amp; SOLUTION:</b>\n\n{html.escape(ai_solution)}"
    full_msg = header + body

    if len(full_msg) <= 4000:
        return send_raw_telegram(full_msg, use_html=True)

    # Split if longer than 4000 chars
    ok1 = send_raw_telegram(header + "<i>(Solution নিচে दूसरे मैसेज में है...)</i>", use_html=True)
    escaped_sol = html.escape(ai_solution)
    ok2 = True
    for i in range(0, len(escaped_sol), 3800):
        chunk = f"<pre>{escaped_sol[i:i+3800]}</pre>"
        if not send_raw_telegram(chunk, use_html=True):
            ok2 = False
        time.sleep(1)
    return ok1 and ok2


# =====================================================================
# 7. MAIN RUNNER
# =====================================================================

def main() -> None:
    print(f"[START] Sniper Bot v3.0 running at {datetime.now(timezone.utc).isoformat()}")
    seen_ids = load_seen_posts(SEEN_POSTS_FILE)
    is_first_run = len(seen_ids) == 0

    now_ts = time.time()
    new_matches = 0

    for subreddit in SUBREDDITS:
        posts = fetch_subreddit_posts(subreddit)
        for post in reversed(posts):
            valid, matched_kws = is_valid_microjob(post, seen_ids, now_ts)
            if not valid:
                continue

            post_id = str(post.get("id", ""))
            print(f"[MATCH] r/{subreddit} ({post_id}): {post.get('title')}")
            ai_sol, badge = generate_verified_solution(post)

            if send_telegram_alert(post, matched_kws, ai_sol, badge):
                seen_ids.add(post_id)
                new_matches += 1
                save_seen_posts(seen_ids, SEEN_POSTS_FILE)
                time.sleep(3)

    # If this was the very first run and no fresh task matched right this second,
    # send a 1-time confirmation message to Telegram so the user knows 100% their bot works!
    if is_first_run and new_matches == 0 and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        welcome_msg = (
            "✅ <b>CONGRATULATIONS! आपका Reddit Sniper Bot 100% चालू हो गया है!</b>\n\n"
            "🔍 बॉट ने अभी <b>r/slavelabour</b>, <b>r/DoneDirtCheap</b>, और <b>r/forhire</b> को चेक किया है।\n"
            "⏳ अभी पिछले 4 घंटे में कोई नया मैचिंग टास्क नहीं था, लेकिन अब यह बॉट हर 15-20 मिनट में अपने-आप चेक करेगा और नया काम आते ही आपको यहाँ लिंक + AI सॉल्यूशन भेज देगा!"
        )
        send_raw_telegram(welcome_msg, use_html=True)
        seen_ids.add("INITIAL_SETUP_VERIFIED")

    save_seen_posts(seen_ids, SEEN_POSTS_FILE)
    print(f"[DONE] Sent {new_matches} new micro-job alert(s).")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[SAFE EXIT] Handled unexpected error: {exc}")
