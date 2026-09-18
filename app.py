import os
import base64
import io
import requests
import re

from PIL import Image
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

from food_ai import (
    analyze_food_image,
    correct_food_analysis,
    add_food_to_analysis,
    classify_user_text,
    food_chat,
)

from database import (
    init_database,
    save_meal,
    get_last_meal,
    update_meal,
    delete_meal,
    get_today_meals,
    get_today_totals,
    save_profile,
    get_profile,
    update_profile_fields,
    get_missing_profile_fields,
    add_food_memory,
    get_food_memories,
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
# Web
# =========================================================

@app.route("/", methods=["GET"])
def home():
    return "LINE Food AI Bot V3 is running!"


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

    with ApiClient(configuration) as api_client:

        line_bot_api = MessagingApi(
            api_client
        )

        line_bot_api.reply_message(
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
# User ID
# =========================================================

def get_user_id(event):

    return (
        getattr(
            event.source,
            "user_id",
            None
        )
        or "unknown_user"
    )


# =========================================================
# 數字安全轉換
# =========================================================

def number(
    value,
    default=0
):

    try:
        return float(
            value or 0
        )

    except Exception:
        return default


def totals_to_dict(totals):

    totals = totals or {}

    return {
        "calories": number(
            totals.get("calories", 0)
        ),

        "protein": number(
            totals.get("protein", 0)
        ),

        "carbs": number(
            totals.get("carbs", 0)
        ),

        "fat": number(
            totals.get("fat", 0)
        ),

        "fiber": number(
            totals.get("fiber", 0)
        ),

        "sodium": number(
            totals.get("sodium", 0)
        ),

        "meal_count": int(
            totals.get("meal_count", 0)
            or 0
        ),
    }


# =========================================================
# V3：個人資料工具
# =========================================================

PROFILE_LABELS = {
    "height_cm": "身高",
    "weight_kg": "體重",
    "age": "年齡",
    "sex": "生理性別",
    "activity_level": "活動量",
    "goal": "目標",
}


def profile_is_complete(profile):
    if not profile:
        return False

    required = [
        "height_cm",
        "weight_kg",
        "age",
        "sex",
        "activity_level",
        "goal",
    ]

    return all(
        profile.get(field) not in [None, ""]
        for field in required
    )


def profile_has_targets(profile):
    return (
        profile_is_complete(profile)
        and number(profile.get("calorie_target")) > 0
    )


def normalize_sex(value):
    text = str(value or "").strip().lower()

    if text in ["男", "男性", "male", "m"]:
        return "男"

    if text in ["女", "女性", "female", "f"]:
        return "女"

    return None


def normalize_activity(value):
    text = str(value or "").strip()

    if "非常高" in text:
        return "非常高"
    if "久坐" in text:
        return "久坐"
    if "輕" in text:
        return "輕量"
    if "中" in text:
        return "中等"
    if "高" in text:
        return "高"

    return None


def normalize_goal(value):
    text = str(value or "").strip()

    if "減" in text:
        return "減脂"
    if "增" in text:
        return "增肌"
    if "維持" in text or "保持" in text:
        return "維持"

    return None


def extract_profile_updates(text, current_profile=None):
    """
    不靠 AI 也能抓常見個人資料說法。
    例如：
    身高162 體重59 年齡27 久坐 減脂
    我現在58公斤
    活動量改輕量
    女
    """
    current_profile = current_profile or {}
    updates = {}
    raw = text.strip()

    patterns = [
        ("height_cm", r"(?:身高\s*)?(\d{2,3}(?:\.\d+)?)\s*(?:cm|公分)"),
        ("weight_kg", r"(?:體重\s*)?(\d{2,3}(?:\.\d+)?)\s*(?:kg|公斤)"),
        ("age", r"(?:年齡\s*)?(\d{1,3})\s*歲"),
    ]

    # 有明確欄位名稱時，即使沒單位也抓
    named_patterns = [
        ("height_cm", r"身高\s*[:：]?\s*(\d{2,3}(?:\.\d+)?)"),
        ("weight_kg", r"體重\s*[:：]?\s*(\d{2,3}(?:\.\d+)?)"),
        ("age", r"年齡\s*[:：]?\s*(\d{1,3})"),
    ]

    for field, pattern in patterns + named_patterns:
        match = re.search(pattern, raw, flags=re.I)
        if match:
            value = float(match.group(1))
            if field == "age":
                value = int(value)
            updates[field] = value

    # 「我現在58公斤」這類
    if "weight_kg" not in updates:
        match = re.search(
            r"(?:現在|目前|變成|改成|降到|升到)\s*(\d{2,3}(?:\.\d+)?)\s*(?:kg|公斤)",
            raw,
            flags=re.I,
        )
        if match:
            updates["weight_kg"] = float(match.group(1))

    # 性別
    if re.search(r"(^|[\s，,、])(?:生理)?性別\s*[:：]?\s*男(?:性)?", raw) or raw in ["男", "男性"]:
        updates["sex"] = "男"
    elif re.search(r"(^|[\s，,、])(?:生理)?性別\s*[:：]?\s*女(?:性)?", raw) or raw in ["女", "女性"]:
        updates["sex"] = "女"
    else:
        # 完整資料句中常直接寫「女／男」
        if re.search(r"(^|[\s，,、])女(?:性)?($|[\s，,、])", raw):
            updates["sex"] = "女"
        elif re.search(r"(^|[\s，,、])男(?:性)?($|[\s，,、])", raw):
            updates["sex"] = "男"

    activity = normalize_activity(raw)
    if activity:
        updates["activity_level"] = activity

    goal = normalize_goal(raw)
    if goal:
        updates["goal"] = goal

    return updates


def merge_profile(profile, updates):
    merged = dict(profile or {})
    merged.update(
        {
            key: value
            for key, value in (updates or {}).items()
            if value is not None
        }
    )
    return merged


def missing_profile_text(profile):
    required = [
        "height_cm",
        "weight_kg",
        "age",
        "sex",
        "activity_level",
        "goal",
    ]

    missing = [
        field
        for field in required
        if not profile or profile.get(field) in [None, ""]
    ]

    if not missing:
        return None

    labels = [PROFILE_LABELS[field] for field in missing]

    if missing == ["sex"]:
        return (
            "👤 前面的資料收到並存好了！\n"
            "現在只差「生理性別」。\n\n"
            "回我「男」或「女」就好～"
        )

    return (
        "👤 已先幫你存下來。\n"
        "還差：" + "、".join(labels) + "\n\n"
        "缺的資料直接補給我就好，不用全部重打。"
    )


def profile_summary(profile):
    if not profile:
        return (
            "👤 你目前還沒有個人資料。\n"
            "直接輸入「設定資料」就可以開始。"
        )

    lines = ["👤 我的資料"]

    basic = []
    if profile.get("height_cm") is not None:
        basic.append(f"{round(number(profile['height_cm']), 1):g} cm")
    if profile.get("weight_kg") is not None:
        basic.append(f"{round(number(profile['weight_kg']), 1):g} kg")
    if profile.get("age") is not None:
        basic.append(f"{int(profile['age'])}歲")
    if profile.get("sex"):
        basic.append(str(profile["sex"]))

    if basic:
        lines.append("｜".join(basic))

    second = []
    if profile.get("activity_level"):
        second.append(f"活動量：{profile['activity_level']}")
    if profile.get("goal"):
        second.append(f"目標：{profile['goal']}")

    if second:
        lines.append("｜".join(second))

    if profile_has_targets(profile):
        lines.extend(
            [
                "",
                f"🔥 BMR 約 {round(number(profile.get('bmr')))} kcal",
                f"⚡ TDEE 約 {round(number(profile.get('tdee')))} kcal",
                f"🎯 每日目標 {round(number(profile.get('calorie_target')))} kcal",
                (
                    f"🥩 {round(number(profile.get('protein_target')))}g"
                    f"｜🍚 {round(number(profile.get('carbs_target')))}g"
                    f"｜🥑 {round(number(profile.get('fat_target')))}g"
                ),
            ]
        )
    else:
        missing = missing_profile_text(profile)
        if missing:
            lines.extend(["", missing])

    return "\n".join(lines)


def save_and_finish_profile(user_id, updates):
    """
    先部分存檔；完整後才計算 BMR/TDEE/營養目標。
    """
    if updates:
        update_profile_fields(user_id, updates)

    profile = get_profile(user_id)

    if not profile_is_complete(profile):
        return profile, False

    calculated = calculate_targets(dict(profile))
    save_profile(user_id, calculated)

    return get_profile(user_id), True


def compact_ai_text(text, max_lines=8, max_chars=430):
    """
    LINE 短答模式：
    移除 Markdown 標記，避免一大篇作文。
    """
    if not text:
        return "我剛剛沒整理出答案，再問我一次 😵‍💫"

    cleaned = str(text)
    cleaned = cleaned.replace("**", "")
    cleaned = cleaned.replace("###", "")
    cleaned = cleaned.replace("##", "")
    cleaned = cleaned.replace("#", "")

    lines = [
        line.strip()
        for line in cleaned.splitlines()
        if line.strip()
    ]

    # 去掉太多重複空泛標題，保留前幾個重點
    lines = lines[:max_lines]
    result = "\n".join(lines)

    if len(result) > max_chars:
        result = result[:max_chars].rsplit("\n", 1)[0].rstrip()
        if not result:
            result = cleaned[:max_chars].rstrip()
        result += "\n\n想看更詳細的再叫我展開 😎"

    return result


def looks_like_meal_correction(text):
    """
    把「地瓜其實比較多」「飯我只吃一半」這類自然句
    優先視為上一餐修正，不要掉進一般聊天。
    """
    keywords = [
        "其實", "不是", "應該是", "改成",
        "比較多", "更多", "比較少", "少一點",
        "一半", "半份", "沒吃", "沒喝",
        "吃完", "只吃", "只喝", "被蓋",
        "漏算", "算錯", "抓太少", "抓太多",
    ]

    food_context = [
        "飯", "地瓜", "肉", "雞", "牛", "豬", "魚",
        "蛋", "豆漿", "牛奶", "優格", "菜", "水果",
        "麵", "飲料", "醬", "湯", "吐司", "饅頭",
    ]

    return (
        any(k in text for k in keywords)
        and any(k in text for k in food_context)
    )


# =========================================================
# 個人營養目標
# =========================================================

def calculate_targets(profile):

    weight = float(
        profile["weight_kg"]
    )

    height = float(
        profile["height_cm"]
    )

    age = int(
        profile["age"]
    )

    sex = str(
        profile["sex"]
    ).lower()

    # Mifflin-St Jeor
    if sex in [
        "男",
        "男性",
        "male",
        "m",
    ]:

        bmr = (
            10 * weight
            + 6.25 * height
            - 5 * age
            + 5
        )

        is_male = True

    else:

        bmr = (
            10 * weight
            + 6.25 * height
            - 5 * age
            - 161
        )

        is_male = False

    activity_factors = {
        "久坐": 1.2,
        "輕量": 1.375,
        "中等": 1.55,
        "高": 1.725,
        "非常高": 1.9,
    }

    activity_factor = (
        activity_factors.get(
            profile["activity_level"],
            1.375
        )
    )

    tdee = (
        bmr
        * activity_factor
    )

    goal = profile["goal"]

    if goal == "減脂":
        calorie_target = (
            tdee - 350
        )

    elif goal == "增肌":
        calorie_target = (
            tdee + 250
        )

    else:
        calorie_target = tdee

    # 防止自動目標過低
    calorie_floor = (
        1500
        if is_male
        else 1200
    )

    calorie_target = max(
        calorie_target,
        calorie_floor
    )

    if goal in [
        "減脂",
        "增肌",
    ]:

        protein_target = (
            weight * 1.6
        )

    else:

        protein_target = (
            weight * 1.4
        )

    fat_target = (
        weight * 0.8
    )

    calories_left_for_carbs = (
        calorie_target
        - protein_target * 4
        - fat_target * 9
    )

    carbs_target = max(
        0,
        calories_left_for_carbs / 4
    )

    return {
        **profile,

        "bmr": round(bmr),

        "tdee": round(tdee),

        "calorie_target":
            round(calorie_target),

        "protein_target":
            round(protein_target),

        "carbs_target":
            round(carbs_target),

        "fat_target":
            round(fat_target),

        "fiber_target": 25,

        "inbody":
            profile.get(
                "inbody",
                {}
            ),
    }


# =========================================================
# 目標進度文字
# =========================================================

def progress_line(
    emoji,
    used,
    target,
    unit
):

    used = number(used)
    target = number(target)

    remaining = (
        target - used
    )

    if remaining >= 0:

        return (
            f"{emoji} "
            f"{round(used, 1)} / "
            f"{round(target, 1)} {unit}"
            f"｜剩 {round(remaining, 1)}"
        )

    return (
        f"{emoji} "
        f"{round(used, 1)} / "
        f"{round(target, 1)} {unit}"
        f"｜超 {round(abs(remaining), 1)}"
    )


# =========================================================
# 餐點 Flex Card
# =========================================================

def make_meal_card(
    data,
    today_totals,
    profile=None,
    corrected=False
):

    today = totals_to_dict(
        today_totals
    )

    total = (
        data.get("total")
        or {}
    )

    foods = (
        data.get("foods")
        or []
    )

    meal_name = (
        data.get("meal_name")
        or "這一餐"
    )

    if corrected:
        title = (
            "✏️ 已更新｜"
            + meal_name
        )
    else:
        title = (
            "🍱 "
            + meal_name
        )

    body = [
        {
            "type": "text",
            "text": title,
            "weight": "bold",
            "size": "xl",
            "wrap": True,
        },

        {
            "type": "text",
            "text": (
                "🔥 約 "
                f"{round(number(total.get('calories')))}"
                " kcal"
            ),
            "weight": "bold",
            "size": "xxl",
            "margin": "md",
        },

        {
            "type": "box",
            "layout": "horizontal",
            "margin": "md",
            "contents": [
                {
                    "type": "text",
                    "text": (
                        "🥩 "
                        f"{round(number(total.get('protein')), 1)}g"
                    ),
                    "size": "sm",
                    "flex": 1,
                },
                {
                    "type": "text",
                    "text": (
                        "🍚 "
                        f"{round(number(total.get('carbs')), 1)}g"
                    ),
                    "size": "sm",
                    "flex": 1,
                },
                {
                    "type": "text",
                    "text": (
                        "🥑 "
                        f"{round(number(total.get('fat')), 1)}g"
                    ),
                    "size": "sm",
                    "flex": 1,
                },
            ],
        },

        {
            "type": "separator",
            "margin": "lg",
        },
    ]

    # -----------------------------------------------------
    # 食物項目
    # -----------------------------------------------------

    for food in foods[:8]:

        food_name = (
            food.get("name")
            or "食物"
        )

        quantity = (
            food.get("quantity")
            or ""
        )

        calories = round(
            number(
                food.get("calories")
            )
        )

        body.append(
            {
                "type": "box",
                "layout": "horizontal",
                "margin": "sm",
                "contents": [
                    {
                        "type": "text",
                        "text": (
                            f"• {food_name} "
                            f"{quantity}"
                        ),
                        "size": "sm",
                        "wrap": True,
                        "flex": 7,
                    },

                    {
                        "type": "text",
                        "text": (
                            f"{calories} kcal"
                        ),
                        "size": "sm",
                        "align": "end",
                        "flex": 3,
                    },
                ],
            }
        )

    # -----------------------------------------------------
    # 今日累計
    # -----------------------------------------------------

    body.extend(
        [
            {
                "type": "separator",
                "margin": "lg",
            },

            {
                "type": "text",
                "text": "📊 今日累計",
                "weight": "bold",
                "margin": "lg",
            },
        ]
    )

    # -----------------------------------------------------
    # 有個人資料
    # -----------------------------------------------------

    if profile_has_targets(profile):

        calorie_target = number(
            profile.get(
                "calorie_target"
            )
        )

        protein_target = number(
            profile.get(
                "protein_target"
            )
        )

        carbs_target = number(
            profile.get(
                "carbs_target"
            )
        )

        fat_target = number(
            profile.get(
                "fat_target"
            )
        )

        fiber_target = number(
            profile.get(
                "fiber_target"
            ),
            25
        )

        remaining_calories = (
            calorie_target
            - today["calories"]
        )

        body.extend(
            [
                {
                    "type": "text",
                    "text": progress_line(
                        "🔥",
                        today["calories"],
                        calorie_target,
                        "kcal",
                    ),
                    "size": "sm",
                    "margin": "sm",
                    "wrap": True,
                },

                {
                    "type": "text",
                    "text": progress_line(
                        "🥩",
                        today["protein"],
                        protein_target,
                        "g",
                    ),
                    "size": "sm",
                    "margin": "sm",
                    "wrap": True,
                },

                {
                    "type": "text",
                    "text": progress_line(
                        "🍚",
                        today["carbs"],
                        carbs_target,
                        "g",
                    ),
                    "size": "sm",
                    "margin": "sm",
                    "wrap": True,
                },

                {
                    "type": "text",
                    "text": progress_line(
                        "🥑",
                        today["fat"],
                        fat_target,
                        "g",
                    ),
                    "size": "sm",
                    "margin": "sm",
                    "wrap": True,
                },

                {
                    "type": "text",
                    "text": progress_line(
                        "🥬",
                        today["fiber"],
                        fiber_target,
                        "g",
                    ),
                    "size": "sm",
                    "margin": "sm",
                    "wrap": True,
                },
            ]
        )

        if remaining_calories >= 0:

            remaining_text = (
                "今天還可以吃約 "
                f"{round(remaining_calories)} kcal"
            )

        else:

            remaining_text = (
                "今天目前超過目標約 "
                f"{round(abs(remaining_calories))} kcal"
            )

        body.append(
            {
                "type": "text",
                "text": remaining_text,
                "weight": "bold",
                "margin": "md",
                "wrap": True,
            }
        )

    # -----------------------------------------------------
    # 沒有個人資料也完全可以使用
    # -----------------------------------------------------

    else:

        body.extend(
            [
                {
                    "type": "text",
                    "text": (
                        f"🔥 {round(today['calories'])} kcal"
                    ),
                    "size": "sm",
                    "margin": "sm",
                },

                {
                    "type": "text",
                    "text": (
                        "🥩 "
                        f"{round(today['protein'], 1)} g"
                        "｜🍚 "
                        f"{round(today['carbs'], 1)} g"
                        "｜🥑 "
                        f"{round(today['fat'], 1)} g"
                    ),
                    "size": "sm",
                    "margin": "sm",
                    "wrap": True,
                },

                {
                    "type": "text",
                    "text": (
                        "🥬 纖維 "
                        f"{round(today['fiber'], 1)} g"
                    ),
                    "size": "sm",
                    "margin": "sm",
                },

                {
                    "type": "text",
                    "text": (
                        "👤 想看每日目標與剩餘額度，"
                        "再輸入「設定資料」就好"
                    ),
                    "size": "xs",
                    "margin": "md",
                    "wrap": True,
                },
            ]
        )

    # -----------------------------------------------------
    # AI 評語
    # -----------------------------------------------------

    comment = data.get(
        "comment"
    )

    if comment:

        body.extend(
            [
                {
                    "type": "separator",
                    "margin": "lg",
                },

                {
                    "type": "text",
                    "text": (
                        "💬 "
                        + comment
                    ),
                    "size": "sm",
                    "wrap": True,
                    "margin": "lg",
                },
            ]
        )

    # -----------------------------------------------------
    # Footer
    # -----------------------------------------------------

    footer = {
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
                    "label": "✏️ 修正上一餐",
                    "text": "我要修正上一餐",
                },
            },

            {
                "type": "box",
                "layout": "horizontal",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "style": "secondary",
                        "height": "sm",
                        "action": {
                            "type": "message",
                            "label": "📊 今天",
                            "text": "查看今日紀錄",
                        },
                    },

                    {
                        "type": "button",
                        "style": "secondary",
                        "height": "sm",
                        "action": {
                            "type": "message",
                            "label": "🗑️ 誤傳刪除",
                            "text": "刪掉上一餐",
                        },
                    },
                ],
            },
        ],
    }

    card = {
        "type": "bubble",

        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "18px",
            "contents": body,
        },

        "footer": footer,
    }

    return FlexMessage(
        alt_text=(
            f"{meal_name}｜"
            f"{round(number(total.get('calories')))} kcal"
        ),

        contents=FlexContainer.from_dict(
            card
        ),
    )


# =========================================================
# 今日飲食帳本
# =========================================================

def today_summary(user_id):

    meals = get_today_meals(
        user_id
    )

    totals = totals_to_dict(
        get_today_totals(
            user_id
        )
    )

    profile = get_profile(
        user_id
    )

    if not meals:

        return (
            "📊 今天還沒有飲食紀錄。\n\n"
            "直接丟餐點照片過來就可以，"
            "不用先設定個人資料 😎"
        )

    lines = [
        "📊 今日飲食帳本",
        "",
    ]

    for meal in meals:

        meal_type = (
            meal.get("meal_type")
            or "餐點"
        )

        meal_name = (
            meal.get("meal_name")
            or "這一餐"
        )

        calories = round(
            number(
                meal.get("calories")
            )
        )

        lines.append(
            f"{meal_type}｜"
            f"{meal_name}　"
            f"🔥 {calories} kcal"
        )

    lines.extend(
        [
            "",
            "──────────",
            f"🔥 {round(totals['calories'])} kcal",

            (
                f"🥩 {round(totals['protein'], 1)} g"
                "｜"
                f"🍚 {round(totals['carbs'], 1)} g"
            ),

            (
                f"🥑 {round(totals['fat'], 1)} g"
                "｜"
                f"🥬 {round(totals['fiber'], 1)} g"
            ),
        ]
    )

    if profile_has_targets(profile):

        calorie_target = number(
            profile.get(
                "calorie_target"
            )
        )

        remaining = (
            calorie_target
            - totals["calories"]
        )

        lines.extend(
            [
                "",
                (
                    "🎯 今日目標 "
                    f"{round(calorie_target)} kcal"
                ),
            ]
        )

        if remaining >= 0:

            lines.append(
                "🔥 還可以吃約 "
                f"{round(remaining)} kcal"
            )

        else:

            lines.append(
                "🔥 目前超過目標約 "
                f"{round(abs(remaining))} kcal"
            )

    else:

        lines.extend(
            [
                "",
                "👤 尚未設定個人目標",
                "想看剩餘額度時再輸入「設定資料」即可。",
            ]
        )

    return "\n".join(lines)


# =========================================================
# 剩餘額度
# =========================================================

def remaining_reply(user_id):

    profile = get_profile(
        user_id
    )

    totals = totals_to_dict(
        get_today_totals(
            user_id
        )
    )

    if not profile_has_targets(profile):

        return (
            "📊 我可以照樣幫你算今天吃了多少，"
            "只是還不知道你的個人目標。\n\n"
            f"目前累計：🔥 {round(totals['calories'])} kcal\n"
            f"🥩 {round(totals['protein'], 1)} g"
            f"｜🍚 {round(totals['carbs'], 1)} g"
            f"｜🥑 {round(totals['fat'], 1)} g\n\n"
            "如果想知道「還能吃多少」，"
            "輸入「設定資料」就可以 👤"
        )

    calorie_target = number(
        profile.get(
            "calorie_target"
        )
    )

    protein_target = number(
        profile.get(
            "protein_target"
        )
    )

    remaining = (
        calorie_target
        - totals["calories"]
    )

    protein_remaining = (
        protein_target
        - totals["protein"]
    )

    if remaining >= 0:

        return (
            "📊 今天目前\n\n"
            f"🔥 {round(totals['calories'])}"
            f" / {round(calorie_target)} kcal\n"
            f"還有約 {round(remaining)} kcal\n\n"
            f"🥩 蛋白質還差約 "
            f"{max(0, round(protein_remaining))} g\n\n"
            "額度還活著，"
            "先不用跟晚餐告別 😂"
        )

    return (
        "📊 今天目前\n\n"
        f"🔥 {round(totals['calories'])}"
        f" / {round(calorie_target)} kcal\n"
        f"目前約超過 "
        f"{round(abs(remaining))} kcal\n\n"
        "一天超過一點不用演災難片 😂 "
        "後面正常吃就好。"
    )


# =========================================================
# 圖片壓縮
# =========================================================

def compress_image(image_bytes):

    try:

        image = Image.open(
            io.BytesIO(
                image_bytes
            )
        )

        image = image.convert(
            "RGB"
        )

        # 長邊最多 1280
        # 不會把小圖硬放大
        image.thumbnail(
            (
                1280,
                1280,
            )
        )

        output = io.BytesIO()

        image.save(
            output,
            format="JPEG",
            quality=82,
            optimize=True,
        )

        compressed = (
            output.getvalue()
        )

        print(
            "IMAGE_SIZE:",
            len(image_bytes),
            "->",
            len(compressed),
            flush=True,
        )

        return (
            compressed,
            "image/jpeg",
        )

    except Exception as e:

        print(
            "IMAGE_COMPRESSION_ERROR:",
            repr(e),
            flush=True,
        )

        return (
            image_bytes,
            "image/jpeg",
        )


# =========================================================
# 個人資料輸入說明
# =========================================================

def profile_help():

    return (
        "👤 個人資料可以一次填，也可以慢慢補。\n\n"
        "例如：\n"
        "身高162 體重59 年齡27 女\n"
        "久坐 減脂\n\n"
        "需要：身高、體重、年齡、生理性別、活動量、目標。\n"
        "活動量：久坐／輕量／中等／高／非常高\n"
        "目標：減脂／維持／增肌\n\n"
        "少填一項沒關係，我會先存，缺什麼只問什麼 😎"
    )



# =========================================================
# 文字訊息
# =========================================================

@handler.add(
    MessageEvent,
    message=TextMessageContent,
)
def handle_text(event):

    user_id = get_user_id(
        event
    )

    text = (
        event.message.text.strip()
    )

    try:

        # -------------------------------------------------
        # V3：個人資料快速處理
        # -------------------------------------------------

        current_profile = get_profile(user_id)

        if text in [
            "我的資料",
            "查看我的資料",
            "個人資料",
            "我的個人資料",
        ]:
            reply_text(
                event.reply_token,
                profile_summary(current_profile),
            )
            return

        profile_updates = extract_profile_updates(
            text,
            current_profile,
        )

        profile_words = [
            "身高", "體重", "年齡", "性別",
            "活動量", "久坐", "輕量", "中等",
            "非常高", "減脂", "增肌", "維持",
            "公斤", "kg", "公分", "cm", "歲",
        ]

        waiting_for_profile = (
            current_profile
            and not profile_is_complete(current_profile)
        )

        # 單獨回「男／女」只在正在補資料時視為 profile
        standalone_sex = (
            text in ["男", "女", "男性", "女性"]
            and waiting_for_profile
        )

        if profile_updates and (
            any(word.lower() in text.lower() for word in profile_words)
            or standalone_sex
        ):
            profile, completed = save_and_finish_profile(
                user_id,
                profile_updates,
            )

            if completed:
                reply_text(
                    event.reply_token,
                    (
                        "✅ 個人資料已更新\n\n"
                        + profile_summary(profile)
                        + "\n\n之後每餐都會自動算今日進度。"
                    ),
                )
            else:
                reply_text(
                    event.reply_token,
                    missing_profile_text(profile),
                )

            return

        # -------------------------------------------------
        # V3：自然語言修正上一餐優先
        # -------------------------------------------------

        if looks_like_meal_correction(text):
            last_meal = get_last_meal(user_id)

            if last_meal:
                corrected_data = correct_food_analysis(
                    last_meal,
                    text,
                )

                update_meal(
                    last_meal["id"],
                    corrected_data,
                )

                reply_messages(
                    event.reply_token,
                    [
                        make_meal_card(
                            corrected_data,
                            get_today_totals(user_id),
                            get_profile(user_id),
                            corrected=True,
                        )
                    ],
                )
                return

        # -------------------------------------------------
        # 快速指令
        # 這些不叫 AI，回覆更快也省費用
        # -------------------------------------------------

        if text == "設定資料":

            reply_text(
                event.reply_token,
                profile_help(),
            )

            return


        if text in [
            "查看今日紀錄",
            "今日紀錄",
            "今天吃了什麼",
            "今天吃多少",
            "今天幾卡",
            "今天多少熱量",
        ]:

            reply_text(
                event.reply_token,
                today_summary(
                    user_id
                ),
            )

            return


        if text in [
            "今天還能吃多少",
            "還能吃多少",
            "剩多少熱量",
        ]:

            reply_text(
                event.reply_token,
                remaining_reply(
                    user_id
                ),
            )

            return


        if text == "我要修正上一餐":

            last_meal = (
                get_last_meal(
                    user_id
                )
            )

            if not last_meal:

                reply_text(
                    event.reply_token,
                    "還沒有上一餐可以修啦 😭",
                )

                return

            reply_text(
                event.reply_token,
                (
                    "✏️ 直接跟我講哪裡不對：\n\n"
                    "「飯其實只有半碗」\n"
                    "「這是牛排不是豬排」\n"
                    "「豆漿是無糖」\n"
                    "「那杯我沒喝」\n"
                    "「雞腿我只吃一半」\n"
                    "「還有一顆茶葉蛋」\n\n"
                    "不用照格式講，我看得懂人話 😎"
                ),
            )

            return


        if text in [
            "刪掉上一餐",
            "刪除上一餐",
            "剛剛傳錯了",
            "上一餐傳錯了",
        ]:

            last_meal = (
                get_last_meal(
                    user_id
                )
            )

            if not last_meal:

                reply_text(
                    event.reply_token,
                    "沒有上一餐可以刪啦 😂",
                )

                return

            delete_meal(
                last_meal["id"],
                user_id,
            )

            reply_text(
                event.reply_token,
                (
                    "🗑️ 好，剛剛那餐刪掉了。\n"
                    "今日熱量也一起扣回去了。\n\n"
                    + today_summary(
                        user_id
                    )
                ),
            )

            return


        # -------------------------------------------------
        # 其餘自然語言交給 AI 分類
        # -------------------------------------------------

        intent_data = (
            classify_user_text(
                text
            )
        )

        intent = (
            intent_data.get(
                "intent"
            )
        )


        # -------------------------------------------------
        # 個人資料
        # -------------------------------------------------

        if intent == "profile":

            incoming = (
                intent_data.get("profile")
                or {}
            )

            updates = {}

            for key in [
                "height_cm",
                "weight_kg",
                "age",
            ]:
                if incoming.get(key) is not None:
                    updates[key] = incoming.get(key)

            sex = normalize_sex(
                incoming.get("sex")
            )
            if sex:
                updates["sex"] = sex

            activity = normalize_activity(
                incoming.get("activity_level")
            )
            if activity:
                updates["activity_level"] = activity

            goal = normalize_goal(
                incoming.get("goal")
            )
            if goal:
                updates["goal"] = goal

            profile, completed = save_and_finish_profile(
                user_id,
                updates,
            )

            if not completed:
                reply_text(
                    event.reply_token,
                    missing_profile_text(profile),
                )
                return

            reply_text(
                event.reply_token,
                (
                    "✅ 個人資料已更新\n\n"
                    + profile_summary(profile)
                    + "\n\n之後每餐都會自動算今日進度 😎"
                ),
            )
            return


        # -------------------------------------------------
        # 修正 / 補記上一餐
        # -------------------------------------------------

        if intent in [
            "correct_last",
            "add_to_last",
        ]:

            last_meal = (
                get_last_meal(
                    user_id
                )
            )

            if not last_meal:

                reply_text(
                    event.reply_token,
                    (
                        "我找不到上一餐可以改 😭\n"
                        "先傳一張餐點照片給我。"
                    ),
                )

                return


            if intent == "add_to_last":

                corrected_data = (
                    add_food_to_analysis(
                        last_meal,
                        text,
                    )
                )

            else:

                corrected_data = (
                    correct_food_analysis(
                        last_meal,
                        text,
                    )
                )


            update_meal(
                last_meal["id"],
                corrected_data,
            )


            # ---------------------------------------------
            # 明確說是固定習慣才永久記住
            # ---------------------------------------------

            memory_keywords = [
                "常喝",
                "常吃",
                "固定",
                "記住",
                "以後都是",
                "每次都是",
                "平常都",
            ]

            if any(
                keyword in text
                for keyword in memory_keywords
            ):

                add_food_memory(
                    user_id,
                    text,
                    data=corrected_data,
                )


            reply_messages(
                event.reply_token,
                [
                    make_meal_card(
                        corrected_data,
                        get_today_totals(
                            user_id
                        ),
                        get_profile(
                            user_id
                        ),
                        corrected=True,
                    )
                ],
            )

            return


        # -------------------------------------------------
        # AI 判斷為刪除
        # -------------------------------------------------

        if intent == "delete_last":

            last_meal = (
                get_last_meal(
                    user_id
                )
            )

            if not last_meal:

                reply_text(
                    event.reply_token,
                    "沒有上一餐可以刪啦 😂",
                )

                return

            delete_meal(
                last_meal["id"],
                user_id,
            )

            reply_text(
                event.reply_token,
                (
                    "🗑️ 好，上一餐刪除了。\n\n"
                    + today_summary(
                        user_id
                    )
                ),
            )

            return


        # -------------------------------------------------
        # 今日帳本
        # -------------------------------------------------

        if intent == "today":

            reply_text(
                event.reply_token,
                today_summary(
                    user_id
                ),
            )

            return


        # -------------------------------------------------
        # 剩餘額度
        # -------------------------------------------------

        if intent == "remaining":

            reply_text(
                event.reply_token,
                remaining_reply(
                    user_id
                ),
            )

            return


        # -------------------------------------------------
        # 永久食物記憶
        # -------------------------------------------------

        if intent == "remember_food":

            memory_text = (
                intent_data.get(
                    "memory_text"
                )
                or text
            )

            add_food_memory(
                user_id,
                memory_text,
            )

            reply_text(
                event.reply_token,
                (
                    "🧠 記住了。\n"
                    "下次照片合理相符時，"
                    "我會優先參考這個習慣。\n\n"
                    "但放心，我不會看到珍奶"
                    "硬說它是無糖豆漿 😂"
                ),
            )

            return


        # -------------------------------------------------
        # 晚餐建議 / 飲食問題
        # -------------------------------------------------

        if intent in [
            "meal_advice",
            "food_question",
        ]:

            answer = food_chat(
                text,
                get_profile(
                    user_id
                ),
                totals_to_dict(
                    get_today_totals(
                        user_id
                    )
                ),
            )

            reply_text(
                event.reply_token,
                compact_ai_text(answer),
            )

            return


        # -------------------------------------------------
        # 無關問題
        # -------------------------------------------------

        reply_text(
            event.reply_token,
            (
                "這題超出我的伙食費範圍了 😂\n"
                "我是飲食 BOT 啦。\n\n"
                "食物、熱量、減脂、增肌、"
                "今天吃什麼、還能吃多少，"
                "這些再丟給我 😎"
            ),
        )


    except Exception as e:

        print(
            "TEXT_ERROR:",
            repr(e),
            flush=True,
        )

        reply_text(
            event.reply_token,
            (
                "🥲 我剛剛腦袋打結了。\n"
                "再跟我說一次，我重來。"
            ),
        )


# =========================================================
# 圖片訊息
# =========================================================

@handler.add(
    MessageEvent,
    message=ImageMessageContent,
)
def handle_image(event):

    user_id = (
        get_user_id(
            event
        )
    )

    try:

        # -------------------------------------------------
        # 下載 LINE 圖片
        # -------------------------------------------------

        message_id = (
            event.message.id
        )

        image_url = (
            "https://api-data.line.me/"
            "v2/bot/message/"
            f"{message_id}/content"
        )

        response = requests.get(
            image_url,

            headers={
                "Authorization":
                    f"Bearer {LINE_ACCESS_TOKEN}"
            },

            timeout=20,
        )

        response.raise_for_status()

        original_bytes = (
            response.content
        )


        # -------------------------------------------------
        # V3 速度優化
        # -------------------------------------------------

        image_bytes, content_type = (
            compress_image(
                original_bytes
            )
        )


        # -------------------------------------------------
        # Base64
        # -------------------------------------------------

        image_base64 = (
            base64.b64encode(
                image_bytes
            ).decode(
                "utf-8"
            )
        )

        data_url = (
            f"data:{content_type};base64,"
            f"{image_base64}"
        )


        # -------------------------------------------------
        # 個人食物記憶
        # -------------------------------------------------

        memories = (
            get_food_memories(
                user_id,
                limit=12,
            )
        )


        # -------------------------------------------------
        # AI 一次完成
        # -------------------------------------------------

        food_data = (
            analyze_food_image(
                data_url,
                memories,
            )
        )


        # -------------------------------------------------
        # 儲存
        # -------------------------------------------------

        meal_id = save_meal(
            user_id,
            food_data,
        )

        print(
            "MEAL_SAVED:",
            f"user={user_id}",
            f"meal_id={meal_id}",
            flush=True,
        )


        # -------------------------------------------------
        # 取得今日累計 + 個人資料
        # -------------------------------------------------

        today_totals = (
            get_today_totals(
                user_id
            )
        )

        profile = (
            get_profile(
                user_id
            )
        )


        # -------------------------------------------------
        # 回覆卡片
        # -------------------------------------------------

        reply_messages(
            event.reply_token,
            [
                make_meal_card(
                    food_data,
                    today_totals,
                    profile,
                    corrected=False,
                )
            ],
        )


    except Exception as e:

        print(
            "IMAGE_ERROR:",
            repr(e),
            flush=True,
        )

        reply_text(
            event.reply_token,
            (
                "🥲 這餐分析翻車了。\n"
                "再傳一次給我。\n\n"
                "如果連續翻車，"
                "我們就去 Render 抓兇手 😂"
            ),
        )


# =========================================================
# 啟動
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000,
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
    )
