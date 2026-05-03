import base64
import anthropic
from capture import screenshot
from config import ANTHROPIC_API_KEY

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

print("capturing screen...")
img_bytes = screenshot()
img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")

print("sending to claude...")
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": img_b64,
                    },
                },
                {
                    "type": "text",
                    "text": "describe what you see on this screen",
                },
            ],
        }
    ],
)

print("\n--- response ---")
print(response.content[0].text)
