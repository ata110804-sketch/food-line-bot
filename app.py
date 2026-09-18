import os
import base64
import io
import re
import requests

from datetime import datetime
from zoneinfo import ZoneInfo
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
    off_topic_reply,
)

from database import (
    init_database,
    save_meal,
    get_last_meal,
    update_meal,
    update_meal_type,
    delete_meal,
    reset_today,
    get_today_meals,
    get_today_totals,
    get_month_summary,
    get_month_weight_logs,
    save_profile,
    get_profile,
    update_profile_fields,
    add_food_memory,
    get_food_memories,
    set_custom_targets,
    reset_custom_targets,
    set_daily_targets,
    clear_daily_targets,
    get_effective_targets,
    save_weight,
)


# =========================================================
# 基本設定
# =========================================================

app = Flask(__name__)
TAIWAN_TZ = ZoneInfo("Asia/Taipei")

LINE_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]

configuration = Configuration(access_token=LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

try:
    init_database()
except Exception as e:
    print("DATABASE_INIT_ERROR:", repr(e), flush=True)


@app.route("/", methods=["GET"])
def home():
    return "LINE Food AI Bot V4 is running!"


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


# =========================================================
# LINE 回覆
# =========================================================

def reply_messages(reply_token, messages):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=messages,
            )
        )


def reply_text(reply_token, text):
    reply_messages(reply_token, [TextMessage(text=str(text))])


def get_user_id(event):
    return getattr(event.source, "user_id", None) or "unknown_user"


# =========================================================
# 共用工具
# =========================================================

def number(value, default=0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def totals_to_dict(totals):
    totals = totals or {}
    return {
        "calories": number(totals.get("calories")),
        "protein": number(totals.get("protein")),
        "carbs": number(totals.get("carbs")),
        "fat": number(totals.get("fat")),
        "fiber": number(totals.get("fiber")),
        "sodium": number(totals.get("sodium")),
        "meal_count": int(totals.get("meal_count", 0) or 0),
    }


def compact_ai_text(text, max_lines=7, max_chars=420):
    if not text:
        return "我剛剛沒整理出答案，再問我一次 😵‍💫"

    cleaned = str(text)
    for mark in ["**", "###", "##", "#"]:
        cleaned = cleaned.replace(mark, "")

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    result = "\n".join(lines[:max_lines])

    if len(result) > max_chars:
        result = result[:max_chars].rstrip()
        result += "\n\n想看更詳細的再叫我展開 😎"

    return result


# =========================================================
# 個人資料
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

    return all(profile.get(field) not in [None, ""] for field in required)


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
    updates = {}
    raw = text.strip()

    patterns = [
        ("height_cm", r"(?:身高\s*)?(\d{2,3}(?:\.\d+)?)\s*(?:cm|公分)"),
        ("weight_kg", r"(?:體重\s*)?(\d{2,3}(?:\.\d+)?)\s*(?:kg|公斤)"),
        ("age", r"(?:年齡\s*)?(\d{1,3})\s*歲"),
        ("height_cm", r"身高\s*[:：]?\s*(\d{2,3}(?:\.\d+)?)"),
        ("weight_kg", r"體重\s*[:：]?\s*(\d{2,3}(?:\.\d+)?)"),
        ("age", r"年齡\s*[:：]?\s*(\d{1,3})"),
    ]

    for field, pattern in patterns:
        match = re.search(pattern, raw, flags=re.I)
        if match:
            value = float(match.group(1))
            if field == "age":
                value = int(value)
            updates[field] = value

    if re.search(r"(?:生理)?性別\s*[:：]?\s*男", raw) or raw in ["男", "男性"]:
        updates["sex"] = "男"
    elif re.search(r"(?:生理)?性別\s*[:：]?\s*女", raw) or raw in ["女", "女性"]:
        updates["sex"] = "女"
    else:
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


def calculate_targets(profile):
    weight = float(profile["weight_kg"])
    height = float(profile["height_cm"])
    age = int(profile["age"])
    sex = str(profile["sex"]).lower()

    if sex in ["男", "男性", "male", "m"]:
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
        calorie_floor = 1500
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161
        calorie_floor = 1200

    activity_factors = {
        "久坐": 1.2,
        "輕量": 1.375,
        "中等": 1.55,
        "高": 1.725,
        "非常高": 1.9,
    }

    tdee = bmr * activity_factors.get(profile["activity_level"], 1.375)
    goal = profile["goal"]

    if goal == "減脂":
        calorie_target = tdee - 350
    elif goal == "增肌":
        calorie_target = tdee + 250
    else:
        calorie_target = tdee

    calorie_target = max(calorie_target, calorie_floor)
    protein_target = weight * (1.6 if goal in ["減脂", "增肌"] else 1.4)
    fat_target = weight * 0.8
    carbs_target = max(
        0,
        (calorie_target - protein_target * 4 - fat_target * 9) / 4,
    )

    return {
        **profile,
        "bmr": round(bmr),
        "tdee": round(tdee),
        "calorie_target": round(calorie_target),
        "protein_target": round(protein_target),
        "carbs_target": round(carbs_target),
        "fat_target": round(fat_target),
        "fiber_target": 25,
        "inbody": profile.get("inbody", {}),
    }


def save_and_finish_profile(user_id, updates):
    if updates:
        update_profile_fields(user_id, updates)

    profile = get_profile(user_id)

    if not profile_is_complete(profile):
        return profile, False

    calculated = calculate_targets(dict(profile))
    save_profile(user_id, calculated)

    # 體重有更新時，同步進體重歷史
    if updates and updates.get("weight_kg") is not None:
        try:
            save_weight(user_id, updates["weight_kg"])
        except Exception as e:
            print("WEIGHT_SYNC_ERROR:", repr(e), flush=True)

    return get_profile(user_id), True


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
        field for field in required
        if not profile or profile.get(field) in [None, ""]
    ]

    if not missing:
        return None

    if missing == ["sex"]:
        return (
            "👤 前面的資料收到並存好了！\n"
            "現在只差「生理性別」。\n\n"
            "回我「男」或「女」就好～"
        )

    return (
        "👤 已先幫你存下來。\n"
        "還差：" + "、".join(PROFILE_LABELS[x] for x in missing)
        + "\n\n缺的資料直接補給我就好，不用全部重打。"
    )


def profile_summary(user_id):
    profile = get_profile(user_id)

    if not profile:
        return "👤 你目前還沒有個人資料。\n輸入「設定資料」就可以開始。"

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

    if profile_is_complete(profile):
        lines.extend([
            "",
            f"🔥 BMR 約 {round(number(profile.get('bmr')))} kcal",
            f"⚡ TDEE 約 {round(number(profile.get('tdee')))} kcal",
        ])

        targets = get_effective_targets(user_id)
        if targets:
            source = targets.get("source")
            mode = targets.get("mode_name")
            label = "系統建議"
            if source == "custom":
                label = "我的自訂"
            elif source == "daily":
                label = mode or "今日自訂"

            lines.extend([
                f"🎯 今日目標｜{label}",
                f"🔥 {round(number(targets.get('calorie_target')))} kcal",
                (
                    f"🥩 {round(number(targets.get('protein_target')))}g"
                    f"｜🍚 {round(number(targets.get('carbs_target')))}g"
                    f"｜🥑 {round(number(targets.get('fat_target')))}g"
                ),
            ])
    else:
        lines.extend(["", missing_profile_text(profile)])

    return "\n".join(lines)


def profile_help():
    return (
        "👤 個人資料可以一次填，也可以慢慢補。\n\n"
        "例如：身高162 體重59 年齡27 女 久坐 減脂\n\n"
        "活動量：久坐／輕量／中等／高／非常高\n"
        "目標：減脂／維持／增肌\n\n"
        "少填一項沒關係，我只問缺的 😎"
    )


# =========================================================
# V4 自訂營養目標
# =========================================================

def extract_targets_fast(text):
    result = {}

    patterns = {
        "calorie_target": [
            r"(?:熱量|卡路里|大卡)\s*(?:改成|改|設成|設定|目標|不要超過|最多)?\s*(\d{3,4})\s*(?:kcal|卡|大卡)?",
            r"(\d{3,4})\s*(?:kcal|大卡)",
        ],
        "protein_target": [
            r"蛋白質\s*(?:改成|改|設成|設定|目標|不要超過|最多|吃)?\s*(\d{1,3}(?:\.\d+)?)\s*g?",
        ],
        "carbs_target": [
            r"(?:碳水(?:化合物)?)\s*(?:改成|改|設成|設定|目標|不要超過|最多|吃)?\s*(\d{1,3}(?:\.\d+)?)\s*g?",
        ],
        "fat_target": [
            r"(?:脂肪|油脂)\s*(?:改成|改|設成|設定|目標|不要超過|最多|吃)?\s*(\d{1,3}(?:\.\d+)?)\s*g?",
        ],
        "fiber_target": [
            r"(?:纖維|膳食纖維)\s*(?:改成|改|設成|設定|目標|不要超過|最多|吃)?\s*(\d{1,3}(?:\.\d+)?)\s*g?",
        ],
    }

    for key, pats in patterns.items():
        for pat in pats:
            match = re.search(pat, text, flags=re.I)
            if match:
                result[key] = float(match.group(1))
                break

    return result


def targets_reply(user_id):
    targets = get_effective_targets(user_id)

    if not targets or not number(targets.get("calorie_target")):
        return (
            "🎯 目前還沒有可用的每日目標。\n"
            "先輸入「設定資料」完成身高、體重、年齡、性別、活動量與目標。"
        )

    source = targets.get("source")
    mode = targets.get("mode_name")

    if source == "daily":
        label = mode or "今日自訂"
    elif source == "custom":
        label = "我的自訂"
    else:
        label = "系統建議"

    return (
        f"🎯 今日目標｜{label}\n"
        f"🔥 {round(number(targets.get('calorie_target')))} kcal\n"
        f"🥩 {round(number(targets.get('protein_target')))} g"
        f"｜🍚 {round(number(targets.get('carbs_target')))} g\n"
        f"🥑 {round(number(targets.get('fat_target')))} g"
        f"｜🥬 {round(number(targets.get('fiber_target')), 1)} g"
    )


def apply_custom_targets(user_id, intent_data, original_text):
    targets = intent_data.get("targets") or {}
    fast = extract_targets_fast(original_text)

    for key, value in fast.items():
        targets[key] = value

    values = {
        key: targets.get(key)
        for key in [
            "calorie_target",
            "protein_target",
            "carbs_target",
            "fat_target",
            "fiber_target",
        ]
    }

    scope = targets.get("scope")
    if "今天" in original_text or "今日" in original_text or "低碳日" in original_text:
        scope = "today"
    elif scope not in ["today", "permanent"]:
        scope = "permanent"

    mode_name = targets.get("mode_name")
    if "低碳" in original_text:
        mode_name = "低碳日"

    if not any(v is not None for v in values.values()):
        if "低碳" in original_text:
            return (
                "🍚 可以，今天要低碳沒問題。\n"
                "但我不會擅自把少掉的碳水硬塞成蛋白質或脂肪。\n\n"
                "直接告訴我，例如：\n"
                "「今天碳水80g」或「今天1200卡、碳水80g、蛋白質80g、脂肪45g」"
            )

        return (
            "🎯 可以自己改。\n"
            "例如直接說：\n"
            "「今天碳水80g」\n"
            "「蛋白質改85g」\n"
            "「每天脂肪45g」"
        )

    if scope == "today":
        set_daily_targets(
            user_id,
            calorie_target=values["calorie_target"],
            protein_target=values["protein_target"],
            carbs_target=values["carbs_target"],
            fat_target=values["fat_target"],
            fiber_target=values["fiber_target"],
            mode_name=mode_name,
        )
        prefix = "✅ 今天的目標已調整"
    else:
        set_custom_targets(
            user_id,
            calorie_target=values["calorie_target"],
            protein_target=values["protein_target"],
            carbs_target=values["carbs_target"],
            fat_target=values["fat_target"],
            fiber_target=values["fiber_target"],
        )
        prefix = "✅ 自訂目標已更新"

    return prefix + "\n\n" + targets_reply(user_id)


# =========================================================
# 帳本 / 月報 / 剩餘
# =========================================================

def progress_line(emoji, used, target, unit):
    used = number(used)
    target = number(target)
    remaining = target - used

    if remaining >= 0:
        return (
            f"{emoji} {round(used, 1)} / {round(target, 1)} {unit}"
            f"｜剩 {round(remaining, 1)}"
        )

    return (
        f"{emoji} {round(used, 1)} / {round(target, 1)} {unit}"
        f"｜超 {round(abs(remaining), 1)}"
    )


def today_summary(user_id):
    meals = get_today_meals(user_id)
    totals = totals_to_dict(get_today_totals(user_id))

    if not meals:
        return (
            "📊 今天還沒有飲食紀錄。\n"
            "直接丟餐點照片過來就可以 😎"
        )

    lines = ["📊 今日飲食帳本"]

    for meal in meals:
        lines.append(
            f"{meal.get('meal_type') or '餐點'}｜"
            f"{meal.get('meal_name') or '這一餐'}　"
            f"🔥 {round(number(meal.get('calories')))}"
        )

    lines.extend([
        "──────────",
        f"🔥 {round(totals['calories'])} kcal",
        f"🥩 {round(totals['protein'], 1)}g｜🍚 {round(totals['carbs'], 1)}g",
        f"🥑 {round(totals['fat'], 1)}g｜🥬 {round(totals['fiber'], 1)}g",
    ])

    targets = get_effective_targets(user_id)
    if targets and number(targets.get("calorie_target")):
        remaining = number(targets.get("calorie_target")) - totals["calories"]
        lines.append(f"🎯 目標 {round(number(targets.get('calorie_target')))} kcal")
        if remaining >= 0:
            lines.append(f"還可以吃約 {round(remaining)} kcal")
        else:
            lines.append(f"目前超過約 {round(abs(remaining))} kcal")

    return "\n".join(lines)


def remaining_reply(user_id):
    totals = totals_to_dict(get_today_totals(user_id))
    targets = get_effective_targets(user_id)

    if not targets or not number(targets.get("calorie_target")):
        return (
            f"📊 目前累計 🔥 {round(totals['calories'])} kcal\n"
            f"🥩 {round(totals['protein'], 1)}g"
            f"｜🍚 {round(totals['carbs'], 1)}g"
            f"｜🥑 {round(totals['fat'], 1)}g\n\n"
            "完成個人資料後，我才能算剩餘額度。"
        )

    lines = ["📊 今天剩餘額度"]
    for emoji, key, unit in [
        ("🔥", "calorie_target", "kcal"),
        ("🥩", "protein_target", "g"),
        ("🍚", "carbs_target", "g"),
        ("🥑", "fat_target", "g"),
    ]:
        used_key = {
            "calorie_target": "calories",
            "protein_target": "protein",
            "carbs_target": "carbs",
            "fat_target": "fat",
        }[key]

        lines.append(
            progress_line(
                emoji,
                totals[used_key],
                targets.get(key),
                unit,
            )
        )

    return "\n".join(lines)


def month_report(user_id, year=None, month=None):
    now = datetime.now(TAIWAN_TZ)
    year = int(year or now.year)
    month = int(month or now.month)

    summary = get_month_summary(user_id, year, month)

    if not summary or summary.get("recorded_days", 0) == 0:
        return f"📅 {year} 年 {month} 月目前還沒有飲食紀錄。"

    lines = [
        f"📅 {year} 年 {month} 月飲食紀錄",
        f"已記錄 {summary['recorded_days']} 天｜{summary['meal_count']} 餐",
        "",
        f"🔥 平均 {round(number(summary['avg_calories']))} kcal / 日",
        f"🥩 {round(number(summary['avg_protein']), 1)}g"
        f"｜🍚 {round(number(summary['avg_carbs']), 1)}g",
        f"🥑 {round(number(summary['avg_fat']), 1)}g"
        f"｜🥬 {round(number(summary['avg_fiber']), 1)}g",
        "",
        f"📈 最高 {round(number(summary['highest_calories']))} kcal",
        f"📉 最低 {round(number(summary['lowest_calories']))} kcal",
    ]

    weights = get_month_weight_logs(user_id, year, month)
    if weights:
        first = number(weights[0].get("weight_kg"))
        last = number(weights[-1].get("weight_kg"))
        diff = last - first
        sign = "+" if diff > 0 else ""
        lines.extend([
            "",
            f"⚖️ {first:g} → {last:g} kg｜{sign}{round(diff, 1):g} kg",
        ])

    days = summary.get("days") or []
    if days:
        lines.append("")
        lines.append("最近紀錄")
        for row in days[-7:][::-1]:
            meal_date = row.get("meal_date")
            label = meal_date.strftime("%m/%d") if hasattr(meal_date, "strftime") else str(meal_date)
            lines.append(f"{label}　{round(number(row.get('calories')))} kcal")

    return "\n".join(lines)


# =========================================================
# 餐點 Flex Card
# =========================================================

def make_meal_card(data, today_totals, user_id, corrected=False):
    today = totals_to_dict(today_totals)
    total = data.get("total") or {}
    foods = data.get("foods") or []
    meal_name = data.get("meal_name") or "這一餐"

    title = ("✏️ 已更新｜" if corrected else "🍱 ") + meal_name

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
            "text": f"🔥 約 {round(number(total.get('calories')))} kcal",
            "weight": "bold",
            "size": "xxl",
            "margin": "md",
        },
        {
            "type": "text",
            "text": (
                f"🥩 {round(number(total.get('protein')), 1)}g"
                f"　🍚 {round(number(total.get('carbs')), 1)}g"
                f"　🥑 {round(number(total.get('fat')), 1)}g"
            ),
            "size": "sm",
            "margin": "sm",
            "wrap": True,
        },
        {"type": "separator", "margin": "lg"},
    ]

    for food in foods[:7]:
        body.append({
            "type": "box",
            "layout": "horizontal",
            "margin": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": f"• {food.get('name') or '食物'} {food.get('quantity') or ''}",
                    "size": "sm",
                    "wrap": True,
                    "flex": 7,
                },
                {
                    "type": "text",
                    "text": f"{round(number(food.get('calories')))} kcal",
                    "size": "sm",
                    "align": "end",
                    "flex": 3,
                },
            ],
        })

    body.extend([
        {"type": "separator", "margin": "lg"},
        {
            "type": "text",
            "text": "📊 今日累計",
            "weight": "bold",
            "margin": "lg",
        },
    ])

    targets = get_effective_targets(user_id)

    if targets and number(targets.get("calorie_target")):
        body.extend([
            {
                "type": "text",
                "text": progress_line(
                    "🔥", today["calories"],
                    targets.get("calorie_target"), "kcal"
                ),
                "size": "sm", "margin": "sm", "wrap": True,
            },
            {
                "type": "text",
                "text": progress_line(
                    "🥩", today["protein"],
                    targets.get("protein_target"), "g"
                ),
                "size": "sm", "margin": "sm", "wrap": True,
            },
            {
                "type": "text",
                "text": progress_line(
                    "🍚", today["carbs"],
                    targets.get("carbs_target"), "g"
                ),
                "size": "sm", "margin": "sm", "wrap": True,
            },
            {
                "type": "text",
                "text": progress_line(
                    "🥑", today["fat"],
                    targets.get("fat_target"), "g"
                ),
                "size": "sm", "margin": "sm", "wrap": True,
            },
        ])
    else:
        body.append({
            "type": "text",
            "text": (
                f"🔥 {round(today['calories'])} kcal｜"
                f"🥩 {round(today['protein'], 1)}g｜"
                f"🍚 {round(today['carbs'], 1)}g｜"
                f"🥑 {round(today['fat'], 1)}g"
            ),
            "size": "sm",
            "margin": "sm",
            "wrap": True,
        })

    comment = data.get("comment")
    if comment:
        body.extend([
            {"type": "separator", "margin": "lg"},
            {
                "type": "text",
                "text": "💬 " + str(comment),
                "size": "sm",
                "wrap": True,
                "margin": "lg",
            },
        ])

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
        alt_text=f"{meal_name}｜{round(number(total.get('calories')))} kcal",
        contents=FlexContainer.from_dict(card),
    )


# =========================================================
# 圖片壓縮
# =========================================================

def compress_image(image_bytes):
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        image.thumbnail((1280, 1280))

        output = io.BytesIO()
        image.save(
            output,
            format="JPEG",
            quality=82,
            optimize=True,
        )

        compressed = output.getvalue()
        print(
            "IMAGE_SIZE:",
            len(image_bytes),
            "->",
            len(compressed),
            flush=True,
        )

        return compressed, "image/jpeg"

    except Exception as e:
        print("IMAGE_COMPRESSION_ERROR:", repr(e), flush=True)
        return image_bytes, "image/jpeg"


# =========================================================
# 快速文字判斷
# =========================================================

def looks_like_meal_correction(text):
    keywords = [
        "其實", "不是", "應該是", "比較多", "更多",
        "比較少", "少一點", "一半", "半份", "沒吃",
        "沒喝", "只吃", "只喝", "漏算", "算錯",
        "抓太少", "抓太多",
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


def extract_month(text):
    match = re.search(r"(?:(20\d{2})\s*年\s*)?(\d{1,2})\s*月", text)
    if not match:
        return None, None

    year = int(match.group(1)) if match.group(1) else None
    month = int(match.group(2))

    if not 1 <= month <= 12:
        return None, None

    return year, month


# =========================================================
# 文字訊息
# =========================================================

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event):
    user_id = get_user_id(event)
    text = event.message.text.strip()

    try:
        current_profile = get_profile(user_id)

        # -------------------------------------------------
        # 快速查詢
        # -------------------------------------------------

        if text in ["我的資料", "查看我的資料", "個人資料", "我的個人資料"]:
            reply_text(event.reply_token, profile_summary(user_id))
            return

        if text in ["我的目標", "今日目標", "今天目標", "營養目標"]:
            reply_text(event.reply_token, targets_reply(user_id))
            return

        if text == "設定資料":
            reply_text(event.reply_token, profile_help())
            return

        if text in [
            "查看今日紀錄", "今日紀錄", "今天吃了什麼",
            "今天吃多少", "今天幾卡", "今天多少熱量",
        ]:
            reply_text(event.reply_token, today_summary(user_id))
            return

        if text in ["今天還能吃多少", "還能吃多少", "剩多少熱量", "剩餘額度"]:
            reply_text(event.reply_token, remaining_reply(user_id))
            return

        # -------------------------------------------------
        # 重置今天
        # -------------------------------------------------

        if text in ["重置今天", "清空今天", "今天重置", "清除今日紀錄"]:
            totals = totals_to_dict(get_today_totals(user_id))

            if totals["meal_count"] == 0:
                reply_text(event.reply_token, "今天本來就是空的啦 😂")
                return

            reply_text(
                event.reply_token,
                (
                    "⚠️ 確定要清空今天的飲食紀錄嗎？\n"
                    f"目前 {totals['meal_count']} 餐｜"
                    f"🔥 {round(totals['calories'])} kcal\n\n"
                    "如果確定，回我「確定重置今天」。"
                ),
            )
            return

        if text in ["確定重置今天", "確定清空今天"]:
            deleted = reset_today(user_id)
            reply_text(
                event.reply_token,
                (
                    f"🗑️ 今天已重置，共清掉 {deleted} 筆餐點。\n"
                    "個人資料、營養目標、食物記憶和以前的紀錄都還在。"
                ),
            )
            return

        # -------------------------------------------------
        # 恢復目標
        # -------------------------------------------------

        if text in [
            "恢復系統建議", "恢復預設", "恢復預設目標",
            "取消自訂目標", "回到系統目標",
        ]:
            clear_daily_targets(user_id)
            reset_custom_targets(user_id)
            reply_text(
                event.reply_token,
                "✅ 已恢復系統建議。\n\n" + targets_reply(user_id),
            )
            return

        if text in ["今天恢復預設", "今天恢復系統建議", "取消今天自訂"]:
            clear_daily_targets(user_id)
            reply_text(
                event.reply_token,
                "✅ 今天已恢復原本目標。\n\n" + targets_reply(user_id),
            )
            return

        # -------------------------------------------------
        # 月報快速指令
        # -------------------------------------------------

        if text in ["這個月紀錄", "本月紀錄", "這個月", "月紀錄", "本月報告"]:
            reply_text(event.reply_token, month_report(user_id))
            return

        year, month = extract_month(text)
        if month and any(k in text for k in ["紀錄", "報告", "總表", "飲食"]):
            reply_text(event.reply_token, month_report(user_id, year, month))
            return

        # -------------------------------------------------
        # 餐別修改
        # -------------------------------------------------

        meal_type_match = re.search(r"(?:上一餐|剛剛|這張|這餐).*?(早餐|午餐|晚餐|點心)", text)
        if meal_type_match:
            last_meal = get_last_meal(user_id)

            if not last_meal:
                reply_text(event.reply_token, "我找不到上一餐可以改 😭")
                return

            meal_type = meal_type_match.group(1)
            update_meal_type(last_meal["id"], user_id, meal_type)
            reply_text(
                event.reply_token,
                f"✅ 好，上一餐已改成「{meal_type}」。\n\n" + today_summary(user_id),
            )
            return

        # -------------------------------------------------
        # 個人資料快速處理
        # -------------------------------------------------

        profile_updates = extract_profile_updates(text, current_profile)

        profile_words = [
            "身高", "體重", "年齡", "性別", "活動量",
            "久坐", "輕量", "中等", "非常高", "減脂",
            "增肌", "維持", "公斤", "kg", "公分", "cm", "歲",
        ]

        waiting_for_profile = current_profile and not profile_is_complete(current_profile)
        standalone_sex = (
            text in ["男", "女", "男性", "女性"]
            and waiting_for_profile
        )

        if profile_updates and (
            any(word.lower() in text.lower() for word in profile_words)
            or standalone_sex
        ):
            profile, completed = save_and_finish_profile(user_id, profile_updates)

            if completed:
                reply_text(
                    event.reply_token,
                    "✅ 個人資料已更新\n\n" + profile_summary(user_id),
                )
            else:
                reply_text(event.reply_token, missing_profile_text(profile))

            return

        # -------------------------------------------------
        # 體重快速紀錄
        # -------------------------------------------------

        weight_match = re.search(
            r"(?:今天|今日)?\s*(?:體重)?\s*(\d{2,3}(?:\.\d+)?)\s*(?:kg|公斤)",
            text,
            flags=re.I,
        )

        if weight_match and any(k in text for k in ["今天", "體重", "公斤", "kg"]):
            weight = float(weight_match.group(1))
            save_weight(user_id, weight)
            reply_text(event.reply_token, f"⚖️ 記下來了：今天 {weight:g} kg")
            return

        # -------------------------------------------------
        # 自訂目標快速處理
        # -------------------------------------------------

        target_words = [
            "蛋白質", "碳水", "碳水化合物", "脂肪", "油脂",
            "熱量目標", "卡路里目標", "低碳", "膳食纖維",
        ]

        if any(k in text for k in target_words) and (
            extract_targets_fast(text)
            or any(k in text for k in ["改", "設定", "目標", "低碳", "不要超過", "最多"])
        ):
            fake_intent = {
                "targets": {
                    **extract_targets_fast(text),
                    "scope": "today" if ("今天" in text or "今日" in text or "低碳日" in text) else "permanent",
                    "mode_name": "低碳日" if "低碳" in text else None,
                }
            }
            reply_text(
                event.reply_token,
                apply_custom_targets(user_id, fake_intent, text),
            )
            return

        # -------------------------------------------------
        # 自然語言修正上一餐
        # -------------------------------------------------

        if looks_like_meal_correction(text):
            last_meal = get_last_meal(user_id)

            if last_meal:
                corrected_data = correct_food_analysis(last_meal, text)
                update_meal(last_meal["id"], corrected_data)

                reply_messages(
                    event.reply_token,
                    [
                        make_meal_card(
                            corrected_data,
                            get_today_totals(user_id),
                            user_id,
                            corrected=True,
                        )
                    ],
                )
                return

        # -------------------------------------------------
        # 刪除上一餐
        # -------------------------------------------------

        if text in [
            "刪掉上一餐", "刪除上一餐", "剛剛傳錯了",
            "上一餐傳錯了", "那餐不要算",
        ]:
            last_meal = get_last_meal(user_id)

            if not last_meal:
                reply_text(event.reply_token, "沒有上一餐可以刪啦 😂")
                return

            delete_meal(last_meal["id"], user_id)
            reply_text(
                event.reply_token,
                "🗑️ 好，上一餐刪除了。\n\n" + today_summary(user_id),
            )
            return

        if text == "我要修正上一餐":
            reply_text(
                event.reply_token,
                (
                    "✏️ 直接跟我講哪裡不對：\n"
                    "「飯其實只有半碗」\n"
                    "「這是牛排不是豬排」\n"
                    "「豆漿是無糖」\n"
                    "「那杯我沒喝」\n"
                    "「還有一顆蛋」"
                ),
            )
            return

        # -------------------------------------------------
        # 其餘交給 V4 AI 路由
        # -------------------------------------------------

        intent_data = classify_user_text(text)
        intent = intent_data.get("intent")

        if intent == "profile":
            incoming = intent_data.get("profile") or {}
            updates = {}

            for key in ["height_cm", "weight_kg", "age"]:
                if incoming.get(key) is not None:
                    updates[key] = incoming.get(key)

            sex = normalize_sex(incoming.get("sex"))
            if sex:
                updates["sex"] = sex

            activity = normalize_activity(incoming.get("activity_level"))
            if activity:
                updates["activity_level"] = activity

            goal = normalize_goal(incoming.get("goal"))
            if goal:
                updates["goal"] = goal

            profile, completed = save_and_finish_profile(user_id, updates)

            if completed:
                reply_text(
                    event.reply_token,
                    "✅ 個人資料已更新\n\n" + profile_summary(user_id),
                )
            else:
                reply_text(event.reply_token, missing_profile_text(profile))
            return

        if intent == "custom_targets":
            reply_text(
                event.reply_token,
                apply_custom_targets(user_id, intent_data, text),
            )
            return

        if intent == "reset_targets":
            scope = (intent_data.get("targets") or {}).get("scope")

            if scope == "today" or "今天" in text:
                clear_daily_targets(user_id)
                msg = "✅ 今天已恢復原本目標。"
            else:
                clear_daily_targets(user_id)
                reset_custom_targets(user_id)
                msg = "✅ 已恢復系統建議。"

            reply_text(event.reply_token, msg + "\n\n" + targets_reply(user_id))
            return

        if intent in ["correct_last", "add_to_last"]:
            last_meal = get_last_meal(user_id)

            if not last_meal:
                reply_text(event.reply_token, "我找不到上一餐可以改 😭")
                return

            if intent == "add_to_last":
                corrected_data = add_food_to_analysis(last_meal, text)
            else:
                corrected_data = correct_food_analysis(last_meal, text)

            update_meal(last_meal["id"], corrected_data)

            memory_keywords = [
                "常喝", "常吃", "固定", "記住",
                "以後都是", "每次都是", "平常都",
            ]

            if any(k in text for k in memory_keywords):
                add_food_memory(user_id, text, data=corrected_data)

            reply_messages(
                event.reply_token,
                [
                    make_meal_card(
                        corrected_data,
                        get_today_totals(user_id),
                        user_id,
                        corrected=True,
                    )
                ],
            )
            return

        if intent == "delete_last":
            last_meal = get_last_meal(user_id)

            if not last_meal:
                reply_text(event.reply_token, "沒有上一餐可以刪啦 😂")
                return

            delete_meal(last_meal["id"], user_id)
            reply_text(
                event.reply_token,
                "🗑️ 好，上一餐刪除了。\n\n" + today_summary(user_id),
            )
            return

        if intent == "set_meal_type":
            last_meal = get_last_meal(user_id)
            meal_type = intent_data.get("meal_type")

            if not last_meal or not meal_type:
                reply_text(event.reply_token, "我找不到要改哪一餐 😭")
                return

            update_meal_type(last_meal["id"], user_id, meal_type)
            reply_text(
                event.reply_token,
                f"✅ 上一餐已改成「{meal_type}」。\n\n" + today_summary(user_id),
            )
            return

        if intent == "reset_today":
            totals = totals_to_dict(get_today_totals(user_id))

            if totals["meal_count"] == 0:
                reply_text(event.reply_token, "今天本來就是空的啦 😂")
            else:
                reply_text(
                    event.reply_token,
                    (
                        "⚠️ 確定清空今天嗎？\n"
                        f"目前 {totals['meal_count']} 餐｜"
                        f"{round(totals['calories'])} kcal\n\n"
                        "回我「確定重置今天」才會真的刪。"
                    ),
                )
            return

        if intent == "today":
            reply_text(event.reply_token, today_summary(user_id))
            return

        if intent == "month_report":
            reply_text(
                event.reply_token,
                month_report(
                    user_id,
                    intent_data.get("report_year"),
                    intent_data.get("report_month"),
                ),
            )
            return

        if intent == "weight_log":
            weight = intent_data.get("weight_kg")

            if weight is None:
                reply_text(event.reply_token, "⚖️ 你今天幾公斤？直接回我數字＋kg 就好。")
            else:
                save_weight(user_id, weight)
                reply_text(event.reply_token, f"⚖️ 記下來了：{number(weight):g} kg")
            return

        if intent == "remaining":
            reply_text(event.reply_token, remaining_reply(user_id))
            return

        if intent == "remember_food":
            memory_text = intent_data.get("memory_text") or text
            add_food_memory(user_id, memory_text)
            reply_text(
                event.reply_token,
                "🧠 記住了。下次照片合理相符時，我會優先參考。",
            )
            return

        if intent in ["meal_advice", "food_question"]:
            answer = food_chat(
                text,
                get_profile(user_id),
                totals_to_dict(get_today_totals(user_id)),
            )
            reply_text(event.reply_token, compact_ai_text(answer))
            return

        # 真正離題才嗆
        reply_text(event.reply_token, off_topic_reply(text))

    except Exception as e:
        print("TEXT_ERROR:", repr(e), flush=True)
        reply_text(
            event.reply_token,
            "🥲 我剛剛腦袋打結了。\n再跟我說一次，我重來。",
        )


# =========================================================
# 圖片訊息
# =========================================================

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    user_id = get_user_id(event)

    try:
        message_id = event.message.id
        image_url = (
            "https://api-data.line.me/"
            f"v2/bot/message/{message_id}/content"
        )

        response = requests.get(
            image_url,
            headers={
                "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
            },
            timeout=20,
        )
        response.raise_for_status()

        image_bytes, content_type = compress_image(response.content)

        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{content_type};base64,{image_base64}"

        memories = get_food_memories(user_id, limit=12)

        food_data = analyze_food_image(
            data_url,
            memories,
        )

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

        reply_messages(
            event.reply_token,
            [
                make_meal_card(
                    food_data,
                    get_today_totals(user_id),
                    user_id,
                    corrected=False,
                )
            ],
        )

    except Exception as e:
        print("IMAGE_ERROR:", repr(e), flush=True)
        reply_text(
            event.reply_token,
            (
                "🥲 這餐分析翻車了。\n"
                "再傳一次給我。\n\n"
                "如果連續翻車，我們就去 Render 抓兇手 😂"
            ),
        )


# =========================================================
# 啟動
# =========================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
    )
