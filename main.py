import os
import hmac
import hashlib
import base64
import requests
from fastapi import FastAPI, Request, Header, HTTPException
from google import genai


app = FastAPI()


LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


client = genai.Client(api_key=GEMINI_API_KEY)


SYSTEM_PROMPT = """
你是一個溫暖、自然、有生活感的聊天夥伴，不是制式的客服或冰冷的機器人。
回覆規則：
1. 像朋友傳 LINE 一樣說話，語氣輕鬆自然、簡短親切，不要長篇大論或列點說教。
2. 不要主動自稱「我是 AI」或「身為一個人工智慧」。
3. 順著對方的情緒與話題接話，偶爾可以自然反問一句，但不要像身家調查。
"""




def verify_signature(body: bytes, signature: str) -> bool:
    if not LINE_CHANNEL_SECRET or not signature:
        return False
    mac = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature)




def reply_line_message(reply_token: str, text: str):
    url = "https://api.line.biz/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text[:4500]}],
    }
    requests.post(url, headers=headers, json=payload, timeout=15)




@app.get("/")
def health_check():
    return {"status": "ok", "message": "LINE AI bot is running"}




@app.post("/webhook")
async def line_webhook(
    request: Request,
    x_line_signature: str = Header(default=""),
):
    body = await request.body()
    if not verify_signature(body, x_line_signature):
        raise HTTPException(status_code=400, detail="Invalid signature")


    data = await request.json()
    for event in data.get("events", []):
        if event.get("type") == "message" and event.get("message", {}).get("type") == "text":
            user_text = event["message"]["text"]
            reply_token = event["replyToken"]


            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=user_text,
                    config={
                        "system_instruction": SYSTEM_PROMPT,
                        "temperature": 0.9,
                    },
                )
                reply_text = (response.text or "我剛剛恍神了一下，可以再跟我說一次嗎？").strip()
            except Exception as e:
                print("Gemini error:", e)
                reply_text = "我剛剛腦袋有點打結，晚一點再跟你好好聊～"


            reply_line_message(reply_token, reply_text)


    return {"status": "ok"}
