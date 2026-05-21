"""
Shifa Therapy - Therapist Sourcing Agent
=========================================
Adapted from the FieldOps SDR Agent by Abdul Moeed.

Instead of finding companies to sell to, this agent:
1. Takes a country + specialization as input
2. Searches for licensed therapists in that country
3. Scores them against Shifa's ideal therapist profile
4. Drafts a personalized recruitment email if they're a strong fit

Shifa Therapy: Global teletherapy platform operating in 20+ countries,
serving Muslim-majority, immigrant, and diaspora communities in 40+ languages.
"""

import os
import json
import csv
import requests
from datetime import datetime
from anthropic import Anthropic
from dotenv import load_dotenv
from bs4 import BeautifulSoup

load_dotenv()

SERPAPI_KEY = os.getenv("SERPAPI_KEY")
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# ─────────────────────────────────────────────
# SHIFA CONTEXT
# ─────────────────────────────────────────────

SHIFA_CONTEXT = """
Shifa Therapy is a global teletherapy platform operating in 20+ countries.
It connects licensed therapists with clients from Muslim-majority, immigrant,
and diaspora communities who want therapy in their native language and cultural context.

"Shifa" (Arabic: شفاء) means healing.

Countries served: USA, Canada, UK, Germany, France, UAE, Saudi Arabia, Egypt,
Pakistan, India, Australia, Indonesia, Malaysia, and more.

Languages supported: Arabic, Urdu, Hindi, Farsi, Turkish, French, Spanish,
Bengali, Swahili, Indonesian, Malay, and 30+ others.

Specializations in demand:
- Anxiety and depression
- Trauma / PTSD (especially EMDR-trained)
- Grief and bereavement
- Cultural identity and acculturation stress
- Faith-based / Islamically-informed therapy
- Couples and family therapy
- Life transitions and immigration stress

Therapist requirements:
- Active license (Psychologist, LPC, LCSW, Psychotherapist or equivalent)
- 2+ years clinical experience
- Fluency in at least one language beyond English
- Cultural competency with Muslim or immigrant communities
- Comfortable working remotely

Work model: fully remote, therapists set their own rates, Shifa takes a platform fee.
"""

# ─────────────────────────────────────────────
# TOOLS
# ─────────────────────────────────────────────

def search_therapists(country: str, specialization: str, language: str = "") -> dict:
    """
    Search Google for licensed therapists in a given country and specialization.
    Returns top results to feed into the scoring pipeline.
    """
    queries = [
        f'licensed therapist "{country}" {specialization} online therapy site:psychology-today.com OR site:therapist.com OR site:linkedin.com',
        f'licensed psychologist counselor "{country}" {specialization} {language} private practice',
        f'"{country}" mental health therapist {specialization} {language} bilingual online',
    ]

    all_results = []

    for query in queries[:2]:  # Use top 2 queries to stay efficient
        url = "https://serpapi.com/search"
        params = {
            "q": query,
            "api_key": SERPAPI_KEY,
            "num": 5,
            "engine": "google"
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            for item in data.get("organic_results", [])[:5]:
                all_results.append({
                    "title": item.get("title"),
                    "link": item.get("link"),
                    "snippet": item.get("snippet")
                })

        except Exception as e:
            all_results.append({"error": str(e)})

    return {
        "success": True,
        "country": country,
        "specialization": specialization,
        "language": language,
        "results": all_results
    }


def fetch_therapist_profile(url: str, max_chars: int = 3000) -> dict:
    """
    Fetch a therapist's public profile page and extract clean text.
    Works on Psychology Today, Therapist.com, LinkedIn, personal sites.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)
        text = " ".join(text.split())

        if len(text) > max_chars:
            text = text[:max_chars] + "... [truncated]"

        return {
            "success": True,
            "url": url,
            "content": text,
            "char_count": len(text)
        }

    except Exception as e:
        return {"success": False, "url": url, "error": str(e)}


def _to_text(val):
    """Coerce any value into a string."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return " ".join(_to_text(v) for v in val)
    if isinstance(val, dict):
        return " ".join(_to_text(v) for v in val.values())
    return str(val)


def score_therapist_fit(therapist_data: dict) -> dict:
    """
    Score a therapist's fit for Shifa's platform.
    Returns score 0-100 and tier: STRONG_FIT / POSSIBLE_FIT / NOT_A_FIT
    """
    score = 0
    signals = []
    red_flags = []

    text_blob = " ".join([
        _to_text(therapist_data.get("name")),
        _to_text(therapist_data.get("profile_content")),
        _to_text(therapist_data.get("search_snippets")),
        _to_text(therapist_data.get("specialization")),
        _to_text(therapist_data.get("country")),
    ]).lower()

    # ── LICENSE / CREDENTIALS (+25) ──────────────────────────────
    license_keywords = [
        "licensed psychologist", "lpc", "licensed professional counselor",
        "lcsw", "licensed clinical social worker", "psychotherapist",
        "registered psychotherapist", "chartered psychologist",
        "licensed therapist", "mft", "marriage and family therapist",
        "clinical psychologist", "counselling psychologist"
    ]
    license_hits = [kw for kw in license_keywords if kw in text_blob]
    if license_hits:
        score += 25
        signals.append(f"Licensed professional: {license_hits[:2]}")
    else:
        # Partial credit for general therapy mentions
        general_hits = [kw for kw in ["therapist", "counselor", "psychologist"] if kw in text_blob]
        if general_hits:
            score += 10
            signals.append(f"Therapy background detected: {general_hits[:2]}")

    # ── MULTILINGUAL (+25, critical for Shifa) ────────────────────
    shifa_languages = [
        "arabic", "urdu", "hindi", "farsi", "persian", "turkish",
        "french", "spanish", "bengali", "swahili", "indonesian",
        "malay", "punjabi", "pashto", "dari", "somali", "amharic"
    ]
    language_hits = [lang for lang in shifa_languages if lang in text_blob]
    if language_hits:
        score += 25
        signals.append(f"Speaks Shifa target language(s): {language_hits[:3]}")
    elif any(kw in text_blob for kw in ["bilingual", "multilingual", "fluent"]):
        score += 10
        signals.append("Bilingual/multilingual mentioned")

    # ── CULTURAL COMPETENCY (+20) ─────────────────────────────────
    cultural_keywords = [
        "muslim", "islamic", "culturally sensitive", "cultural competency",
        "immigrant", "diaspora", "multicultural", "faith-based",
        "religious", "south asian", "middle eastern", "arab",
        "acculturation", "cross-cultural"
    ]
    cultural_hits = [kw for kw in cultural_keywords if kw in text_blob]
    if cultural_hits:
        score += 20
        signals.append(f"Cultural competency signals: {cultural_hits[:3]}")

    # ── SPECIALIZATION MATCH (+15) ────────────────────────────────
    shifa_specializations = [
        "anxiety", "depression", "trauma", "ptsd", "emdr",
        "grief", "bereavement", "relationship", "couples",
        "family therapy", "cultural identity", "life transitions",
        "immigration", "faith", "religious"
    ]
    spec_hits = [kw for kw in shifa_specializations if kw in text_blob]
    if spec_hits:
        score += 15
        signals.append(f"Specialization match: {spec_hits[:4]}")

    # ── ONLINE / REMOTE THERAPY (+10) ─────────────────────────────
    online_keywords = [
        "online therapy", "telehealth", "teletherapy", "virtual therapy",
        "video sessions", "remote therapy", "online counseling"
    ]
    online_hits = [kw for kw in online_keywords if kw in text_blob]
    if online_hits:
        score += 10
        signals.append(f"Already does remote/online therapy: {online_hits[:2]}")

    # ── EXPERIENCE LEVEL (+5) ─────────────────────────────────────
    experience_keywords = ["years of experience", "years experience", "clinical experience"]
    exp_hits = [kw for kw in experience_keywords if kw in text_blob]
    if exp_hits:
        score += 5
        signals.append("Experience level mentioned")

    # ── NEGATIVE SIGNALS ──────────────────────────────────────────

    # Already on competing platforms (they may not need Shifa)
    competitor_keywords = [
        "betterhelp", "talkspace", "cerebral", "brightside",
        "monument", "headway", "alma"
    ]
    competitor_hits = [kw for kw in competitor_keywords if kw in text_blob]
    if competitor_hits:
        score -= 15
        red_flags.append(f"Already on competing platform: {competitor_hits}")

    # Not a therapist - could be a coach or unlicensed
    non_therapist_keywords = ["life coach", "wellness coach", "mindset coach", "unlicensed"]
    non_hits = [kw for kw in non_therapist_keywords if kw in text_blob]
    if non_hits and not license_hits:
        score -= 20
        red_flags.append(f"May not be licensed therapist: {non_hits}")

    # Cap at 0-100
    score = max(0, min(100, score))

    if score >= 60:
        tier = "STRONG_FIT"
        recommendation = "Great match for Shifa — send personalized recruitment outreach"
    elif score >= 35:
        tier = "POSSIBLE_FIT"
        recommendation = "Worth reaching out — queue for manual review"
    else:
        tier = "NOT_A_FIT"
        recommendation = "Skip — doesn't match Shifa's therapist profile"

    return {
        "success": True,
        "therapist": therapist_data.get("name", "Unknown"),
        "score": score,
        "tier": tier,
        "recommendation": recommendation,
        "signals": signals,
        "red_flags": red_flags
    }


def draft_recruitment_email(therapist_data: dict, angle: str = "general") -> dict:
    """
    Use Claude to draft a personalized therapist recruitment email on behalf of Shifa.
    Angles: 'multilingual', 'cultural_fit', 'flexibility', 'mission', 'general'
    """
    prompt = f"""You are writing a therapist recruitment outreach email on behalf of Shifa Therapy.

ABOUT SHIFA THERAPY:
{SHIFA_CONTEXT}

THERAPIST YOU ARE REACHING OUT TO:
- Name: {therapist_data.get("name", "Unknown")}
- Country: {therapist_data.get("country", "Unknown")}
- Specialization: {therapist_data.get("specialization", "Unknown")}
- Profile content: {str(therapist_data.get("profile_content", "N/A"))[:1200]}
- Search snippet: {str(therapist_data.get("search_snippets", "N/A"))[:400]}

ANGLE: {angle}

WRITE A RECRUITMENT EMAIL THAT:
- Is under 100 words
- Opens with one specific and genuine observation about THEIR background or work
- Explains why they are a natural fit for Shifa's mission specifically
- Makes the opportunity feel exciting, not transactional (remote, flexible, mission-driven)
- Ends with a soft low-commitment CTA — a question or an invite to learn more
- Sounds human and warm, not like a mass template
- Does NOT use corporate buzzwords or generic flattery

OUTPUT FORMAT — return JSON only, no other text:
{{"subject": "...", "body": "..."}}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )

        raw_text = response.content[0].text.strip()

        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        email = json.loads(raw_text)

        return {
            "success": True,
            "therapist": therapist_data.get("name", "Unknown"),
            "angle": angle,
            "subject": email.get("subject"),
            "body": email.get("body"),
            "tokens": {
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens
            }
        }

    except json.JSONDecodeError:
        return {"success": False, "error": f"Claude returned non-JSON: {raw_text[:200]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def log_therapist(therapist_data: dict, decision: str) -> dict:
    """
    Log the therapist and outreach decision to a CSV file.
    decision: OUTREACH | REVIEW | SKIP
    """
    timestamp = datetime.now().isoformat()

    row = {
        "timestamp": timestamp,
        "therapist": therapist_data.get("name", "Unknown"),
        "country": therapist_data.get("country", "Unknown"),
        "specialization": therapist_data.get("specialization", "Unknown"),
        "score": therapist_data.get("score", 0),
        "tier": therapist_data.get("tier", "UNKNOWN"),
        "decision": decision,
        "subject": therapist_data.get("subject", ""),
        "body": therapist_data.get("body", "")
    }

    filename_map = {
        "OUTREACH": "shifa_outreach_queue.csv",
        "REVIEW": "shifa_review_queue.csv",
        "SKIP": "shifa_skipped.csv"
    }

    filename = filename_map.get(decision)
    if not filename:
        return {"success": False, "error": f"Invalid decision: {decision}"}

    file_exists = os.path.exists(filename)

    try:
        with open(filename, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)

        return {
            "success": True,
            "therapist": row["therapist"],
            "decision": decision,
            "logged_to": filename
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
# TOOL DEFINITIONS FOR CLAUDE
# ─────────────────────────────────────────────

TOOLS = [
    {
        "name": "search_therapists",
        "description": "Search Google for licensed therapists in a given country and specialization. Use this FIRST to find candidate therapist profiles.",
        "input_schema": {
            "type": "object",
            "properties": {
                "country": {
                    "type": "string",
                    "description": "Country to search in, e.g. 'Pakistan', 'United Kingdom', 'Egypt'"
                },
                "specialization": {
                    "type": "string",
                    "description": "Therapy specialization to target, e.g. 'trauma', 'anxiety', 'couples therapy'"
                },
                "language": {
                    "type": "string",
                    "description": "Optional: target language beyond English, e.g. 'Urdu', 'Arabic', 'French'"
                }
            },
            "required": ["country", "specialization"]
        }
    },
    {
        "name": "fetch_therapist_profile",
        "description": "Fetch and extract clean text from a therapist's public profile page. Use after search_therapists to learn more about a specific candidate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL of the therapist profile to fetch"
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "score_therapist_fit",
        "description": "Score a therapist's fit for Shifa's platform based on their license, languages, cultural competency, and specializations. Pass everything you've learned about them.",
        "input_schema": {
            "type": "object",
            "properties": {
                "therapist_data": {
                    "type": "object",
                    "description": "Object with keys: name, country, specialization, profile_content, search_snippets"
                }
            },
            "required": ["therapist_data"]
        }
    },
    {
        "name": "draft_recruitment_email",
        "description": "Draft a personalized recruitment email to invite a therapist to join Shifa. Only call after scoring shows POSSIBLE_FIT or STRONG_FIT.",
        "input_schema": {
            "type": "object",
            "properties": {
                "therapist_data": {
                    "type": "object",
                    "description": "Same shape as score_therapist_fit input, enriched with score and tier"
                },
                "angle": {
                    "type": "string",
                    "description": "The hook: 'multilingual', 'cultural_fit', 'flexibility', 'mission', or 'general'",
                    "enum": ["multilingual", "cultural_fit", "flexibility", "mission", "general"]
                }
            },
            "required": ["therapist_data", "angle"]
        }
    },
    {
        "name": "log_therapist",
        "description": "Final action. Log the therapist and outreach decision to a CSV file. Always call this last.",
        "input_schema": {
            "type": "object",
            "properties": {
                "therapist_data": {
                    "type": "object",
                    "description": "Object with therapist name, country, specialization, score, tier, subject, body"
                },
                "decision": {
                    "type": "string",
                    "enum": ["OUTREACH", "REVIEW", "SKIP"],
                    "description": "OUTREACH for STRONG_FIT, REVIEW for POSSIBLE_FIT, SKIP for NOT_A_FIT"
                }
            },
            "required": ["therapist_data", "decision"]
        }
    }
]

TOOL_FUNCTIONS = {
    "search_therapists": search_therapists,
    "fetch_therapist_profile": fetch_therapist_profile,
    "score_therapist_fit": score_therapist_fit,
    "draft_recruitment_email": draft_recruitment_email,
    "log_therapist": log_therapist
}

# ─────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are a therapist sourcing agent for Shifa Therapy.

{SHIFA_CONTEXT}

YOUR JOB: Given a country and a therapy specialization, find licensed therapists
who are a strong fit for Shifa's platform and send them a personalized recruitment email.

WORKFLOW:
1. search_therapists using the country + specialization (+ language if provided)
2. fetch_therapist_profile on the most promising 1-2 results to learn more
3. score_therapist_fit with everything you've learned about the best candidate
4. If tier is POSSIBLE_FIT or STRONG_FIT: draft_recruitment_email with the best angle:
   - Use 'multilingual' if they speak a Shifa target language
   - Use 'cultural_fit' if they have Muslim/immigrant community experience
   - Use 'flexibility' if they mention work-life balance or private practice
   - Use 'mission' if they express strong values around access to mental health
   - Use 'general' if no strong signal
5. Always end with log_therapist:
   - STRONG_FIT -> OUTREACH
   - POSSIBLE_FIT -> REVIEW
   - NOT_A_FIT -> SKIP

Be efficient. 3-5 tool calls is normal. After log_therapist, give a clear final summary
of who you found, their score, and the email drafted (if any)."""


# ─────────────────────────────────────────────
# AGENT LOOP
# ─────────────────────────────────────────────

def run_shifa_agent(country: str, specialization: str, language: str = "", max_turns: int = 10):
    """
    Run the Shifa therapist sourcing agent.

    Args:
        country: Country to search in (e.g. 'Pakistan', 'United Kingdom')
        specialization: Therapy specialization (e.g. 'trauma', 'anxiety')
        language: Optional target language (e.g. 'Urdu', 'Arabic')
    """
    print(f"\n{'='*60}")
    print(f"SHIFA SOURCING AGENT")
    print(f"Country: {country} | Specialization: {specialization}" + (f" | Language: {language}" if language else ""))
    print(f"{'='*60}\n")

    user_message = f"Find a licensed therapist in {country} who specializes in {specialization}"
    if language:
        user_message += f" and speaks {language}"
    user_message += ". Score them and draft a recruitment email if they're a fit for Shifa."

    messages = [{"role": "user", "content": user_message}]

    turn = 0
    while turn < max_turns:
        turn += 1

        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages
        )

        for block in response.content:
            if block.type == "text" and block.text.strip():
                print(f"[Turn {turn} - Agent]: {block.text}\n")

        if response.stop_reason == "end_turn":
            print(f"\nAgent finished after {turn} turns.")
            break

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input

                print(f"[Turn {turn} - Tool]: {tool_name}({json.dumps(tool_input)[:200]})")

                fn = TOOL_FUNCTIONS[tool_name]
                result = fn(**tool_input)

                print(f"[Turn {turn} - Result]: {json.dumps(result)[:300]}\n")

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result)
                })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    print(f"\n{'='*60}\n")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # Demo: Find a trauma therapist in Pakistan who speaks Urdu
    # This is the kind of search Shifa needs most — underserved markets
    run_shifa_agent(
        country="Pakistan",
        specialization="trauma",
        language="Urdu"
    )
