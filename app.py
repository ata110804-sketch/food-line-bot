import os
import base64
import io
import re
import random
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
    StickerMessageContent,
    PostbackEvent,
)

import food_ai as _food_ai

analyze_food_image = _food_ai.analyze_food_image
correct_food_analysis = _food_ai.correct_food_analysis
add_food_to_analysis = _food_ai.add_food_to_analysis
classify_user_text = _food_ai.classify_user_text
food_chat = _food_ai.food_chat
off_topic_reply = _food_ai.off_topic_reply

# 相容保護：即使 Render 暫時還載到舊版 food_ai.py，也不會因缺少
# analyze_food_text 而整個服務啟動失敗。
if hasattr(_food_ai, "analyze_food_text"):
    analyze_food_text = _food_ai.analyze_food_text
else:
    def analyze_food_text(text, meal_type=None):
        meal_label = meal_type or "未指定餐別"
        prompt = f"""
使用者正在新增一筆實際飲食紀錄。
餐別：{meal_label}
使用者描述：「{text}」
請只分析實際吃下或喝下的內容，不要提供建議。
依台灣常見份量合理估算每項食物的 estimated_grams、calories、protein、carbs、fat、fiber、sodium。
meal_name 要簡短；total 為各項合理加總；份量不確定時採中心估計並降低 confidence。
comment 最多一句。
"""
        return _food_ai.structured_response(
            _food_ai.FOOD_SYSTEM_PROMPT, prompt, _food_ai.FOOD_SCHEMA,
            "text_food_analysis", max_tokens=1000
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
    add_water,
    get_today_water,
    get_water_total,
    get_water_target,
    set_water_target,
    reset_water_target,
    delete_last_water,
    reset_water_day,
    get_month_water_summary,
    should_show_yesterday_summary,
    mark_yesterday_summary_shown,
    get_yesterday_snapshot,
    save_exercise,
    get_exercise_by_date,
    get_exercise_totals,
    save_exercise_plan,
    get_latest_exercise_plan,
    mark_exercise_plan,
    get_exercise_range,
    get_unfinished_exercise_plans,
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
    return "LINE Food AI Bot V5.7 is running!"


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


def start_loading(user_id, seconds=60):
    """LINE 一對一聊天室顯示處理中動畫；失敗時不影響主要流程。"""
    if not user_id or user_id == "unknown_user":
        return False

    try:
        response = requests.post(
            "https://api.line.me/v2/bot/chat/loading/start",
            headers={
                "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "chatId": user_id,
                "loadingSeconds": seconds,
            },
            timeout=5,
        )
        response.raise_for_status()
        return True
    except Exception as e:
        print("LOADING_ANIMATION_ERROR:", repr(e), flush=True)
        return False


def social_reply(text):
    raw = str(text or "").strip()
    lower = raw.lower()

    greetings = [
        "嗨", "嗨嗨", "哈囉", "哈啰", "hello", "hi", "hey",
        "安安", "你好", "在嗎", "在嘛", "有人嗎","我來了",
    ]

    if lower in greetings:
        return random.choice([
            "嗨 👋 我在。吃東西就拍給我，別等晚上才來問今天是不是吃爆了🙂",
            "有～我在 😎 今天吃了什麼就丟過來，我幫你記。",
            "哈囉 👋 今天也要記得顧一下熱量跟蛋白質，不准裝沒看到。",
            "在啦 😂 要記飲食、看今天剩多少，還是想找東西吃？",
             "還以為你早就把我忘到九霄雲外去，打算徹底放飛自我了呢！這次過來，是終於肯好好面對今天的飲食紀錄了，還是又默默吃了什麼壞東西不敢面對啊🧐？🔥？",
            "唷 終於肯打開我了，原來你還會在乎你的身體和飲食🧐？",
        ])

    if any(word in raw for word in ["早安", "早ㄤ", "早上好","早"]):
        return random.choice([
            "早安 ☀️ 新的一天重新算，早餐吃了記得拍給我。",
            "早～☀️ 昨天不管吃怎樣今天都正常吃，別搞絕食補償。早餐交出來🙂",
            "早安 👋 今天的帳本是乾淨的，拜託不要第一餐就直接炸掉 😂",
        ])

    if any(word in raw for word in ["晚安", "睡了", "要睡了"]):
        return random.choice([
            "晚安 😴 今天結束就別再巡冰箱了🙂 明天繼續。",
            "去睡 😂 睡眠也很重要，宵夜先不要偷偷加戲。",
            "晚安～今天有記錄就很可以，明天再繼續 📊",
        ])

    if raw in ["謝謝", "感謝", "謝啦", "3q", "thanks", "thank you"]:
        return random.choice([
            "不客氣 😎 記得真的照做，不是看完建議就算完成喔。",
            "可以～有吃東西再丟給我 📸",
            "免客氣，下一餐繼續交作業🙂",
            "你居然也懂得感激我，中國人飛上天了嗎?🙂",
        ])

    return None


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


def compact_ai_text(text, max_lines=16, max_chars=760):
    """整理成 LINE 手機好讀格式；保留條列，不再只截前 7 行。"""
    if not text:
        return "我剛剛沒整理出答案，拜託再問我一次 😵‍💫"

    cleaned = str(text)
    for mark in ["**", "###", "##", "#"]:
        cleaned = cleaned.replace(mark, "")

    raw_lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    lines = []
    for line in raw_lines:
        # 統一常見 Markdown bullet，LINE 看起來比較乾淨。
        line = re.sub(r"^[-*•]\s*", "・", line)
        lines.append(line)

    result = "\n".join(lines[:max_lines])
    if len(result) > max_chars:
        result = result[:max_chars].rstrip(" ・、，。")
        result += "…\n\n想看更詳細的再叫我展開 😎"
    return result


def looks_like_explicit_meal_log(text):
    """先抓明確『我吃了什麼』的陳述，避免被 AI 誤判成 today / advice。"""
    t = re.sub(r"\s+", "", str(text or ""))
    meal_marks = ["早餐", "早上", "午餐", "中午", "晚餐", "晚上", "點心", "宵夜"]
    eat_marks = ["吃了", "吃", "喝了", "喝", "記錄", "紀錄", "幫我記", "記一下"]
    question_marks = ["吃什麼", "可以吃", "能吃", "要吃", "推薦", "建議", "怎麼吃", "嗎", "?", "？"]

    if any(q in t for q in question_marks):
        return False
    if not any(m in t for m in meal_marks):
        return False
    if not any(e in t for e in eat_marks):
        return False

    # 至少有一個餐別後面跟著「吃/喝」；多餐整天輸入尤其優先。
    return bool(re.search(r"(早餐|早上|午餐|中午|晚餐|晚上|點心|宵夜).{0,6}(吃|喝)", t))


def parse_meal_log_by_rules(text):
    """規則式拆餐：明確陳述吃過什麼時，不花 intent token，直接拆成 meal_log。"""
    original = str(text or "").strip()
    t = re.sub(r"\s+", " ", original)
    compact = re.sub(r"\s+", "", original)

    # 問句 / 求建議不要誤記成已吃。
    advice_words = ["吃什麼", "喝什麼", "推薦", "建議", "可以吃", "能吃", "可不可以", "好嗎", "嗎？", "嗎?", "怎麼吃", "該吃", "要吃什麼"]
    if any(w in compact for w in advice_words):
        return []

    aliases = {
        "早餐": "早餐", "早上": "早餐",
        "午餐": "午餐", "中午": "午餐",
        "晚餐": "晚餐", "晚上": "晚餐",
        "點心": "點心", "宵夜": "宵夜",
    }
    pattern = re.compile(r"早餐|早上|午餐|中午|晚餐|晚上|點心|宵夜")
    matches = list(pattern.finditer(t))
    meals = []

    # 有明確餐別：支援「早餐兩顆蛋 午餐健康餐 晚餐漢堡」以及「我早餐吃兩顆蛋」。
    if matches:
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(t)
            body = t[start:end].strip(" ，,、。；;：:")
            body = re.sub(r"^(有|是|吃了|吃|喝了|喝|我吃了|我吃|我喝了|我喝)", "", body).strip(" ，,、。；;：:")
            body = re.sub(r"(幫我)?(記錄|紀錄|記一下|記起來)$", "", body).strip(" ，,、。；;：:")
            if body:
                meals.append({"meal_type": aliases[m.group()], "text": body})
        if meals:
            return meals[:4]

    # 沒寫餐別，但明確說已經吃/喝：交給時間判餐別，至少能記「剛剛吃了一根香蕉」。
    eaten = re.search(r"(?:我)?(?:剛剛|剛才|剛|今天)?(?:又)?(?:吃了|喝了|吃|喝)(.+)", t)
    if eaten:
        body = eaten.group(1).strip(" ，,、。；;：:")
        body = re.sub(r"(幫我)?(記錄|紀錄|記一下|記起來)$", "", body).strip(" ，,、。；;：:")
        if body:
            hour = datetime.now(TAIWAN_TZ).hour
            meal_type = "早餐" if hour < 10 else "午餐" if hour < 14 else "點心" if hour < 17 else "晚餐" if hour < 22 else "宵夜"
            return [{"meal_type": meal_type, "text": body}]

    return []


def advice_request_for_line(user_text, intent):
    """把 AI 輸出限制成適合 LINE 手機閱讀的短條列。"""
    if intent == "exercise_advice":
        format_rule = (
            "請用繁體中文、LINE手機好讀格式回答。先用1句話說今天適合的強度，"
            "再給『方案 A｜約20分鐘』與『方案 B｜約40分鐘』；"
            "每個方案用『・』列2～4個動作，附時間/次數/組數。"
            "最後最多1句提醒。不要寫長段落，不要Markdown表格，總長盡量350字內。"
        )
    elif intent == "meal_advice":
        format_rule = (
            "請用繁體中文、LINE手機好讀格式回答。先用1句話說今天飲食重點，"
            "再給①②③三個可實際吃的組合；每組名稱獨立一行，食物用『・』逐項列出並附大約份量。"
            "最後用👉給1句怎麼選。不要長篇說教，不要Markdown表格，總長盡量400字內。"
        )
    else:
        format_rule = (
            "請用繁體中文、LINE手機好讀格式回答：先直接回答重點，"
            "需要列舉時用『・』條列，每段最多2～3行，最後最多1句提醒。"
            "不要長篇說教，不要Markdown表格，總長盡量320字內。"
        )
    return f"使用者問題：{user_text}\n\n輸出規則：{format_rule}"


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
# V5.2：喝水／昨日摘要／使用說明
# =========================================================

def water_progress_bar(percent):
    filled = max(0, min(10, int(round(float(percent or 0) / 10))))
    return "█" * filled + "░" * (10 - filled)


def water_status_reply(user_id, extra_title=None):
    water = get_today_water(user_id)
    total = int(water["total_ml"])
    target = int(water["target_ml"])
    remaining = int(water["remaining_ml"])
    percent = float(water["percent"])
    hour = datetime.now(TAIWAN_TZ).hour

    if water["reached"]:
        comment = random.choice([
            "今天達標。很好，這項暫時沒有東西可以嘴你 😌",
            "水有喝夠，過關。今天不是仙人掌了 🌵",
            "漂亮，今天喝水有做事。這題我閉嘴 😎",
        ])
    elif hour >= 20 and percent < 70:
        comment = "都晚上了還差這麼多，你的水壺今天是在放年假嗎🙂"
    elif hour >= 15 and percent < 50:
        comment = "都下午了這進度很有勇氣🙂 先去補個 300～500 mL。"
    elif percent < 30:
        comment = "這進度有點像靠空氣補水🙂 水拿起來，先喝一杯。"
    elif remaining <= 300:
        comment = "都走到這裡了，最後一杯不要給我擺爛。"
    else:
        comment = "還沒達標，看到水就喝幾口，別等口渴才想到它。"

    title = (extra_title + "\n") if extra_title else ""
    return (
        f"{title}💧 今日喝水\n"
        f"{total:,} / {target:,} mL\n"
        f"{water_progress_bar(percent)} {round(percent)}%\n"
        f"還差 {remaining:,} mL\n\n"
        f"{comment}"
    )


def has_plain_water_context(text):
    """
    只有明確在講「白開水／飲水」才啟動飲水帳本。
    豆漿、牛奶、咖啡、茶、飲料等不直接算白開水。
    """
    t = str(text or "").lower().strip()

    non_water_drinks = [
        "豆漿", "牛奶", "拿鐵", "咖啡", "奶茶", "紅茶", "綠茶",
        "烏龍", "茶", "果汁", "可樂", "汽水", "飲料", "酒",
        "運動飲料", "能量飲料", "湯",
    ]
    if any(word in t for word in non_water_drinks):
        return False

    strong_water_words = [
        "喝水", "飲水", "白開水", "開水", "水量", "補水",
        "水目標", "飲水目標", "喝水目標",
    ]
    if any(word in t for word in strong_water_words):
        return True

    # 「喝了300ml」這種日常省略「水」的說法可以接受，
    # 但必須同時有喝的動作 + 容量單位，避免把雞胸300g之類誤判。
    has_drink_action = bool(re.search(r"(喝了|喝完|剛剛喝|我喝|有喝|再喝|喝掉)", t))
    has_volume = bool(re.search(r"\d+(?:\.\d+)?\s*(ml|毫升|cc)", t, re.I))
    return has_drink_action and has_volume


def extract_water_amount(text):
    t = str(text or "").lower().replace(",", "")
    t = t.replace("毫升", "ml").replace("cc", "ml")

    if not has_plain_water_context(text):
        return None

    match = re.search(r"(\d+(?:\.\d+)?)\s*ml", t, re.I)
    if match:
        return float(match.group(1))

    # 有明確「喝水」語境時，允許「喝水300」這種省略單位的寫法。
    if any(k in t for k in ["喝水", "飲水", "白開水", "開水", "補水"]):
        match = re.search(r"(\d+(?:\.\d+)?)", t)
        if match:
            value = float(match.group(1))
            if 1 <= value <= 5000:
                return value

    return None


def is_water_log_message(text):
    t = str(text or "").lower()
    if not has_plain_water_context(t):
        return False

    # 目標、查詢、刪除、重置交給各自規則，不當成新增飲水。
    blocked = ["目標", "多少", "進度", "紀錄", "刪", "重置", "清空", "恢復"]
    if any(word in t for word in blocked):
        return False

    action_words = [
        "喝了", "喝完", "剛剛喝", "我喝", "有喝", "再喝",
        "喝水", "補水", "加水", "記水",
    ]
    return any(word in t for word in action_words)


def water_target_from_text(text):
    t = str(text or "").lower().replace(",", "")
    t = t.replace("毫升", "ml").replace("cc", "ml")

    target_phrases = [
        "水目標", "喝水目標", "飲水目標",
        "每天喝水目標", "每日喝水目標",
    ]
    if not any(k in t for k in target_phrases):
        return None

    # 因為已經有明確「喝水目標」關鍵字，所以 2000 / 2000ml 都可接受。
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:ml)?", t, re.I)
    if not match:
        return None

    value = float(match.group(1))
    return value if 500 <= value <= 6000 else None


def usage_help():
    return (
        "📖 BOT 使用說明\n\n"
        "📸／⌨️ 記錄飲食\n"
        "可以傳餐點照片，也可以直接打字。\n"
        "例：『早餐吃蛋餅豆漿』\n"
        "也能一次說：『早餐吃蛋，中午雞胸便當，晚餐鮭魚地瓜』\n"
        "修正例：『剛剛飯只吃一半』『那不是肉，是豆干』\n\n"
        "📊 今日進度\n"
        "『今天還能吃多少？』『蛋白質還差多少？』\n\n"
        "🍱 吃什麼\n"
        "『晚餐吃什麼？』『我想吃鮭魚怎麼配？』\n\n"
        "💧 喝水\n"
        "『喝了500ml』『今天喝多少？』『水目標改2000ml』\n\n"
        "🏃 運動\n"
        "『今天只有20分鐘，做什麼？』『今天很累想動一下』\n\n"
        "⚖️ 體重\n"
        "『今天58.6kg』\n\n"
        "📅 紀錄\n"
        "『今日紀錄』『月紀錄』『昨日紀錄』\n\n"
        "🛠️ 管理\n"
        "『刪掉上一餐』『重置今天』『我的資料』『我的目標』\n\n"
        "不用背格式，直接跟我講人話就好🙂"
    )


def yesterday_summary_reply(user_id):
    snap = get_yesterday_snapshot(user_id)
    totals = totals_to_dict(snap.get("totals"))
    water = snap.get("water") or {}
    targets = snap.get("targets") or {}

    if totals["meal_count"] == 0 and float(water.get("total_ml") or 0) <= 0:
        return None

    lines = [
        f"📅 昨日紀錄｜{snap['date'].strftime('%m/%d')}",
        f"🍽️ {totals['meal_count']} 餐｜🔥 {round(totals['calories'])} kcal",
        f"🥩 {round(totals['protein'], 1)}g｜🍚 {round(totals['carbs'], 1)}g｜🥑 {round(totals['fat'], 1)}g",
    ]

    water_total = int(float(water.get("total_ml") or 0))
    if water_total:
        lines.append(f"💧 喝水 {water_total:,} mL")

    comments = []
    cal_target = targets.get("calorie_target")
    protein_target = targets.get("protein_target")

    if cal_target:
        diff = float(totals["calories"]) - float(cal_target)
        if diff > 150:
            comments.append(f"熱量超過約 {round(diff)} kcal，昨天吃完就算了，今天正常吃，別演絕食戲碼🙂")
        elif diff < -300:
            comments.append(f"熱量比目標少約 {round(abs(diff))} kcal，減脂不是比誰餓得久。")
        else:
            comments.append("熱量大致在目標附近，這項可以。")

    if protein_target:
        pdiff = float(protein_target) - float(totals["protein"])
        if pdiff > 10:
            comments.append(f"蛋白質還差約 {round(pdiff)}g，今天記得補起來。")

    if comments:
        lines.append("")
        lines.append("📝 " + "\n".join(comments[:2]))

    return "\n".join(lines)


def maybe_push_yesterday_summary(user_id):
    """每天第一次互動時主動補一則昨日摘要；沒有昨日紀錄就安靜略過。"""
    try:
        if not should_show_yesterday_summary(user_id):
            return

        summary = yesterday_summary_reply(user_id)
        mark_yesterday_summary_shown(user_id)

        if not summary:
            return

        # 用 Push API，不占用這次事件的 reply token。
        requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "to": user_id,
                "messages": [{"type": "text", "text": summary}],
            },
            timeout=10,
        )
    except Exception as e:
        # 昨日摘要失敗不能影響主要功能
        print("YESTERDAY_SUMMARY_ERROR:", repr(e), flush=True)


def interaction_water_nudge(user_id):
    """互動式提醒：只用在查詢／打招呼等情境，不會因為一則訊息狂洗版。"""
    try:
        water = get_today_water(user_id)
        hour = datetime.now(TAIWAN_TZ).hour
        percent = float(water.get("percent") or 0)

        if hour >= 20 and percent < 60:
            return "💧 順便提醒：都晚上了，今天的水還沒到六成。你的水壺不是擺設🙂"
        if hour >= 15 and percent < 35:
            return "💧 順便提醒：下午了水還不到四成，先補一杯，別靠意志力補水🙂"
        return None
    except Exception:
        return None



# =========================================================
# V5.3 LINE Rich Menu
# =========================================================

def rich_menu_today_reply(user_id):
    """今日進度：飲食剩餘額度 + 喝水進度一起看。"""
    food = remaining_reply(user_id)
    water = water_status_reply(user_id)
    return f"📊 今日進度\n\n{food}\n\n────────────\n{water}"


def rich_menu_food_entry_reply():
    return (
        "📸／⌨️ 記錄飲食\n\n"
        "傳餐點照片，或直接打字告訴我吃了什麼，我都可以幫你記。\n"
        "也可以一次輸入早餐、午餐、晚餐，我會自動拆開。\n\n"
        "拍清楚一點，我比較不會把豆干認成肉🙂\n"
        "如果份量或食物猜錯，直接跟我說：\n"
        "「飯只有半碗」／「那是豆干不是肉」／「這杯我沒喝」"
    )


def rich_menu_water_reply(user_id):
    return (
        water_status_reply(user_id)
        + "\n\n💧 快速記錄\n"
          "直接傳：『喝了250ml』或『喝了500ml』\n"
          "要改目標：『水目標改2000ml』\n\n"
          "水不是看到就算喝，真的喝下去再記🙂"
    )


def rich_menu_more_reply():
    return (
        "☰ 更多功能\n\n"
        "👤 我的資料　→ 傳「我的資料」\n"
        "🎯 我的目標　→ 傳「我的目標」\n"
        "⚖️ 記錄體重　→ 例「今天58.6kg」\n"
        "📅 昨日紀錄　→ 傳「昨日紀錄」\n"
        "🗓️ 月紀錄　→ 傳「月紀錄」\n"
        "✏️ 修正上一餐 → 傳「我要修正上一餐」\n"
        "🗑️ 刪除上一餐 → 傳「刪掉上一餐」\n"
        "🧹 重置今天　→ 傳「重置今天」\n"
        "❓ 完整說明　→ 傳「使用說明」\n\n"
        "不用背啦，想做什麼直接跟我講也可以 😂"
    )



# =========================================================
# V5.6：互動式運動中心（短、直覺、可追蹤）
# =========================================================
EXERCISE_PLANS = {
 "A":{"title":"20 分鐘｜輕鬆保底","minutes":20,"met":4.0,"muscles":"核心・臀部・背部","items":[
  ("死蟲 Dead Bug","3組 × 10下","核心・腹橫肌"),("鳥狗 Bird Dog","2組 × 8下／邊","核心・下背・臀部"),("臀橋 Glute Bridge","3組 × 12下","臀大肌・腿後側"),("彈力帶／滑輪划船","3組 × 12下","背部・二頭肌")]},
 "B":{"title":"45–60 分鐘｜健身房主力","minutes":50,"met":5.5,"muscles":"臀腿・核心・背部","items":[
  ("深蹲／史密斯深蹲","4組 × 5–8下","臀部・大腿前側・核心"),("羅馬尼亞硬舉","4組 × 6–10下","臀部・腿後側"),("腿推","3組 × 8–12下","臀腿"),("腿屈伸","3組 × 10–15下","大腿前側"),("腿後勾","3組 × 10–15下","腿後側")]},
 "C":{"title":"25–30 分鐘｜健身房簡單版","minutes":28,"met":4.5,"muscles":"全身・臀腿・背部","items":[
  ("腿推","3組 × 10下","臀腿"),("坐姿划船","3組 × 10下","背部・二頭肌"),("臀橋／臀推","3組 × 12下","臀部・腿後側"),("核心抗旋轉","2組 × 10下／邊","核心")]},
 "D":{"title":"15–20 分鐘｜低衝擊版","minutes":18,"met":3.0,"muscles":"核心・臀部・上半身","items":[
  ("死蟲","2組 × 8下／邊","核心"),("臀橋","3組 × 12下","臀部"),("坐姿划船","3組 × 12下","背部"),("舒適範圍活動","5分鐘","全身放鬆")]},
}

def _weight_for_exercise(user_id):
    p=get_profile(user_id) or {}; return float(p.get("weight_kg") or 60)

def _cal_range(user_id, minutes, met):
    w=_weight_for_exercise(user_id); mid=met*3.5*w/200*minutes
    return max(1,round(mid*.8)), max(2,round(mid*1.2))

def _postback_button(label,data,style="secondary"):
    return {"type":"button","style":style,"height":"sm","action":{"type":"postback","label":label,"data":data,"displayText":label}}

def exercise_choice_flex(user_id):
    cards=[]
    for code in ["A","B","C","D"]:
        p=EXERCISE_PLANS[code]; lo,hi=_cal_range(user_id,p["minutes"],p["met"])
        cards.append({"type":"bubble","size":"kilo","body":{"type":"box","layout":"vertical","spacing":"md","contents":[
          {"type":"text","text":f"{code}｜{p['title']}","weight":"bold","size":"lg","wrap":True},
          {"type":"text","text":f"🎯 {p['muscles']}","size":"sm","wrap":True,"color":"#555555"},
          {"type":"text","text":f"🔥 約 {lo}–{hi} kcal","size":"sm","color":"#555555"}]},
          "footer":{"type":"box","layout":"vertical","contents":[_postback_button("看這套",f"ex:show:{code}","primary")]}})
    return FlexMessage(alt_text="🏃 今天的運動方案",contents=FlexContainer.from_dict({"type":"carousel","contents":cards}))

def exercise_plan_flex(user_id, code):
    p=EXERCISE_PLANS.get(code,EXERCISE_PLANS["A"]); lo,hi=_cal_range(user_id,p["minutes"],p["met"])
    row=save_exercise_plan(user_id,code,p["title"],p["minutes"],lo,hi,p["muscles"],[{"name":a,"sets":b,"muscles":c} for a,b,c in p["items"]])
    contents=[{"type":"text","text":f"🏋️ {p['title']}","weight":"bold","size":"xl","wrap":True},
      {"type":"text","text":f"🎯 {p['muscles']}   🔥 約 {lo}–{hi} kcal","size":"sm","wrap":True,"color":"#555555"},{"type":"separator","margin":"md"}]
    for i,(name,sets,muscles) in enumerate(p["items"],1):
        contents += [{"type":"text","text":f"{i}  {name}","weight":"bold","margin":"md","wrap":True},
                     {"type":"text","text":f"{sets}｜{muscles}","size":"sm","wrap":True,"color":"#666666"}]
    footer=[_postback_button("▶️ 開始這套",f"ex:start:{row['id']}","primary"),
            _postback_button("✅ 完成訓練",f"ex:done:{row['id']}","primary"),
            _postback_button("🌓 只做一部分",f"ex:partial:{row['id']}"),
            _postback_button("🔄 看其他方案","ex:choices")]
    return FlexMessage(alt_text=f"🏋️ {p['title']}",contents=FlexContainer.from_dict({"type":"bubble","size":"mega","body":{"type":"box","layout":"vertical","contents":contents},"footer":{"type":"box","layout":"vertical","spacing":"sm","contents":footer}}))

def _finish_plan(user_id, plan_id, ratio=1.0):
    row=mark_exercise_plan(user_id,plan_id,'completed' if ratio>=.99 else 'partial',ratio)
    if not row: return "找不到這份訓練紀錄。"
    kcal=round(((float(row.get('calories_low') or 0)+float(row.get('calories_high') or 0))/2)*ratio)
    mins=max(1,round(float(row.get('duration_minutes') or 0)*ratio))
    save_exercise(user_id,row.get('title') or '運動',mins,kcal,'中等',f"方案 {row.get('plan_code')}；完成 {round(ratio*100)}%",row.get('plan_date'))
    return f"✅ 收工，記下來了！\n⏱ {mins} 分鐘　🔥 約 {kcal} kcal\n🎯 {row.get('muscle_groups') or '全身'}\n今天有交作業，可以 😎"

def _date_from_text(text):
    from datetime import timedelta
    now=datetime.now(TAIWAN_TZ).date()
    if '前天' in text: return now-timedelta(days=2)
    if '昨天' in text or '昨日' in text: return now-timedelta(days=1)
    return now

def _parse_exercise_log(text):
    compact=re.sub(r"\s+","",text)
    if not any(k in compact for k in ['運動','健身','走路','快走','跑步','游泳','騎車','腳踏車','深蹲','臀橋','重訓','瑜珈','有氧','練腿','練背','練胸']): return None
    if any(k in compact for k in ['建議','推薦','做什麼','菜單','怎麼練','可以做']): return None
    m=re.search(r'(\d+(?:\.\d+)?)\s*(小時|分鐘|分)',text)
    minutes=None
    if m: minutes=float(m.group(1))*(60 if m.group(2)=='小時' else 1)
    if not minutes: return None
    kind=next((k for k in ['健身','快走','走路','跑步','游泳','騎車','腳踏車','深蹲','臀橋','重訓','瑜珈','有氧','練腿','練背','練胸'] if k in compact),'運動')
    return kind,minutes

def _exercise_history_reply(user_id,text):
    from datetime import timedelta
    today=datetime.now(TAIWAN_TZ).date()
    if '這週' in text or '本週' in text: start=today-timedelta(days=today.weekday()); end=today
    elif '上週' in text: end=today-timedelta(days=today.weekday()+1); start=end-timedelta(days=6)
    elif '這個月' in text or '本月' in text: start=today.replace(day=1); end=today
    else: start=end=_date_from_text(text)
    rows=get_exercise_range(user_id,start,end)
    if not rows:
        pending=get_unfinished_exercise_plans(user_id,7)
        extra="\n👀 不過最近有排過方案、還沒確認完成。可以回我「昨天有做」補登。" if pending else ""
        return f"📊 {start.strftime('%m/%d')}～{end.strftime('%m/%d')} 沒有已確認的運動紀錄。{extra}"
    mins=sum(float(r.get('duration_minutes') or 0) for r in rows); kcal=sum(float(r.get('calories_burned') or 0) for r in rows)
    lines=[f"📊 運動戰報｜{start.strftime('%m/%d')}～{end.strftime('%m/%d')}",f"🏃 {len(rows)} 次　⏱ {round(mins)} 分　🔥 約 {round(kcal)} kcal",""]
    for r in rows[:6]: lines.append(f"・{r['log_date'].strftime('%m/%d')} {r['exercise_type']}｜{round(float(r.get('duration_minutes') or 0))}分・約{round(float(r.get('calories_burned') or 0))}kcal")
    return "\n".join(lines)

def handle_exercise_text_v56(event,user_id,text):
    compact=re.sub(r"\s+","",text)
    if any(k in compact for k in ['有運動嗎','運動幾次','運動多久','消耗多少','運動紀錄','運動戰報','這週運動','本週運動','上週運動','這個月運動','本月運動']):
        reply_text(event.reply_token,_exercise_history_reply(user_id,text)); return True
    if any(k in compact for k in ['運動建議','健身房菜單','健身菜單','今天練什麼','今天做什麼運動']):
        reply_messages(event.reply_token,[exercise_choice_flex(user_id)]); return True
    parsed=_parse_exercise_log(text)
    if parsed:
        kind,mins=parsed; met={'走路':3.3,'快走':4.3,'跑步':7.5,'游泳':6.0,'騎車':5.5,'腳踏車':5.5,'瑜珈':2.8}.get(kind,5.0)
        lo,hi=_cal_range(user_id,mins,met); kcal=round((lo+hi)/2); d=_date_from_text(text)
        save_exercise(user_id,kind,mins,kcal,'中等','自然語言補登',d)
        reply_text(event.reply_token,f"✅ 補登完成｜{d.strftime('%m/%d')}\n🏃 {kind}　⏱ {round(mins)} 分\n🔥 約 {kcal} kcal\n有做就算數，沒有漏掉 😎"); return True
    if any(k in compact for k in ['昨天有做','前天有做','那套做完','剛剛那套做完']):
        d=_date_from_text(text); row=get_latest_exercise_plan(user_id,target_date=d)
        if row: reply_text(event.reply_token,_finish_plan(user_id,row['id'],1.0)); return True
    return False



# =========================================================
# V5.7：常用運動模板 + 飲食 ABC 中心
# =========================================================
WORKOUT_TEMPLATES = {
    "UPPER": {"title":"上半身日","subtitle":"胸・背・肩・手臂","minutes":45,"met":5.0,"muscles":"胸・背・肩・二頭・三頭","items":[
        ("胸推／啞鈴臥推","3組 × 8–12下","胸・三頭"),("坐姿划船","3組 × 8–12下","背・二頭"),("肩推","3組 × 8–12下","肩・三頭"),("滑輪下拉","3組 × 8–12下","背・二頭"),("二頭彎舉","2組 × 10–15下","二頭"),("三頭下壓","2組 × 10–15下","三頭")]},
    "LOWER": {"title":"下半身日","subtitle":"臀・腿前・腿後","minutes":50,"met":5.5,"muscles":"臀部・大腿前側・腿後側","items":[
        ("深蹲／史密斯深蹲","4組 × 6–10下","臀・腿前・核心"),("羅馬尼亞硬舉","3組 × 8–12下","臀・腿後"),("腿推","3組 × 10–12下","臀腿"),("腿屈伸","3組 × 10–15下","腿前"),("腿後勾","3組 × 10–15下","腿後")]},
    "PUSH": {"title":"推日 Push","subtitle":"胸・肩・三頭","minutes":45,"met":5.0,"muscles":"胸・肩・三頭","items":[
        ("胸推／臥推","4組 × 6–10下","胸・三頭"),("肩推","3組 × 8–12下","肩・三頭"),("上斜胸推","3組 × 8–12下","上胸"),("側平舉","3組 × 12–15下","中束三角肌"),("三頭下壓","3組 × 10–15下","三頭")]},
    "PULL": {"title":"拉日 Pull","subtitle":"背・後肩・二頭","minutes":45,"met":5.0,"muscles":"背部・後肩・二頭","items":[
        ("滑輪下拉","4組 × 8–12下","背闊肌・二頭"),("坐姿划船","3組 × 8–12下","中背・二頭"),("單臂划船","3組 × 10下／邊","背闊肌"),("面拉 Face Pull","3組 × 12–15下","後肩・上背"),("二頭彎舉","3組 × 10–15下","二頭")]},
    "FULL": {"title":"全身日","subtitle":"時間少就練這套","minutes":40,"met":5.0,"muscles":"臀腿・胸・背・核心","items":[
        ("腿推／深蹲","3組 × 8–12下","臀腿"),("胸推","3組 × 8–12下","胸・三頭"),("坐姿划船","3組 × 8–12下","背・二頭"),("臀橋／臀推","3組 × 10–12下","臀部"),("核心抗旋轉","2組 × 10下／邊","核心")]},
    "LOW": {"title":"低衝擊日","subtitle":"不跳、不跑、溫和完成","minutes":25,"met":3.0,"muscles":"核心・臀部・上半身","items":[
        ("死蟲 Dead Bug","2組 × 8下／邊","核心"),("臀橋","3組 × 12下","臀部"),("坐姿划船","3組 × 12下","背部"),("坐姿肩推","2組 × 10下","肩部"),("舒適範圍活動","5分鐘","放鬆")]} }

DIET_MODES = {
 "CUT": {"title":"一般減脂日","note":"穩穩吃，不用餓。蛋白質先顧好。","choices":[
   ("A｜超商快狠準","雞胸 1 份＋茶葉蛋 2 顆＋地瓜 1 條＋生菜","約 500 kcal","蛋白質 45g｜碳水 48g｜脂肪 14g","糖 約 9g｜鈉 約 850mg"),
   ("B｜便當穩定版","烤雞腿便當：飯半碗＋青菜 2 格＋蛋／豆腐","約 560 kcal","蛋白質 38g｜碳水 55g｜脂肪 20g","糖 約 8g｜鈉 約 950mg"),
   ("C｜火鍋舒服版","瘦肉 1 份＋豆腐＋大量青菜＋冬粉半份","約 520 kcal","蛋白質 40g｜碳水 42g｜脂肪 18g","糖 約 10g｜鈉 約 1100mg")]},
 "HIGH": {"title":"高蛋白日","note":"今天蛋白質落後，就從這裡補。","choices":[
   ("A｜雞胸組","雞胸 150g＋蛋 2 顆＋飯半碗＋青菜","約 520 kcal","蛋白質 55g｜碳水 42g｜脂肪 16g","糖 約 5g｜鈉 約 750mg"),
   ("B｜魚肉組","鮭魚 120g＋豆腐＋飯半碗＋青菜","約 560 kcal","蛋白質 43g｜碳水 40g｜脂肪 24g","糖 約 5g｜鈉 約 700mg"),
   ("C｜懶人組","無糖高蛋白飲＋茶葉蛋 2 顆＋雞肉沙拉＋香蕉","約 480 kcal","蛋白質 45g｜碳水 45g｜脂肪 14g","糖 約 18g｜鈉 約 800mg")]},
 "LOWCARB": {"title":"低碳日","note":"低碳不是零碳；蔬菜和蛋白質照吃。","choices":[
   ("A｜雞肉低碳","雞腿排／雞胸＋蛋＋青菜 2–3 份＋豆腐","約 450 kcal","蛋白質 48g｜碳水 18g｜脂肪 21g","糖 約 7g｜鈉 約 800mg"),
   ("B｜火鍋低碳","肉片＋蛋＋豆腐＋菇菜，不加麵飯","約 500 kcal","蛋白質 45g｜碳水 22g｜脂肪 25g","糖 約 9g｜鈉 約 1200mg"),
   ("C｜超商低碳","雞胸＋茶葉蛋 2 顆＋無糖豆漿＋沙拉","約 430 kcal","蛋白質 50g｜碳水 20g｜脂肪 17g","糖 約 8g｜鈉 約 900mg")]},
 "FREE": {"title":"放縱日／彈性餐","note":"可以爽，但不是從容地走進去、狼狽地扶牆出來 😂","choices":[
   ("A｜漢堡想吃就吃","單層漢堡＋無糖飲；薯條小份或不點","約 550–700 kcal","蛋白質 25–35g｜碳水 55–75g｜脂肪 22–30g","糖 約 8–18g｜鈉 約 1000–1500mg"),
   ("B｜麵飯派","喜歡的主食正常 1 份＋蛋白質 1 份＋青菜","約 650–800 kcal","蛋白質 30–40g｜碳水 75–100g｜脂肪 20–30g","糖依餐點｜鈉約 1000–1600mg"),
   ("C｜甜點派","正餐先吃蛋白質＋蔬菜，再留 1 份甜點","約 650–850 kcal","蛋白質 30–40g｜碳水 70–100g｜脂肪 25–35g","糖 約 25–45g｜鈉依餐點")]} }

def workout_template_menu_flex(user_id):
    cards=[]
    for code,p in WORKOUT_TEMPLATES.items():
        lo,hi=_cal_range(user_id,p['minutes'],p['met'])
        cards.append({"type":"bubble","size":"kilo","body":{"type":"box","layout":"vertical","spacing":"md","contents":[
          {"type":"text","text":f"🏋️ {p['title']}","weight":"bold","size":"xl","wrap":True},
          {"type":"text","text":p['subtitle'],"size":"sm","color":"#666666","wrap":True},
          {"type":"text","text":f"⏱ {p['minutes']} 分鐘　🔥 約 {lo}–{hi} kcal","size":"sm","wrap":True},
          {"type":"text","text":f"🎯 {p['muscles']}","size":"sm","wrap":True}]},
          "footer":{"type":"box","layout":"vertical","contents":[_postback_button("直接看菜單",f"tpl:show:{code}","primary")]}})
    return FlexMessage(alt_text="🏋️ 我的常用運動模板",contents=FlexContainer.from_dict({"type":"carousel","contents":cards}))

def workout_template_detail_flex(user_id,code):
    p=WORKOUT_TEMPLATES.get(code,WORKOUT_TEMPLATES['FULL']); lo,hi=_cal_range(user_id,p['minutes'],p['met'])
    row=save_exercise_plan(user_id,f"TPL_{code}",p['title'],p['minutes'],lo,hi,p['muscles'],[{"name":a,"sets":b,"muscles":c} for a,b,c in p['items']])
    body=[{"type":"text","text":f"🏋️ {p['title']}","weight":"bold","size":"xl"},
          {"type":"text","text":f"⏱ {p['minutes']} 分　🔥 約 {lo}–{hi} kcal","size":"sm","color":"#555555"},
          {"type":"text","text":f"🎯 {p['muscles']}","size":"sm","wrap":True},{"type":"separator","margin":"md"}]
    for i,(name,sets,muscles) in enumerate(p['items'],1):
        body += [{"type":"text","text":f"{i}  {name}","weight":"bold","margin":"md","wrap":True},{"type":"text","text":f"{sets}｜{muscles}","size":"sm","color":"#666666","wrap":True}]
    footer=[_postback_button("▶️ 開始這套",f"ex:start:{row['id']}","primary"),_postback_button("✅ 完成訓練",f"ex:done:{row['id']}","primary"),_postback_button("🌓 做一部分",f"ex:partial:{row['id']}"),_postback_button("↩️ 其他模板","tpl:menu")]
    return FlexMessage(alt_text=f"🏋️ {p['title']}",contents=FlexContainer.from_dict({"type":"bubble","size":"mega","body":{"type":"box","layout":"vertical","contents":body},"footer":{"type":"box","layout":"vertical","spacing":"sm","contents":footer}}))

def diet_mode_menu_flex():
    cards=[]
    for code,p in DIET_MODES.items():
        cards.append({"type":"bubble","size":"kilo","body":{"type":"box","layout":"vertical","spacing":"md","contents":[
          {"type":"text","text":f"🍱 {p['title']}","weight":"bold","size":"xl","wrap":True},{"type":"text","text":p['note'],"size":"sm","color":"#666666","wrap":True},
          {"type":"text","text":"點進去看 A／B／C 三種吃法","size":"sm","wrap":True}]},"footer":{"type":"box","layout":"vertical","contents":[_postback_button("看 ABC",f"diet:mode:{code}","primary")]}})
    return FlexMessage(alt_text="🍱 飲食 ABC",contents=FlexContainer.from_dict({"type":"carousel","contents":cards}))

def diet_choices_flex(code):
    p=DIET_MODES.get(code,DIET_MODES['CUT']); cards=[]
    for title,foods,kcal,macro,extra in p['choices']:
        cards.append({"type":"bubble","size":"kilo","body":{"type":"box","layout":"vertical","spacing":"md","contents":[
          {"type":"text","text":title,"weight":"bold","size":"xl","wrap":True},{"type":"text","text":foods,"size":"md","wrap":True},
          {"type":"separator","margin":"md"},{"type":"text","text":f"🔥 {kcal}","weight":"bold","margin":"md"},{"type":"text","text":f"🥩 {macro}","size":"sm","wrap":True},{"type":"text","text":f"🧂 {extra}","size":"sm","color":"#666666","wrap":True}]},
          "footer":{"type":"box","layout":"vertical","contents":[_postback_button("↩️ 換飲食模式","diet:menu")]}})
    return FlexMessage(alt_text=f"🍱 {p['title']} A/B/C",contents=FlexContainer.from_dict({"type":"carousel","contents":cards}))

@handler.add(PostbackEvent)
def handle_postback_v56(event):
    user_id=get_user_id(event); data=getattr(event.postback,'data','') or ''
    try:
        if data=='tpl:menu': reply_messages(event.reply_token,[workout_template_menu_flex(user_id)]); return
        m=re.match(r'tpl:show:(UPPER|LOWER|PUSH|PULL|FULL|LOW)$',data)
        if m: reply_messages(event.reply_token,[workout_template_detail_flex(user_id,m.group(1))]); return
        if data=='diet:menu': reply_messages(event.reply_token,[diet_mode_menu_flex()]); return
        m=re.match(r'diet:mode:(CUT|HIGH|LOWCARB|FREE)$',data)
        if m: reply_messages(event.reply_token,[diet_choices_flex(m.group(1))]); return
        if data=='ex:choices': reply_messages(event.reply_token,[exercise_choice_flex(user_id)]); return
        m=re.match(r'ex:show:([A-D])$',data)
        if m: reply_messages(event.reply_token,[exercise_plan_flex(user_id,m.group(1))]); return
        m=re.match(r'ex:start:(\d+)$',data)
        if m:
            row=mark_exercise_plan(user_id,int(m.group(1)),'started',0)
            reply_text(event.reply_token,f"▶️ 開始！{row.get('title') if row else '今天這套'}\n照順序做就好，不用一次看一大坨文字 💪"); return
        m=re.match(r'ex:done:(\d+)$',data)
        if m: reply_text(event.reply_token,_finish_plan(user_id,int(m.group(1)),1.0)); return
        m=re.match(r'ex:partial:(\d+)$',data)
        if m:
            pid=m.group(1)
            flex={"type":"bubble","body":{"type":"box","layout":"vertical","contents":[{"type":"text","text":"🌓 今天做到多少？","weight":"bold","size":"xl"},{"type":"text","text":"不用硬湊100%，有做就記。","margin":"md","color":"#666666"}]},"footer":{"type":"box","layout":"vertical","spacing":"sm","contents":[_postback_button("大約 75%",f"ex:pct:{pid}:75","primary"),_postback_button("大約 50%",f"ex:pct:{pid}:50"),_postback_button("大約 25%",f"ex:pct:{pid}:25")]}}
            reply_messages(event.reply_token,[FlexMessage(alt_text='🌓 選擇完成程度',contents=FlexContainer.from_dict(flex))]); return
        m=re.match(r'ex:pct:(\d+):(25|50|75)$',data)
        if m: reply_text(event.reply_token,_finish_plan(user_id,int(m.group(1)),int(m.group(2))/100)); return
    except Exception as e:
        print('POSTBACK_V56_ERROR',repr(e),flush=True); reply_text(event.reply_token,'🥲 剛剛按鈕卡了一下，再按一次就好。')

def rich_menu_smart_advice(user_id, mode):
    profile = get_profile(user_id)
    totals = totals_to_dict(get_today_totals(user_id))
    targets = get_effective_targets(user_id)

    if mode == "meal":
        prompt = (
            "我現在不知道下一餐吃什麼。請直接依照我的個人資料、減脂/維持/增肌目標、"
            "今天已吃的營養與今天剩餘額度，推薦 2～3 個實際可吃的下一餐組合。"
            "優先補不足的營養，不要讓已經偏高的項目繼續爆掉。"
            "請用LINE手機好讀格式：先1句飲食重點，再列①②③三個組合；"
            "每組食物用『・』逐項列出並附大約份量，最後用👉給1句怎麼選。"
            "不要長段落、不要表格，總長盡量400字內。"
        )
    else:
        prompt = (
            "請依照我的個人資料、目標和今天的飲食狀況，給我今天適合的運動建議。"
            "給 2 個選擇：一個約20分鐘、一個約40分鐘。"
            "請用LINE手機好讀格式：先1句今天適合的強度，再列『方案 A｜約20分鐘』"
            "和『方案 B｜約40分鐘』；每個方案用『・』列動作與時間/次數/組數。"
            "最後最多1句提醒。不要長篇說教、不要表格。"
            "如果資料不足，就給一般安全的中等強度方案，不要假裝知道我的傷病狀況。"
        )

    answer = food_chat(prompt, profile, totals, targets)
    title = "🍱 今天吃什麼" if mode == "meal" else "🏃 今天動什麼"
    return title + "\n\n" + compact_ai_text(answer)


# =========================================================
# 文字訊息
# =========================================================

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event):
    user_id = get_user_id(event)
    text = event.message.text.strip()

    try:
        current_profile = get_profile(user_id)
        maybe_push_yesterday_summary(user_id)

        # -------------------------------------------------
        # V5.3 LINE Rich Menu 六大入口
        # 必須放在一般聊天 / AI 判斷之前，避免選單文字被誤判。
        # -------------------------------------------------

        if text in ["我的模板","常用模板","運動模板","我的常用模板"]:
            reply_messages(event.reply_token,[workout_template_menu_flex(user_id)])
            return

        if text in ["飲食ABC","飲食 ABC","菜單ABC","菜單 ABC","飲食選擇"]:
            reply_messages(event.reply_token,[diet_mode_menu_flex()])
            return

        if text in ["低碳日","低碳菜單"]:
            reply_messages(event.reply_token,[diet_choices_flex("LOWCARB")])
            return

        if text in ["放縱日","放縱餐","彈性餐"]:
            reply_messages(event.reply_token,[diet_choices_flex("FREE")])
            return

        if text == "記錄飲食":
            reply_text(event.reply_token, rich_menu_food_entry_reply())
            return

        if text == "今日進度":
            reply_text(event.reply_token, rich_menu_today_reply(user_id))
            return

        if text == "吃什麼":
            reply_text(event.reply_token, rich_menu_smart_advice(user_id, "meal"))
            return

        if text == "喝水":
            reply_text(event.reply_token, rich_menu_water_reply(user_id))
            return

        if text == "運動建議":
            reply_messages(event.reply_token, [exercise_choice_flex(user_id)])
            return

        if text == "更多功能":
            reply_text(event.reply_token, rich_menu_more_reply())
            return

        # -------------------------------------------------
        # V5.6 運動：查詢 / 補登 / 建議（不碰 V5.5 飲食路由）
        # -------------------------------------------------
        if handle_exercise_text_v56(event, user_id, text):
            return

        # -------------------------------------------------
        # V5.5 核心文字路由：規則優先於閒聊與 AI
        # -------------------------------------------------
        # 1) 喝水查詢先攔截，避免「我今天喝了多少水」被當成飲食或喝水新增。
        water_query_compact = re.sub(r"\s+", "", text)
        if (
            ("水" in water_query_compact or "喝" in water_query_compact)
            and any(k in water_query_compact for k in ["多少", "幾ml", "幾ML", "幾毫升", "進度", "喝水紀錄", "飲水紀錄"])
            and not re.search(r"\d+(?:\.\d+)?\s*(?:ml|mL|ML|毫升|cc|CC)", text)
        ):
            reply_text(event.reply_token, water_status_reply(user_id))
            return

        # 2) 明確『已經吃了什麼』直接規則拆餐，不再交給 AI 猜 intent。
        #    支援：早餐兩顆蛋／我早餐吃兩顆蛋／早餐...午餐...晚餐...／剛剛吃了香蕉。
        rule_meals = parse_meal_log_by_rules(text)
        if rule_meals:
            # 昨日補登目前不可偷寫成今天；保留安全擋板。
            if "昨天" in text or "昨日" in text:
                reply_text(
                    event.reply_token,
                    "📅 我知道你是在補昨天的飲食，但目前這版先不把它誤寫進今天。"
                )
                return

            start_loading(user_id, 60)
            saved = []
            for meal in rule_meals[:4]:
                meal_type = meal.get("meal_type") or "點心"
                meal_text = str(meal.get("text") or "").strip()
                if not meal_text:
                    continue
                food_data = analyze_food_text(meal_text, meal_type)
                food_data["meal_type"] = meal_type
                save_meal(user_id, food_data, meal_type=meal_type)
                saved.append((meal_type, food_data))

            if saved:
                totals = totals_to_dict(get_today_totals(user_id))
                lines = [f"✅ 已記錄 {len(saved)} 餐"]
                for meal_type, data in saved:
                    total = data.get("total") or {}
                    name = data.get("meal_name") or meal_text
                    lines.append(f"・{meal_type}｜{name}　🔥 {round(number(total.get('calories')))} kcal")
                lines.extend([
                    "──────────",
                    f"📊 今日累計｜🔥 {round(totals['calories'])} kcal",
                    f"🥩 {round(totals['protein'], 1)}g｜🍚 {round(totals['carbs'], 1)}g｜🥑 {round(totals['fat'], 1)}g",
                ])
                reply_text(event.reply_token, "\n".join(lines))
                return

        # -------------------------------------------------
        # 日常互動：嗨／早安／晚安／謝謝
        # 注意：一定放在飲食規則後面，否則「早餐／早上」會被早安邏輯攔走。
        # -------------------------------------------------

        casual = social_reply(text)
        if casual:
            reply_text(event.reply_token, casual)
            return

        # -------------------------------------------------
        # V5.2 使用說明
        # -------------------------------------------------

        if text.lower() in [
            "怎麼用", "使用說明", "使用方法", "指令", "help",
            "你會什麼", "功能", "功能說明",
        ]:
            reply_text(event.reply_token, usage_help())
            return

        # -------------------------------------------------
        # V5.2 昨日紀錄
        # -------------------------------------------------

        if text in ["昨日紀錄", "昨天紀錄", "昨天吃了什麼", "昨日飲食", "昨天飲食"]:
            summary = yesterday_summary_reply(user_id)
            reply_text(
                event.reply_token,
                summary or "📅 昨天沒有找到飲食或喝水紀錄。",
            )
            return

        # -------------------------------------------------
        # V5.2 喝水
        # -------------------------------------------------

        if text in ["今天喝多少", "今天喝多少水", "喝水進度", "今日喝水", "喝水紀錄"]:
            reply_text(event.reply_token, water_status_reply(user_id))
            return

        if text in ["我的喝水目標", "喝水目標", "飲水目標"]:
            target = get_water_target(user_id)
            reply_text(
                event.reply_token,
                f"💧 你目前的每日喝水目標是 {target:,} mL。\n"
                "要改可以直接說：『水目標改2000ml』"
            )
            return

        if text in ["恢復喝水預設", "恢復飲水預設", "重設喝水目標"]:
            reset_water_target(user_id)
            target = get_water_target(user_id)
            reply_text(
                event.reply_token,
                f"✅ 已恢復依體重估算的喝水目標：{target:,} mL／天。"
            )
            return

        target_ml = water_target_from_text(text)
        if target_ml is not None:
            try:
                set_water_target(user_id, target_ml)
                reply_text(
                    event.reply_token,
                    f"💧 好，每日喝水目標改成 {round(target_ml):,} mL。\n"
                    "既然是你自己訂的，之後沒喝到就不要裝失憶🙂"
                )
            except ValueError as e:
                reply_text(event.reply_token, f"⚠️ {e}")
            return

        if text in ["刪掉上一筆喝水", "刪除上一筆喝水", "剛剛的水不要算"]:
            deleted = delete_last_water(user_id)
            if deleted:
                reply_text(event.reply_token, "🗑️ 上一筆喝水已刪除。\n\n" + water_status_reply(user_id))
            else:
                reply_text(event.reply_token, "今天沒有喝水紀錄可以刪。")
            return

        if text in ["重置今天喝水", "清空今天喝水", "喝水重置"]:
            count = reset_water_day(user_id)
            reply_text(event.reply_token, f"🗑️ 今天喝水紀錄已清空，共 {count} 筆。")
            return

        if has_plain_water_context(text) and any(
            phrase in text for phrase in ["我今天有喝水", "今天有喝水", "有喝水", "喝了水", "剛剛喝水","喝水"]
        ) and extract_water_amount(text) is None:
            reply_text(
                event.reply_token,
                "💧 有喝水我知道了，但你喝多少？\n"
                "告訴我容量才記得進去，例如：『喝了300ml』"
            )
            return

        if is_water_log_message(text):
            amount = extract_water_amount(text)
            if amount is None:
                reply_text(
                    event.reply_token,
                    "💧 有喝很好，但容量要告訴我，不然我不能通靈🙂\n"
                    "例如：『喝了300ml的水』"
                )
                return

            try:
                add_water(user_id, amount)
                reply_text(
                    event.reply_token,
                    water_status_reply(
                        user_id,
                        f"✅ +{round(amount):,} mL，記下來了。"
                    )
                )
            except ValueError as e:
                reply_text(event.reply_token, f"⚠️ {e}")
            return

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

        # V5.4.4：飲食陳述「規則優先、AI 第二」。
        # 例如：早餐兩顆茶葉蛋 午餐健康餐 晚餐漢堡，直接拆餐，不再讓 intent AI 猜。
        rule_meals = parse_meal_log_by_rules(text)
        if rule_meals:
            intent_data = {"intent": "meal_log", "meals": rule_meals, "target_date": "今天"}
            intent = "meal_log"
        else:
            intent_data = classify_user_text(text)
            intent = intent_data.get("intent")

        # 舊 AI 路由的第二層保護；規則沒抓到時才可能走到這裡。
        # AI 偶爾會把整天飲食陳述誤判成 today，這裡用 deterministic rule 校正。
        if looks_like_explicit_meal_log(text) and intent != "meal_log":
            retry = classify_user_text(
                "這是一則已經吃過的飲食紀錄，請拆成 meal_log；不要判成 today 或 meal_advice。原文：" + text
            )
            if retry.get("intent") == "meal_log" and retry.get("meals"):
                intent_data = retry
                intent = "meal_log"

        # -------------------------------------------------
        # V5.4 文字飲食紀錄：支援單餐 / 一次多餐
        # -------------------------------------------------

        if intent == "meal_log":
            meals = intent_data.get("meals") or []
            target_date = intent_data.get("target_date")

            # V5.4 第一階段先正式支援「今天」文字記餐。
            # 昨日補登會在 database.py V5.4 接上指定日期後開放，避免嘴上說昨天卻寫進今天。
            if target_date == "昨天" or "昨天" in text or "昨日" in text:
                reply_text(
                    event.reply_token,
                    "📅 我有看懂你是在補昨天的飲食，但目前先不亂寫進今天。\n"
                    "下一版資料庫接上指定日期後，就會直接幫你補登昨天。",
                )
                return

            if not meals:
                reply_text(
                    event.reply_token,
                    "🍱 我知道你是在記飲食，但這句我沒拆出食物內容。\n"
                    "可以直接說：『早餐吃蛋餅豆漿』，或一次把早餐、午餐、晚餐都告訴我。",
                )
                return

            start_loading(user_id, 60)
            saved = []

            for meal in meals[:4]:
                meal_type = meal.get("meal_type") or "點心"
                meal_text = str(meal.get("text") or "").strip()
                if not meal_text:
                    continue

                food_data = analyze_food_text(meal_text, meal_type)
                food_data["meal_type"] = meal_type
                save_meal(user_id, food_data, meal_type=meal_type)
                saved.append((meal_type, food_data))

            if not saved:
                reply_text(event.reply_token, "🍱 這次沒有成功拆出可記錄的餐點，再換個說法給我一次。")
                return

            totals = totals_to_dict(get_today_totals(user_id))
            lines = [f"✅ 已記錄 {len(saved)} 餐"]
            for meal_type, data in saved:
                total = data.get("total") or {}
                name = data.get("meal_name") or "這一餐"
                lines.append(f"{meal_type}｜{name}　🔥 {round(number(total.get('calories')))} kcal")

            lines.extend([
                "──────────",
                f"📊 今日累計 🔥 {round(totals['calories'])} kcal",
                f"🥩 {round(totals['protein'], 1)}g｜🍚 {round(totals['carbs'], 1)}g｜🥑 {round(totals['fat'], 1)}g",
            ])

            # 多餐只回一份精簡總結，避免 LINE 一次噴三四張卡，也節省輸出。
            if len(saved) >= 3:
                lines.append(random.choice([
                    "三餐一次交作業，可以，今天效率有料 😎",
                    "本來應該一餐一餐記，結果你直接從從容容一次交齊 😂",
                    "整天一次報帳成功。這次不是匆匆忙忙連滾帶爬了🙂",
                ]))
            elif len(saved) == 1:
                lines.append(random.choice([
                    "記好了，吃過的就誠實面對帳本🙂",
                    "收到，這餐已入帳。熱量沒有失憶的機會 😂",
                    "好，這餐我已經幫你記錄了。",
                ]))

            reply_text(event.reply_token, "\n".join(lines))
            return

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
                "常喝", "常吃", "固定", "記住","每天吃",
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

        # -------------------------------------------------
        # V5 智能飲食 / 菜單 / 運動建議
        # -------------------------------------------------

        if intent in ["meal_advice", "food_question", "exercise_advice"]:
            # V5 會同時讀：個人資料、今天已吃、今天真正生效的營養目標。
            # 因此可以回答「還差多少蛋白質」、「已超多少熱量」、
            # 「晚餐怎麼配」以及「今天做什麼運動」。
            answer = food_chat(
                advice_request_for_line(text, intent),
                get_profile(user_id),
                totals_to_dict(get_today_totals(user_id)),
                get_effective_targets(user_id),
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
# 貼圖訊息
# =========================================================

@handler.add(MessageEvent, message=StickerMessageContent)
def handle_sticker(event):
    user_id = get_user_id(event)
    maybe_push_yesterday_summary(user_id)

    replies = [
        "收到你的貼圖了 😂 有吃東西的話照片也一起交出來。",
        "貼圖很會喔🙂 今天飲食有乖乖記嗎？",
        "好啦有看到 😂 要查今天進度就跟我說「今天還能吃多少」。",
        "我也想回你一張，但先把正事顧好 😎 吃飯記得拍。",
        "什麼意思? 想要跟我圖戰是不是🙊 來啊who怕who 線下單挑減肥敢不敢🥱。",
        "你好 緩光臨~ 今天要吃什麼也可以直接問我喔💖。",
    ]
    reply_text(event.reply_token, random.choice(replies))


# =========================================================
# 圖片訊息
# =========================================================

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    user_id = get_user_id(event)
    maybe_push_yesterday_summary(user_id)

    # 先讓使用者知道 BOT 有收到照片。LINE 新訊息送出時動畫會自動消失。
    start_loading(user_id, 60)

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
                "⚠️ 這張照片沒有成功分析。\n"
                "這次沒有記進今天的飲食帳本，不用自己刪除。\n\n"
                "再傳一次給我就好 📸\n"
                "如果連續失敗，我們再去 Render 抓兇手 😂"
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
