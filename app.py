import os
import requests
import time

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

from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    ImageMessageContent,
)

# 我們剛剛做好的三層 AI
from food_ai import (
    recognize_foods,
    understand_recipes,
    estimate_nutrition,
)


# =========================================================
# 基本設定
# =========================================================

app = Flask(__name__)

LINE_ACCESS_TOKEN = os.environ[
    "LINE_CHANNEL_ACCESS_TOKEN"
]

LINE_CHANNEL_SECRET = os.environ[
    "LINE_CHANNEL_SECRET"
]

configuration = Configuration(
    access_token=LINE_ACCESS_TOKEN
)

handler = WebhookHandler(
    LINE_CHANNEL_SECRET
)


# =========================================================
# 網站首頁
# =========================================================

@app.route("/", methods=["GET"])
def home():
    return "LINE Food AI V3 is running!"


# =========================================================
# LINE Webhook
# =========================================================

@app.route("/callback", methods=["POST"])
def callback():

    signature = request.headers.get(
        "X-Line-Signature",
        ""
    )

    body = request.get_data(
        as_text=True
    )

    try:
        handler.handle(
            body,
            signature
        )

    except InvalidSignatureError:
        abort(400)

    return "OK"


# =========================================================
# LINE 回覆
# =========================================================

def reply_text(
    reply_token,
    text
):

    with ApiClient(
        configuration
    ) as api_client:

        line_bot_api = MessagingApi(
            api_client
        )

        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[
                    TextMessage(
                        text=text
                    )
                ]
            )
        )


# =========================================================
# LINE 圖片下載
# =========================================================

def download_line_image(
    message_id
):

    image_url = (
        "https://api-data.line.me/"
        f"v2/bot/message/"
        f"{message_id}/content"
    )

    response = requests.get(
        image_url,
        headers={
            "Authorization":
            f"Bearer {LINE_ACCESS_TOKEN}"
        },
        timeout=30
    )

    response.raise_for_status()

    image_bytes = response.content

    content_type = response.headers.get(
        "Content-Type",
        "image/jpeg"
    )

    return (
        image_bytes,
        content_type
    )


# =========================================================
# 數字顯示
# 31.0 → 31
# 31.6 → 31.6
# =========================================================

def pretty_number(value):

    if value is None:
        return "-"

    value = float(value)

    if value.is_integer():
        return str(
            int(value)
        )

    return str(
        round(value, 1)
    )


# =========================================================
# 食物 Emoji
# =========================================================

def food_emoji(name):

    rules = [
        (
            ["蛋"],
            "🥚"
        ),
        (
            ["雞", "豬", "牛", "排骨"],
            "🥩"
        ),
        (
            ["魚", "鮭", "鯖", "蝦"],
            "🐟"
        ),
        (
            ["飯", "米"],
            "🍚"
        ),
        (
            ["麵"],
            "🍜"
        ),
        (
            ["地瓜", "馬鈴薯"],
            "🍠"
        ),
        (
            ["玉米"],
            "🌽"
        ),
        (
            [
                "菜",
                "花椰",
                "菠菜",
                "高麗",
                "青江"
            ],
            "🥬"
        ),
        (
            ["豆漿", "牛奶", "鮮奶"],
            "🥛"
        ),
        (
            ["咖啡", "拿鐵"],
            "☕"
        ),
        (
            ["茶", "飲料"],
            "🧋"
        ),
        (
            ["香蕉"],
            "🍌"
        ),
        (
            ["蘋果"],
            "🍎"
        ),
    ]

    for keywords, emoji in rules:

        for keyword in keywords:

            if keyword in name:
                return emoji

    return "🍴"


# =========================================================
# 組成 LINE 顯示文字
# =========================================================

def build_meal_message(
    vision_data,
    nutrition_data,
    elapsed_seconds
):

    foods = nutrition_data.get(
        "food_items",
        []
    )

    totals = nutrition_data.get(
        "totals",
        {}
    )

    lines = [
        "🍱 好，這餐我抓到了！",
        ""
    ]

    # ---------------------------------------------
    # 每項食物
    # ---------------------------------------------

    for food in foods:

        name = food.get(
            "name",
            "食物"
        )

        quantity = pretty_number(
            food.get(
                "quantity",
                1
            )
        )

        unit = food.get(
            "unit",
            "份"
        )

        calories = round(
            food.get(
                "calories",
                0
            )
        )

        emoji = food_emoji(
            name
        )

        lines.append(
            f"{emoji} {name} × "
            f"{quantity}{unit}"
            f"｜約 {calories} kcal"
        )

    # ---------------------------------------------
    # 總營養
    # ---------------------------------------------

    lines.extend([
        "",
        "━━━━━━━━━━━━",
        "",
        (
            "🔥 約 "
            f"{round(totals.get('calories', 0))} kcal"
        ),
        (
            "🥩 蛋白質 "
            f"{pretty_number(totals.get('protein_g', 0))} g"
        ),
        (
            "🍚 碳水 "
            f"{pretty_number(totals.get('carbohydrate_g', 0))} g"
        ),
        (
            "🥑 脂肪 "
            f"{pretty_number(totals.get('fat_g', 0))} g"
        ),
        (
            "🥬 纖維 "
            f"{pretty_number(totals.get('fiber_g', 0))} g"
        ),
        (
            "🧂 鈉 "
            f"{pretty_number(totals.get('sodium_mg', 0))} mg"
        ),
    ])

    # ---------------------------------------------
    # 估算可信度
    # ---------------------------------------------

    confidence = nutrition_data.get(
        "overall_nutrition_confidence",
        0
    )

    if confidence >= 0.85:

        confidence_text = (
            "這餐辨識得滿穩的 👌"
        )

    elif confidence >= 0.70:

        confidence_text = (
            "這餐大致抓得到，"
            "份量可能有些誤差。"
        )

    else:

        confidence_text = (
            "這餐有些地方比較難估，"
            "數字先當範圍參考。"
        )

    lines.extend([
        "",
        f"👀 {confidence_text}"
    ])

    # ---------------------------------------------
    # 真的需要確認才問
    # ---------------------------------------------

    if vision_data.get(
        "needs_confirmation",
        False
    ):

        question = vision_data.get(
            "confirmation_question"
        )

        if question:

            lines.extend([
                "",
                "🤔 但有一個地方我要問一下：",
                question
            ])

    # ---------------------------------------------
    # 暫時顯示處理速度
    # 測試階段才留著
    # ---------------------------------------------

    lines.extend([
        "",
        (
            "⚡ 分析時間："
            f"{elapsed_seconds:.1f} 秒"
        ),
        "",
        (
            "⚠️ 外食照片的份量、用油與醬料"
            "無法完全從影像得知，營養為估算值。"
        )
    ])

    return "\n".join(
        lines
    )


# =========================================================
# 文字訊息
# =========================================================

@handler.add(
    MessageEvent,
    message=TextMessageContent
)
def handle_text(event):

    user_text = (
        event.message.text
        or ""
    ).strip()

    # V3 目前先測照片
    reply_text(
        event.reply_token,
        "👀 我現在正在測試新版食物辨識！\n\n"
        "直接丟餐點照片給我 📷\n"
        "我會先認食物 → 理解料理 → "
        "再估營養。\n\n"
        "先把我的眼睛練好，等等再讓我陪你嘴砲 😂"
    )


# =========================================================
# 圖片訊息
# =========================================================

@handler.add(
    MessageEvent,
    message=ImageMessageContent
)
def handle_image(event):

    start_time = time.time()

    try:

        # ---------------------------------------------
        # 1. LINE 下載照片
        # ---------------------------------------------

        image_bytes, content_type = (
            download_line_image(
                event.message.id
            )
        )

        print(
            "IMAGE_DOWNLOADED",
            len(image_bytes),
            content_type
        )

        # ---------------------------------------------
        # 2. 第一層：視覺辨識
        # ---------------------------------------------

        vision_data = recognize_foods(
            image_bytes,
            content_type
        )

        print(
            "VISION_RESULT:",
            vision_data
        )

        # ---------------------------------------------
        # 3. 第二層：料理理解
        # ---------------------------------------------

        recipe_data = understand_recipes(
            vision_data
        )

        print(
            "RECIPE_RESULT:",
            recipe_data
        )

        # ---------------------------------------------
        # 4. 第三層：營養估算
        # ---------------------------------------------

        nutrition_data = estimate_nutrition(
            vision_data,
            recipe_data
        )

        print(
            "NUTRITION_RESULT:",
            nutrition_data
        )

        # ---------------------------------------------
        # 5. 計算整體速度
        # ---------------------------------------------

        elapsed_seconds = (
            time.time()
            - start_time
        )

        print(
            "TOTAL_ANALYSIS_TIME:",
            elapsed_seconds
        )

        # ---------------------------------------------
        # 6. 組成 LINE 回覆
        # ---------------------------------------------

        result = build_meal_message(
            vision_data,
            nutrition_data,
            elapsed_seconds
        )

        # ---------------------------------------------
        # 7. 回覆
        # ---------------------------------------------

        reply_text(
            event.reply_token,
            result
        )

    except Exception as e:

        print(
            "FOOD_AI_ERROR:",
            repr(e)
        )

        reply_text(
            event.reply_token,
            "🥲 欸，我剛剛腦袋卡住了。\n"
            "這張先別算我的，再傳一次給我 😂\n\n"
            "如果第二次還不行，我們就抓兇手。"
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
