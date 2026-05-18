# AI SDR Agent

An autonomous SDR agent for **FieldOps** (a hypothetical field service management SaaS for construction subcontractors). Given a company name, the agent researches them, scores their ICP fit, drafts a personalized cold email, and routes it to send, review, or skip.

**Built with:** Python, Anthropic Claude API (tool use), SerpApi, BeautifulSoup

---

## What makes this an agent (not just automation)

Most "AI outbound" tools are sequential pipelines:

This is **not** that. Here, Claude is the brain. It's given 5 tools and decides which one to call next based on what it just learned. The Python code is the runtime; the LLM is the control flow.

In a real run against Faith Technologies, the `fetch_page` tool failed with a DNS error. A scripted pipeline would have crashed. The agent looked at the search snippets it already had, decided that was enough context, and continued to scoring + drafting. **That's the difference.**

---
[ run_agent() ]                         <- Python loop, calls Claude until done
       |
       v
[ Claude (haiku-4-5) + 5 tools ]        <- LLM decides which tool to call next
       |
       v
[ Tool execution in Python ]
   1. search_web      -> SerpApi
   2. fetch_page      -> requests + BeautifulSoup
   3. score_icp_fit   -> rules engine
   4. draft_email     -> Claude (nested LLM call)
   5. send_or_queue   -> CSV (+ optional Gmail SMTP)

---

## The 5 Tools

| Tool | Purpose | Tech |
|---|---|---|
| `search_web` | Google search for the company | SerpApi |
| `fetch_page` | Extract clean text from their homepage | `requests` + `BeautifulSoup` |
| `score_icp_fit` | Score 0–100 against FieldOps ICP | Pure Python rules engine |
| `draft_email` | Generate personalized cold email | Claude Haiku 4.5 |
| `send_or_queue` | Route based on decision | CSV (+ optional Gmail SMTP) |

---

## ICP scoring logic

FieldOps targets US construction **subcontractors**, 20–500 employees, currently using paper timecards or spreadsheets.

The scorer rewards:
- Specialty/trade contractor keywords (+25)
- Commercial/industrial focus (+15)
- Field operations language: crews, jobsites, dispatch (+20)
- Scale indicators: payroll, timesheets, multi-site (+15)
- High-intent pain signals: "paper timecards," "spreadsheets," "QuickBooks" (+25)
- Employee count in 20–500 range (+20)

And penalizes:
- Residential-only focus (–25)
- Already using competing FSM software (ServiceTitan, Jobber, etc.) (–30)

**Tier thresholds:** HIGH ≥ 60, MEDIUM ≥ 35, else LOW.

---

## Real test results

Tested against 3 companies during development:

| Company | Type | Score | Tier | Decision |
|---|---|---|---|---|
| Corvus Construction | General contractor (Houston) | 30 | LOW | SKIP |
| Mister Sparky | Residential electrician | 30 | LOW | SKIP |
| Faith Technologies | Commercial electrical subcontractor (national) | 55 | MEDIUM | QUEUE |

**Why this matters:** the agent correctly distinguished a general contractor from a subcontractor, and a residential trades business from a commercial subcontractor — *despite the surface keywords being similar*. Both are "electrical contractors" in plain language; only one is the ICP.

The drafted email for Faith Technologies (preserved in `review_queue.csv`) opened with their multi-state industrial project work and pitched payroll time savings with a concrete 70% claim. Under 90 words, no template-y fluff.

---

## Files

Note: `review_queue.csv` includes one row from an early manual test of `send_or_queue`. The remaining rows are from live agent runs.

---

## Run it

```bash
# Setup
python -m venv venv
.\venv\Scripts\Activate.ps1   # Windows
pip install anthropic python-dotenv requests beautifulsoup4

# Set your keys in .env
ANTHROPIC_API_KEY=sk-ant-...
SERPAPI_KEY=...

# Test API connectivity
python test_api.py

# Run the agent on a company
python agent.py
```

Change the company name in `agent.py`'s `if __name__ == "__main__":` block to process a different target.

---

## Cost

Per agent run (Haiku 4.5, 4–6 tool calls): **~$0.01–0.02**

At scale: a list of 1,000 prospects costs ~$15 to process end-to-end. A human SDR at $25/hr taking 5 minutes per prospect would cost $2,083 for the same list.

---

## What's next

- **Enrichment tool** — add Apollo or Clay lookup for verified employee count, tech stack, decision-maker contact
- **Multi-channel routing** — route MEDIUM tier to LinkedIn auto-connect instead of email
- **Reply handling** — second agent that triages replies and schedules meetings
- **Batch mode** — feed in Project 2's `construction_companies.csv` and run the agent across all 60 leads

---

## Project context

Part of a GTM Engineering portfolio. Companion to:
- **[Construction Company Scraper](https://github.com/moeedabdul00988-tech/construction-scraper)** — the data source this agent could be pointed at
- **Outbound automation pipeline** — Make → HubSpot → Gmail (Project 1)