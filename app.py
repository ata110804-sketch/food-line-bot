import os
import re

from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent


app = Flask(__name__)

configuration = Configuration(
    access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
)

handler = WebhookHandler(
    os.environ["LINE_CHANNEL_SECRET"]
)


# 台灣常見食物資料庫
# 數值為常見份量的概略值：
# 熱量 kcal / 蛋白質 g / 碳水 g / 脂肪 g
FOODS = {
    "蛋餅": {
        "calories": 300,
        "protein": 10,
        "carbs": 35,
        "fat": 13,
        "unit": "1份"
    },
    "茶葉蛋": {
        "calories": 75,
        "protein": 7,
        "carbs": 1,
        "fat": 5,
        "unit": "1顆"
    },
    "水煮蛋": {
        "calories": 70,
        "protein": 6,
        "carbs": 1,
        "fat": 5,
        "unit": "1顆"
    },
    "香蕉": {
        "calories": 100,
        "protein": 1,
        "carbs": 27,
        "fat": 0,
        "unit": "1根"
    },
    "無糖豆漿": {
        "calories": 100,
        "protein": 9,
        "carbs": 8,
        "fat": 4,
        "unit": "約400ml"
    },
    "白飯": {
        "calories": 280,
        "protein": 5,
        "carbs": 62,
        "fat": 1,
        "unit": "1碗"
    },
    "雞胸肉": {
        "calories": 165,
        "protein": 31,
        "carbs": 0,
        "fat": 4,
        "unit": "100g"
    },
    "地瓜": {
        "calories": 120,
        "protein": 2,
        "carbs": 28,
        "fat": 0,
        "unit": "約150g"
    },
    "鮭魚": {
        "calories": 208,
        "protein": 20,
        "carbs": 0,
        "fat": 13,
        "unit": "100g"
    },
    "御飯糰": {
        "calories": 200,
        "protein": 5,
        "carbs": 40,
        "fat": 3,
        "unit": "1個"
    },
    "雞腿便當": {
        "calories": 700,
        "protein": 35,
        "carbs": 85,
        "fat": 25,
        "unit": "1份"
    },
    "滷肉飯": {
        "calories": 450,
        "protein": 12,
        "carbs": 65,
        "fat": 16,
        "unit": "1碗"
    },
}


@app.route("/", methods=["GET"])
def home():
    return "LINE Food Bot is running!"


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


def analyze_food(text):
    found = []

    for name, data in FOODS.items():
        if name in text:
            found.append((name, data))

    if not found:
        return (
            "🥹 我目前還不認識這個食物～\n\n"
            "目前可以辨識：\n"
            "蛋餅、茶葉蛋、水煮蛋、香蕉、無糖豆漿、"
            "白飯、雞胸肉、地瓜、鮭魚、御飯糰、"
            "雞腿便當、滷肉飯\n\n"
            "之後我們會繼續增加食物資料庫 🍱"
        )

    total_calories = 0
    total_protein = 0
    total_carbs = 0
    total_fat = 0

    lines = ["🍱 飲食分析", ""]

    for name, data in found:
        total_calories += data["calories"]
        total_protein += data["protein"]
        total_carbs += data["carbs"]
        total_fat += data["fat"]

        lines.append(
            f"• {name}（{data['unit']}）"
            f"：約 {data['calories']} kcal"
        )

    lines.extend([
        "",
        f"🔥 熱量：約 {total_calories} kcal",
        f"🥩 蛋白質：約 {total_protein} g",
        f"🍚 碳水：約 {total_carbs} g",
        f"🥑 脂肪：約 {total_fat} g",
        "",
        "📌 數值為常見份量估算，實際營養會依品牌、"
        "份量及烹調方式不同。"
    ])

    return "\n".join(lines)


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text.strip()

    result = analyze_food(user_text)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(text=result)
                ],
            )
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
