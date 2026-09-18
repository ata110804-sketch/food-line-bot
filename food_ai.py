import os
import json
import time

from openai import OpenAI


# =========================================================
# OpenAI 設定
# =========================================================

client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"]
)

MODEL = "gpt-5.4-mini"


# =========================================================
# AI 食物分析核心 Prompt
# =========================================================

FOOD_SYSTEM_PROMPT = """
你是一位專門服務台灣使用者的
AI 飲食影像辨識、營養分析與飲食紀錄助手。

這是一個實際每天使用的飲食紀錄工具。

你的產品目標依序是：

1. 準確
2. 快速
3. 方便
4. 專業
5. 自然
6. 像熟悉使用者的朋友

━━━━━━━━━━━━━━━━━━
【一、影像辨識流程】
━━━━━━━━━━━━━━━━━━

收到餐點照片時，
必須在一次分析中完成：

第一層：
辨識照片實際出現的食物。

第二層：
理解該料理通常由什麼組成。

第三層：
根據照片與料理知識，
推估合理的原料與烹調方式。

第四層：
估計實際可食份量。

第五層：
估算營養素。

不要拆成多次 AI 分析。

━━━━━━━━━━━━━━━━━━
【二、辨識食物】
━━━━━━━━━━━━━━━━━━

辨識時綜合：

- 形狀
- 顏色
- 表面質地
- 切面
- 食物纖維
- 肉類紋理
- 脂肪分布
- 大小
- 厚度
- 數量
- 煎烤痕跡
- 餐具
- 碗盤
- 杯子
- 包裝
- 配菜
- 食物彼此比例
- 台灣常見飲食情境

不能只依單一視覺特徵判斷。

例如：

白色圓形食物不能只因為白色，
就在：

水煮蛋
饅頭
包子
魚丸
麻糬

之間亂猜。

應該綜合：

尺寸
表面
形狀
排列方式
附近食物
早餐／便當／超商等情境

進行判斷。

━━━━━━━━━━━━━━━━━━
【三、不要過度猶豫】
━━━━━━━━━━━━━━━━━━

這不是刑事鑑識。

這是一個日常飲食紀錄工具。

如果圖片中的最可能答案已經明顯，
直接採用最合理答案。

不要一直輸出：

「可能是 A」
「也可能是 B」
「也可能是 C」

讓使用者自己選。

如果有合理答案，
先完成紀錄。

使用者之後可以直接修正。

confidence：

0.75 以上：
直接判斷。

0.55～0.74：
採用最可能答案，
整體 confidence 可設 medium。

低於 0.55：
仍然提供最合理暫時估計，
整體 confidence 可設 low。

不要因為不確定就拒絕計算整餐。

━━━━━━━━━━━━━━━━━━
【四、熟悉台灣飲食】
━━━━━━━━━━━━━━━━━━

你必須熟悉台灣常見：

早餐店
便當店
自助餐
便利商店
夜市
麵店
火鍋
健身餐
家庭料理
日式料理
韓式料理
西式料理
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
雞胸
雞腿
牛排
豬排
排骨
滷肉
雞肉飯
滷肉飯
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

台灣常見程度是輔助判斷，
不能凌駕照片本身。

━━━━━━━━━━━━━━━━━━
【五、理解料理】
━━━━━━━━━━━━━━━━━━

不要只辨識表面的食物名稱。

例如：

蛋餅
=
雞蛋
+
餅皮
+
合理煎油

雞肉飯
=
白飯
+
雞肉
+
合理雞油／醬汁

鮪魚蛋吐司
=
吐司
+
雞蛋
+
鮪魚餡
+
依料理合理考慮少量美乃滋

鍋貼
=
麵皮
+
肉菜餡
+
合理煎油

牛排定食
=
牛排
+
合理煎烤油／醬汁
+
照片實際看到的白飯與配菜

但是：

不要加入照片沒有證據、
料理本身也沒有合理必要性的食材。

━━━━━━━━━━━━━━━━━━
【六、份量估計】
━━━━━━━━━━━━━━━━━━

參考：

碗
盤
杯子
筷子
湯匙
便當盒
食物數量
食物與容器比例
食物彼此比例
台灣一般外食份量

沒有電子秤時，
提供合理估計。

不要製造假的精確度。

例如：

不要假裝非常確定是 137 g。

可以：

quantity：
約半碗

estimated_grams：
100

或：

quantity：
1顆

estimated_grams：
55

estimated_grams 是供系統計算使用，
可以是合理中心估計值。

━━━━━━━━━━━━━━━━━━
【七、營養估算】
━━━━━━━━━━━━━━━━━━

每一項食物都估算：

calories
protein
carbs
fat
fiber
sodium

需要合理考慮：

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

所有 food 項目的營養加總，
必須與 total 大致一致。

━━━━━━━━━━━━━━━━━━
【八、使用者修正優先】
━━━━━━━━━━━━━━━━━━

使用者對自己吃的東西
擁有最高優先權。

例如使用者說：

「這是牛排不是豬排」

就修改成牛排，
重新估算牛排營養。

使用者說：

「飯只有半碗」

就修改白飯份量，
重新計算。

使用者說：

「豆漿是無糖」

就按照無糖豆漿重新估算。

使用者說：

「那個我沒有吃」

就刪除那項食物。

使用者說：

「我只吃一半」

就依實際吃掉的比例重新估算。

不要跟使用者爭論。

━━━━━━━━━━━━━━━━━━
【九、食物記憶】
━━━━━━━━━━━━━━━━━━

系統可能提供：

「使用者食物記憶」

例如：

- 我固定喝無糖豆漿
- 這家的雞胸一包是 120 g
- 我的早餐咖啡通常不加糖
- 這個便當通常是半碗飯

這些資料代表使用者過去明確提供的資訊。

使用方式：

如果照片中的食物與記憶
合理相符，
可以優先參考。

但是不能盲目套用。

例如使用者記憶中有：

「固定喝無糖豆漿」

但照片明顯是一杯珍珠奶茶，
不能硬判定成豆漿。

記憶是個人化先驗資訊，
不是絕對答案。

━━━━━━━━━━━━━━━━━━
【十、評語風格】
━━━━━━━━━━━━━━━━━━

像一個懂營養、
又跟使用者很熟的朋友。

可以：

自然
有梗
稍微毒舌
偶爾吐槽

例如：

「蛋白質有在上班，這餐可以 😎」

「菜是有出現啦，但這個量比較像來點名的 😂」

「牛排本人沒什麼問題，醬汁才是後面的熱量刺客。」

「今天碳水有點熱情喔 😂」

但是禁止：

羞辱體重
羞辱身材
羞辱外貌
製造飲食焦慮
鼓勵極端節食

吐槽最多一句。

━━━━━━━━━━━━━━━━━━
【十一、meal_name】
━━━━━━━━━━━━━━━━━━

meal_name 必須：

簡短
自然
方便閱讀

例如：

雞腿健康餐
牛排定食
蛋餅＋豆漿
雞腿便當

不要寫成一大串料理描述。

━━━━━━━━━━━━━━━━━━
【十二、最重要原則】
━━━━━━━━━━━━━━━━━━

使用者需要的是：

外食時，
沒有電子秤時，
沒有營養標示時，

快速得到一個
「實用且合理」
的飲食紀錄。

不要為了追求理論上的 100% 確定，
把產品變得很難用。
"""


# =========================================================
# 食物分析 JSON Schema
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
# 自然語言意圖 Schema
# =========================================================

INTENT_SCHEMA = {

    "type": "object",

    "properties": {

        "intent": {

            "type": "string",

            "enum": [
                "profile",
                "correct_last",
                "delete_last",
                "add_to_last",
                "today",
                "remaining",
                "meal_advice",
                "remember_food",
                "food_question",
                "other"
            ]
        },

        "reply": {
            "type": "string"
        },

        "profile": {

            "type": [
                "object",
                "null"
            ],

            "properties": {

                "height_cm": {
                    "type": [
                        "number",
                        "null"
                    ]
                },

                "weight_kg": {
                    "type": [
                        "number",
                        "null"
                    ]
                },

                "age": {
                    "type": [
                        "integer",
                        "null"
                    ]
                },

                "sex": {
                    "type": [
                        "string",
                        "null"
                    ]
                },

                "activity_level": {
                    "type": [
                        "string",
                        "null"
                    ]
                },

                "goal": {
                    "type": [
                        "string",
                        "null"
                    ]
                }
            },

            "required": [
                "height_cm",
                "weight_kg",
                "age",
                "sex",
                "activity_level",
                "goal"
            ],

            "additionalProperties": False
        },

        "memory_text": {
            "type": [
                "string",
                "null"
            ]
        }
    },

    "required": [
        "intent",
        "reply",
        "profile",
        "memory_text"
    ],

    "additionalProperties": False
}


# =========================================================
# Structured Output 共用函式
# =========================================================

def structured_response(
    instructions,
    text,
    schema,
    schema_name,
    image_url=None,
    max_tokens=1600
):

    content = [

        {
            "type": "input_text",
            "text": text
        }
    ]

    if image_url:

        content.append(
            {
                "type": "input_image",
                "image_url": image_url,
                "detail": "high"
            }
        )

    response = client.responses.create(

        model=MODEL,

        reasoning={
            "effort": "none"
        },

        instructions=instructions,

        input=[
            {
                "role": "user",
                "content": content
            }
        ],

        text={
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": schema
            },

            "verbosity": "low"
        },

        max_output_tokens=max_tokens,

        store=False
    )

    return json.loads(
        response.output_text.strip()
    )


# =========================================================
# 第一次分析照片
# =========================================================

def analyze_food_image(
    image_data_url,
    memories=None
):

    start_time = time.time()

    memory_lines = []

    for memory in memories or []:

        memory_text = memory.get(
            "memory_text",
            ""
        )

        if memory_text:

            memory_lines.append(
                f"- {memory_text}"
            )

    prompt = """
分析這張餐點照片。

請一次完成：

1. 食物辨識
2. 料理理解
3. 份量估算
4. 營養估算
5. 整餐總計
6. 簡短飲食評語

答案明顯時直接判斷，
不要把使用者丟回選擇題。
"""

    if memory_lines:

        prompt += (
            "\n\n"
            "以下是這位使用者過去明確提供的"
            "個人食物記憶。\n"
            "只有在照片合理相符時才參考：\n\n"
            + "\n".join(memory_lines)
        )

    data = structured_response(

        FOOD_SYSTEM_PROMPT,

        prompt,

        FOOD_SCHEMA,

        "food_analysis",

        image_url=image_data_url,

        max_tokens=1600
    )

    elapsed = (
        time.time()
        - start_time
    )

    print(
        f"FOOD_AI_ANALYSIS_TIME: "
        f"{elapsed:.2f}s",
        flush=True
    )

    return data


# =========================================================
# 把資料庫上一餐轉成 AI 可以理解的格式
# =========================================================

def meal_to_dict(
    previous_meal
):

    return {

        "meal_name":
            previous_meal.get(
                "meal_name",
                "這一餐"
            ),

        "foods":
            previous_meal.get(
                "foods",
                []
            ),

        "total": {

            "calories":
                float(
                    previous_meal.get(
                        "calories",
                        0
                    )
                    or 0
                ),

            "protein":
                float(
                    previous_meal.get(
                        "protein",
                        0
                    )
                    or 0
                ),

            "carbs":
                float(
                    previous_meal.get(
                        "carbs",
                        0
                    )
                    or 0
                ),

            "fat":
                float(
                    previous_meal.get(
                        "fat",
                        0
                    )
                    or 0
                ),

            "fiber":
                float(
                    previous_meal.get(
                        "fiber",
                        0
                    )
                    or 0
                ),

            "sodium":
                float(
                    previous_meal.get(
                        "sodium",
                        0
                    )
                    or 0
                )
        },

        "confidence":
            previous_meal.get(
                "ai_confidence"
            )
            or "medium",

        "comment":
            previous_meal.get(
                "ai_comment"
            )
            or ""
    }


# =========================================================
# 修正上一餐
# =========================================================

def correct_food_analysis(
    previous_meal,
    correction_text
):

    start_time = time.time()

    previous_data = meal_to_dict(
        previous_meal
    )

    prompt = f"""
以下是上一餐目前的完整紀錄：

{json.dumps(
    previous_data,
    ensure_ascii=False
)}

使用者現在明確修正：

「{correction_text}」

使用者提供的資訊優先。

你必須：

1. 找出被修正的食物
2. 修改該食物
3. 保留沒有被修正的其他食物
4. 重新估算受影響項目的營養
5. 重新計算整餐 total
6. 必要時更新 meal_name
7. 重新產生簡短 comment

例如：

「這是牛排不是豬排」
→ 把豬排改成牛排並重算。

「飯只有半碗」
→ 修改白飯份量並重算。

「豆漿是無糖」
→ 改成無糖豆漿並重算。

「那個我沒有吃」
→ 移除對應項目並重算。

「我只吃一半」
→ 將對應食物改成實際吃掉的一半。

不要只回覆一句：
「好的已修正。」

必須輸出修正後完整餐點資料。
"""

    data = structured_response(

        FOOD_SYSTEM_PROMPT,

        prompt,

        FOOD_SCHEMA,

        "corrected_food_analysis",

        max_tokens=1600
    )

    print(
        "FOOD_AI_CORRECTION_TIME: "
        f"{time.time() - start_time:.2f}s",
        flush=True
    )

    return data


# =========================================================
# 在上一餐新增食物
# =========================================================

def add_food_to_analysis(
    previous_meal,
    text
):

    start_time = time.time()

    previous_data = meal_to_dict(
        previous_meal
    )

    prompt = f"""
以下是使用者目前的上一餐：

{json.dumps(
    previous_data,
    ensure_ascii=False
)}

使用者現在說：

「{text}」

這句話的意思是：

使用者要把新的食物或飲料
加入上一餐紀錄。

例如：

「再加一顆蛋」
「還有一根香蕉」
「我還喝了一杯無糖豆漿」
「漏掉一個地瓜」

請：

1. 保留原本所有食物
2. 新增使用者說的食物
3. 合理估計新增食物份量
4. 計算新增食物營養
5. 重新計算整餐 total
6. 必要時更新 meal_name
7. 重新產生簡短 comment

不要刪除原本沒有被提及的食物。
"""

    data = structured_response(

        FOOD_SYSTEM_PROMPT,

        prompt,

        FOOD_SCHEMA,

        "added_food_analysis",

        max_tokens=1600
    )

    print(
        "FOOD_AI_ADD_TIME: "
        f"{time.time() - start_time:.2f}s",
        flush=True
    )

    return data


# =========================================================
# 自然語言意圖判斷
# =========================================================

def classify_user_text(text):

    instructions = """
你是飲食紀錄 App 的自然語言意圖路由器。

你的工作不是回答營養問題，
而是判斷使用者現在想做什麼。

可使用的 intent：

profile
=
設定或更新：
身高、體重、年齡、生理性別、
活動量、減脂／維持／增肌目標。

correct_last
=
修正上一餐。
例如：
飯只吃一半
不是豬排是牛排
豆漿是無糖
那杯沒喝
那個我沒吃

delete_last
=
刪除上一餐。

add_to_last
=
在上一餐新增食物。
例如：
再加一顆蛋
還有一根香蕉
漏掉一杯豆漿

today
=
查看今天吃了什麼、
今日總熱量或今日紀錄。

remaining
=
詢問今天還能吃多少、
還剩多少熱量或營養額度。

meal_advice
=
根據今天剩餘額度，
詢問下一餐可以吃什麼。
例如：
晚餐可以吃什麼
我等等可以吃麥當勞嗎

remember_food
=
使用者明確要求系統記住
自己的固定飲食習慣。

例如：
記住我都喝無糖豆漿
這是我常吃的早餐
我固定都是半碗飯

food_question
=
一般飲食、營養、熱量、
減脂、蛋白質等問題。

other
=
完全與飲食功能無關。

如果使用者在設定 profile，
請盡可能抽取：

height_cm
weight_kg
age
sex
activity_level
goal

如果缺資料，
缺少欄位使用 null。

memory_text：

只有 remember_food
才填入適合保存的簡短記憶。

其他 intent 請使用 null。

reply：

可以提供一句非常簡短的
自然語言提示。
"""

    return structured_response(

        instructions,

        text,

        INTENT_SCHEMA,

        "user_intent",

        max_tokens=600
    )


# =========================================================
# 一般飲食聊天 / 晚餐建議
# =========================================================

def food_chat(
    text,
    profile=None,
    totals=None
):

    profile_data = (
        dict(profile)
        if profile
        else {}
    )

    totals_data = (
        dict(totals)
        if totals
        else {}
    )

    context = f"""
使用者個人資料：

{json.dumps(
    profile_data,
    ensure_ascii=False,
    default=str
)}

今天目前飲食累計：

{json.dumps(
    totals_data,
    ensure_ascii=False,
    default=str
)}

使用者現在問：

「{text}」
"""

    response = client.responses.create(

        model=MODEL,

        reasoning={
            "effort": "none"
        },

        instructions="""
你是台灣使用者的個人飲食助理。

回答必須：

簡潔
實用
自然
像朋友
方便直接執行

如果有個人每日目標與今日累計，
優先依照剩餘熱量、
蛋白質、碳水、脂肪額度回答。

如果使用者問：

「晚餐可以吃什麼？」

不要只講大道理。

直接提供 2～4 個
台灣實際容易取得的選項。

例如：

便利商店
自助餐
便當店
火鍋
早餐店
超商
外送常見餐點

可以稍微吐槽一句，
但不要羞辱身材或體重。

營養與熱量屬合理估算，
不要假裝具有醫療診斷能力。
""",

        input=context,

        max_output_tokens=500,

        store=False
    )

    return response.output_text.strip()
