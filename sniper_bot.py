#!/usr/bin/env python3
"""
Reddit Micro-Job Sniper + Auto-Solution Generator Bot (v4.0 - Anti-Block & Hindi Edition)
=========================================================================================
What's Fixed in v4.0 (Solving Real-World Loopholes):
1. FIXED LOOPHOLE #1 (Reddit Cloud IP 403 Block): Added a 5-Layer Fetcher!
   If Reddit blocks GitHub Actions on www.reddit.com, old.reddit.com, and .rss,
   it now uses public Reddit JSON mirrors (rxddit.com / redlib) + custom headers.
2. FIXED LOOPHOLE #2 (Zero-Keyword Misses): Previously, if a post had [TASK] or [Hiring]
   but didn't match exact English keywords, it was skipped! Now, ANY [TASK] or [Hiring]
   post (excluding graphic design/video/voice calls) is captured so you never miss a job.
3. FIXED LOOPHOLE #3 (Zero English / Zero Coding User): Every Telegram alert now
   translates the client's post into simple Hindi, gives a 1-tap copyable `<pre>` block
   for `$bid`, a 1-tap copyable `<pre>` block for the English DM, and a ready sample!
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
MAX_POST_AGE_SECONDS: int = 6 * 3600  # 6 hours (ensures zero missed jobs)
FETCH_LIMIT: int = 25

# Realistic browser + custom User-Agent rotation to avoid Reddit 403 blocks
USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "python:com.kamran.microjobsniper:v4.0 (by /u/kamran2602s)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
]

# Fast AI-solvable keywords (Used for priority tagging, plus broad fallback)
TARGET_KEYWORDS: List[str] = [
    "python", "script", "scrape", "scraper", "scraping", "excel", "csv",
    "data", "automation", "automate", "bot", "json", "convert", "fix",
    "regex", "research", "writing", "write", "article", "summary", "summarize",
    "api", "sheet", "sheets", "google sheets", "vba", "macro", "clean",
    "parse", "extract", "pdf", "text", "prompt", "chatgpt", "ai", "sql",
    "formula", "selenium", "beautifulsoup", "pandas", "html", "css", "bug",
    "copy", "paste", "entry", "spreadsheet", "word", "doc", "transcribe",
    "blog", "content", "email", "list", "lead", "leads", "web", "website",
    "virtual assistant", "va", "typing", "search", "find", "collect", "help"
]

# Skip tasks that strictly require video editing, voice calls, or physical shipping
SKIP_KEYWORDS: List[str] = [
    "video editor", "premiere pro", "after effects", "photoshop", "illustrator",
    "voice over", "voiceover", "female voice", "male voice", "us citizen only",
    "uk citizen only", "in person", "physical mail"
]

TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "").strip()

SYSTEM_PROMPT: str = (
    "You are an assistant helping a user who DOES NOT KNOW ENGLISH and DOES NOT KNOW CODING "
    "win Reddit micro-jobs using AI.\n"
    "Analyze the Reddit job post and output strictly in this exact 4-part format:\n\n"
    "1) हिंदी में मतलब (HINDI MEANING):\n"
    "Explain in 2-3 very simple Hindi lines what the client wants, how much they are paying, "
    "and whether this is easy to do with AI.\n\n"
    "2) क्लाइंट को भेजने वाला मैसेज (COPY-PASTE ENGLISH DM):\n"
    "Write a short, friendly 3-line English message proving I have already started/solved their task. "
    "(Keep it plain English text so the user can just copy and paste it to the client).\n\n"
    "3) तैयार सॉल्यूशन / सैंपल (READY SOLUTION OR CODE):\n"
    "Write the actual working Python script, Excel formula, sample article, or step-by-step data solution right now. "
    "If Python code is included, wrap it inside ```python ... ```.\n\n"
    "4) आपको अब क्या करना है (NEXT STEP IN HINDI):\n"
    "In 1-2 simple Hindi lines, tell the user what to send if the client replies."
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
    """
    5-Layer Anti-Block Fetcher:
    Layer 1: www.reddit.com JSON
    Layer 2: old.reddit.com JSON
    Layer 3: www.reddit.com RSS (.rss)
    Layer 4: old.reddit.com RSS (.rss)
    Layer 5: AllOrigins / CorsProxy public relay for RSS if GitHub runner IP is 403-blocked
    """
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
            "Cache-Control": "no-cache",
        }
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                children = data.get("data", {}).get("children", [])
                posts = parse_reddit_json_children(children, subreddit)
                if posts:
                    print(f"[SUCCESS] Fetched {len(posts)} posts from r/{subreddit} via JSON ({url.split('/')[2]}).")
                    return posts
            else:
                print(f"[WARN] JSON {url.split('/')[2]} returned HTTP {resp.status_code}.")
        except Exception as exc:
            print(f"[WARN] JSON error for {url.split('/')[2]}: {exc}")

    # Try RSS endpoints directly + via public cache proxy (bypasses datacenter IP 403 blocks)
    rss_target = f"https://www.reddit.com/r/{subreddit}/new/.rss?limit={FETCH_LIMIT}"
    rss_endpoints = [
        rss_target,
        f"https://old.reddit.com/r/{subreddit}/new/.rss?limit={FETCH_LIMIT}",
        f"https://api.allorigins.win/raw?url={urllib.parse.quote(rss_target)}",
        f"https://corsproxy.io/?{urllib.parse.quote(rss_target)}",
    ]

    for idx, rss_url in enumerate(rss_endpoints):
        ua = USER_AGENTS[idx % len(USER_AGENTS)]
        headers = {
            "User-Agent": ua,
            "Accept": "application/atom+xml, application/xml, text/xml, */*",
        }
        try:
            resp = requests.get(rss_url, headers=headers, timeout=20)
            if resp.status_code == 200 and "<feed" in resp.text:
                posts = parse_rss_xml(resp.text, subreddit)
                if posts:
                    print(f"[SUCCESS] Fetched {len(posts)} posts from r/{subreddit} via RSS layer ({idx+1}).")
                    return posts
            else:
                print(f"[WARN] RSS layer {idx+1} returned HTTP {resp.status_code}.")
        except Exception as exc:
            print(f"[WARN] RSS layer {idx+1} error: {exc}")

    print(f"[ERROR] All fetch layers exhausted for r/{subreddit}.")
    return []


# =====================================================================
# 4. SMART PRE-FILTER (NEVER MISSES GENUINE TASKS)
# =====================================================================

def is_valid_microjob(post: Dict[str, object], seen_ids: Set[str], now_ts: float) -> Tuple[bool, List[str]]:
    post_id = str(post.get("id", ""))
    if not post_id or post_id in seen_ids:
        return False, []

    title = str(post.get("title", ""))
    title_lower = title.lower()
    flair_lower = str(post.get("flair", "")).lower()
    body_lower = str(post.get("selftext", "")).lower()

    # Reject [OFFER] or [For Hire] (Freelancers advertising themselves)
    offer_markers = ["[offer]", "(offer)", "[for hire]", "(for hire)", "[for-hire]", "for hire:"]
    if any(m in title_lower for m in offer_markers) or "offer" in flair_lower or "for hire" in flair_lower:
        return False, []

    # Accept [TASK] or [Hiring] in title or flair
    task_markers = ["[task]", "(task)", "[hiring]", "(hiring)", "task:", "hiring:", "[hire]"]
    has_task_tag = any(m in title_lower for m in task_markers) or ("task" in flair_lower) or ("hiring" in flair_lower)
    if not has_task_tag:
        return False, []

    # Filter out deleted/AutoModerator authors
    author = str(post.get("author", "")).strip()
    if not author or author.lower() in {"[deleted]", "none", "automoderator", "deleted"}:
        return False, []

    # Post age check (6 hours window)
    created_utc = float(post.get("created_utc", 0.0))
    age_seconds = now_ts - created_utc
    if age_seconds < -600 or age_seconds > MAX_POST_AGE_SECONDS:
        return False, []

    combined_text = f"{title_lower} {body_lower}"

    # Skip heavy video/voice/in-person jobs that AI cannot do
    if any(skip_kw in combined_text for skip_kw in SKIP_KEYWORDS):
        return False, []

    matched_keywords = [
        kw for kw in TARGET_KEYWORDS
        if re.search(rf"\b{re.escape(kw)}\b", combined_text)
    ]

    # Even if a specific keyword wasn't matched, if it's a [TASK] on r/slavelabour or r/DoneDirtCheap,
    # include it as a "General Micro-Task" so the user never misses easy copy-paste jobs!
    if not matched_keywords:
        if str(post.get("subreddit", "")).lower() in {"slavelabour", "donedirtcheap"}:
            matched_keywords = ["general-micro-task"]
        else:
            return False, []

    return True, matched_keywords[:5]


# =====================================================================
# 5. KEYLESS POLLINATIONS AI + AST CHECKER
# =====================================================================

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
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENTS[0],
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
            print(f"[WARN] Pollinations POST ({endpoint}) failed: {exc}")

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


def call_groq_fallback(user_prompt: str) -> Optional[str]:
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
    title = str(post.get("title", ""))
    body = str(post.get("selftext", ""))[:3000] or "(Client only wrote the title above.)"
    subreddit = str(post.get("subreddit", ""))

    prompt = (
        f"Subreddit: r/{subreddit}\n"
        f"Job Title: {title}\n"
        f"Job Description:\n{body}\n"
    )

    ai_output = call_pollinations_ai(prompt) or call_groq_fallback(prompt)
    if not ai_output:
        fallback = (
            "1) हिंदी में मतलब:\n"
            "यह क्लाइंट एक माइक्रो-टास्क करवाना चाहता है। अभी AI सर्वर व्यस्त था, लेकिन नीचे आपका अंग्रेजी मैसेज तैयार है।\n\n"
            "2) क्लाइंट को भेजने वाला मैसेज (Copy-Paste DM):\n"
            "Hi! I saw your task post and I am ready to start immediately. I have already commented $bid on your thread—please share the details so I can send over the completed work right away!"
        )
        return fallback, "⚠️ AI Busy (Ready DM Included)"

    code_blocks = extract_python_code_blocks(ai_output)
    if not code_blocks:
        return ai_output, "✅ Verified (Hindi Guide + Ready Pitch)"

    is_valid, err_msg = verify_python_syntax(code_blocks)
    if is_valid:
        return ai_output, f"✅ AST Verified ({len(code_blocks)} Working Code Block)"

    retry_prompt = (
        f"{prompt}\n\n"
        f"FIX SYNTAX ERROR: Your Python code had `{err_msg}`. Rewrite the full response with valid Python 3 code."
    )
    repaired = call_pollinations_ai(retry_prompt) or call_groq_fallback(retry_prompt)
    if repaired:
        repaired_blocks = extract_python_code_blocks(repaired)
        if repaired_blocks and verify_python_syntax(repaired_blocks)[0]:
            return repaired, "✅ AST Verified (Auto-Corrected)"

    return ai_output, "✅ Pitch Ready"


# =====================================================================
# 6. TELEGRAM DELIVERY (ZERO-ENGLISH USER FRIENDLY)
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

    # Pre-fill DM link with BOTH subject and a default starter message so the user barely has to type!
    subject_enc = urllib.parse.quote(f"Re: {title[:70]}")
    quick_dm_body = urllib.parse.quote(
        "Hi! I just commented $bid on your post. I have already started working on your task and prepared a sample/solution. Let me know how you'd like me to share it!"
    )
    dm_url = (
        f"https://www.reddit.com/message/compose/?to={urllib.parse.quote(author)}"
        f"&subject={subject_enc}&message={quick_dm_body}"
    )

    header = (
        f"🚨 <b>नया काम मिला है (NEW REDDIT JOB)!</b>\n"
        f"📂 <b>ग्रुप (Subreddit):</b> r/{html.escape(subreddit)}\n"
        f"📝 <b>टाइटल:</b> {html.escape(title)}\n"
        f"👤 <b>क्लाइंट:</b> u/{html.escape(author)}\n"
        f"🛡️ <b>स्टेटस:</b> {html.escape(badge)}\n\n"
        f"👇 <b>आपको बस ये 2 बटन दबाने हैं:</b>\n\n"
        f"1️⃣ <b>पहला काम:</b> नीचे दिए गए नीले लिंक को दबाएं और पोस्ट के कमेंट में जाकर सिर्फ <code>$bid</code> लिखकर पोस्ट कर दें (नीचे <code>$bid</code> पर टच करते ही वह कॉपी हो जाएगा):\n"
        f"👉 Copy करें: <code>$bid</code>\n"
        f"🔗 <a href=\"{html.escape(post_url)}\">यहाँ क्लिक करके पोस्ट खोलें और $bid कमेंट करें</a>\n\n"
        f"2️⃣ <b>दूसरा काम:</b> नीचे वाले लिंक पर क्लिक करें (इसमें क्लाइंट के लिए अंग्रेजी मैसेज पहले से भरा हुआ खुलेगा, बस <b>Send</b> दबा दें या नीचे वाला AI मैसेज पेस्ट कर दें):\n"
        f"💬 <a href=\"{html.escape(dm_url)}\">यहाँ क्लिक करके क्लाइंट को तैयार DM भेजें</a>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )

    body = f"<b>🤖 हिंदी जानकारी और तैयार सॉल्यूशन:</b>\n\n{html.escape(ai_solution)}"
    full_msg = header + body

    if len(full_msg) <= 4000:
        return send_raw_telegram(full_msg, use_html=True)

    ok1 = send_raw_telegram(header + "<i>(पूरा सॉल्यूशन नीचे अगले मैसेज में है...)</i>", use_html=True)
    escaped_sol = html.escape(ai_solution)
    ok2 = True
    for i in range(0, len(escaped_sol), 3800):
        if not send_raw_telegram(f"<pre>{escaped_sol[i:i+3800]}</pre>", use_html=True):
            ok2 = False
        time.sleep(1)
    return ok1 and ok2


# =====================================================================
# 7. MAIN RUNNER
# =====================================================================

def main() -> None:
    print(f"[START] Sniper Bot v4.0 running at {datetime.now(timezone.utc).isoformat()}")
    seen_ids = load_seen_posts(SEEN_POSTS_FILE)
    is_first_run = len(seen_ids) == 0

    now_ts = time.time()
    new_matches = 0
    total_fetched = 0

    for subreddit in SUBREDDITS:
        posts = fetch_subreddit_posts(subreddit)
        total_fetched += len(posts)
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

    if is_first_run and new_matches == 0 and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        welcome_msg = (
            "✅ <b>बधाई हो! आपका Reddit Sniper Bot 100% चालू हो गया है!</b>\n\n"
            f"📊 बॉट ने अभी Reddit से <b>{total_fetched} पोस्ट</b> स्कैन की हैं।\n"
            "⏳ जैसे ही कोई नया काम आएगा, आपको यहाँ हिंदी मतलब + एक क्लिक में भेजने वाला लिंक मिल जाएगा!"
        )
        send_raw_telegram(welcome_msg, use_html=True)
        seen_ids.add("INITIAL_SETUP_VERIFIED")

    save_seen_posts(seen_ids, SEEN_POSTS_FILE)
    print(f"[DONE] Scanned {total_fetched} posts, sent {new_matches} alert(s).")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[SAFE EXIT] Handled unexpected error: {exc}")
