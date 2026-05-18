"""
Tools the SDR agent can call.
"""

import os
import json
import requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup

load_dotenv()

SERPAPI_KEY = os.getenv("SERPAPI_KEY")


def search_web(query: str, num_results: int = 5) -> dict:
    """Search Google via SerpApi. Returns top organic results."""
    url = "https://serpapi.com/search"
    params = {
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": num_results,
        "engine": "google"
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get("organic_results", [])[:num_results]:
            results.append({
                "title": item.get("title"),
                "link": item.get("link"),
                "snippet": item.get("snippet")
            })

        return {"success": True, "query": query, "results": results}

    except Exception as e:
        return {"success": False, "error": str(e)}


def fetch_page(url: str, max_chars: int = 3000) -> dict:
    """Fetch a webpage and extract clean text content."""
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
    """Coerce any value into a string. Handles strings, lists, dicts, None."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return " ".join(_to_text(v) for v in val)
    if isinstance(val, dict):
        return " ".join(_to_text(v) for v in val.values())
    return str(val)


def score_icp_fit(company_data: dict) -> dict:
    """Score a company's ICP fit for FieldOps."""
    score = 0
    signals = []
    red_flags = []

    text_blob = " ".join([
        _to_text(company_data.get("name")),
        _to_text(company_data.get("website_content")),
        _to_text(company_data.get("search_snippets")),
        _to_text(company_data.get("industry"))
    ]).lower()

    # --- TRADE / INDUSTRY (max +25) ---
    trade_keywords = [
        "subcontractor", "subcontracting", "electrical contractor",
        "mechanical contractor", "plumbing contractor", "hvac contractor",
        "roofing contractor", "concrete contractor", "framing contractor",
        "drywall contractor", "specialty contractor", "trade contractor"
    ]
    trade_hits = [kw for kw in trade_keywords if kw in text_blob]
    if trade_hits:
        score += 25
        signals.append(f"Specialty/subcontractor match: {trade_hits[:3]}")
    else:
        # Fallback: generic construction match (lower weight)
        construction_keywords = [
            "construction", "contractor", "builder", "electrical",
            "plumbing", "hvac", "roofing", "concrete", "framing"
        ]
        construction_hits = [kw for kw in construction_keywords if kw in text_blob]
        if construction_hits:
            score += 15
            signals.append(f"Construction industry match: {construction_hits[:3]}")

    # --- COMMERCIAL FOCUS (+15) ---
    commercial_keywords = [
        "commercial", "industrial", "design-build", "design build",
        "general contractor", "construction management"
    ]
    commercial_hits = [kw for kw in commercial_keywords if kw in text_blob]
    if commercial_hits:
        score += 15
        signals.append(f"Commercial/industrial focus: {commercial_hits[:2]}")

    # --- FIELD OPERATIONS (+20) ---
    field_keywords = [
        "crew", "field", "jobsite", "job site", "on-site", "onsite",
        "technician", "service call", "field service", "field team",
        "project site", "labor", "fleet"
    ]
    field_hits = [kw for kw in field_keywords if kw in text_blob]
    if field_hits:
        score += 20
        signals.append(f"Field operations: {field_hits[:3]}")

    # --- SCALE INDICATORS (+15) ---
    scale_keywords = [
        "multiple crews", "multiple projects", "multi-site", "project management",
        "estimating", "scheduling", "dispatch", "payroll", "timesheet", "timecard"
    ]
    scale_hits = [kw for kw in scale_keywords if kw in text_blob]
    if scale_hits:
        score += 15
        signals.append(f"Scale operations: {scale_hits[:3]}")

    # --- HIGH-INTENT PAIN SIGNALS (+25, big jump) ---
    paper_keywords = [
        "paper timecard", "paper timesheets", "manual scheduling",
        "spreadsheet", "excel", "quickbooks"
    ]
    paper_hits = [kw for kw in paper_keywords if kw in text_blob]
    if paper_hits:
        score += 25
        signals.append(f"Manual processes (high-intent): {paper_hits}")

    # --- EMPLOYEE COUNT (+20 if in range) ---
    emp = company_data.get("employee_count")
    if emp:
        try:
            emp = int(emp)
            if 20 <= emp <= 500:
                score += 20
                signals.append(f"Employee count in ICP range: {emp}")
            elif emp < 20:
                red_flags.append(f"Too small: {emp} employees")
                score -= 10
            elif emp > 500:
                red_flags.append(f"Too large: {emp} employees")
                score -= 5
        except (ValueError, TypeError):
            pass

    # --- NEGATIVE SIGNALS ---
    
    # Residential-only = wrong ICP for FieldOps
    residential_only_keywords = [
        "residential electrician", "home repair", "homeowner",
        "house calls", "appointment-based"
    ]
    residential_hits = [kw for kw in residential_only_keywords if kw in text_blob]
    if residential_hits and not commercial_hits:
        score -= 25
        red_flags.append(f"Residential-only focus: {residential_hits[:2]}")

    # Already using competing FSM software
    competitor_keywords = [
        "servicetitan", "service titan", "jobber", "housecall pro",
        "fieldedge", "buildertrend", "procore", "fieldwire"
    ]
    competitor_hits = [kw for kw in competitor_keywords if kw in text_blob]
    if competitor_hits:
        score -= 30
        red_flags.append(f"Already uses FSM software: {competitor_hits}")

    # Cap at 0-100
    score = max(0, min(100, score))

    # Tuned thresholds for realistic data
    if score >= 60:
        tier = "HIGH"
        recommendation = "Strong fit — send personalized outreach"
    elif score >= 35:
        tier = "MEDIUM"
        recommendation = "Worth a touch — queue for review"
    else:
        tier = "LOW"
        recommendation = "Skip — not a fit"

    return {
        "success": True,
        "company": company_data.get("name", "Unknown"),
        "score": score,
        "tier": tier,
        "recommendation": recommendation,
        "signals": signals,
        "red_flags": red_flags
    }

def draft_email(company_data: dict, angle: str = "general") -> dict:
    """Use Claude to draft a personalized cold email."""
    from anthropic import Anthropic

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    product_context = """
You're writing on behalf of FieldOps — field service management software for construction subcontractors.
Replaces paper timecards, GPS-tracks crews, syncs labor data to QuickBooks.
ICP: US construction companies, 20-500 employees, currently using paper timecards or spreadsheets.
Key benefits: cuts payroll prep time by 70%, eliminates timecard disputes, gives owners real-time crew location.
"""

    prompt = f"""You are an expert B2B SDR writing a cold email to a construction company.

PRODUCT YOU'RE SELLING:
{product_context}

PROSPECT COMPANY DATA:
- Name: {company_data.get('name', 'Unknown')}
- Website content: {str(company_data.get('website_content', 'N/A'))[:1500]}
- Search snippets: {str(company_data.get('search_snippets', 'N/A'))[:500]}
- Employee count: {company_data.get('employee_count', 'Unknown')}

ANGLE: {angle}

WRITE A COLD EMAIL THAT:
- Is under 90 words total
- Opens with one specific observation about THEIR company (not generic)
- Names a pain point construction firms their size face
- Makes ONE concrete claim about FieldOps with a number
- Ends with a soft CTA — a question, not a meeting ask
- No corporate fluff
- Sounds like a human, not a template

OUTPUT FORMAT — return JSON only, no other text:
{{"subject": "...", "body": "..."}}
"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=400,
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
            "company": company_data.get("name", "Unknown"),
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


def send_or_queue(email_data: dict, decision: str, send_for_real: bool = False) -> dict:
    """Final action tool. Logs the email to a CSV based on decision."""
    import csv
    from datetime import datetime

    timestamp = datetime.now().isoformat()

    row = {
        "timestamp": timestamp,
        "company": email_data.get("company", "Unknown"),
        "score": email_data.get("score", 0),
        "tier": email_data.get("tier", "UNKNOWN"),
        "decision": decision,
        "subject": email_data.get("subject", ""),
        "body": email_data.get("body", "")
    }

    if decision == "SEND":
        filename = "sent_log.csv"
    elif decision == "QUEUE":
        filename = "review_queue.csv"
    elif decision == "SKIP":
        filename = "skipped_log.csv"
    else:
        return {"success": False, "error": f"Invalid decision: {decision}"}

    file_exists = os.path.exists(filename)

    try:
        with open(filename, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)

        gmail_status = "not_sent (demo mode)"
        if decision == "SEND" and send_for_real:
            gmail_status = "would_send_in_production"

        return {
            "success": True,
            "company": row["company"],
            "decision": decision,
            "logged_to": filename,
            "gmail_status": gmail_status
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    print("Running quick sanity test on score_icp_fit + draft_email...\n")
    test_company = {
        "name": "Corvus Construction",
        "website_content": "Family-owned general contractor in Houston. 28 years.",
        "search_snippets": ["Houston construction", "general contractor"],
        "employee_count": 75
    }
    print(json.dumps(score_icp_fit(test_company), indent=2))