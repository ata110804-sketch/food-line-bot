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
# 啟動資料庫
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
# 網站
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

    with ApiClient(
        configuration
    ) as api_client:

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
# 使用者 ID
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
# 數字處理
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


def totals_to_dict(
    totals
):

    totals = totals or {}

    return {

        "calories":
            number(
                totals.get(
                    "calories",
                    0
                )
            ),

        "protein":
            number(
                totals.get(
                    "protein",
                    0
                )
            ),

        "carbs":
            number(
                totals.get(
                    "carbs",
                    0
                )
            ),

        "fat":
            number(
                totals.get(
                    "fat",
                    0
                )
            ),

        "fiber":
            number(
                totals.get(
                    "fiber",
                    0
                )
            ),

        "sodium":
            number(
                totals.get(
                    "sodium",
                    0
                )
            ),

        "meal_count":
            int(
                totals.get(
                    "meal_count",
                    0
                )
                or 0
            )
    }


# =========================================================
# BMR / TDEE / 每日營養目標
# =========================================================

def calculate_targets(
    profile
):

    weight = profile["weight_kg"]
    height = profile["height_cm"]
    age = profile["age"]

    sex = str(
        profile["sex"]
    ).lower()

    # Mifflin-St Jeor
    if sex in [
        "男",
        "男性",
        "male",
        "m"
    ]:

        bmr = (
            10 * weight
            + 6.25 * height
            - 5 * age
            + 5
        )

    else:

        bmr = (
            10 * weight
            + 6.25 * height
            - 5 * age
            - 161
        )

    activity_factors = {

        "久坐": 1.2,

        "輕量": 1.375,

        "中等": 1.55,

        "高": 1.725,

        "非常高": 1.9
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
            tdee
            - 350
        )

    elif goal == "增肌":

        calorie_target = (
            tdee
            + 250
        )

    else:

        calorie_target = tdee

    # 避免系統自動產生過低的熱量目標
    if sex in [
        "男",
        "男性",
        "male",
        "m"
    ]:

        calorie_target = max(
            calorie_target,
            1500
        )

    else:

        calorie_target = max(
            calorie_target,
            1200
        )

    if goal in [
        "減脂",
        "增肌"
    ]:

        protein_target = (
            weight
            * 1.6
        )

    else:

        protein_target = (
            weight
            * 1.4
        )

    fat_target = (
        weight
        * 0.8
    )

    remaining_calories = (
        calorie_target
        - protein_target * 4
        - fat_target * 9
    )

    carbs_target = max(
        0,
        remaining_calories / 4
    )

    return {

        **profile,

        "bmr":
            round(bmr),

        "tdee":
            round(tdee),

        "calorie_target":
            round(
                calorie_target
            ),

        "protein_target":
            round(
                protein_target
            ),

        "carbs_target":
            round(
                carbs_target
            ),

        "fat_target":
            round(
                fat_target
            ),

        "fiber_target": 25,

        "inbody":
            profile.get(
                "inbody",
                {}
            )
    }


# =========================================================
# 今日進度文字
# =========================================================

def target_line(
    emoji,
    used,
    target,
    unit
):

    remaining = max(
        0,
        target - used
    )

    return (
        f"{emoji} "
        f"{round(used, 1)} / "
        f"{round(target, 1)} {unit}"
        f"｜剩 {round(remaining, 1)}"
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

    total = data.get(
        "total",
        {}
    )

    foods = data.get(
        "foods",
        []
    )

    meal_name = data.get(
        "meal_name",
        "這一餐"
    )

    title = (
        "✏️ 已修正｜"
        if corrected
        else "🍱 "
    ) + meal_name

    body = [

        {
            "type": "text",
            "text": title,
            "weight": "bold",
            "size": "xl",
            "wrap": True
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
            "margin": "md"
        },

        {
            "type": "separator",
            "margin": "lg"
        }
    ]

    # -----------------------------------------------------
    # 食物清單
    # -----------------------------------------------------

    for food in foods[:8]:

        food_name = food.get(
            "name",
            "食物"
        )

        quantity = food.get(
            "quantity",
            ""
        )

        calories = round(
            number(
                food.get(
                    "calories"
                )
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
                        "flex": 7
                    },

                    {
                        "type": "text",
                        "text": (
                            f"{calories} kcal"
                        ),
                        "size": "sm",
                        "align": "end",
                        "flex": 3
                    }
                ]
            }
        )

    body.extend(
        [

            {
                "type": "separator",
                "margin": "lg"
            },

            {
                "type": "text",
                "text": "📊 今日進度",
                "weight": "bold",
                "margin": "lg"
            }
        ]
    )

    # -----------------------------------------------------
    # 有設定個人目標
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

        remaining_calories = max(
            0,
            calorie_target
            - today["calories"]
        )

        body.extend(
            [

                {
                    "type": "text",
                    "text": target_line(
                        "🔥",
                        today["calories"],
                        calorie_target,
                        "kcal"
                    ),
                    "size": "sm",
                    "margin": "sm"
                },

                {
                    "type": "text",
                    "text": target_line(
                        "🥩",
                        today["protein"],
                        protein_target,
                        "g"
                    ),
                    "size": "sm",
                    "margin": "sm"
                },

                {
                    "type": "text",
                    "text": target_line(
                        "🍚",
                        today["carbs"],
                        carbs_target,
                        "g"
                    ),
                    "size": "sm",
                    "margin": "sm"
                },

                {
                    "type": "text",
                    "text": target_line(
                        "🥑",
                        today["fat"],
                        fat_target,
                        "g"
                    ),
                    "size": "sm",
                    "margin": "sm"
                },

                {
                    "type": "text",
                    "text": (
                        "今天還可以吃約 "
                        f"{round(remaining_calories)} kcal"
                    ),
                    "weight": "bold",
                    "margin": "md",
                    "wrap": True
                }
            ]
        )

    # -----------------------------------------------------
    # 還沒有個人資料
    # -----------------------------------------------------

    else:

        body.extend(
            [

                {
                    "type": "text",
                    "text": (
                        f"🔥 {round(today['calories'])} kcal"
                        "｜"
                        f"🥩 {round(today['protein'], 1)} g"
                    ),
                    "size": "sm",
                    "margin": "sm"
                },

                {
                    "type": "text",
                    "text": (
                        "輸入「設定資料」"
                        "可開啟每日目標 👤"
                    ),
                    "size": "xs",
                    "margin": "md",
                    "wrap": True
                }
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
                    "margin": "lg"
                },

                {
                    "type": "text",
                    "text": (
                        "💬 "
                        + comment
                    ),
                    "size": "sm",
                    "wrap": True,
                    "margin": "lg"
                }
            ]
        )

    # -----------------------------------------------------
    # 卡片
    # -----------------------------------------------------

    card = {

        "type": "bubble",

        "body": {

            "type": "box",
            "layout": "vertical",
            "paddingAll": "18px",
            "contents": body
        },

        "footer": {

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
                        "text": "我要修正上一餐"
                    }
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
                                "text": "查看今日紀錄"
                            }
                        },

                        {
                            "type": "button",
                            "style": "secondary",
                            "height": "sm",

                            "action": {
                                "type": "message",
                                "label": "🗑️ 刪上一餐",
                                "text": "刪掉上一餐"
                            }
                        }
                    ]
                }
            ]
        }
    }

    return FlexMessage(

        alt_text=(
            f"{meal_name}｜"
            f"{round(number(total.get('calories')))} kcal"
        ),

        contents=FlexContainer.from_dict(
            card
        )
    )


# =========================================================
# 今日帳本
# =========================================================

def today_summary(
    user_id
):

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
            "食物照片丟過來，"
            "我來幫你記 😎"
        )

    lines = [

        "📊 今日飲食帳本",
        ""
    ]

    for meal in meals:

        meal_type = (
            meal.get(
                "meal_type"
            )
            or "餐點"
        )

        meal_name = (
            meal.get(
                "meal_name"
            )
            or "這一餐"
        )

        calories = round(
            number(
                meal.get(
                    "calories"
                )
            )
        )

        lines.append(
            f"{meal_type}｜"
            f"{meal_name}  "
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
                "｜"
                f"🥑 {round(totals['fat'], 1)} g"
            )
        ]
    )

    if profile:

        target = number(
            profile.get(
                "calorie_target"
            )
        )

        remaining = (
            target
            - totals["calories"]
        )

        lines.extend(
            [

                "",

                f"🎯 今日目標 "
                f"{round(target)} kcal",

                (
                    "還可以吃約 "
                    f"{max(0, round(remaining))} kcal"
                )
            ]
        )

    return "\n".join(
        lines
    )


# =========================================================
# 今天還能吃多少
# =========================================================

def remaining_reply(
    user_id
):

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
            "先輸入「設定資料」建立"
            "身高、體重和目標，"
            "我才知道你今天還有多少額度 😎"
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

    if remaining > 0:

        return (
            "📊 今天目前\n\n"
            f"🔥 {round(totals['calories'])}"
            f" / {round(calorie_target)} kcal\n"
            f"還有約 {round(remaining)} kcal\n\n"
            f"🥩 蛋白質還差約 "
            f"{max(0, round(protein_remaining))} g\n\n"
            "額度還活著，先別急著開珍奶慶功 😂"
        )

    return (
        "📊 今天目前\n\n"
        f"🔥 {round(totals['calories'])} kcal\n"
        f"約超過目標 "
        f"{round(abs(remaining))} kcal\n\n"
        "不用演災難片 😂 "
        "下一餐正常吃，"
        "蛋白質和蔬菜顧好就行。"
    )


# =========================================================
# 圖片速度優化
# =========================================================

def compress_image(
    image_bytes
):

    try:

        image = Image.open(
            io.BytesIO(
                image_bytes
            )
        )

        image = image.convert(
            "RGB"
        )

        # 不放大，只縮小過大的照片
        image.thumbnail(
            (
                1280,
                1280
            )
        )

        output = io.BytesIO()

        image.save(
            output,
            format="JPEG",
            quality=82,
            optimize=True
        )

        return (
            output.getvalue(),
            "image/jpeg"
        )

    except Exception as e:

        print(
            "IMAGE_COMPRESSION_ERROR:",
            repr(e),
            flush=True
        )

        # 壓縮失敗也不要讓整個 BOT 死掉
        return (
            image_bytes,
            "image/jpeg"
        )


# =========================================================
# 個人資料說明
# =========================================================

def profile_help():

    return (
        "👤 把資料一次傳給我就好，例如：\n\n"
        "身高160 體重65 年齡28 女\n"
        "活動量輕量 目標減脂\n\n"
        "活動量可以填：\n"
        "久坐／輕量／中等／高／非常高\n\n"
        "目標：\n"
        "減脂／維持／增肌"
    )


# =========================================================
# 文字訊息
# =========================================================

@handler.add(
    MessageEvent,
    message=TextMessageContent
)
def handle_text(event):

    user_id = get_user_id(
        event
    )

    text = event.message.text.strip()

    try:

        # -------------------------------------------------
        # 常用功能：
        # 不需要 AI 的就不要浪費時間叫 AI
        # -------------------------------------------------

        if text == "設定資料":

            reply_text(
                event.reply_token,
                profile_help()
            )

            return


        if text in [

            "查看今日紀錄",
            "今日紀錄",
            "今天吃了什麼",
            "今天吃多少",
            "今天幾卡",
            "今天多少熱量"
        ]:

            reply_text(
                event.reply_token,
                today_summary(
                    user_id
                )
            )

            return


        if text in [

            "今天還能吃多少",
            "還能吃多少",
            "剩多少熱量"
        ]:

            reply_text(
                event.reply_token,
                remaining_reply(
                    user_id
                )
            )

            return


        if text == "我要修正上一餐":

            last_meal = get_last_meal(
                user_id
            )

            if not last_meal:

                reply_text(
                    event.reply_token,
                    "還沒有上一餐可以修啦 😭"
                )

                return

            reply_text(
                event.reply_token,

                "✏️ 直接告訴我哪裡要改。\n\n"
                "例如：\n"
                "• 飯只吃一半\n"
                "• 這是牛排不是豬排\n"
                "• 豆漿是無糖\n"
                "• 那杯我沒喝\n"
                "• 我只吃了一半"
            )

            return


        if text in [

            "刪掉上一餐",
            "刪除上一餐"
        ]:

            last_meal = get_last_meal(
                user_id
            )

            if not last_meal:

                reply_text(
                    event.reply_token,
                    "沒有上一餐可以刪啦 😂"
                )

                return

            delete_meal(
                last_meal["id"],
                user_id
            )

            reply_text(
                event.reply_token,

                "🗑️ 好，上一餐已經刪掉。\n\n"
                + today_summary(
                    user_id
                )
            )

            return


        # -------------------------------------------------
        # 其他文字交給 AI 判斷真正意圖
        # -------------------------------------------------

        intent_data = classify_user_text(
            text
        )

        intent = intent_data[
            "intent"
        ]


        # -------------------------------------------------
        # 設定個人資料
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
                "goal"
            ]

            missing = [

                field
                for field
                in required_fields

                if profile.get(
                    field
                )
                is None
            ]

            if missing:

                reply_text(
                    event.reply_token,
                    profile_help()
                )

                return

            # ---------------------------------------------
            # 活動量正規化
            # ---------------------------------------------

            activity_text = str(
                profile[
                    "activity_level"
                ]
            )

            for activity in [

                "久坐",
                "輕量",
                "中等",
                "非常高",
                "高"
            ]:

                if activity in activity_text:

                    profile[
                        "activity_level"
                    ] = activity

                    break


            # ---------------------------------------------
            # 目標正規化
            # ---------------------------------------------

            goal_text = str(
                profile[
                    "goal"
                ]
            )

            if "減" in goal_text:

                profile["goal"] = "減脂"

            elif "增" in goal_text:

                profile["goal"] = "增肌"

            else:

                profile["goal"] = "維持"


            profile = calculate_targets(
                profile
            )

            save_profile(
                user_id,
                profile
            )

            reply_text(
                event.reply_token,

                "👤 個人資料設定完成！\n\n"

                f"🔥 BMR：約 "
                f"{profile['bmr']} kcal\n"

                f"⚡ TDEE：約 "
                f"{profile['tdee']} kcal\n\n"

                f"🎯 每日目標："
                f"{profile['calorie_target']} kcal\n"

                f"🥩 蛋白質："
                f"{profile['protein_target']} g\n"

                f"🍚 碳水："
                f"{profile['carbs_target']} g\n"

                f"🥑 脂肪："
                f"{profile['fat_target']} g\n"

                f"🥬 纖維："
                f"{profile['fiber_target']} g\n\n"

                "之後每餐我都會直接幫你算"
                "今天還剩多少額度 😎"
            )

            return


        # -------------------------------------------------
        # 修正上一餐 / 新增上一餐食物
        # -------------------------------------------------

        if intent in [

            "correct_last",
            "add_to_last"
        ]:

            last_meal = get_last_meal(
                user_id
            )

            if not last_meal:

                reply_text(
                    event.reply_token,

                    "我找不到上一餐可以改 😭\n"
                    "先傳一張餐點照片給我。"
                )

                return

            if intent == "add_to_last":

                corrected_data = (
                    add_food_to_analysis(
                        last_meal,
                        text
                    )
                )

            else:

                corrected_data = (
                    correct_food_analysis(
                        last_meal,
                        text
                    )
                )

            update_meal(
                last_meal["id"],
                corrected_data
            )


            # ---------------------------------------------
            # 只有明確長期習慣才建立食物記憶
            # ---------------------------------------------

            memory_keywords = [

                "常喝",
                "常吃",
                "固定",
                "記住",
                "以後都是"
            ]

            if any(
                keyword in text
                for keyword
                in memory_keywords
            ):

                add_food_memory(

                    user_id,

                    text,

                    data=corrected_data
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

                        corrected=True
                    )
                ]
            )

            return


        # -------------------------------------------------
        # AI 判斷為刪除上一餐
        # -------------------------------------------------

        if intent == "delete_last":

            last_meal = get_last_meal(
                user_id
            )

            if not last_meal:

                reply_text(
                    event.reply_token,
                    "沒有上一餐可以刪啦 😂"
                )

                return

            delete_meal(
                last_meal["id"],
                user_id
            )

            reply_text(
                event.reply_token,

                "🗑️ 上一餐刪掉了。\n\n"
                + today_summary(
                    user_id
                )
            )

            return


        # -------------------------------------------------
        # 查看今天
        # -------------------------------------------------

        if intent == "today":

            reply_text(
                event.reply_token,
                today_summary(
                    user_id
                )
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
                )
            )

            return


        # -------------------------------------------------
        # 食物記憶
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
                memory_text
            )

            reply_text(
                event.reply_token,

                "🧠 好，這個我記住了。\n"
                "下次看到合理相符的餐點，"
                "我會優先參考這個習慣。"
            )

            return


        # -------------------------------------------------
        # 飲食建議 / 一般營養問題
        # -------------------------------------------------

        if intent in [

            "meal_advice",
            "food_question"
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
                )
            )

            reply_text(
                event.reply_token,
                answer
            )

            return


        # -------------------------------------------------
        # 無關問題
        # -------------------------------------------------

        reply_text(
            event.reply_token,

            "這題超出我的伙食費範圍了 😂\n"
            "我是飲食 BOT 啦！\n\n"
            "食物、熱量、減脂、"
            "蛋白質、今天吃什麼，"
            "這些再來找我 😎"
        )


    except Exception as e:

        print(
            "TEXT_ERROR:",
            repr(e),
            flush=True
        )

        reply_text(
            event.reply_token,

            "🥲 我剛剛腦袋打結了。\n"
            "再跟我說一次，我重來。"
        )


# =========================================================
# 圖片訊息
# =========================================================

@handler.add(
    MessageEvent,
    message=ImageMessageContent
)
def handle_image(event):

    user_id = get_user_id(
        event
    )

    try:

        # -------------------------------------------------
        # 從 LINE 下載原圖
        # -------------------------------------------------

        message_id = (
            event.message.id
        )

        image_url = (
            "https://api-data.line.me/"
            f"v2/bot/message/"
            f"{message_id}/content"
        )

        response = requests.get(

            image_url,

            headers={
                "Authorization":
                    f"Bearer "
                    f"{LINE_ACCESS_TOKEN}"
            },

            timeout=20
        )

        response.raise_for_status()

        original_bytes = (
            response.content
        )


        # -------------------------------------------------
        # V2：先縮圖，減少 AI 傳輸時間
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
        # 取得個人食物記憶
        # -------------------------------------------------

        memories = get_food_memories(
            user_id,
            limit=12
        )


        # -------------------------------------------------
        # AI 一次完成分析
        # -------------------------------------------------

        food_data = (
            analyze_food_image(
                data_url,
                memories
            )
        )


        # -------------------------------------------------
        # 儲存餐點
        # -------------------------------------------------

        meal_id = save_meal(
            user_id,
            food_data
        )

        print(
            "MEAL_SAVED:",
            f"user={user_id}",
            f"meal_id={meal_id}",
            flush=True
        )


        # -------------------------------------------------
        # 今日累計
        # -------------------------------------------------

        today_totals = (
            get_today_totals(
                user_id
            )
        )

        profile = get_profile(
            user_id
        )


        # -------------------------------------------------
        # 回覆漂亮卡片
        # -------------------------------------------------

        reply_messages(

            event.reply_token,

            [

                make_meal_card(

                    food_data,

                    today_totals,

                    profile,

                    corrected=False
                )
            ]
        )


    except Exception as e:

        print(
            "IMAGE_ERROR:",
            repr(e),
            flush=True
        )

        reply_text(
            event.reply_token,

            "🥲 這餐分析翻車了。\n"
            "再傳一次給我。\n\n"
            "如果連續翻車，"
            "我們就去 Render 抓兇手 😂"
        )


# =========================================================
# 啟動
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
