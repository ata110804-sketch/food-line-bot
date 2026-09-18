import os
import base64
import io
import requests

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
    return "LINE Food AI Bot V2 is running!"


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

    if profile:

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

    if profile:

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

    if not profile:

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
        "👤 想開啟個人熱量目標的話，"
        "把資料一次傳給我：\n\n"
        "例如：\n"
        "身高160 體重65 年齡28 女\n"
        "活動量輕量 目標減脂\n\n"
        "活動量：\n"
        "久坐／輕量／中等／高／非常高\n\n"
        "目標：\n"
        "減脂／維持／增肌\n\n"
        "不想設定也沒關係，"
        "照樣可以直接拍照記錄。"
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

            profile = (
                intent_data.get(
                    "profile"
                )
                or {}
            )

            required_fields = [
                "height_cm",
                "weight_kg",
                "age",
                "sex",
                "activity_level",
                "goal",
            ]

            missing = [
                field
                for field in required_fields
                if profile.get(field) is None
            ]

            if missing:

                reply_text(
                    event.reply_token,
                    profile_help(),
                )

                return

            activity_text = str(
                profile[
                    "activity_level"
                ]
            )

            # 非常高一定要先判斷
            # 不然會被「高」先吃掉
            if "非常高" in activity_text:
                activity_level = "非常高"

            elif "久坐" in activity_text:
                activity_level = "久坐"

            elif "輕" in activity_text:
                activity_level = "輕量"

            elif "中" in activity_text:
                activity_level = "中等"

            elif "高" in activity_text:
                activity_level = "高"

            else:
                activity_level = "輕量"

            profile[
                "activity_level"
            ] = activity_level


            goal_text = str(
                profile["goal"]
            )

            if "減" in goal_text:
                profile["goal"] = "減脂"

            elif "增" in goal_text:
                profile["goal"] = "增肌"

            else:
                profile["goal"] = "維持"


            profile = (
                calculate_targets(
                    profile
                )
            )

            save_profile(
                user_id,
                profile,
            )

            reply_text(
                event.reply_token,
                (
                    "👤 個人模式開好了！\n\n"

                    f"🔥 BMR 約 {profile['bmr']} kcal\n"
                    f"⚡ TDEE 約 {profile['tdee']} kcal\n\n"

                    f"🎯 每日熱量 "
                    f"{profile['calorie_target']} kcal\n"

                    f"🥩 蛋白質 "
                    f"{profile['protein_target']} g\n"

                    f"🍚 碳水 "
                    f"{profile['carbs_target']} g\n"

                    f"🥑 脂肪 "
                    f"{profile['fat_target']} g\n"

                    f"🥬 纖維 "
                    f"{profile['fiber_target']} g\n\n"

                    "之後拍每一餐，我都會順便告訴你"
                    "今天還剩多少額度 😎"
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
                answer,
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
        # V2 速度優化
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
