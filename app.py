import os
import requests
import time
import threading

from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
)

from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    ImageMessageContent,
)

# =========================================================
# 三層 AI
# =========================================================

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
# 首頁
# =========================================================

@app.route("/", methods=["GET"])
def home():

    return "LINE Food AI V4 is running!"


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
# LINE 即時回覆
# =========================================================

def reply_text(reply_token, text):

    with ApiClient(configuration) as api_client:

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
# LINE 主動推送
# AI 分析完成後使用
# =========================================================

def push_text(user_id, text):

    with ApiClient(configuration) as api_client:

        line_bot_api = MessagingApi(
            api_client
        )

        line_bot_api.push_message(
            PushMessageRequest(
                to=user_id,
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

def download_line_image(message_id):

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
# 數字漂亮顯示
# 31.0 → 31
# 31.6 → 31.6
# =========================================================

def pretty_number(value):

    if value is None:

        return "-"

    try:

        value = float(value)

    except (TypeError, ValueError):

        return str(value)

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

    name = str(name)

    rules = [

        (
            ["蛋"],
            "🥚"
        ),

        (
            ["雞", "豬", "牛", "排骨", "肉"],
            "🥩"
        ),

        (
            ["魚", "鮭", "鯖", "蝦", "海鮮"],
            "🐟"
        ),

        (
            ["飯", "米", "飯糰"],
            "🍚"
        ),

        (
            ["麵", "烏龍", "拉麵"],
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
                "青江",
                "生菜"
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
            ["茶", "奶茶", "飲料"],
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

        (
            ["梨"],
            "🍐"
        ),

        (
            ["橘", "柳橙"],
            "🍊"
        ),

        (
            ["麵包", "吐司", "可頌"],
            "🥐"
        ),

        (
            ["豆腐", "豆干"],
            "🫘"
        ),
    ]

    for keywords, emoji in rules:

        for keyword in keywords:

            if keyword in name:

                return emoji

    return "🍴"


# =========================================================
# LINE 餐點結果
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

    # =====================================================
    # 每項食物
    # =====================================================

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

        try:

            calories = round(
                float(
                    food.get(
                        "calories",
                        0
                    )
                )
            )

        except (TypeError, ValueError):

            calories = 0

        emoji = food_emoji(
            name
        )

        lines.append(
            f"{emoji} {name} × "
            f"{quantity}{unit}"
            f"｜約 {calories} kcal"
        )

    # =====================================================
    # 總營養
    # =====================================================

    try:

        total_calories = round(
            float(
                totals.get(
                    "calories",
                    0
                )
            )
        )

    except (TypeError, ValueError):

        total_calories = 0

    lines.extend([

        "",

        "━━━━━━━━━━━━",

        "",

        (
            "🔥 約 "
            f"{total_calories} kcal"
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


    # =====================================================
    # 可信度
    # =====================================================

    try:

        confidence = float(
            nutrition_data.get(
                "overall_nutrition_confidence",
                0
            )
        )

    except (TypeError, ValueError):

        confidence = 0


    if confidence >= 0.90:

        confidence_text = (
            "這餐我看得滿清楚，"
            "這次眼睛有帶出門 😎"
        )

    elif confidence >= 0.80:

        confidence_text = (
            "這餐辨識得滿穩的 👌"
        )

    elif confidence >= 0.70:

        confidence_text = (
            "食物大致抓得到，"
            "份量可能有一點誤差。"
        )

    else:

        confidence_text = (
            "這餐有幾個地方比較難估，"
            "營養數字先當參考。"
        )

    lines.extend([

        "",

        f"👀 {confidence_text}"
    ])


    # =====================================================
    # 真的有必要才詢問
    # =====================================================

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

                "🤔 有一個地方我真的看不透：",

                question
            ])


    # =====================================================
    # 分析速度
    # =====================================================

    lines.extend([

        "",

        (
            "⚡ 分析時間："
            f"{elapsed_seconds:.1f} 秒"
        ),

        "",

        (
            "⚠️ 外食照片的實際重量、"
            "用油與醬料無法完全從照片得知，"
            "營養數字為合理估算。"
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

    # -----------------------------------------------------
    # 一些基本互動
    # -----------------------------------------------------

    if user_text in [
        "嗨",
        "哈囉",
        "你好",
        "hi",
        "Hi",
        "HI"
    ]:

        reply_text(
            event.reply_token,

            "嗨屁嗨 😂\n\n"
            "我是你的 AI 飲食小助理 🍱\n"
            "直接把你要吃的東西拍給我。\n\n"
            "我負責算，你負責不要偷偷漏報 😏"
        )

        return


    if "怎麼用" in user_text:

        reply_text(
            event.reply_token,

            "很簡單啦 😂\n\n"
            "📷 拍你要吃的東西\n"
            "➡️ 照片丟給我\n"
            "➡️ 等我認食物\n"
            "➡️ 我幫你估熱量跟營養\n\n"
            "就這樣，沒有要你考營養師執照。"
        )

        return


    # -----------------------------------------------------
    # 目前非飲食問題
    # -----------------------------------------------------

    reply_text(
        event.reply_token,

        "？？？\n"
        "我是飲食機器人欸 😂\n\n"
        "食物、熱量、減脂、蛋白質可以問我。\n"
        "其他東西先不要考我，我還在上班 🍱"
    )


# =========================================================
# 圖片訊息
#
# 收到圖片後：
#
# 1. 立刻回 LINE
# 2. 背景開始分析
# 3. AI 完成後 Push 結果
#
# =========================================================

@handler.add(
    MessageEvent,
    message=ImageMessageContent
)
def handle_image(event):

    try:

        user_id = event.source.user_id

        message_id = event.message.id

        # -------------------------------------------------
        # 先立即告訴使用者：收到照片了
        # -------------------------------------------------

        reply_text(
            event.reply_token,

            "📸 收到！這餐交給我。\n"
            "我正在認食物 → 拆料理 → 算營養 🧠\n\n"
            "不用顧著我，你可以繼續傳 😂"
        )

        # -------------------------------------------------
        # AI 放到背景執行
        # -------------------------------------------------

        thread = threading.Thread(
            target=analyze_food_image,
            args=(
                user_id,
                message_id
            ),
            daemon=True
        )

        thread.start()

    except Exception as e:

        print(
            "IMAGE_HANDLER_ERROR:",
            repr(e)
        )

        try:

            reply_text(
                event.reply_token,

                "🥲 欸，照片我是收到了，"
                "但剛剛啟動分析時卡了一下。\n\n"
                "再傳一次給我。"
            )

        except Exception:

            pass


# =========================================================
# 背景 AI 分析
# =========================================================

def analyze_food_image(
    user_id,
    message_id
):

    start_time = time.time()

    try:

        # =================================================
        # STEP 1
        # 下載 LINE 圖片
        # =================================================

        download_start = time.time()

        image_bytes, content_type = (
            download_line_image(
                message_id
            )
        )

        download_time = (
            time.time()
            - download_start
        )

        print(
            "IMAGE_DOWNLOADED:",
            len(image_bytes),
            content_type
        )

        print(
            "DOWNLOAD_TIME:",
            f"{download_time:.2f}s"
        )


        # =================================================
        # STEP 2
        # 第一層 AI：辨識「眼前是什麼」
        # =================================================

        vision_start = time.time()

        vision_data = recognize_foods(
            image_bytes,
            content_type
        )

        vision_time = (
            time.time()
            - vision_start
        )

        print(
            "VISION_RESULT:",
            vision_data
        )

        print(
            "VISION_TIME:",
            f"{vision_time:.2f}s"
        )


        # =================================================
        # STEP 3
        # 第二層 AI：理解料理
        # =================================================

        recipe_start = time.time()

        recipe_data = understand_recipes(
            vision_data
        )

        recipe_time = (
            time.time()
            - recipe_start
        )

        print(
            "RECIPE_RESULT:",
            recipe_data
        )

        print(
            "RECIPE_TIME:",
            f"{recipe_time:.2f}s"
        )


        # =================================================
        # STEP 4
        # 第三層 AI：營養估算
        # =================================================

        nutrition_start = time.time()

        nutrition_data = estimate_nutrition(
            vision_data,
            recipe_data
        )

        nutrition_time = (
            time.time()
            - nutrition_start
        )

        print(
            "NUTRITION_RESULT:",
            nutrition_data
        )

        print(
            "NUTRITION_TIME:",
            f"{nutrition_time:.2f}s"
        )


        # =================================================
        # STEP 5
        # 計算總耗時
        # =================================================

        elapsed_seconds = (
            time.time()
            - start_time
        )

        print(
            "================================="
        )

        print(
            "DOWNLOAD_TIME:",
            f"{download_time:.2f}s"
        )

        print(
            "VISION_TIME:",
            f"{vision_time:.2f}s"
        )

        print(
            "RECIPE_TIME:",
            f"{recipe_time:.2f}s"
        )

        print(
            "NUTRITION_TIME:",
            f"{nutrition_time:.2f}s"
        )

        print(
            "TOTAL_ANALYSIS_TIME:",
            f"{elapsed_seconds:.2f}s"
        )

        print(
            "================================="
        )


        # =================================================
        # STEP 6
        # 建立 LINE 訊息
        # =================================================

        result = build_meal_message(
            vision_data,
            nutrition_data,
            elapsed_seconds
        )


        # =================================================
        # STEP 7
        # AI 完成後主動推送
        # =================================================

        push_text(
            user_id,
            result
        )


    except Exception as e:

        print(
            "FOOD_AI_BACKGROUND_ERROR:",
            repr(e)
        )

        try:

            push_text(
                user_id,

                "🥲 欸，我這餐算到一半腦袋打結了。\n"
                "照片有收到，但分析沒有成功。\n\n"
                "再丟一次給我，我們抓兇手 😂"
            )

        except Exception as push_error:

            print(
                "PUSH_ERROR:",
                repr(push_error)
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
