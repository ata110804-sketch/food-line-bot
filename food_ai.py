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


# =========================================================
# 第二層：料理 / 原料理解
# =========================================================

RECIPE_PROMPT = """
你是熟悉台灣飲食、外食、早餐店、便利商店、
便當、自助餐與家常料理的料理結構分析系統。

第一層視覺 AI 已經辨識出照片中的食物。
你現在不需要重新看圖片，也不要推翻第一層的辨識。

你的任務是：

「理解這些食物本身是什麼，以及料理通常由哪些
具有營養意義的主要成分組成。」

━━━━━━━━━━━━━━━━━━
【1. 單一食材不要亂拆】
━━━━━━━━━━━━━━━━━━

如果本身就是單一或接近單一食材，例如：

水煮蛋
香蕉
地瓜
白飯
玉米
雞胸肉
鮭魚
花椰菜
豆腐
毛豆

直接保留這個食物。

例如：

水煮蛋
→ 水煮蛋

不要拆成：
蛋白＋蛋黃

香蕉
→ 香蕉

不要幻想其他成分。

━━━━━━━━━━━━━━━━━━
【2. 複合料理才拆解】
━━━━━━━━━━━━━━━━━━

如果是由多種食材組成的料理，
理解其主要營養來源。

例如：

原味蛋餅
→ 蛋餅皮
→ 雞蛋
→ 煎製用油

起司蛋餅
→ 蛋餅皮
→ 雞蛋
→ 起司
→ 煎製用油

鮪魚蛋餅
→ 蛋餅皮
→ 雞蛋
→ 鮪魚
→ 煎製用油
→ 可能含少量美乃滋

雞腿便當
不能只理解成「一個雞腿便當」。

如果第一層已辨識出：
白飯、雞腿、高麗菜、豆干、滷蛋

就應分別保留這些項目。

━━━━━━━━━━━━━━━━━━
【3. 區分確定與推定】
━━━━━━━━━━━━━━━━━━

ingredient_source 必須標示：

"direct"
= 第一層直接辨識到的食物，
或該食物本身就是單一食材。

"recipe"
= 根據料理名稱，可以合理確定的基本組成。

"possible"
= 常見但不能確定一定存在的成分。

例如鮪魚蛋餅：

蛋餅皮 → recipe
雞蛋 → recipe
鮪魚 → recipe
煎製用油 → recipe

美乃滋 → possible

不要把 possible 當成一定有。

━━━━━━━━━━━━━━━━━━
【4. 避免重複計算】
━━━━━━━━━━━━━━━━━━

這非常重要。

如果第一層已經分別辨識：

白飯
雞腿
高麗菜
滷蛋

不要第二層又額外新增：

「雞腿便當」

否則後續熱量會重複計算。

同樣：

如果第一層辨識：
水煮蛋 × 2

不要再另外新增：
雞蛋 × 2

保留「水煮蛋 × 2」即可。

━━━━━━━━━━━━━━━━━━
【5. 烹調方式】
━━━━━━━━━━━━━━━━━━

盡可能判斷或推定：

boiled = 水煮
steamed = 蒸
grilled = 烤
pan_fried = 煎
stir_fried = 炒
deep_fried = 油炸
braised = 滷
raw = 生食
unknown = 無法判斷

如果第一層名稱已經明確包含烹調方式：

水煮蛋 → boiled
炸雞 → deep_fried
滷蛋 → braised

直接使用。

不要無根據亂猜。

━━━━━━━━━━━━━━━━━━
【6. 隱藏熱量來源】
━━━━━━━━━━━━━━━━━━

料理理解時要特別注意：

食用油
美乃滋
沙拉醬
奶油
起司
糖
肉燥
濃稠醬汁
花生醬
芝麻醬

但只有：

料理基本上必然需要
或
非常常見且具有營養影響

才列入。

不確定就標示 possible。

━━━━━━━━━━━━━━━━━━
【7. 台灣飲食情境】
━━━━━━━━━━━━━━━━━━

你應熟悉台灣常見料理的典型組成，
但不能因為「通常如此」就假裝照片證明了它。

料理知識是用來補充視覺辨識，
不是取代視覺證據。

━━━━━━━━━━━━━━━━━━
【8. 這一層仍然不要算熱量】
━━━━━━━━━━━━━━━━━━

不要提供：

kcal
蛋白質
碳水
脂肪
纖維
鈉
健康評分
飲食建議

第三層營養系統會負責。

你的工作只有：

「把食物理解正確，建立可供營養計算的料理結構。」
"""


RECIPE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "original_name": {
                        "type": "string"
                    },
                    "is_composite_dish": {
                        "type": "boolean"
                    },
                    "cooking_method": {
                        "type": "string",
                        "enum": [
                            "boiled",
                            "steamed",
                            "grilled",
                            "pan_fried",
                            "stir_fried",
                            "deep_fried",
                            "braised",
                            "raw",
                            "unknown"
                        ]
                    },
                    "ingredients": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string"
                                },
                                "ingredient_source": {
                                    "type": "string",
                                    "enum": [
                                        "direct",
                                        "recipe",
                                        "possible"
                                    ]
                                },
                                "quantity_description": {
                                    "type": [
                                        "string",
                                        "null"
                                    ]
                                }
                            },
                            "required": [
                                "name",
                                "ingredient_source",
                                "quantity_description"
                            ],
                            "additionalProperties": False
                        }
                    }
                },
                "required": [
                    "original_name",
                    "is_composite_dish",
                    "cooking_method",
                    "ingredients"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": [
        "items"
    ],
    "additionalProperties": False
}


def understand_recipes(vision_data):
    """
    第一層辨識結果 → 第二層料理結構
    """

    food_data = {
        "foods": vision_data.get(
            "foods",
            []
        )
    }

    response = client.responses.create(
        model="gpt-5.6",

        instructions=RECIPE_PROMPT,

        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "以下是第一層視覺辨識結果：\n"
                            + json.dumps(
                                food_data,
                                ensure_ascii=False
                            )
                            + "\n\n"
                            "請進行料理與原料結構分析。"
                        )
                    }
                ]
            }
        ],

        text={
            "format": {
                "type": "json_schema",
                "name": "recipe_understanding",
                "strict": True,
                "schema": RECIPE_SCHEMA
            }
        }
    )

    return json.loads(
        response.output_text
    )

# =========================================================
# 第三層：營養估算 / 合理性檢查
# =========================================================

NUTRITION_PROMPT = """
你是熟悉台灣飲食的營養估算系統。

你會收到：

1. 第一層的食物辨識結果
2. 第二層的料理 / 原料理解結果

你的任務是根據：
食物種類、數量、估計重量、料理組成與烹調方式，
估算這一餐的營養。

━━━━━━━━━━━━━━━━━━
【1. 營養項目】
━━━━━━━━━━━━━━━━━━

每項食物估算：

- 熱量 kcal
- 蛋白質 protein_g
- 碳水 carbohydrate_g
- 脂肪 fat_g
- 膳食纖維 fiber_g
- 鈉 sodium_mg

並計算整餐總和。

━━━━━━━━━━━━━━━━━━
【2. 份量優先】
━━━━━━━━━━━━━━━━━━

如果第一層有 estimated_grams，
優先使用重量計算。

如果沒有重量，
才依照台灣常見份量估計。

例如：

水煮蛋 1 顆
應以一般雞蛋可食份量估算。

白飯 1 碗
應以台灣常見一碗熟飯份量估算。

不要假裝知道照片無法支持的精確重量。

━━━━━━━━━━━━━━━━━━
【3. 複合料理】
━━━━━━━━━━━━━━━━━━

複合料理使用第二層 ingredients 理解營養來源。

例如：

原味蛋餅：
蛋餅皮 + 雞蛋 + 合理煎油量

鮪魚蛋餅：
蛋餅皮 + 雞蛋 + 鮪魚 + 煎油
possible 的美乃滋不可直接當成確定存在。

ingredient_source = "possible"
的成分：

如果沒有其他證據，
不要直接完整計入總熱量。

可以用 uncertainty_note 提醒。

━━━━━━━━━━━━━━━━━━
【4. 烹調油】
━━━━━━━━━━━━━━━━━━

煎、炒、炸料理要考慮合理的吸油量。

但不要因為看到「煎」
就假設使用大量油脂。

依台灣一般餐飲合理估計。

油炸食品則必須考慮吸油造成的熱量。

━━━━━━━━━━━━━━━━━━
【5. 飲料】
━━━━━━━━━━━━━━━━━━

如果第一層只能辨識為「飲料」，
不要擅自猜糖量與營養。

這種情況：
nutrition_confidence 應降低，
並在 uncertainty_note 說明
需要飲料名稱或營養標示才能更準。

如果明確辨識為：
無糖豆漿、鮮奶、美式咖啡等，
才可以合理估算。

━━━━━━━━━━━━━━━━━━
【6. 不製造假精準】
━━━━━━━━━━━━━━━━━━

這是外食照片估算工具。

營養數值本來就存在誤差。

不要因為 JSON 需要數字，
就假裝結果精確到實驗室程度。

數字可以使用合理的近似值。

例如：
76 kcal
可以。

但不要因為估算而寫：
76.348 kcal

━━━━━━━━━━━━━━━━━━
【7. 熱量合理性檢查】
━━━━━━━━━━━━━━━━━━

完成後必須自行檢查：

蛋白質 × 4
+
碳水 × 4
+
脂肪 × 9

應與估計熱量大致合理。

因為纖維、酒精、糖醇、標示差異、
四捨五入等因素，
不要求完全相等。

但如果差距非常大，
必須重新檢查估算。

━━━━━━━━━━━━━━━━━━
【8. 總和檢查】
━━━━━━━━━━━━━━━━━━

所有 food_items 的：

calories
protein_g
carbohydrate_g
fat_g
fiber_g
sodium_mg

加總後，
應與 totals 大致一致。

禁止前後數字互相矛盾。

━━━━━━━━━━━━━━━━━━
【9. 營養信心】
━━━━━━━━━━━━━━━━━━

nutrition_confidence 表示：
「這項營養估算有多可靠」。

它和第一層的圖片辨識 confidence 不完全相同。

例如：

AI 可能 99% 確定那是蛋餅，
但不知道早餐店用了多少油。

因此：

food recognition confidence = 高
nutrition confidence = 中高

這是正常的。

━━━━━━━━━━━━━━━━━━
【10. 資料來源類型】
━━━━━━━━━━━━━━━━━━

目前第三層尚未連接正式食品資料庫。

因此 nutrition_source 必須誠實標示：

"ai_estimate"

禁止假裝數值來自：
政府資料庫
品牌官方資料
食品包裝營養標示

未來系統接入正式資料來源後，
才可以使用其他 source。

━━━━━━━━━━━━━━━━━━
【11. 不要在這層做人性化聊天】
━━━━━━━━━━━━━━━━━━

這層只負責可靠的營養資料。

不要：

- 毒舌
- 稱讚
- 評分
- 減肥建議
- 寫長篇文章

朋友式回覆會由最後的呈現層負責。

專業計算與人格必須分開。
"""


NUTRITION_SCHEMA = {
    "type": "object",
    "properties": {

        "food_items": {
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

                    "calories": {
                        "type": "number"
                    },

                    "protein_g": {
                        "type": "number"
                    },

                    "carbohydrate_g": {
                        "type": "number"
                    },

                    "fat_g": {
                        "type": "number"
                    },

                    "fiber_g": {
                        "type": "number"
                    },

                    "sodium_mg": {
                        "type": "number"
                    },

                    "nutrition_confidence": {
                        "type": "number"
                    },

                    "nutrition_source": {
                        "type": "string",
                        "enum": [
                            "ai_estimate"
                        ]
                    },

                    "uncertainty_note": {
                        "type": [
                            "string",
                            "null"
                        ]
                    }
                },

                "required": [
                    "name",
                    "quantity",
                    "unit",
                    "estimated_grams",
                    "calories",
                    "protein_g",
                    "carbohydrate_g",
                    "fat_g",
                    "fiber_g",
                    "sodium_mg",
                    "nutrition_confidence",
                    "nutrition_source",
                    "uncertainty_note"
                ],

                "additionalProperties": False
            }
        },

        "totals": {
            "type": "object",
            "properties": {

                "calories": {
                    "type": "number"
                },

                "protein_g": {
                    "type": "number"
                },

                "carbohydrate_g": {
                    "type": "number"
                },

                "fat_g": {
                    "type": "number"
                },

                "fiber_g": {
                    "type": "number"
                },

                "sodium_mg": {
                    "type": "number"
                }
            },

            "required": [
                "calories",
                "protein_g",
                "carbohydrate_g",
                "fat_g",
                "fiber_g",
                "sodium_mg"
            ],

            "additionalProperties": False
        },

        "overall_nutrition_confidence": {
            "type": "number"
        },

        "overall_uncertainty_note": {
            "type": [
                "string",
                "null"
            ]
        }
    },

    "required": [
        "food_items",
        "totals",
        "overall_nutrition_confidence",
        "overall_uncertainty_note"
    ],

    "additionalProperties": False
}


def estimate_nutrition(
    vision_data,
    recipe_data
):
    """
    第一層 + 第二層
    → 第三層營養估算
    """

    analysis_input = {
        "vision": vision_data,
        "recipe": recipe_data
    }

    response = client.responses.create(
        model="gpt-5.6",

        instructions=NUTRITION_PROMPT,

        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "請根據以下資料估算營養：\n\n"
                            + json.dumps(
                                analysis_input,
                                ensure_ascii=False
                            )
                        )
                    }
                ]
            }
        ],

        text={
            "format": {
                "type": "json_schema",
                "name": "nutrition_analysis",
                "strict": True,
                "schema": NUTRITION_SCHEMA
            }
        }
    )

    return json.loads(
        response.output_text
    )

