import os
import json
import time

from openai import OpenAI


# =========================================================
# OpenAI
# =========================================================

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

client = OpenAI(
    api_key=OPENAI_API_KEY
)

MODEL = "gpt-5.4-mini"


# =========================================================
# 食物分析核心 Prompt
# =========================================================

FOOD_SYSTEM_PROMPT = """
你是台灣使用者的 AI 飲食辨識與營養紀錄助手。

你的產品目標：

1. 快速
2. 準確
3. 方便
4. 專業
5. 像朋友一樣自然

這是一個實際拿來記錄每天飲食的工具，
不是圖片鑑識報告。

━━━━━━━━━━━━━━━━━━
【分析流程】
━━━━━━━━━━━━━━━━━━

看到餐點照片後，在一次分析中完成：

第一層：辨識照片中的食物

第二層：理解料理本身

第三層：推估料理可能包含的原料與烹調方式

第四層：推估份量

第五層：估算營養

不要把這些步驟拆成多次回答。

━━━━━━━━━━━━━━━━━━
【1. 食物辨識】
━━━━━━━━━━━━━━━━━━

辨識時綜合：

- 形狀
- 顏色
- 表面質地
- 切面
- 肉類纖維
- 脂肪分布
- 大小
- 厚度
- 數量
- 煎烤痕跡
- 容器
- 餐具
- 包裝
- 配菜
- 食物彼此比例
- 台灣常見飲食情境

不要因為單一特徵就亂猜。

例如：

白色圓形食物不能只因為白色，
就在水煮蛋、包子、饅頭、魚丸之間亂猜。

如果外型、尺寸、表面與飲食情境
高度符合完整去殼雞蛋，
應優先判定為水煮蛋。

肉排要綜合：

肉纖維
油脂
厚度
形狀
煎烤痕跡
料理情境

判斷牛肉、豬肉或雞肉。

━━━━━━━━━━━━━━━━━━
【2. 不要過度猶豫】
━━━━━━━━━━━━━━━━━━

這是一個飲食紀錄工具。

如果最可能答案已經很明顯，
直接採用最合理答案。

不要一直回答：

「可能是A，也可能是B，也可能是C。」

confidence >= 0.75：
直接判斷。

confidence 0.55～0.74：
採用最可能答案，
但 confidence 設為 medium。

confidence < 0.55：
confidence 設為 low。

即使 confidence 是 low，
仍然要給出最合理的暫時估計，
讓使用者之後可以直接修正。

━━━━━━━━━━━━━━━━━━
【3. 台灣飲食知識】
━━━━━━━━━━━━━━━━━━

熟悉台灣常見：

早餐店
便當
自助餐
超商
夜市
麵店
火鍋
健身餐
日式定食
韓式料理
西式餐點
家庭料理
飲料店

例如：

水煮蛋
茶葉蛋
荷包蛋
蛋餅
蘿蔔糕
飯糰
饅頭
包子
吐司
三明治
漢堡
鐵板麵
地瓜
玉米
白飯
糙米飯
雞胸肉
雞腿
牛排
豬排
排骨
滷肉
雞肉飯
滷肉飯
便當
豆腐
豆干
水餃
鍋貼
牛肉麵
乾麵
鹽水雞
滷味
御飯糰
舒肥雞胸
豆漿
鮮奶
拿鐵
奶茶
無糖茶

━━━━━━━━━━━━━━━━━━
【4. 料理理解】
━━━━━━━━━━━━━━━━━━

不能只辨識表面名稱。

例如：

蛋餅
→ 蛋 + 餅皮 + 合理的煎油

雞肉飯
→ 白飯 + 雞肉 + 合理的雞油或醬汁

鮪魚蛋吐司
→ 吐司 + 雞蛋 + 鮪魚餡
+ 視料理情況考慮少量美乃滋

牛排定食
→ 牛排 + 合理的煎烤油或醬汁
+ 照片實際看到的白飯與配菜

鍋貼
→ 麵皮 + 肉菜餡 + 合理煎油

但是：

不要加入照片完全沒有依據、
料理本身也不合理需要的食材。

━━━━━━━━━━━━━━━━━━
【5. 份量推估】
━━━━━━━━━━━━━━━━━━

參考：

餐盤
碗
杯子
筷子
湯匙
便當盒
包裝
食物彼此比例
台灣一般外食份量

沒有秤重資訊時，
採用合理估算。

不要製造假的精確度。

例如不要假裝知道：

137 g

如果只能合理判斷約一份，
quantity 可以寫：

約1份

estimated_grams 則提供合理估計值。

━━━━━━━━━━━━━━━━━━
【6. 營養估算】
━━━━━━━━━━━━━━━━━━

每項食物估算：

calories
protein
carbs
fat
fiber
sodium

注意可能存在：

煎炒油
炸物吸油
醬汁
糖
奶油
美乃滋
起司
肉燥
內餡

但不要誇大照片無法支持的隱藏熱量。

所有 food 項目加總，
必須與 total 大致一致。

━━━━━━━━━━━━━━━━━━
【7. 使用者修正最優先】
━━━━━━━━━━━━━━━━━━

如果使用者明確告訴你：

「這是牛排不是豬排」

那就是牛排。

不要跟使用者爭論。

如果使用者說：

「白飯只有半碗」

就把白飯修改成半碗，
並重新計算營養。

如果使用者說：

「豆漿是無糖」

就依無糖豆漿重新估算。

如果使用者說：

「我沒有吃那個」

就刪除那項食物並重新計算。

如果使用者說：

「其實有兩顆蛋」

就修改數量並重新計算。

使用者提供的明確資訊，
優先於先前的影像推測。

━━━━━━━━━━━━━━━━━━
【8. 評語風格】
━━━━━━━━━━━━━━━━━━

像一個懂營養又熟的朋友。

可以：

自然
有梗
稍微毒舌
偶爾吐槽

但不要：

羞辱體重
羞辱身材
羞辱外貌
製造飲食焦慮

吐槽最多一句。

例如：

「蛋白質有在上班，這餐可以 😎」

「菜是有出現啦，但這個量比較像來點名的 😂」

「牛排本人沒什麼問題，醬汁才是躲在後面的熱量刺客。」

「好喔，今天碳水有點熱情 😂」

━━━━━━━━━━━━━━━━━━
【9. meal_name】
━━━━━━━━━━━━━━━━━━

meal_name 要簡潔、自然。

例如：

牛排定食
雞胸健康餐
蛋餅＋豆漿
雞腿便當

不要產生很長的名稱。

━━━━━━━━━━━━━━━━━━
【10. 最重要原則】
━━━━━━━━━━━━━━━━━━

這個系統的用途是：

讓使用者在外食、
沒有電子秤、
無法精準測量時，

可以快速得到一個
實用且合理的飲食紀錄。

不要因為追求理論上的100%確定，
讓產品變得很難用。
"""


# =========================================================
# JSON Schema
# =========================================================

FOOD_SCHEMA = {
    "type": "object",
    "properties": {

        "meal_name": {
            "type": "string"
        },

        "foods": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {

                    "name": {
                        "type": "string"
                    },

                    "quantity": {
                        "type": "string"
                    },

                    "estimated_grams": {
                        "type": "number"
                    },

                    "calories": {
                        "type": "number"
                    },

                    "protein": {
                        "type": "number"
                    },

                    "carbs": {
                        "type": "number"
                    },

                    "fat": {
                        "type": "number"
                    },

                    "fiber": {
                        "type": "number"
                    },

                    "sodium": {
                        "type": "number"
                    },

                    "confidence": {
                        "type": "number"
                    }
                },

                "required": [
                    "name",
                    "quantity",
                    "estimated_grams",
                    "calories",
                    "protein",
                    "carbs",
                    "fat",
                    "fiber",
                    "sodium",
                    "confidence"
                ],

                "additionalProperties": False
            }
        },

        "total": {
            "type": "object",
            "properties": {

                "calories": {
                    "type": "number"
                },

                "protein": {
                    "type": "number"
                },

                "carbs": {
                    "type": "number"
                },

                "fat": {
                    "type": "number"
                },

                "fiber": {
                    "type": "number"
                },

                "sodium": {
                    "type": "number"
                }
            },

            "required": [
                "calories",
                "protein",
                "carbs",
                "fat",
                "fiber",
                "sodium"
            ],

            "additionalProperties": False
        },

        "confidence": {
            "type": "string",
            "enum": [
                "high",
                "medium",
                "low"
            ]
        },

        "comment": {
            "type": "string"
        }
    },

    "required": [
        "meal_name",
        "foods",
        "total",
        "confidence",
        "comment"
    ],

    "additionalProperties": False
}


# =========================================================
# 共用：Structured Output
# =========================================================

def _response_to_food_data(response):

    text = response.output_text.strip()

    data = json.loads(text)

    return data


# =========================================================
# 第一次分析照片
# =========================================================

def analyze_food_image(image_data_url):

    start_time = time.time()

    response = client.responses.create(

        model=MODEL,

        reasoning={
            "effort": "none"
        },

        instructions=FOOD_SYSTEM_PROMPT,

        input=[
            {
                "role": "user",
                "content": [

                    {
                        "type": "input_text",
                        "text":
                            "分析這張餐點照片。"
                            "請辨識照片中的食物、理解料理、"
                            "估算份量與營養。"
                    },

                    {
                        "type": "input_image",
                        "image_url": image_data_url,
                        "detail": "high"
                    }
                ]
            }
        ],

        text={
            "format": {
                "type": "json_schema",
                "name": "food_analysis",
                "strict": True,
                "schema": FOOD_SCHEMA
            },
            "verbosity": "low"
        },

        max_output_tokens=1800,

        store=False
    )

    data = _response_to_food_data(
        response
    )

    elapsed = time.time() - start_time

    print(
        f"FOOD_AI_ANALYSIS_TIME: {elapsed:.2f}s",
        flush=True
    )

    return data


# =========================================================
# 修正上一餐
# =========================================================

def correct_food_analysis(
    previous_meal,
    correction_text
):

    start_time = time.time()

    previous_data = {
        "meal_name": previous_meal.get(
            "meal_name",
            "這一餐"
        ),

        "foods": previous_meal.get(
            "foods",
            []
        ),

        "total": {
            "calories": float(
                previous_meal.get(
                    "calories",
                    0
                )
            ),

            "protein": float(
                previous_meal.get(
                    "protein",
                    0
                )
            ),

            "carbs": float(
                previous_meal.get(
                    "carbs",
                    0
                )
            ),

            "fat": float(
                previous_meal.get(
                    "fat",
                    0
                )
            ),

            "fiber": float(
                previous_meal.get(
                    "fiber",
                    0
                )
            ),

            "sodium": float(
                previous_meal.get(
                    "sodium",
                    0
                )
            )
        },

        "confidence": previous_meal.get(
            "ai_confidence"
        ) or "medium",

        "comment": previous_meal.get(
            "ai_comment"
        ) or ""
    }

    prompt = f"""
以下是上一餐目前的分析結果：

{json.dumps(
    previous_data,
    ensure_ascii=False
)}

使用者現在明確補充或修正：

「{correction_text}」

請以使用者提供的新資訊為最高優先。

你必須：

1. 修改受影響的食物
2. 保留沒有被修正的其他食物
3. 重新估算受影響食物的營養
4. 重新計算整餐 total
5. 更新 meal_name（如果有必要）
6. 產生新的簡短 comment

例如：

豬排 → 牛排
必須重新估算肉類營養。

白飯一碗 → 半碗
必須修改白飯份量與營養。

有糖豆漿 → 無糖豆漿
必須重新估算飲料。

「沒有吃醃菜」
必須把醃菜刪掉。

不要只是回覆使用者一句話。
要輸出修正後完整的一餐資料。
"""

    response = client.responses.create(

        model=MODEL,

        reasoning={
            "effort": "none"
        },

        instructions=FOOD_SYSTEM_PROMPT,

        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": prompt
                    }
                ]
            }
        ],

        text={
            "format": {
                "type": "json_schema",
                "name": "corrected_food_analysis",
                "strict": True,
                "schema": FOOD_SCHEMA
            },
            "verbosity": "low"
        },

        max_output_tokens=1800,

        store=False
    )

    data = _response_to_food_data(
        response
    )

    elapsed = time.time() - start_time

    print(
        f"FOOD_AI_CORRECTION_TIME: {elapsed:.2f}s",
        flush=True
    )

    return data
