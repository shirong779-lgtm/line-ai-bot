import os
import time
import hmac
import hashlib
import base64
import requests
from fastapi import FastAPI, Request, Header, HTTPException
from google import genai
from google.genai import types


app = FastAPI()


LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "").strip()
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()


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
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text[:4500]}],
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print("LINE reply error:", e)


def generate_ai_reply(user_text: str) -> str:
    # 更新為官方建議的 3.5 / 3.8 模型，並以 lite 為優先降低 503 機率
    models_to_try = [
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
    ]
    # 第一次立即嘗試，若遇 503 則等 1.5 秒再試一次，隨即切換備援模型
    retry_delays = [0, 1.5]

    for model_name in models_to_try:
        for delay in retry_delays:
            if delay > 0:
                time.sleep(delay)
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=user_text,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.9,
                    ),
                )
                text = (response.text or "").strip()
                if text:
                    return text
            except Exception as e:
                err_str = str(e)
                print(f"Gemini error ({model_name}):", err_str)
                # 遇到額度超限 (429) 或模型不存在 (404)，直接換下一個模型
                if "429" in err_str or "404" in err_str:
                    break
                # 只有遇到 503 高負載才進行同模型的延遲重試，其他錯誤直接換模型
                if "503" not in err_str and "UNAVAILABLE" not in err_str:
                    break

    return "我剛剛腦袋有點打結，晚一點再跟你好好聊～"


@app.get("/")
def health_check():
    return {"status": "ok", "message": "LINE AI bot is running"}


# 改用同步 def，讓 FastAPI 自動在背景執行緒處理阻塞的網路請求與 time.sleep
@app.post("/webhook")
def line_webhook(
    request: Request,
    x_line_signature: str = Header(default=""),
):
    body = request.stream()
    raw_body = b"".join(body)
    if not verify_signature(raw_body, x_line_signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    import json
    data = json.loads(raw_body.decode("utf-8"))
    for event in data.get("events", []):
        if event.get("type") == "message" and event.get("message", {}).get("type") == "text":
            user_text = event["message"]["text"]
            reply_token = event["replyToken"]
            reply_text = generate_ai_reply(user_text)
            reply_line_message(reply_token, reply_text)

    return {"status": "ok"}
