import os
import base64
import json
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

configuration = Configuration(
    access_token=LINE_ACCESS_TOKEN
)

handler = WebhookHandler(
    LINE_CHANNEL_SECRET
)

client = OpenAI(
    api_key=OPENAI_API_KEY
)


# =========================================================
# AI 食物分析設定
# =========================================================

FOOD_PROMPT = """
你是一位專門服務台灣使用者的 AI 飲食辨識與營養分析助手。

你的目標是：
快速、準確、方便、專業，而且像一個懂營養的朋友。

你必須依照以下順序分析：

第一層：辨識照片中真正出現的食物
第二層：理解這道料理通常包含哪些原料與烹調方式
第三層：根據照片中的容器、餐具與比例估算份量
第四層：估算每項食物的營養
第五層：加總整餐營養

【辨識原則】

不要只根據顏色或形狀猜食物。

要綜合：
- 形狀
- 顏色
- 表面質地
- 切面
- 肉類纖維
- 油脂分布
- 烹調痕跡
- 食物彼此比例
- 餐具與容器
- 配菜
- 台灣常見料理情境

例如：

完整去殼、橢圓形、具有雞蛋典型大小與表面的食物，
應優先辨識為水煮蛋，而不是因為白色就猜饅頭。

肉排應綜合肉纖維、脂肪、厚度、煎烤痕跡與料理情境，
判斷牛肉、豬肉或雞肉。

如果視覺證據已經充分，
直接給最合理的答案，不要一直提出沒有必要的候選。

真的無法合理判斷時才降低信心。

【料理理解】

辨識完食物後，要理解料理。

例如：

蛋餅：
蛋、餅皮、少量煎油

牛排定食：
牛排、可能的煎烤油或醬汁，以及照片實際出現的白飯與配菜

滷肉飯：
白飯、滷肉、醬汁與脂肪

不要加入照片完全沒有依據的食材。

【份量估算】

利用：
- 碗
- 盤
- 杯
- 筷子
- 湯匙
- 便當盒
- 其他食物

作為尺寸比例。

沒有秤重資訊時，使用合理的台灣外食份量估計。

【營養】

估算：
- 熱量 kcal
- 蛋白質 g
- 碳水化合物 g
- 脂肪 g
- 膳食纖維 g
- 鈉 mg

注意可能的：
- 煎炒油
- 醬汁
- 糖
- 奶油
- 美乃滋
- 起司
- 炸物吸油

但不要把看不到的油脂誇大計算。

【說話風格】

像懂營養的朋友。

可以幽默、吐槽、微毒舌，
但不要羞辱使用者的身材、體重或外貌。

例如：

「蛋白質很可以，這餐有在認真做事 😎」

「菜是有出現啦，但這個量比較像來簽到的 😂」

「牛排本人沒什麼問題，醬汁才是躲在後面的熱量刺客。」

【重要】

最後只能輸出合法 JSON。
不要輸出 Markdown。
不要輸出 ```json。
不要在 JSON 前後加任何文字。

格式：

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
  "comment": "一句簡短朋友式飲食評語"
}

所有營養欄位都必須是數字。
foods 加總必須和 total 大致一致。
comment 最多約45個中文字。
"""


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

def reply_messages(reply_token, messages):

    with ApiClient(configuration) as api_client:

        api = MessagingApi(api_client)

        api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=messages
            )
        )


def reply_text(reply_token, text):

    reply_messages(
        reply_token,
        [
            TextMessage(
                text=text
            )
        ]
    )


# =========================================================
# JSON 清理
# =========================================================

def parse_ai_json(text):

    text = text.strip()

    if text.startswith("```json"):
        text = text[7:]

    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    return json.loads(
        text.strip()
    )


# =========================================================
# Flex Message 元件
# =========================================================

def nutrition_row(icon, label, value):

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
        float(
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


# =========================================================
# 建立漂亮的飲食卡片
# =========================================================

def build_food_card(data):

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
        float(
            total.get(
                "calories",
                0
            )
        )
    )

    protein = round(
        float(
            total.get(
                "protein",
                0
            )
        ),
        1
    )

    carbs = round(
        float(
            total.get(
                "carbs",
                0
            )
        ),
        1
    )

    fat = round(
        float(
            total.get(
                "fat",
                0
            )
        ),
        1
    )

    fiber = round(
        float(
            total.get(
                "fiber",
                0
            )
        ),
        1
    )

    sodium = round(
        float(
            total.get(
                "sodium",
                0
            )
        )
    )

    body = [
        {
            "type": "text",
            "text": f"🍱 {meal_name}",
            "size": "xl",
            "weight": "bold",
            "wrap": True
        },

        {
            "type": "text",
            "text": f"🔥 {calories} kcal",
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
            "text": "我抓到這些 👀",
            "size": "sm",
            "weight": "bold",
            "color": "#888888",
            "margin": "lg"
        }
    ]

    for food in foods[:8]:

        body.append(
            food_row(food)
        )

    body.append({
        "type": "separator",
        "margin": "lg"
    })

    body.extend([
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

    if comment:

        body.extend([
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

    body.append({
        "type": "text",
        "text": "※ 外食份量、用油與醬料為影像估算",
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
                        "label": "✏️ 補充 / 修正這餐",
                        "text": "我要修正上一餐"
                    }
                },

                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "📊 查看今日紀錄",
                        "text": "查看今日紀錄"
                    }
                }
            ]
        }
    }

    return FlexMessage(
        alt_text=f"{meal_name}｜{calories} kcal",
        contents=FlexContainer.from_dict(card)
    )


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
            "✏️ 好，哪裡抓錯直接糾正我。\n\n"
            "例如：\n"
            "「這是牛排不是豬排」\n"
            "「白飯只有半碗」\n"
            "「這杯是無糖豆漿」\n\n"
            "你說，我改。這次不跟你裝傻 😂"
        )

        return

    if text == "查看今日紀錄":

        reply_text(
            event.reply_token,
            "📊 今日紀錄正在準備接上。\n"
            "下一階段會把早餐、午餐、晚餐全部自動累計。"
        )

        return

    reply_text(
        event.reply_token,
        "？？？\n"
        "我是飲食機器人欸 😂\n\n"
        "📷 丟食物照片給我，\n"
        "或問我熱量、蛋白質、減脂、飲食問題。\n\n"
        "其他東西先不要考我，我還在上班 🍱"
    )


# =========================================================
# 圖片訊息
# =========================================================

@handler.add(
    MessageEvent,
    message=ImageMessageContent
)
def handle_image(event):

    try:

        message_id = event.message.id

        # LINE 下載圖片
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

        # Base64
        image_base64 = base64.b64encode(
            image_bytes
        ).decode("utf-8")

        data_url = (
            f"data:{content_type};base64,"
            f"{image_base64}"
        )

        # AI 分析
        ai_response = client.responses.create(

            model="gpt-5.4-mini",

            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": FOOD_PROMPT
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

        result_text = ai_response.output_text

        print(
            "AI_RAW_RESULT:",
            result_text
        )

        data = parse_ai_json(
            result_text
        )

        flex = build_food_card(
            data
        )

        reply_messages(
            event.reply_token,
            [flex]
        )

    except Exception as e:

        print(
            "IMAGE_ANALYSIS_ERROR:",
            repr(e)
        )

        reply_text(
            event.reply_token,
            "🥲 這餐分析到一半翻車了。\n"
            "再傳一次給我。\n\n"
            "如果我又翻車，我們就去 Render 抓兇手 😂"
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
