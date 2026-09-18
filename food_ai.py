import os
import json
import time
import random

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
【十二、V5.2 份量與辨識精準度】
━━━━━━━━━━━━━━━━━━

照片分析最容易出錯的不是加總，而是「食物種類」與「份量」。
因此每一個 foods 項目都必須先辨識，再估克數，最後才算營養。

A. 食物種類先判斷
- 不要用「豆製品與肉塊」「炒菜」「配菜」這種模糊名稱，除非真的無法再細分。
- 台灣便當/營養午餐常見的豆干、豆皮、麵腸、素雞、肉片、芋頭、地瓜、馬鈴薯、玉米、毛豆、豆芽菜、白飯、糙米飯、雜糧飯要特別區分。
- 看不清楚時採最可能答案，但 confidence 必須降低，不要假裝很確定。

B. 每項先估 estimated_grams
- quantity 寫人看得懂的份量，例如「約半碗」「約 5 塊」「約 1 小份」。
- estimated_grams 必須是該項實際可食重量的單一最佳估計值。
- 優先用餐盒格子、碗、盤、筷子、湯匙、杯子、手掌與其他食物作比例尺。
- 不可因為食物被其他食物遮住，就把看不到的部分任意放大。
- 若照片只看到一部分，依可見體積保守估計。

C. 飯與澱粉特別處理
- 先判斷白飯/糙米/紫米/雜糧飯，再估克數。
- 半碗、1/3 碗等文字只是輔助，營養計算必須以 estimated_grams 為主要依據。
- 芋頭、地瓜、南瓜、馬鈴薯、玉米不可全部當成同一種澱粉。

D. 混合料理拆解
- 若能看出是「豆芽菜炒豆干」，應拆成合理的主要成分，或以明確料理名稱估算；不要誤寫成肉。
- 油、醬汁等看不見但合理存在的熱量可以估入，但要保守，避免為了湊熱量亂加油。

E. confidence 真正有用途
- 每項食物 confidence 0~1。
- 0.80 以上：種類與份量都相對清楚。
- 0.60~0.79：可用，但有一定估算誤差。
- 低於 0.60：仍先記錄最可能答案，但 comment 要用一句短話提醒使用者可修正該項。
- 整餐 confidence 應由關鍵食物的辨識與份量可信度綜合決定，不能只因總熱量看似合理就給 high。

F. 禁止用總熱量反推食物
先決定照片裡是什麼、多少克，再計算營養。
不要為了讓整餐落在「看起來合理的 400~600 kcal」而調整食物或份量。

━━━━━━━━━━━━━━━━━━
【十三、最重要原則】
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
                "custom_targets",
                "reset_targets",
                "correct_last",
                "delete_last",
                "add_to_last",
                "set_meal_type",
                "reset_today",
                "today",
                "month_report",
                "weight_log",
                "remaining",
                "meal_advice",
                "exercise_advice",
                "remember_food",
                "food_question",
                "other"
            ]
        },
        "reply": {"type": "string"},
        "profile": {
            "type": ["object", "null"],
            "properties": {
                "height_cm": {"type": ["number", "null"]},
                "weight_kg": {"type": ["number", "null"]},
                "age": {"type": ["integer", "null"]},
                "sex": {"type": ["string", "null"]},
                "activity_level": {"type": ["string", "null"]},
                "goal": {"type": ["string", "null"]}
            },
            "required": [
                "height_cm", "weight_kg", "age", "sex",
                "activity_level", "goal"
            ],
            "additionalProperties": False
        },
        "targets": {
            "type": ["object", "null"],
            "properties": {
                "calorie_target": {"type": ["number", "null"]},
                "protein_target": {"type": ["number", "null"]},
                "carbs_target": {"type": ["number", "null"]},
                "fat_target": {"type": ["number", "null"]},
                "fiber_target": {"type": ["number", "null"]},
                "scope": {"type": ["string", "null"], "enum": ["today", "permanent",     None]},
                "mode_name": {"type": ["string", "null"]}
            },
            "required": [
                "calorie_target", "protein_target", "carbs_target",
                "fat_target", "fiber_target", "scope", "mode_name"
            ],
            "additionalProperties": False
        },
        "meal_type": {
            "type": ["string", "null"],
            "enum": ["早餐", "午餐", "晚餐", "點心", None]
        },
        "target_date": {"type": ["string", "null"]},
        "report_year": {"type": ["integer", "null"]},
        "report_month": {"type": ["integer", "null"]},
        "weight_kg": {"type": ["number", "null"]},
        "memory_text": {"type": ["string", "null"]}
    },
    "required": [
        "intent", "reply", "profile", "targets", "meal_type",
        "target_date", "report_year", "report_month", "weight_kg",
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

請一次完成，但務必依這個順序：

1. 逐項辨識照片真正出現的食物，不要先猜總熱量
2. 區分容易混淆的食材（尤其豆干/麵腸/肉、白飯/雜糧飯、芋頭/地瓜/馬鈴薯）
3. 以餐盒、碗盤、餐具與食物比例估每項 estimated_grams
4. 依「食物種類 + estimated_grams + 烹調方式」估營養
5. 再把各項加總成整餐 total
6. 為每項給真實 confidence；低信心項目不要硬裝確定
7. 最後只給一句簡短飲食評語

答案明顯時直接判斷，不要把使用者丟回選擇題。
如果看不清楚，仍給最可能的暫時估計，但降低 confidence，讓使用者之後可以直接修正。
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
你是台灣飲食紀錄 App 的自然語言意圖路由器。
你的任務是「判斷使用者想做什麼」，不要寫長篇營養文章。

最重要：只要與飲食、營養、熱量、三大營養素、體重、個人資料、餐點紀錄有關，就不是 other。
不要因為句子口語、簡短或不完整就亂判成 other。

可用 intent：

profile
= 設定或更新身高、體重、年齡、生理性別、活動量、減脂/維持/增肌。
若只是回「男」「女」且上下文可能正在補個人資料，也可判 profile。

custom_targets
= 使用者想修改自己吃的熱量、蛋白質、碳水、脂肪、纖維目標。
例如：
「今天碳水改80g」
「今天低碳，蛋白質80、碳水80、脂肪45」
「蛋白質我想改85g」
「以後脂肪抓45g」
「我不想低碳日吃那麼多脂肪蛋白質」如果是在要求修改目標，也屬於此類。

scope：
- 有「今天／今日／低碳日」等單日語意 → today
- 有「以後／平常／每天／固定」 → permanent
- 無法判斷時，若句子明確說今天則 today，否則 permanent

只抽取使用者明確提供的數字，不要自行補湊三大營養素。
「低碳」但沒給數字時，targets 數值可全部 null，mode_name 填「低碳日」。

reset_targets
= 恢復系統建議、取消自訂營養目標、今天恢復預設。
若明確說今天，target_date 填「今天」；否則視為永久自訂恢復。

correct_last
= 修正上一餐內容或份量，例如「飯只吃一半」「地瓜其實更多」「不是豬排是牛排」。

delete_last
= 刪除上一餐。

add_to_last
= 在上一餐新增食物，例如「再加一顆蛋」。

set_meal_type
= 指定或修改最近一餐的餐別，例如「這是早餐」「上一餐改成晚餐」「剛剛那張算午餐」。
meal_type 必須填早餐/午餐/晚餐/點心。

target_date：
若使用者說今天填「今天」，昨天填「昨天」。沒有日期填 null。

reset_today
= 「重置今天」「清空今天紀錄」「今天測試的全部刪掉」。
注意這是刪除今天所有餐點，不是刪個人資料。

today
= 查看今天吃了什麼、今日紀錄、今日總熱量。

month_report
= 查看本月或指定月份飲食總表。
例如「這個月紀錄」「9月紀錄」「2026年8月總表」。
能抽取年份月份就填 report_year/report_month，沒有年份可 null。

weight_log
= 明確記錄體重，例如「我今天58.2公斤」「今天體重58.2」。
weight_kg 填數值；target_date 可填今天/昨天。
如果句子是在修改個人資料的體重而不是紀錄今天體重，可判 profile。

remaining
= 今天還能吃多少、剩多少熱量或營養額度。

meal_advice
= 根據今天剩餘額度問下一餐怎麼吃、晚餐吃什麼、今天怎麼吃、想吃某種食物要怎麼搭配。

exercise_advice
= 使用者想知道今天做什麼運動、只有幾分鐘怎麼練、減脂/增肌適合什麼運動、想安排運動。

remember_food
= 明確要求記住固定飲食習慣，例如「記住我都喝無糖豆漿」。
只有此 intent 填 memory_text。

food_question
= 一般飲食、營養、熱量、減脂、蛋白質、碳水、脂肪、外食等正經問題。

other
= 完全與飲食 App 無關，例如感情八卦、數學亂問、人物關係、星座等。
真的離題才用 other。

reply 只要一句極短提示，不要長文。
未使用的欄位一律填 null。
"""

    return structured_response(
        instructions,
        text,
        INTENT_SCHEMA,
        "user_intent_v4",
        max_tokens=800
    )


def off_topic_reply(text=None):
    """朋友式輕嗆：只給真正離題的問題使用。"""
    replies = [
        "🙄 我是飲食 BOT，不是戶政事務所。你吃多少我比較有興趣。",
        "😂 這題沒有熱量，我拒絕幫它入帳。問點能吃的啦。",
        "你再亂問，我要開始算你講廢話消耗幾卡了 😎",
        "感情問題請右轉，我這裡主要處理碳水化合物 😂",
        "蛤？你是餓到開始亂問是不是。先問我今天還能吃多少啦 😂",
        "這題跟蛋白質一樣——跟我有關係，但真的不多 😌",
        "我管你吃什麼，不太管你愛誰 😂 下一題請問雞胸肉。",
    ]
    return random.choice(replies)


# =========================================================
# 一般飲食聊天 / 晚餐建議
# =========================================================

def food_chat(
    text,
    profile=None,
    totals=None,
    targets=None
):
    """V5 智能體態回覆：依個人資料、今日累計與有效目標給飲食/運動建議。"""
    profile_data = dict(profile) if profile else {}
    totals_data = dict(totals) if totals else {}
    targets_data = dict(targets) if targets else {}

    def n(d, key):
        try:
            return float(d.get(key, 0) or 0)
        except Exception:
            return 0.0

    remaining = {}
    pairs = [
        ("calories", "calorie_target"),
        ("protein", "protein_target"),
        ("carbs", "carbs_target"),
        ("fat", "fat_target"),
        ("fiber", "fiber_target"),
    ]
    for used_key, target_key in pairs:
        target = n(targets_data, target_key)
        if target > 0:
            remaining[used_key] = round(target - n(totals_data, used_key), 1)

    context = f"""
使用者個人資料：
{json.dumps(profile_data, ensure_ascii=False, default=str)}

今天有效營養目標：
{json.dumps(targets_data, ensure_ascii=False, default=str)}

今天目前飲食累計：
{json.dumps(totals_data, ensure_ascii=False, default=str)}

系統已計算的今日剩餘（負數代表已超標）：
{json.dumps(remaining, ensure_ascii=False)}

使用者現在說：
「{text}」
"""

    response = client.responses.create(
        model=MODEL,
        reasoning={"effort": "none"},
        instructions="""
你是台灣使用者每天會使用的飲食與體態 BOT。不要自稱教練。

你要像一個很熟使用者、懂飲食與運動、會盯進度的朋友。語氣可以偏魔鬼、會催、會吐槽，但重點永遠是實用。不要每一句都嗆，只有偷懶、明顯偏離目標或適合開玩笑時才吐槽一句。

回答規則：
1. 預設 3～8 行，先回答問題，不寫長篇大道理。
2. 有每日目標和今日累計時，必須優先使用「剩餘」數字，不要自己重新亂算。
3. 蛋白質不足可以明確說「還差約 X g」；熱量/脂肪/碳水超標可以說「已超約 X」。
4. 小幅超標不要製造焦慮，也不要叫使用者跳餐、挨餓或用大量運動補償。
5. 問「今天/晚餐吃什麼」時，給 2～3 組台灣容易取得的具體餐點組合，並依剩餘額度調整份量；可包含超商、自助餐、便當、火鍋、早餐店等。
6. 使用者指定想吃某樣東西時，不要只禁止；優先告訴他怎麼搭配、怎麼調整份量比較適合今天。
7. 問運動時，依目標、活動量及使用者說的時間/疲勞程度，直接給可執行安排。若沒有時間資訊，預設給 20～40 分鐘版本。
8. 運動安排以一般成人安全範圍為主，可用快走、腳踏車、基礎阻力訓練、深蹲、臀橋、划船、推舉、核心等；若使用者提到疼痛、受傷、疾病或醫療限制，不要硬排動作，改請其依醫療專業建議調整。
9. 不要羞辱體重、身材、外貌，不鼓勵極端節食。
10. 若資料不足，仍可提供一般建議，但要簡短說明「先用一般版」。

語氣示例（不要固定照抄）：
「蛋白質還差 28g，這個數字不要假裝沒看到🙂 晚餐優先補雞胸/魚/豆腐。」
「熱量剩 350 kcal，炸雞今天先不要演偶像劇。選烤雞＋青菜比較穩。」
「只有20分鐘也能動，不准拿時間當擋箭牌 😂 快走5分鐘＋三個動作循環15分鐘。」
""",
        input=context,
        max_output_tokens=420,
        store=False
    )
    return response.output_text.strip()
