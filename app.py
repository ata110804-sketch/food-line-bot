import os
import base64
import requests

from flask import Flask, request, abort
from openai import OpenAI

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    ImageMessageContent,
)


app = Flask(__name__)

# ===== LINE 設定 =====
LINE_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]

configuration = Configuration(
    access_token=LINE_ACCESS_TOKEN
)

handler = WebhookHandler(
    LINE_CHANNEL_SECRET
)

# ===== OpenAI 設定 =====
client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"]
)


@app.route("/", methods=["GET"])
def home():
    return "LINE Food AI Bot is running!"


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


def reply_text(reply_token, text):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[
                    TextMessage(text=text)
                ],
            )
        )


# ===== 收到文字 =====
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event):

    reply_text(
        event.reply_token,
        "🍱 快點傳給我你今天吃了啥!！\n\n"
        "直接傳一張餐點照片給我 📷\n"
        "我會幫你辨識食物並估算營養。"
    )


# ===== 收到圖片 =====
@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):

    try:
        # 取得 LINE 使用者傳來的圖片
        message_id = event.message.id

        image_url = (
            f"https://api-data.line.me/"
            f"v2/bot/message/{message_id}/content"
        )

        response = requests.get(
            image_url,
            headers={
                "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
            },
            timeout=30,
        )

        response.raise_for_status()

        image_bytes = response.content
        content_type = response.headers.get(
            "Content-Type",
            "image/jpeg"
        )

        # 轉成 OpenAI 可以讀取的 base64 圖片
        image_base64 = base64.b64encode(
            image_bytes
        ).decode("utf-8")

        data_url = (
            f"data:{content_type};base64,"
            f"{image_base64}"
        )

        # ===== AI 分析 =====
        ai_response = client.responses.create(
            model="gpt-5.6-luna",
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": """
你是一位台灣飲食營養紀錄助手。

請分析這張餐點照片。

請：
1. 判斷照片中有哪些食物。
2. 估計每種食物的份量。
3. 估算每種食物的熱量。
4. 估算整餐的：
   - 總熱量 kcal
   - 蛋白質 g
   - 碳水化合物 g
   - 脂肪 g
5. 如果無法從照片確定重量、醬料、
   烹調油或內餡，請清楚說明是估算值。
6. 使用繁體中文。
7. 回覆要適合直接顯示在 LINE，
   簡潔、好閱讀。

格式：

🍱 AI 餐點分析

【辨識到的食物】
• 食物：估計份量｜約 xxx kcal
• 食物：估計份量｜約 xxx kcal

🔥 總熱量：約 xxx kcal
🥩 蛋白質：約 xx g
🍚 碳水：約 xx g
🥑 脂肪：約 xx g

💡 簡短飲食建議：
一句話即可。

⚠️ 照片分析為估算值，實際營養會受到
份量、調味與烹調方式影響。
"""
                        },
                        {
                            "type": "input_image",
                            "image_url": data_url,
                            "detail": "low",
                        },
                    ],
                }
            ],
        )

        result = ai_response.output_text

        reply_text(
            event.reply_token,
            result
        )

    except Exception as e:

        print("IMAGE ANALYSIS ERROR:", repr(e))

        reply_text(
            event.reply_token,
            "🥲 這張照片目前分析失敗了。\n"
            "請稍後再傳一次，我會再試試看！"
        )


if __name__ == "__main__":
    port = int(
        os.environ.get("PORT", 5000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
