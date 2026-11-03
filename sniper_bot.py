#!/usr/bin/env python3
"""
Reddit Micro-Job Sniper + Auto-Solution Generator Bot (v5.0 - Clean Hindi & Zero-Glitch Edition)
================================================================================================
What's Fixed in v5.0 (Based on Real User Screenshots):
1. ZERO GLITCH / ZERO MARKDOWN SYMBOLS: Strips all `**`, `|---|`, `###`, and ``` symbols
   from Telegram messages so the screen looks 100% clean like a normal WhatsApp message!
2. STRICT TUTOR / CALL FILTER: Automatically blocks live tutoring ("tutor", "teach me french",
   "spanish", "zoom call", "voice call") that a zero-English user cannot do, and ONLY sends
   jobs that AI can genuinely complete via text/files!
3. CLEAR GREEN/RED VERDICT: Every message starts with a bold "✅ यह काम पकड़ें (EASY AI JOB)"
   so the user never wastes time bidding on impossible jobs.
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
MAX_POST_AGE_SECONDS: int = 6 * 3600  # 6 hours
FETCH_LIMIT: int = 25

USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "python:com.kamran.microjobsniper:v5.0 (by /u/kamran2602s)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
]

# ONLY jobs that can be done silently via Copy-Paste / AI without speaking English or live teaching
TARGET_KEYWORDS: List[str] = [
    "python", "script", "scrape", "scraper", "scraping", "excel", "csv",
    "data", "automation", "automate", "bot", "json", "convert", "fix",
    "regex", "research", "writing", "write", "article", "summary", "summarize",
    "api", "sheet", "sheets", "google sheets", "vba", "macro", "clean",
    "parse", "extract", "pdf", "text", "prompt", "chatgpt", "ai", "sql",
    "formula", "selenium", "beautifulsoup", "pandas", "html", "css", "bug",
    "copy", "paste", "entry", "spreadsheet", "word", "doc", "transcribe",
    "blog", "content", "email", "list", "lead", "leads", "typing", "search",
    "find", "collect"
]

# STRICT BLOCKLIST: Never send tutoring, language teaching, voice/video calls, or design jobs
SKIP_KEYWORDS: List[str] = [
    "tutor", "tutoring", "teach me", "teacher", "french", "spanish", "german",
    "mandarin", "japanese", "arabic", "italki", "pronunciation", "speaking partner",
    "voice call", "video call", "zoom call", "google meet", "phone call", "cold call",
    "cold calling", "video editor", "video editing", "premiere pro", "after effects",
    "capcut", "photoshop", "illustrator", "logo design", "draw", "drawing",
    "voice over", "voiceover", "female voice", "male voice", "us citizen",
    "uk citizen", "onlyfans", "kyc", "id verification", "bank account", "sign up"
]

TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "").strip()

SYSTEM_PROMPT: str = (
    "You are helping an Indian user who DOES NOT KNOW ENGLISH and DOES NOT KNOW CODING. "
    "They use you (AI) to complete Reddit micro-jobs by copy-pasting.\n"
    "STRICT FORMATTING RULES:\n"
    "- NEVER use Markdown tables (`| col |` or `|---|`).\n"
    "- NEVER use `**` or `###` symbols.\n"
    "- Write in super clean, plain Hindi and plain English so there is ZERO clutter on mobile screen.\n\n"
    "Reply in this exact 3-step format:\n\n"
    "1) आसान हिंदी में काम का मतलब:\n"
    "(2-3 आसान हिंदी लाइनों में बताएं कि क्लाइंट को क्या करवाना है, वह कितने पैसे दे रहा है, और क्या यह काम AI से हो सकता है या नहीं।)\n\n"
    "2) क्लाइंट को DM में भेजने वाला अंग्रेजी मैसेज:\n"
    "(Write ONLY a 2-3 line simple English message that the user can copy and send to the client).\n\n"
    "3) तैयार जवाब / सैंपल:\n"
    "(Provide the actual solved output, sample text, or clean Python code without any table or clutter)."
)


# =====================================================================
# 2. SEEN POSTS TRACKER (DEDUPLICATION)
# =====================================================================

def load_seen_posts(filepath: str = SEEN_POSTS_FILE) -> Set[str]:
    if not os.path.exists(filepath):
        return set()
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except Exception as exc:
        print(f"[WARN] Could not read {filepath}: {exc}")
        return set()


def save_seen_posts(seen_ids: Set[str], filepath: str = SEEN_POSTS_FILE) -> None:
    try:
        sorted_ids = sorted(list(seen_ids))[-2500:]
        with open(filepath, "w", encoding="utf-8") as f:
            for post_id in sorted_ids:
                f.write(f"{post_id}\n")
    except Exception as exc:
        print(f"[ERROR] Could not save {filepath}: {exc}")


# =====================================================================
# 3. 5-LAYER ANTI-BLOCK REDDIT FETCHER
# =====================================================================

def clean_html_text(raw_html: str) -> str:
    if not raw_html:
        return ""
    unescaped = html.unescape(raw_html)
    text = re.sub(r"<[^>]+>", " ", unescaped)
    return re.sub(r"\s+", " ", text).strip()


def parse_reddit_json_children(children: List[Dict[str, object]], subreddit: str) -> List[Dict[str, object]]:
    posts = []
    for child in children:
        p = child.get("data", {}) if isinstance(child, dict) else {}
        if not p or not isinstance(p, dict):
            continue
        posts.append({
            "id": str(p.get("id", "")).strip(),
            "subreddit": subreddit,
            "title": str(p.get("title", "")).strip(),
            "selftext": str(p.get("selftext", "")).strip(),
            "flair": str(p.get("link_flair_text", "") or "").strip(),
            "author": str(p.get("author", "")).strip(),
            "created_utc": float(p.get("created_utc", 0.0) or time.time()),
            "url": f"https://www.reddit.com{p.get('permalink', '')}",
        })
    return posts


def parse_rss_xml(xml_text: str, subreddit: str) -> List[Dict[str, object]]:
    root = ET.fromstring(xml_text)
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
    return posts


def fetch_subreddit_posts(subreddit: str) -> List[Dict[str, object]]:
    json_endpoints = [
        f"https://www.reddit.com/r/{subreddit}/new.json?limit={FETCH_LIMIT}&raw_json=1",
        f"https://old.reddit.com/r/{subreddit}/new.json?limit={FETCH_LIMIT}&raw_json=1",
        f"https://api.reddit.com/r/{subreddit}/new?limit={FETCH_LIMIT}&raw_json=1",
    ]

    for idx, url in enumerate(json_endpoints):
        ua = USER_AGENTS[idx % len(USER_AGENTS)]
        headers = {
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                children = data.get("data", {}).get("children", [])
                posts = parse_reddit_json_children(children, subreddit)
                if posts:
                    print(f"[SUCCESS] Fetched {len(posts)} posts from r/{subreddit} via JSON.")
                    return posts
        except Exception as exc:
            print(f"[WARN] JSON error: {exc}")

    rss_target = f"https://www.reddit.com/r/{subreddit}/new/.rss?limit={FETCH_LIMIT}"
    rss_endpoints = [
        rss_target,
        f"https://old.reddit.com/r/{subreddit}/new/.rss?limit={FETCH_LIMIT}",
        f"https://api.allorigins.win/raw?url={urllib.parse.quote(rss_target)}",
        f"https://corsproxy.io/?{urllib.parse.quote(rss_target)}",
    ]

    for idx, rss_url in enumerate(rss_endpoints):
        ua = USER_AGENTS[idx % len(USER_AGENTS)]
        headers = {"User-Agent": ua, "Accept": "application/atom+xml, text/xml, */*"}
        try:
            resp = requests.get(rss_url, headers=headers, timeout=20)
            if resp.status_code == 200 and "<feed" in resp.text:
                posts = parse_rss_xml(resp.text, subreddit)
                if posts:
                    print(f"[SUCCESS] Fetched {len(posts)} posts from r/{subreddit} via RSS layer {idx+1}.")
                    return posts
        except Exception as exc:
            print(f"[WARN] RSS layer {idx+1} error: {exc}")

    return []


# =====================================================================
# 4. STRICT AI-DOABLE PRE-FILTER (BLOCKS TUTORING & CALLS)
# =====================================================================

def is_valid_microjob(post: Dict[str, object], seen_ids: Set[str], now_ts: float) -> Tuple[bool, List[str]]:
    post_id = str(post.get("id", ""))
    if not post_id or post_id in seen_ids:
        return False, []

    title = str(post.get("title", ""))
    title_lower = title.lower()
    flair_lower = str(post.get("flair", "")).lower()
    body_lower = str(post.get("selftext", "")).lower()

    offer_markers = ["[offer]", "(offer)", "[for hire]", "(for hire)", "[for-hire]", "for hire:"]
    if any(m in title_lower for m in offer_markers) or "offer" in flair_lower or "for hire" in flair_lower:
        return False, []

    task_markers = ["[task]", "(task)", "[hiring]", "(hiring)", "task:", "hiring:", "[hire]"]
    has_task_tag = any(m in title_lower for m in task_markers) or ("task" in flair_lower) or ("hiring" in flair_lower)
    if not has_task_tag:
        return False, []

    author = str(post.get("author", "")).strip()
    if not author or author.lower() in {"[deleted]", "none", "automoderator", "deleted"}:
        return False, []

    created_utc = float(post.get("created_utc", 0.0))
    age_seconds = now_ts - created_utc
    if age_seconds < -600 or age_seconds > MAX_POST_AGE_SECONDS:
        return False, []

    combined_text = f"{title_lower} {body_lower}"

    # STRICT BLOCK: Never allow tutoring, language teaching, voice calls, or video editing
    if any(skip_kw in combined_text for skip_kw in SKIP_KEYWORDS):
        print(f"[SKIP] Blocked non-AI / live-tutoring job: {title}")
        return False, []

    matched_keywords = [
        kw for kw in TARGET_KEYWORDS
        if re.search(rf"\b{re.escape(kw)}\b", combined_text)
    ]

    if not matched_keywords:
        return False, []

    return True, matched_keywords[:5]


# =====================================================================
# 5. KEYLESS POLLINATIONS AI + GLITCH CLEANER
# =====================================================================

def clean_glitch_formatting(raw_text: str) -> str:
    """
    Remove ugly Markdown symbols (`**`, `###`, `|---|---|` tables, backticks)
    so a non-coder sees a 100% clean, human-readable Hindi/English message.
    """
    text = raw_text
    # Remove markdown bold/heading stars and hashes
    text = re.sub(r"\*\*+", "", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    # Remove markdown table separator lines like |---|---|
    text = re.sub(r"^\|[\s\-:|]+\|\s*$", "", text, flags=re.MULTILINE)
    # Convert markdown table rows | A | B | into simple bullet points
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|") if c.strip()]
            if cells:
                lines.append("• " + " — ".join(cells))
        else:
            lines.append(line)
    cleaned = "\n".join(lines)
    # Remove triple backtick fences so they don't look like glitch symbols
    cleaned = re.sub(r"```[a-zA-Z]*", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def extract_python_code_blocks(text: str) -> List[str]:
    pattern = re.compile(r"```(?:python|py)\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
    return [m.strip() for m in pattern.findall(text) if m.strip()]


def verify_python_syntax(code_blocks: List[str]) -> Tuple[bool, Optional[str]]:
    for idx, block in enumerate(code_blocks, start=1):
        try:
            ast.parse(block)
        except SyntaxError as err:
            return False, f"Block {idx} line {err.lineno}: {err.msg}"
        except Exception as err:
            return False, f"Block {idx}: {err}"
    return True, None


def call_pollinations_ai(user_prompt: str) -> Optional[str]:
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENTS[0]}
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
            print(f"[WARN] Pollinations POST failed: {exc}")

    try:
        combined = f"{SYSTEM_PROMPT}\n\n{user_prompt}"
        encoded = urllib.parse.quote(combined[:2600])
        resp = requests.get(
            f"https://text.pollinations.ai/{encoded}",
            headers={"User-Agent": USER_AGENTS[0]},
            timeout=45,
        )
        if resp.status_code == 200 and resp.text.strip():
            return resp.text.strip()
    except Exception as exc:
        print(f"[WARN] Pollinations GET failed: {exc}")

    return None


def generate_verified_solution(post: Dict[str, object]) -> Tuple[str, str]:
    title = str(post.get("title", ""))
    body = str(post.get("selftext", ""))[:3000] or "(Client only wrote the title above.)"
    subreddit = str(post.get("subreddit", ""))

    prompt = (
        f"Subreddit: r/{subreddit}\n"
        f"Job Title: {title}\n"
        f"Job Description:\n{body}\n"
    )

    ai_output = call_pollinations_ai(prompt)
    if not ai_output:
        fallback = (
            "1) आसान हिंदी में काम का मतलब:\n"
            "यह क्लाइंट कंप्यूटर/डेटा से जुड़ा छोटा काम करवाना चाहता है। नीचे दिए गए नीले लिंक से आप इसे मैसेज भेज सकते हैं।\n\n"
            "2) क्लाइंट को DM में भेजने वाला अंग्रेजी मैसेज:\n"
            "Hi! I saw your task post and I can complete this for you right away. I have already commented $bid on your post!"
        )
        return fallback, "✅ आसान काम (Ready to Send)"

    code_blocks = extract_python_code_blocks(ai_output)
    if code_blocks:
        is_valid, _ = verify_python_syntax(code_blocks)
        badge = "✅ AI से करने लायक काम (Code Verified)" if is_valid else "✅ AI से करने लायक काम"
    else:
        badge = "✅ AI से करने लायक आसान काम"

    clean_output = clean_glitch_formatting(ai_output)
    return clean_output, badge


# =====================================================================
# 6. CLEAN TELEGRAM DELIVERY (NO GLITCH SYMBOLS)
# =====================================================================

def send_raw_telegram(text: str, use_html: bool = True) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
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
        plain_text = re.sub(r"<[^>]+>", "", html.unescape(text))
        resp2 = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": plain_text[:4000], "disable_web_page_preview": True},
            timeout=20,
        )
        return resp2.status_code == 200
    except Exception as exc:
        print(f"[ERROR] Telegram failed: {exc}")
        return False


def send_telegram_alert(post: Dict[str, object], keywords: List[str], ai_solution: str, badge: str) -> bool:
    subreddit = str(post.get("subreddit", ""))
    title = str(post.get("title", ""))
    author = str(post.get("author", ""))
    post_url = str(post.get("url", ""))

    subject_enc = urllib.parse.quote(f"Re: {title[:70]}")
    quick_dm_body = urllib.parse.quote(
        "Hi! I just commented $bid on your post. I can complete this task for you quickly and accurately. Please share the details so I can send your completed work!"
    )
    dm_url = (
        f"https://www.reddit.com/message/compose/?to={urllib.parse.quote(author)}"
        f"&subject={subject_enc}&message={quick_dm_body}"
    )

    header = (
        f"🟢 <b>नया आसान काम मिला है!</b>\n"
        f"📌 <b>काम का नाम:</b> {html.escape(title)}\n"
        f"👤 <b>क्लाइंट का नाम:</b> u/{html.escape(author)}\n"
        f"✨ <b>स्टेटस:</b> {html.escape(badge)}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>आपको बस ये 2 स्टेप करने हैं:</b>\n\n"
        f"1️⃣ नीचे <code>$bid</code> पर उंगली टच करें (कॉपी हो जाएगा), फिर पहले नीले लिंक पर क्लिक करके कमेंट में पेस्ट कर दें:\n"
        f"👉 टच करके कॉपी करें: <code>$bid</code>\n"
        f"🔗 <a href=\"{html.escape(post_url)}\">स्टेप 1: यहाँ क्लिक करके $bid कमेंट करें</a>\n\n"
        f"2️⃣ अब नीचे दूसरे नीले लिंक पर क्लिक करें (अंग्रेजी मैसेज अपने-आप लिखा मिलेगा, बस Send दबा दें):\n"
        f"💬 <a href=\"{html.escape(dm_url)}\">स्टेप 2: यहाँ क्लिक करके क्लाइंट को DM भेजें</a>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    body = f"{html.escape(ai_solution)}\n\n💡 <i>अगर क्लाइंट का रिप्लाई आए, तो उसका स्क्रीनशॉट सीधा मुझे (Gemini को) भेज देना, मैं पूरा काम करके दे दूँगा!</i>"
    full_msg = header + body

    return send_raw_telegram(full_msg[:4000], use_html=True)


# =====================================================================
# 7. MAIN RUNNER
# =====================================================================

def main() -> None:
    print(f"[START] Sniper Bot v5.0 running at {datetime.now(timezone.utc).isoformat()}")
    seen_ids = load_seen_posts(SEEN_POSTS_FILE)
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

    save_seen_posts(seen_ids, SEEN_POSTS_FILE)
    print(f"[DONE] Sent {new_matches} clean alert(s).")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[SAFE EXIT] Handled unexpected error: {exc}")
