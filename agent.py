"""
The SDR agent loop.
Claude is the brain — picks which tools to call, in what order, until done.
"""

import os
import json
from anthropic import Anthropic
from dotenv import load_dotenv

from tools import search_web, fetch_page, score_icp_fit, draft_email, send_or_queue

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


TOOLS = [
    {
        "name": "search_web",
        "description": "Search Google for a company. Returns top 5 results with title, link, snippet. Use this FIRST to find the company's website and basic info.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query, e.g. 'Corvus Construction Houston general contractor'"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "fetch_page",
        "description": "Fetch and extract clean text from a webpage URL. Use this after search_web to read the company's homepage and learn what they do.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL to fetch, e.g. 'https://corvusconstruction.com/'"
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "score_icp_fit",
        "description": "Score a company's ICP fit for FieldOps. Pass everything you've learned about them. Returns score 0-100 and tier (HIGH/MEDIUM/LOW).",
        "input_schema": {
            "type": "object",
            "properties": {
                "company_data": {
                    "type": "object",
                    "description": "Object with keys: name, website_content, search_snippets, employee_count (if known), industry (if known)"
                }
            },
            "required": ["company_data"]
        }
    },
    {
        "name": "draft_email",
        "description": "Draft a personalized cold email. Only call AFTER scoring shows MEDIUM or HIGH tier.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company_data": {
                    "type": "object",
                    "description": "Same shape as score_icp_fit's input"
                },
                "angle": {
                    "type": "string",
                    "description": "The hook: 'paper_timecards', 'crew_size', 'growth', 'safety', or 'general'"
                }
            },
            "required": ["company_data", "angle"]
        }
    },
    {
        "name": "send_or_queue",
        "description": "Final action. Logs the email to a CSV based on decision. Always end your workflow with this tool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email_data": {
                    "type": "object",
                    "description": "Object with company, score, tier, subject, body"
                },
                "decision": {
                    "type": "string",
                    "enum": ["SEND", "QUEUE", "SKIP"],
                    "description": "SEND for HIGH tier, QUEUE for MEDIUM, SKIP for LOW (no email needed)"
                }
            },
            "required": ["email_data", "decision"]
        }
    }
]


TOOL_FUNCTIONS = {
    "search_web": search_web,
    "fetch_page": fetch_page,
    "score_icp_fit": score_icp_fit,
    "draft_email": draft_email,
    "send_or_queue": send_or_queue
}


SYSTEM_PROMPT = """You are an SDR agent for FieldOps — field service management software for US construction subcontractors (20-500 employees, replaces paper timecards).

Your job: given a company name, research them, decide if they're a fit, and either send a personalized email, queue it for review, or skip them.

WORKFLOW:
1. search_web for the company to find their website and basic info
2. fetch_page on their homepage to read what they do
3. score_icp_fit with everything you've learned
4. If score is MEDIUM or HIGH: draft_email with the best angle for them
5. Always end with send_or_queue:
   - HIGH score -> decision="SEND"
   - MEDIUM score -> decision="QUEUE"
   - LOW score -> decision="SKIP" (no email needed, just log)

Be efficient. Don't over-research. 2-4 tool calls is normal. After send_or_queue, give a brief final summary."""


def run_agent(company_name: str, max_turns: int = 10):
    """Run the agent loop on a single company."""
    print(f"\n{'='*60}")
    print(f"AGENT RUN: {company_name}")
    print(f"{'='*60}\n")
    
    messages = [
        {"role": "user", "content": f"Process this company: {company_name}"}
    ]
    
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
                print(f"[Turn {turn} - Claude]: {block.text}\n")
        
        if response.stop_reason == "end_turn":
            print(f"\nAgent finished after {turn} turns.")
            break
        
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                
                print(f"[Turn {turn} - Tool call]: {tool_name}({json.dumps(tool_input)[:200]})")
                
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


if __name__ == "__main__":
    # Subcontractor with commercial focus — should score MEDIUM/HIGH
    run_agent("Faith Technologies electrical contractor Wisconsin")