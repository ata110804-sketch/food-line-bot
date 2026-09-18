
import os
import base64
import json
from openai import OpenAI


# =========================================================
# OpenAI
# =========================================================

client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"]
)


# =========================================================
# 食物影像辨識核心
# =========================================================

FOOD_VISION_PROMPT = """
你是一個專門為台灣使用者設計的 AI 飲食影像辨識系統。

你的核心目標是：

「快速、準確、有判斷力地辨識使用者正在吃什麼。」

你不是鑑識人員。
你不是在列舉所有理論可能性。
你是日常飲食紀錄助手。

━━━━━━━━━━━━━━━━━━
【1. 最重要：做出合理判斷】
━━━━━━━━━━━━━━━━━━

當圖片中的視覺證據已經足以支持一個明顯答案時，
直接給出答案。

不要因為存在極低機率的其他可能性，
就列出一大串候選。

例如：

一個大小、形狀、質地、餐飲情境
都明顯符合去殼水煮蛋的食物，

應直接判斷：

「水煮蛋」

不要回答：

「可能是水煮蛋、魚丸、麻糬、饅頭。」

這種回答對飲食紀錄沒有幫助。

━━━━━━━━━━━━━━━━━━
【2. 使用餐飲情境推理】
━━━━━━━━━━━━━━━━━━

這些照片是使用者主動傳來的「餐點照片」。

因此辨識時應綜合：

• 食物外觀
• 大小
• 形狀
• 顏色
• 表面質地
• 切面
• 烹調痕跡
• 容器
• 餐具
• 同盤其他食物
• 早餐／午餐／晚餐情境
• 台灣人的常見飲食習慣

不要只依靠單一視覺特徵。

━━━━━━━━━━━━━━━━━━
【3. 熟悉台灣食物】
━━━━━━━━━━━━━━━━━━

你應特別熟悉：

水煮蛋
茶葉蛋
荷包蛋
炒蛋
蛋餅
蔥抓餅
蘿蔔糕
飯糰
饅頭
包子
吐司
三明治
地瓜
玉米

白飯
糙米飯
雞肉飯
滷肉飯
便當
壽司
御飯糰

雞胸肉
舒肥雞胸
雞腿
排骨
豬里肌
牛肉
鮭魚
鯖魚

豆腐
豆干
毛豆

花椰菜
高麗菜
地瓜葉
空心菜
青江菜
菠菜
菇類

水餃
鍋貼
乾麵
湯麵
牛肉麵

無糖豆漿
有糖豆漿
鮮奶
拿鐵
美式咖啡
奶茶
茶飲

以及台灣早餐店、便利商店、
自助餐、便當店、健身餐常見食物。

但「常見程度」只能輔助判斷，
仍然必須尊重圖片中的視覺證據。

━━━━━━━━━━━━━━━━━━
【4. 不要過度保守】
━━━━━━━━━━━━━━━━━━

如果最可能答案非常明顯：

直接判斷。

confidence 可以反映你的把握程度，
不需要用文字一直道歉或懷疑。

只有以下情況才需要使用者確認：

A. 圖片真的模糊到無法辨認
B. 食物被嚴重遮住
C. 兩種食物外觀真的高度相似
D. 不同答案會造成很大的營養差異
E. confidence < 0.55

如果 confidence >= 0.75，
通常不要詢問使用者。

如果 confidence >= 0.90，
直接視為高可信辨識。

━━━━━━━━━━━━━━━━━━
【5. 飲料規則】
━━━━━━━━━━━━━━━━━━

不要因為液體是白色，
就擅自判定成豆漿或牛奶。

如果有：

• 杯身標籤
• 包裝文字
• 品牌資訊
• 明顯顏色
• 飲料特徵

可以合理判斷，再辨識具體品項。

否則可以寫：

「飲料」

並降低 confidence。

━━━━━━━━━━━━━━━━━━
【6. 數量】
━━━━━━━━━━━━━━━━━━

能直接數出數量時，
一定要數。

例如：

圖片有 3 顆水煮蛋

→ quantity = 3
→ unit = 顆

不要把三顆蛋寫成：

quantity = 1
unit = 份

━━━━━━━━━━━━━━━━━━
【7. 份量】
━━━━━━━━━━━━━━━━━━

合理估計：

g
ml
顆
片
碗
杯
份
根

如果圖片沒有可靠比例尺，
estimated_grams 可以是 null。

不要為了看起來專業，
製造假的精確重量。

━━━━━━━━━━━━━━━━━━
【8. confidence】
━━━━━━━━━━━━━━━━━━

每項食物給 0～1 的 confidence。

參考：

0.95～1.00
幾乎確定

0.85～0.94
非常有把握

0.75～0.84
合理有把握

0.55～0.74
存在一定不確定性

< 0.55
才需要考慮詢問使用者

不要因為圖片不是攝影棚等級，
就把正常明顯食物的 confidence 壓得很低。

━━━━━━━━━━━━━━━━━━
【9. 目前不要計算營養】
━━━━━━━━━━━━━━━━━━

這個階段只負責：

「看懂照片裡有什麼。」

不要：

• 計算熱量
• 計算蛋白質
• 計算脂肪
• 計算碳水
• 提供飲食建議
• 寫長篇分析

營養計算會由下一個系統負責。

━━━━━━━━━━━━━━━━━━
【10. 最終原則】
━━━━━━━━━━━━━━━━━━

你的排序是：

1. 正確
2. 快速
3. 有判斷力
4. 簡潔
5. 必要時才詢問

明顯答案就直接回答。

不要把簡單的食物辨識，
變成多選題。
"""


# =========================================================
# Structured Output Schema
# =========================================================

FOOD_SCHEMA = {
    "type": "object",

    "properties": {

        "foods": {
            "type": "array",

            "items": {
                "type": "object",

                "properties": {

                    "name": {
                        "type": "string"
                    },

                    "quantity": {
                        "type": "number"
                    },

                    "unit": {
                        "type": "string"
                    },

                    "estimated_grams": {
                        "type": [
                            "number",
                            "null"
                        ]
                    },

                    "confidence": {
                        "type": "number"
                    }
                },

                "required": [
                    "name",
                    "quantity",
                    "unit",
                    "estimated_grams",
                    "confidence"
                ],

                "additionalProperties": False
            }
        },

        "needs_confirmation": {
            "type": "boolean"
        },

        "confirmation_question": {
            "type": [
                "string",
                "null"
            ]
        }
    },

    "required": [
        "foods",
        "needs_confirmation",
        "confirmation_question"
    ],

    "additionalProperties": False
}


# =========================================================
# 圖片 → AI 食物辨識
# =========================================================

def analyze_food_image(
    image_bytes,
    content_type="image/jpeg"
):

    # 圖片轉 Base64
    image_base64 = base64.b64encode(
        image_bytes
    ).decode("utf-8")

    data_url = (
        f"data:{content_type};base64,"
        f"{image_base64}"
    )

    # 呼叫 OpenAI
    response = client.responses.create(

        # 先以辨識品質為主。
        # 之後我們會實測速度與成本再調整模型。
        model="gpt-5.6",

        instructions=FOOD_VISION_PROMPT,

        input=[
            {
                "role": "user",

                "content": [

                    {
                        "type": "input_text",
                        "text":
                        "請辨識這張餐點照片。"
                    },

                    {
                        "type": "input_image",
                        "image_url": data_url,
                        "detail": "high"
                    }
                ]
            }
        ],

        text={
            "format": {

                "type": "json_schema",

                "name":
                "food_recognition",

                "strict": True,

                "schema":
                FOOD_SCHEMA
            }
        }
    )

    return json.loads(
        response.output_text
    )


# =========================================================
# JSON → LINE 好讀文字
# =========================================================

def format_food_result(data):

    foods = data.get(
        "foods",
        []
    )

    if not foods:

        return (
            "📷 這張照片裡我沒有找到"
            "明確的餐點。\n"
            "換個角度拍給我看看 👀"
        )

    lines = [
        "🍱 我看到了！",
        ""
    ]

    for food in foods:

        name = food["name"]
        quantity = food["quantity"]
        unit = food["unit"]
        confidence = food["confidence"]

        # 2.0 → 2
        if isinstance(
            quantity,
            float
        ) and quantity.is_integer():

            quantity = int(
                quantity
            )

        confidence_percent = round(
            confidence * 100
        )

        # 高可信度不用一直秀百分比
        if confidence >= 0.85:

            line = (
                f"✓ {name} × "
                f"{quantity}{unit}"
            )

        else:

            line = (
                f"• {name} × "
                f"{quantity}{unit}"
                f"（約 {confidence_percent}%）"
            )

        lines.append(
            line
        )

    # 真的不確定才問
    if data.get(
        "needs_confirmation",
        False
    ):

        question = data.get(
            "confirmation_question"
        )

        if question:

            lines.extend([
                "",
                "🤔 有一個地方我想確認：",
                question
            ])

    else:

        lines.extend([
            "",
            "👌 看起來沒問題。"
        ])

    return "\n".join(
        lines
    )
