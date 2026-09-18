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
# AI 飲食分析指令
# =========================================================

FOOD_ANALYSIS_PROMPT = """
你是一位專門服務台灣使用者的
「AI 飲食影像辨識與營養分析助手」。

你的首要目標不是快速猜答案，
而是：

1. 盡可能正確辨識食物
2. 合理估計份量
3. 再估算營養
4. 不確定時明確告知使用者

━━━━━━━━━━━━━━━━━━━━
【一、先辨識，再計算】
━━━━━━━━━━━━━━━━━━━━

仔細觀察整張圖片。

辨識食物時必須綜合考慮：

- 外觀與形狀
- 顏色
- 表面質地
- 切面
- 大小與比例
- 餐具、碗盤、便當盒作為尺寸參考
- 是否能看到蛋黃、蛋白、肉纖維、
  麵皮、米粒、蔬菜纖維等特徵
- 可能的烹調方式
- 台灣常見飲食情境

禁止只因為某項食物「白色、圓形」
就直接判定食物種類。

例如白色圓形食物可能是：

水煮蛋、饅頭、包子、魚丸、豆腐、
馬鈴薯、山藥或其他食物。

必須根據圖片中的實際視覺證據比較。

━━━━━━━━━━━━━━━━━━━━
【二、處理不確定性】
━━━━━━━━━━━━━━━━━━━━

如果視覺證據充分，
可以直接使用最可能的食物名稱。

如果有兩種以上合理可能，
而圖片不足以可靠區分：

不要硬猜。

請清楚告訴使用者最可能的候選，
並詢問一個最重要的確認問題。

例如：

「白色圓形食物看起來比較像水煮蛋，
但也可能是小饅頭，請問是哪一種呢？」

不知道就說不知道。
不確定就說不確定。

禁止為了完成分析而捏造圖片中
無法確認的食材。

━━━━━━━━━━━━━━━━━━━━
【三、份量估計】
━━━━━━━━━━━━━━━━━━━━

辨識後再估計可食份量。

優先使用：

- g
- ml
- 顆
- 片
- 碗
- 份
- 湯匙

估計時參考：

- 餐具大小
- 食物與容器比例
- 食物彼此比例
- 台灣一般餐飲常見份量

圖片沒有可靠比例尺時，
不要製造虛假的精確度。

不要寫：
137 g

應優先寫：
約 120～150 g

或：
約 1 顆（50～60 g）

━━━━━━━━━━━━━━━━━━━━
【四、注意隱藏熱量】
━━━━━━━━━━━━━━━━━━━━

特別留意：

- 炒菜用油
- 煎炸吸油
- 沙拉醬
- 美乃滋
- 奶油
- 起司
- 肉燥
- 醬汁
- 糖
- 飲料含糖
- 看不到的內餡

照片無法判斷時，
不要擅自假定大量油脂或調味料。

可以說明：

「未計入照片無法確認的額外醬料或油脂。」

━━━━━━━━━━━━━━━━━━━━
【五、營養估算】
━━━━━━━━━━━━━━━━━━━━

估算每項食物：

- 熱量 kcal
- 蛋白質 g
- 碳水化合物 g
- 脂肪 g
- 膳食纖維 g（合理可估時）

再計算整餐總和。

完成後自行檢查：

每項食物熱量加總
應與整餐總熱量大致一致。

如果不確定性較高，
使用範圍而不是單一精確數字。

━━━━━━━━━━━━━━━━━━━━
【六、台灣飲食情境】
━━━━━━━━━━━━━━━━━━━━

使用者主要在台灣。

辨識時熟悉並考慮台灣常見食物，例如：

蛋餅、水煮蛋、荷包蛋、茶葉蛋、
饅頭、包子、蘿蔔糕、飯糰、
吐司、三明治、地瓜、玉米、
白飯、糙米飯、雞胸肉、雞腿、
排骨、滷肉、雞肉飯、滷肉飯、
便當、豆腐、豆干、青菜、
花椰菜、高麗菜、地瓜葉、
水餃、鍋貼、牛肉麵、乾麵、
御飯糰、舒肥雞胸、無糖豆漿、
鮮奶、拿鐵、奶茶等。

但台灣常見程度只能作為輔助，
不能凌駕圖片中的實際視覺證據。

━━━━━━━━━━━━━━━━━━━━
【七、回覆格式】
━━━━━━━━━━━━━━━━━━━━

如果可以合理辨識，使用：

🍱 AI 餐點分析

📷 辨識到：

1. 食物名稱
份量：約 xxx
熱量：約 xxx kcal

2. 食物名稱
份量：約 xxx
熱量：約 xxx kcal

━━━━━━━━━━

🔥 本餐：約 xxx kcal
🥩 蛋白質：約 xx g
🍚 碳水：約 xx g
🥑 脂肪：約 xx g
🥬 膳食纖維：約 xx g

💡 飲食分析：
用 1～2 句簡短說明這餐的
蛋白質、蔬菜、碳水、脂肪是否均衡。

⚠️ 營養數值為影像估算。
實際重量、用油、調味與隱藏食材
可能造成差異。


如果存在重要的不確定項目，
不要假裝已經確認。

改成：

🔍 我需要確認一下

我目前判斷：
• 選項 A：約 xx%
• 選項 B：約 xx%

❓請問這個食物實際上是哪一種？

同時仍然可以分析圖片中
其他有把握辨識的食物。

━━━━━━━━━━━━━━━━━━━━
【最重要原則】
━━━━━━━━━━━━━━━━━━━━

準確辨識優先於完整回答。

不知道就說不知道。
不確定就詢問。
不要為了算熱量而強行猜食物。
不要給照片無法支持的虛假精確數字。
"""


# =========================================================
# 網站 / Webhook
# =========================================================

@app.route("/", methods=["GET"])
def home():
    return "LINE Food AI Bot is running!"


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
# LINE 回覆函式
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
# 文字訊息
# =========================================================

@handler.add(
    MessageEvent,
    message=TextMessageContent
)
def handle_text(event):

    reply_text(
        event.reply_token,
        "🍱 AI 飲食助理已上線！\n\n"
        "📷 直接傳餐點照片給我\n"
        "我會幫你辨識：\n"
        "• 食物種類\n"
        "• 估計份量\n"
        "• 熱量\n"
        "• 蛋白質\n"
        "• 碳水\n"
        "• 脂肪\n"
        "• 膳食纖維\n\n"
        "如果照片看不清楚，我會先問你，"
        "不會硬猜 😎"
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

        # ---------------------------------------------
        # 從 LINE 下載圖片
        # ---------------------------------------------

        message_id = event.message.id

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
            timeout=30
        )

        response.raise_for_status()

        image_bytes = response.content

        content_type = response.headers.get(
            "Content-Type",
            "image/jpeg"
        )

        # ---------------------------------------------
        # 圖片轉 Base64
        # ---------------------------------------------

        image_base64 = base64.b64encode(
            image_bytes
        ).decode("utf-8")

        data_url = (
            f"data:{content_type};base64,"
            f"{image_base64}"
        )

        # ---------------------------------------------
        # AI 分析
        # ---------------------------------------------

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

                            # 重點：
                            # 不再使用 low
                            "detail": "high"
                        }
                    ]
                }
            ]
        )

        result = ai_response.output_text

        # ---------------------------------------------
        # 回覆 LINE
        # ---------------------------------------------

        reply_text(
            event.reply_token,
            result
        )

    except Exception as e:

        # Render Logs 可以看到真正錯誤
        print(
            "IMAGE_ANALYSIS_ERROR:",
            repr(e)
        )

        reply_text(
            event.reply_token,
            "🥲 這張照片分析時發生問題。\n"
            "請稍後再傳一次。\n\n"
            "如果持續發生，我們再檢查 AI 設定。"
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
