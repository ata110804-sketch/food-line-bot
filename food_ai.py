import os
import base64
import json
import time
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
    FlexMessage,
    FlexContainer,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    ImageMessageContent,
)


# =========================================================
# 基本設定
# =========================================================

app = Flask(__name__)

LINE_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

configuration = Configuration(access_token=LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
client = OpenAI(api_key=OPENAI_API_KEY)


# =========================================================
# AI 分析 Prompt
# =========================================================

FOOD_ANALYSIS_PROMPT = """
你是一位專門服務台灣使用者的 AI 飲食辨識與營養分析助手。

你的工作流程必須分成兩層：

第一層：辨識照片中的食物與料理
第二層：理解料理的常見原料、烹調方式與份量，再估算營養

不要只看顏色或形狀直接猜。

例如看到一塊肉，應綜合：
肉的形狀、纖維、油脂分布、厚度、烹調痕跡、
配菜、餐具、餐廳料理情境等判斷。

使用者主要在台灣，因此應熟悉台灣常見：
早餐店、便當、自助餐、超商、夜市、火鍋、
日式定食、韓式料理、西式餐點、健身餐等。

如果照片中的食物具有明顯特徵，
直接採用最合理答案，不要過度猶豫。

只有在真的無法合理判斷時才標示不確定。

份量估算要參考：
餐盤、碗、杯子、筷子、湯匙及其他食物比例。

不要製造假精確度。

請輸出純 JSON。
不要 Markdown。
不要 ```json。

格式必須完全符合：

{
  "meal_name": "餐點簡稱",
  "foods": [
    {
      "name": "食物名稱",
      "quantity": "約1份",
      "calories": 300,
      "protein": 20,
      "carbs": 30,
      "fat": 10,
      "fiber": 2,
      "sodium": 500
    }
  ],
  "total": {
    "calories": 500,
    "protein": 30,
    "carbs": 50,
    "fat": 20,
    "fiber": 5,
    "sodium": 1000
  },
  "confidence": "high",
  "comment": "一句自然、簡短、有朋友感的飲食評語"
}

規則：

1. calories 為 kcal
2. protein、carbs、fat、fiber 為 g
3. sodium 為 mg
4. 所有營養數值都必須是數字
5. foods 加總必須與 total 大致一致
6. comment 最多約 45 個中文字
7. comment 可以有一點朋友式吐槽，但不要羞辱使用者
8. 不要把免責聲明放進 comment
9. 不要輸出 JSON 以外的內容
"""


# =========================================================
# LINE 基礎功能
# =========================================================

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


def reply_messages(reply_token, messages):

    with ApiClient(configuration) as api_client:

        line_bot_api = MessagingApi(api_client)

        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=messages
            )
        )


def reply_text(reply_token, text):

    reply_messages(
        reply_token,
        [TextMessage(text=text)]
    )


# =========================================================
# Flex Message 工具
# =========================================================

def stat_row(icon, label, value):

    return {
        "type": "box",
        "layout": "horizontal",
        "margin": "md",
        "contents": [
            {
                "type": "text",
                "text": f"{icon} {label}",
                "size": "md",
                "color": "#555555",
                "flex": 4
            },
            {
                "type": "text",
                "text": str(value),
                "size": "md",
                "weight": "bold",
                "align": "end",
                "color": "#222222",
                "flex": 5
            }
        ]
    }


def food_row(food):

    name = food.get("name", "餐點")
    quantity = food.get("quantity", "")
    calories = round(float(food.get("calories", 0)))

    return {
        "type": "box",
        "layout": "horizontal",
        "margin": "sm",
        "contents": [
            {
                "type": "text",
                "text": f"• {name} {quantity}",
                "size": "sm",
                "color": "#555555",
                "wrap": True,
                "flex": 7
            },
            {
                "type": "text",
                "text": f"{calories} kcal",
                "size": "sm",
                "color": "#555555",
                "align": "end",
                "flex": 3
            }
        ]
    }


def build_food_flex(data, analysis_seconds):

    meal_name = data.get("meal_name", "這一餐")
    foods = data.get("foods", [])
    total = data.get("total", {})
    comment = data.get("comment", "")

    calories = round(float(total.get("calories", 0)))
    protein = round(float(total.get("protein", 0)), 1)
    carbs = round(float(total.get("carbs", 0)), 1)
    fat = round(float(total.get("fat", 0)), 1)
    fiber = round(float(total.get("fiber", 0)), 1)

    body_contents = [
        {
            "type": "text",
            "text": f"🍱 {meal_name}",
            "weight": "bold",
            "size": "xl",
            "color": "#222222",
            "wrap": True
        },
        {
            "type": "text",
            "text": f"🔥 約 {calories} kcal",
            "weight": "bold",
            "size": "xxl",
            "margin": "md",
            "color": "#333333"
        },
        {
            "type": "separator",
            "margin": "lg"
        }
    ]

    # 食物明細
    if foods:

        body_contents.append({
            "type": "text",
            "text": "這餐我抓到",
            "size": "sm",
            "weight": "bold",
            "color": "#888888",
            "margin": "lg"
        })

        for food in foods[:8]:
            body_contents.append(food_row(food))

        body_contents.append({
            "type": "separator",
            "margin": "lg"
        })

    # 營養數據
    body_contents.extend([
        stat_row("🥩", "蛋白質", f"{protein} g"),
        stat_row("🍚", "碳水", f"{carbs} g"),
        stat_row("🥑", "脂肪", f"{fat} g"),
        stat_row("🥬", "膳食纖維", f"{fiber} g"),
    ])

    # 評語
    if comment:

        body_contents.extend([
            {
                "type": "separator",
                "margin": "lg"
            },
            {
                "type": "text",
                "text": f"💬 {comment}",
                "size": "sm",
                "color": "#555555",
                "wrap": True,
                "margin": "lg"
            }
        ])

    body_contents.extend([
        {
            "type": "text",
            "text": f"⚡ 分析約 {analysis_seconds:.1f} 秒",
            "size": "xs",
            "color": "#AAAAAA",
            "margin": "lg"
        },
        {
            "type": "text",
            "text": "※ 外食份量、用油與醬料為影像估算",
            "size": "xs",
            "color": "#AAAAAA",
            "wrap": True,
            "margin": "sm"
        }
    ])

    flex_json = {
        "type": "bubble",

        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": body_contents,
            "paddingAll": "20px"
        },

        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "✏️ 修正這餐",
                        "text": "我要修正上一餐"
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "📋 今日紀錄",
                        "text": "查看今日紀錄"
                    }
                }
            ]
        }
    }

    return FlexMessage(
        alt_text=f"{meal_name}｜約 {calories} kcal",
        contents=FlexContainer.from_dict(flex_json)
    )


# =========================================================
# AI JSON 清理
# =========================================================

def parse_ai_json(text):

    text = text.strip()

    if text.startswith("```"):
        text = text.replace("```json", "")
        text = text.replace("```", "")
        text = text.strip()

    return json.loads(text)


# =========================================================
# 文字訊息
# =========================================================

@handler.add(
    MessageEvent,
    message=TextMessageContent
)
def handle_text(event):

    text = event.message.text.strip()

    if text == "我要修正上一餐":

        reply_text(
            event.reply_token,
            "✏️ 可以，直接告訴我哪裡錯。\n\n"
            "例如：\n"
            "「那是牛排不是豬排」\n"
            "「白飯只有半碗」\n"
            "「飲料是無糖豆漿」\n\n"
            "下一關我會讓我自己重新算，不准裝死 😌"
        )

        return

    if text == "查看今日紀錄":

        reply_text(
            event.reply_token,
            "📋 今日紀錄功能下一關接上。\n"
            "到時候早餐、午餐、晚餐會全部自動累計。"
        )

        return

    reply_text(
        event.reply_token,
        "🍱 我現在主要負責顧你的嘴 😂\n\n"
        "直接傳食物照片給我就好。\n"
        "我會幫你抓：\n"
        "🔥 熱量\n"
        "🥩 蛋白質\n"
        "🍚 碳水\n"
        "🥑 脂肪\n"
        "🥬 膳食纖維\n\n"
        "其他問題先放過我，我還在上班 😌"
    )


# =========================================================
# 圖片分析
# =========================================================

@handler.add(
    MessageEvent,
    message=ImageMessageContent
)
def handle_image(event):

    start_time = time.time()

    try:

        message_id = event.message.id

        # -------------------------------------------------
        # 從 LINE 下載圖片
        # -------------------------------------------------

        image_url = (
            "https://api-data.line.me/"
            f"v2/bot/message/{message_id}/content"
        )

        response = requests.get(
            image_url,
            headers={
                "Authorization":
                f"Bearer {LINE_ACCESS_TOKEN}"
            },
            timeout=20
        )

        response.raise_for_status()

        image_bytes = response.content

        content_type = response.headers.get(
            "Content-Type",
            "image/jpeg"
        )

        # -------------------------------------------------
        # Base64
        # -------------------------------------------------

        image_base64 = base64.b64encode(
            image_bytes
        ).decode("utf-8")

        data_url = (
            f"data:{content_type};base64,"
            f"{image_base64}"
        )

        # -------------------------------------------------
        # AI
        # -------------------------------------------------

        ai_start = time.time()

        ai_response = client.responses.create(
            model="gpt-5.4-mini",

            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": FOOD_ANALYSIS_PROMPT
                        },
                        {
                            "type": "input_image",
                            "image_url": data_url,
                            "detail": "high"
                        }
                    ]
                }
            ]
        )

        ai_seconds = time.time() - ai_start

        result_text = ai_response.output_text

        print(
            "AI_RAW_RESULT:",
            result_text
        )

        data = parse_ai_json(
            result_text
        )

        total_seconds = time.time() - start_time

        print(
            f"AI_TIME={ai_seconds:.2f}s "
            f"TOTAL_TIME={total_seconds:.2f}s"
        )

        # -------------------------------------------------
        # Flex Message
        # -------------------------------------------------

        flex_message = build_food_flex(
            data,
            total_seconds
        )

        reply_messages(
            event.reply_token,
            [flex_message]
        )

    except Exception as e:

        print(
            "IMAGE_ANALYSIS_ERROR:",
            repr(e)
        )

        reply_text(
            event.reply_token,
            "🥲 這張我處理到一半翻車了。\n"
            "先再傳一次給我。\n\n"
            "如果又翻，我們就去 Render 抓兇手。"
        )


# =========================================================
# 啟動
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
