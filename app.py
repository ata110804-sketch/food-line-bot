import os
import base64
import json
import requests

from flask import Flask, request, abort

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

# 我們自己的兩個模組
from food_ai import (
    analyze_food_image,
    correct_food_analysis,
)

from database import (
    init_database,
    save_meal,
    get_last_meal,
    update_meal,
    get_today_meals,
    get_today_totals,
)


# =========================================================
# 基本設定
# =========================================================

app = Flask(__name__)

LINE_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]

configuration = Configuration(
    access_token=LINE_ACCESS_TOKEN
)

handler = WebhookHandler(
    LINE_CHANNEL_SECRET
)


# =========================================================
# 初始化資料庫
# =========================================================

try:
    init_database()

except Exception as e:
    print(
        "DATABASE_INIT_ERROR:",
        repr(e),
        flush=True
    )


# =========================================================
# 首頁
# =========================================================

@app.route("/", methods=["GET"])
def home():

    return "LINE Food AI Bot is running!"


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

def reply_messages(
    reply_token,
    messages
):

    with ApiClient(
        configuration
    ) as api_client:

        api = MessagingApi(
            api_client
        )

        api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=messages
            )
        )


def reply_text(
    reply_token,
    text
):

    reply_messages(
        reply_token,
        [
            TextMessage(
                text=text
            )
        ]
    )


# =========================================================
# 取得 LINE User ID
# =========================================================

def get_user_id(event):

    try:

        user_id = event.source.user_id

        if user_id:
            return user_id

    except Exception:
        pass

    return "unknown_user"


# =========================================================
# 安全轉數字
# =========================================================

def number(
    value,
    default=0
):

    try:
        return float(value)

    except Exception:
        return default


# =========================================================
# 今日總計整理
# =========================================================

def clean_totals(totals):

    if not totals:

        return {
            "meal_count": 0,
            "calories": 0,
            "protein": 0,
            "carbs": 0,
            "fat": 0,
            "fiber": 0,
            "sodium": 0,
        }

    return {
        "meal_count":
            int(
                totals.get(
                    "meal_count",
                    0
                )
                or 0
            ),

        "calories":
            number(
                totals.get(
                    "calories",
                    0
                )
            ),

        "protein":
            number(
                totals.get(
                    "protein",
                    0
                )
            ),

        "carbs":
            number(
                totals.get(
                    "carbs",
                    0
                )
            ),

        "fat":
            number(
                totals.get(
                    "fat",
                    0
                )
            ),

        "fiber":
            number(
                totals.get(
                    "fiber",
                    0
                )
            ),

        "sodium":
            number(
                totals.get(
                    "sodium",
                    0
                )
            ),
    }


# =========================================================
# Flex：營養列
# =========================================================

def nutrition_row(
    icon,
    label,
    value
):

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
                "flex": 5
            },

            {
                "type": "text",
                "text": value,
                "size": "md",
                "weight": "bold",
                "align": "end",
                "color": "#222222",
                "flex": 5
            }
        ]
    }


# =========================================================
# Flex：食物列
# =========================================================

def food_row(food):

    name = food.get(
        "name",
        "食物"
    )

    quantity = food.get(
        "quantity",
        ""
    )

    calories = round(
        number(
            food.get(
                "calories",
                0
            )
        )
    )

    return {
        "type": "box",
        "layout": "horizontal",
        "margin": "sm",

        "contents": [

            {
                "type": "text",
                "text":
                    f"• {name} {quantity}",
                "size": "sm",
                "color": "#555555",
                "wrap": True,
                "flex": 7
            },

            {
                "type": "text",
                "text":
                    f"{calories} kcal",
                "size": "sm",
                "color": "#555555",
                "align": "end",
                "flex": 3
            }
        ]
    }


# =========================================================
# 建立「單餐＋今日累計」卡片
# =========================================================

def build_meal_card(
    data,
    today_totals,
    corrected=False
):

    totals = clean_totals(
        today_totals
    )

    meal_name = data.get(
        "meal_name",
        "這一餐"
    )

    foods = data.get(
        "foods",
        []
    )

    total = data.get(
        "total",
        {}
    )

    comment = data.get(
        "comment",
        ""
    )

    calories = round(
        number(
            total.get(
                "calories",
                0
            )
        )
    )

    protein = round(
        number(
            total.get(
                "protein",
                0
            )
        ),
        1
    )

    carbs = round(
        number(
            total.get(
                "carbs",
                0
            )
        ),
        1
    )

    fat = round(
        number(
            total.get(
                "fat",
                0
            )
        ),
        1
    )

    fiber = round(
        number(
            total.get(
                "fiber",
                0
            )
        ),
        1
    )

    sodium = round(
        number(
            total.get(
                "sodium",
                0
            )
        )
    )

    title = (
        f"✏️ 已修正｜{meal_name}"
        if corrected
        else f"🍱 {meal_name}"
    )

    body = [

        {
            "type": "text",
            "text": title,
            "size": "xl",
            "weight": "bold",
            "wrap": True
        },

        {
            "type": "text",
            "text":
                f"🔥 約 {calories} kcal",
            "size": "xxl",
            "weight": "bold",
            "margin": "md"
        },

        {
            "type": "separator",
            "margin": "lg"
        },

        {
            "type": "text",
            "text": "這餐有這些 👀",
            "size": "sm",
            "weight": "bold",
            "color": "#888888",
            "margin": "lg"
        }
    ]

    # 食物明細
    for food in foods[:8]:

        body.append(
            food_row(food)
        )

    # 本餐營養
    body.extend([

        {
            "type": "separator",
            "margin": "lg"
        },

        {
            "type": "text",
            "text": "本餐營養",
            "size": "sm",
            "weight": "bold",
            "color": "#888888",
            "margin": "lg"
        },

        nutrition_row(
            "🥩",
            "蛋白質",
            f"{protein} g"
        ),

        nutrition_row(
            "🍚",
            "碳水",
            f"{carbs} g"
        ),

        nutrition_row(
            "🥑",
            "脂肪",
            f"{fat} g"
        ),

        nutrition_row(
            "🥬",
            "纖維",
            f"{fiber} g"
        ),

        nutrition_row(
            "🧂",
            "鈉",
            f"{sodium} mg"
        )
    ])

    # 今日累計
    body.extend([

        {
            "type": "separator",
            "margin": "lg"
        },

        {
            "type": "text",
            "text":
                f"📊 今日累計｜"
                f"{totals['meal_count']} 筆",
            "size": "md",
            "weight": "bold",
            "margin": "lg"
        },

        {
            "type": "text",
            "text":
                f"🔥 {round(totals['calories'])} kcal",
            "size": "xl",
            "weight": "bold",
            "margin": "md"
        },

        nutrition_row(
            "🥩",
            "蛋白質",
            f"{round(totals['protein'], 1)} g"
        ),

        nutrition_row(
            "🍚",
            "碳水",
            f"{round(totals['carbs'], 1)} g"
        ),

        nutrition_row(
            "🥑",
            "脂肪",
            f"{round(totals['fat'], 1)} g"
        ),

        nutrition_row(
            "🥬",
            "纖維",
            f"{round(totals['fiber'], 1)} g"
        )
    ])

    # AI 評語
    if comment:

        body.extend([

            {
                "type": "separator",
                "margin": "lg"
            },

            {
                "type": "text",
                "text":
                    f"💬 {comment}",
                "size": "sm",
                "color": "#555555",
                "wrap": True,
                "margin": "lg"
            }
        ])

    body.append({

        "type": "text",
        "text":
            "※ 份量、用油與醬料為影像估算",
        "size": "xs",
        "color": "#AAAAAA",
        "wrap": True,
        "margin": "lg"
    })

    card = {

        "type": "bubble",

        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "20px",
            "contents": body
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
                        "label":
                            "✏️ 補充 / 修正這餐",
                        "text":
                            "我要修正上一餐"
                    }
                },

                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",

                    "action": {
                        "type": "message",
                        "label":
                            "📊 查看今日紀錄",
                        "text":
                            "查看今日紀錄"
                    }
                }
            ]
        }
    }

    return FlexMessage(

        alt_text=
            f"{meal_name}｜"
            f"{calories} kcal｜"
            f"今日 {round(totals['calories'])} kcal",

        contents=
            FlexContainer.from_dict(
                card
            )
    )


# =========================================================
# 今日紀錄文字
# =========================================================

def build_today_summary(
    meals,
    totals
):

    totals = clean_totals(
        totals
    )

    if not meals:

        return (
            "📊 今天還沒有飲食紀錄。\n\n"
            "你是還沒吃，"
            "還是偷偷吃了沒報備 😂"
        )

    lines = [
        "📊 今日飲食紀錄",
        ""
    ]

    for meal in meals:

        meal_type = (
            meal.get(
                "meal_type"
            )
            or "餐點"
        )

        meal_name = (
            meal.get(
                "meal_name"
            )
            or "這一餐"
        )

        calories = round(
            number(
                meal.get(
                    "calories",
                    0
                )
            )
        )

        corrected = (
            " ✏️"
            if meal.get(
                "corrected"
            )
            else ""
        )

        lines.append(
            f"{meal_type}｜"
            f"{meal_name}{corrected}"
        )

        lines.append(
            f"🔥 {calories} kcal"
        )

        lines.append("")

    lines.extend([

        "━━━━━━━━━━━━",

        f"🔥 今日總熱量 "
        f"{round(totals['calories'])} kcal",

        f"🥩 蛋白質 "
        f"{round(totals['protein'], 1)} g",

        f"🍚 碳水 "
        f"{round(totals['carbs'], 1)} g",

        f"🥑 脂肪 "
        f"{round(totals['fat'], 1)} g",

        f"🥬 纖維 "
        f"{round(totals['fiber'], 1)} g",

        f"🧂 鈉 "
        f"{round(totals['sodium'])} mg",
    ])

    return "\n".join(
        lines
    )


# =========================================================
# 判斷是不是飲食修正
# =========================================================

def looks_like_correction(text):

    keywords = [

        "不是",
        "其實",
        "改成",
        "更正",
        "修正",
        "只有",
        "半碗",
        "半份",
        "兩顆",
        "2顆",
        "三顆",
        "3顆",
        "無糖",
        "微糖",
        "少糖",
        "正常糖",
        "沒吃",
        "沒有吃",
        "沒喝",
        "沒有喝",
        "吃一半",
        "喝一半",
        "漏掉",
        "還有",
        "是牛",
        "是豬",
        "是雞",
    ]

    return any(
        keyword in text
        for keyword in keywords
    )


# =========================================================
# 處理文字
# =========================================================

@handler.add(
    MessageEvent,
    message=TextMessageContent
)
def handle_text(event):

    user_id = get_user_id(
        event
    )

    text = event.message.text.strip()

    # ---------------------------------------------
    # 查看今日紀錄
    # ---------------------------------------------

    if text in [
        "查看今日紀錄",
        "今日紀錄",
        "今天吃了什麼",
        "今天吃多少",
        "今天幾卡",
        "今天多少熱量",
    ]:

        try:

            meals = get_today_meals(
                user_id
            )

            totals = get_today_totals(
                user_id
            )

            summary = build_today_summary(
                meals,
                totals
            )

            reply_text(
                event.reply_token,
                summary
            )

        except Exception as e:

            print(
                "TODAY_SUMMARY_ERROR:",
                repr(e),
                flush=True
            )

            reply_text(
                event.reply_token,
                "🥲 今天的帳本突然翻不開。\n"
                "等等再試一次。"
            )

        return

    # ---------------------------------------------
    # 按下修正按鈕
    # ---------------------------------------------

    if text == "我要修正上一餐":

        last_meal = get_last_meal(
            user_id
        )

        if not last_meal:

            reply_text(
                event.reply_token,
                "你今天連上一餐都還沒交給我 😂\n"
                "先傳一張餐點照片再來修。"
            )

            return

        meal_name = (
            last_meal.get(
                "meal_name"
            )
            or "上一餐"
        )

        reply_text(
            event.reply_token,
            f"✏️ 好，現在要改「{meal_name}」。\n\n"
            "直接告訴我哪裡不對就好：\n"
            "• 這是牛排不是豬排\n"
            "• 飯只有半碗\n"
            "• 豆漿是無糖\n"
            "• 那個我沒有吃\n"
            "• 其實有兩顆蛋\n\n"
            "你講，我直接重算。"
        )

        return

    # ---------------------------------------------
    # 判斷是不是在糾正上一餐
    # ---------------------------------------------

    if looks_like_correction(
        text
    ):

        try:

            last_meal = get_last_meal(
                user_id
            )

            if not last_meal:

                reply_text(
                    event.reply_token,
                    "我找不到上一餐可以改 😭\n"
                    "先傳餐點照片給我。"
                )

                return

            corrected_data = (
                correct_food_analysis(
                    last_meal,
                    text
                )
            )

            update_meal(
                last_meal["id"],
                corrected_data
            )

            totals = get_today_totals(
                user_id
            )

            flex = build_meal_card(
                corrected_data,
                totals,
                corrected=True
            )

            reply_messages(
                event.reply_token,
                [flex]
            )

        except Exception as e:

            print(
                "CORRECTION_ERROR:",
                repr(e),
                flush=True
            )

            reply_text(
                event.reply_token,
                "🥲 我知道你是在糾正上一餐，"
                "但我重算的時候翻車了。\n"
                "再說一次給我。"
            )

        return

    # ---------------------------------------------
    # 飲食相關簡單指令
    # ---------------------------------------------

    if any(
        keyword in text
        for keyword in [
            "熱量",
            "蛋白質",
            "碳水",
            "脂肪",
            "纖維",
            "減脂",
            "飲食",
            "吃",
            "喝",
        ]
    ):

        reply_text(
            event.reply_token,
            "🍱 如果是要記錄你實際吃的東西，"
            "直接傳照片給我最快。\n\n"
            "吃完才想起來也沒關係，"
            "之後我們會再把純文字記餐補上 😎"
        )

        return

    # ---------------------------------------------
    # 無關問題
    # ---------------------------------------------

    reply_text(
        event.reply_token,
        "？？？這題不是我管的吧 😂\n\n"
        "我是你的飲食記帳仔。\n"
        "📷 食物照片丟過來，"
        "熱量我來處理。\n\n"
        "不要拿數學作業來偷襲我。"
    )


# =========================================================
# 處理圖片
# =========================================================

@handler.add(
    MessageEvent,
    message=ImageMessageContent
)
def handle_image(event):

    user_id = get_user_id(
        event
    )

    try:

        message_id = event.message.id

        # ---------------------------------------------
        # 下載 LINE 圖片
        # ---------------------------------------------

        image_url = (
            "https://api-data.line.me/"
            f"v2/bot/message/"
            f"{message_id}/content"
        )

        response = requests.get(

            image_url,

            headers={
                "Authorization":
                    f"Bearer "
                    f"{LINE_ACCESS_TOKEN}"
            },

            timeout=20
        )

        response.raise_for_status()

        image_bytes = response.content

        content_type = (
            response.headers.get(
                "Content-Type",
                "image/jpeg"
            )
        )

        # ---------------------------------------------
        # Base64
        # ---------------------------------------------

        image_base64 = (
            base64.b64encode(
                image_bytes
            ).decode(
                "utf-8"
            )
        )

        data_url = (
            f"data:{content_type};"
            f"base64,{image_base64}"
        )

        # ---------------------------------------------
        # AI 一次完成分析
        # ---------------------------------------------

        data = analyze_food_image(
            data_url
        )

        # ---------------------------------------------
        # 儲存這一餐
        # ---------------------------------------------

        meal_id = save_meal(
            user_id,
            data
        )

        print(
            f"MEAL_SAVED: "
            f"user={user_id} "
            f"meal_id={meal_id}",
            flush=True
        )

        # ---------------------------------------------
        # 重新取得今日總計
        # ---------------------------------------------

        totals = get_today_totals(
            user_id
        )

        # ---------------------------------------------
        # 回覆卡片
        # ---------------------------------------------

        flex = build_meal_card(
            data,
            totals,
            corrected=False
        )

        reply_messages(
            event.reply_token,
            [flex]
        )

    except Exception as e:

        print(
            "IMAGE_ERROR:",
            repr(e),
            flush=True
        )

        reply_text(
            event.reply_token,
            "🥲 這餐處理到一半翻車了。\n"
            "再傳一次給我。\n\n"
            "如果我連續翻車，"
            "我們就去 Render 抓兇手 😂"
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
