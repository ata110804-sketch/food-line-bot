import os
import base64
import json
from openai import OpenAI


client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"]
)


# =========================================================
# 第一層：視覺食物辨識
# =========================================================

VISION_PROMPT = """
你是專門辨識台灣日常飲食照片的 AI 視覺系統。

目前只執行第一層任務：

「看懂照片裡實際有哪些食物與飲料。」

此階段不要計算熱量、營養素，
不要提供健康建議，也不要寫長篇解釋。

【核心原則】

1. 先看完整畫面，再辨識個別食物。

2. 綜合判斷：
- 形狀
- 顏色
- 質地
- 切面
- 大小比例
- 數量
- 烹調痕跡
- 容器
- 餐具
- 同盤食物
- 台灣飲食情境

3. 這是「飲食紀錄」情境，不是物體鑑識。

如果一個答案明顯最合理，
直接採用最可能答案。

例如視覺、尺寸、形狀與餐飲情境
都高度符合去殼水煮蛋：

直接辨識為「水煮蛋」。

不要為了理論上的極低機率，
另外列出麻糬、魚丸、饅頭等候選。

4. 對台灣常見食物要有良好的判斷力。

包括但不限於：

水煮蛋、茶葉蛋、荷包蛋、炒蛋、
蛋餅、蔥抓餅、蘿蔔糕、飯糰、
饅頭、包子、吐司、三明治、
地瓜、玉米、

白飯、糙米飯、雞肉飯、滷肉飯、
便當、壽司、御飯糰、

雞胸肉、舒肥雞胸、雞腿、排骨、
豬肉、牛肉、鮭魚、鯖魚、蝦、

豆腐、豆干、毛豆、

花椰菜、高麗菜、空心菜、
地瓜葉、青江菜、菠菜、菇類、

水餃、鍋貼、乾麵、湯麵、牛肉麵、

豆漿、鮮奶、拿鐵、美式咖啡、
奶茶、茶飲等。

5. 數量能數就直接數。

看到三顆水煮蛋：
quantity = 3
unit = "顆"

不要寫成「1份」。

6. 估計重量時不要假裝過度精確。

能合理估計：
estimated_grams 填數值。

無法合理估計：
estimated_grams = null。

7. confidence 是你對食物名稱辨識的信心。

0.95～1.00：幾乎確定
0.85～0.94：非常有把握
0.75～0.84：合理有把握
0.55～0.74：存在明顯不確定性
低於 0.55：真的難以辨識

對典型、清楚、常見食物，
不要刻意降低 confidence。

8. needs_confirmation 預設為 false。

只有：
- 圖片真的太模糊
- 食物嚴重遮擋
- 兩種合理答案真的難以區分
- 判斷錯誤會大幅影響後續營養計算
- 主要食物 confidence < 0.55

才設為 true。

不要對明顯答案反覆詢問使用者。

9. 飲料要特別注意。

如果有包裝、文字、品牌或明顯特徵，
可以辨識具體飲品。

如果單靠圖片無法知道內容物，
請寫「飲料」，
不要因為液體是白色就直接猜豆漿或牛奶。

10. 不要幻想圖片中沒有的東西。

輸出只描述實際看見或
有充分視覺依據判斷的食物。
"""


# =========================================================
# 第一層輸出格式
# =========================================================

VISION_SCHEMA = {
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
                        "type": ["number", "null"]
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
            "type": ["string", "null"]
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
# 執行第一層辨識
# =========================================================

def recognize_foods(
    image_bytes,
    content_type="image/jpeg"
):
    image_base64 = base64.b64encode(
        image_bytes
    ).decode("utf-8")

    data_url = (
        f"data:{content_type};base64,"
        f"{image_base64}"
    )

    response = client.responses.create(
        model="gpt-5.6",

        instructions=VISION_PROMPT,

        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text":
                        "辨識這張飲食照片中的食物與飲料。"
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
                "name": "food_vision",
                "strict": True,
                "schema": VISION_SCHEMA
            }
        }
    )

    return json.loads(
        response.output_text
    )


# =========================================================
# 暫時的測試顯示
# =========================================================

def format_recognition_result(data):
    foods = data.get("foods", [])

    if not foods:
        return (
            "👀 我這張沒有抓到明確的食物，"
            "換個角度再給我看一次。"
        )

    lines = [
        "👀 第一層辨識完成",
        ""
    ]

    for food in foods:
        quantity = food["quantity"]

        if (
            isinstance(quantity, float)
            and quantity.is_integer()
        ):
            quantity = int(quantity)

        confidence = round(
            food["confidence"] * 100
        )

        lines.append(
            f"✓ {food['name']} × "
            f"{quantity}{food['unit']} "
            f"｜{confidence}%"
        )

    if data.get("needs_confirmation"):
        question = data.get(
            "confirmation_question"
        )

        if question:
            lines.extend([
                "",
                f"🤔 {question}"
            ])

    return "\n".join(lines)
