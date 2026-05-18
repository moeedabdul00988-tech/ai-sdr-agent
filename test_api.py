import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

response = client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=100,
    messages=[
        {"role": "user", "content": "Say 'API works' and nothing else."}
    ]
)

print(response.content[0].text)
print(f"\nTokens used: {response.usage.input_tokens} in, {response.usage.output_tokens} out")