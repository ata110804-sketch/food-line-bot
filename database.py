import os
import json
import psycopg2

from psycopg2.extras import RealDictCursor
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo


# =========================================================
# 基本設定
# =========================================================

DATABASE_URL = os.environ["DATABASE_URL"]
TAIWAN_TZ = ZoneInfo("Asia/Taipei")


# =========================================================
# 資料庫連線
# =========================================================

def get_connection():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )


# =========================================================
# 初始化資料庫 V4
# =========================================================

def init_database():

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            # =================================================
            # 餐點紀錄
            # =================================================

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS meals (

                    id SERIAL PRIMARY KEY,

                    user_id TEXT NOT NULL,

                    meal_date DATE NOT NULL,
                    meal_time TIMESTAMPTZ NOT NULL,

                    meal_type TEXT,
                    meal_name TEXT,

                    foods JSONB NOT NULL,

                    calories DOUBLE PRECISION DEFAULT 0,
                    protein DOUBLE PRECISION DEFAULT 0,
                    carbs DOUBLE PRECISION DEFAULT 0,
                    fat DOUBLE PRECISION DEFAULT 0,
                    fiber DOUBLE PRECISION DEFAULT 0,
                    sodium DOUBLE PRECISION DEFAULT 0,

                    ai_confidence TEXT,
                    ai_comment TEXT,

                    corrected BOOLEAN DEFAULT FALSE,

                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_meals_user_date
                ON meals(user_id, meal_date);
                """
            )

            # =================================================
            # 個人資料
            # =================================================

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (

                    user_id TEXT PRIMARY KEY,

                    height_cm DOUBLE PRECISION,
                    weight_kg DOUBLE PRECISION,
                    age INTEGER,
                    sex TEXT,

                    activity_level TEXT,
                    goal TEXT,

                    bmr DOUBLE PRECISION,
                    tdee DOUBLE PRECISION,

                    calorie_target DOUBLE PRECISION,
                    protein_target DOUBLE PRECISION,
                    carbs_target DOUBLE PRECISION,
                    fat_target DOUBLE PRECISION,
                    fiber_target DOUBLE PRECISION DEFAULT 25,

                    inbody JSONB DEFAULT '{}'::jsonb,

                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )

            # =================================================
            # V4：加入自訂目標欄位
            # 舊資料庫也可以直接升級
            # =================================================

            cursor.execute(
                """
                ALTER TABLE user_profiles
                ADD COLUMN IF NOT EXISTS
                custom_calorie_target DOUBLE PRECISION;
                """
            )

            cursor.execute(
                """
                ALTER TABLE user_profiles
                ADD COLUMN IF NOT EXISTS
                custom_protein_target DOUBLE PRECISION;
                """
            )

            cursor.execute(
                """
                ALTER TABLE user_profiles
                ADD COLUMN IF NOT EXISTS
                custom_carbs_target DOUBLE PRECISION;
                """
            )

            cursor.execute(
                """
                ALTER TABLE user_profiles
                ADD COLUMN IF NOT EXISTS
                custom_fat_target DOUBLE PRECISION;
                """
            )

            cursor.execute(
                """
                ALTER TABLE user_profiles
                ADD COLUMN IF NOT EXISTS
                custom_fiber_target DOUBLE PRECISION;
                """
            )

            cursor.execute(
                """
                ALTER TABLE user_profiles
                ADD COLUMN IF NOT EXISTS
                use_custom_targets BOOLEAN DEFAULT FALSE;
                """
            )

            # =================================================
            # V4：單日營養目標
            #
            # 用途：
            # 今天低碳、明天恢復正常
            # 不需要一直修改永久個人資料
            # =================================================

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_targets (

                    id SERIAL PRIMARY KEY,

                    user_id TEXT NOT NULL,
                    target_date DATE NOT NULL,

                    calorie_target DOUBLE PRECISION,
                    protein_target DOUBLE PRECISION,
                    carbs_target DOUBLE PRECISION,
                    fat_target DOUBLE PRECISION,
                    fiber_target DOUBLE PRECISION,

                    mode_name TEXT,

                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),

                    UNIQUE(user_id, target_date)
                );
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_daily_targets_user_date
                ON daily_targets(user_id, target_date);
                """
            )

            # =================================================
            # V4：體重歷史
            # =================================================

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS weight_logs (

                    id SERIAL PRIMARY KEY,

                    user_id TEXT NOT NULL,
                    log_date DATE NOT NULL,
                    weight_kg DOUBLE PRECISION NOT NULL,

                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),

                    UNIQUE(user_id, log_date)
                );
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_weight_logs_user_date
                ON weight_logs(user_id, log_date);
                """
            )

            # =================================================
            # 食物記憶
            # =================================================

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS food_memories (

                    id SERIAL PRIMARY KEY,

                    user_id TEXT NOT NULL,

                    memory_text TEXT NOT NULL,
                    food_name TEXT,

                    data JSONB DEFAULT '{}'::jsonb,

                    use_count INTEGER DEFAULT 1,

                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_food_memory_user
                ON food_memories(
                    user_id,
                    updated_at DESC
                );
                """
            )

        # =================================================
        # V5.2：飲水紀錄＋每日互動狀態
        # =================================================
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS water_logs (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    log_date DATE NOT NULL,
                    amount_ml DOUBLE PRECISION NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_water_logs_user_date
                ON water_logs(user_id, log_date);
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS water_targets (
                    user_id TEXT PRIMARY KEY,
                    target_ml DOUBLE PRECISION NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_interaction_state (
                    user_id TEXT NOT NULL,
                    state_date DATE NOT NULL,
                    yesterday_summary_shown BOOLEAN DEFAULT FALSE,
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (user_id, state_date)
                );
                """
            )

        conn.commit()

        print(
            "DATABASE_V5_2_READY",
            flush=True
        )

    finally:
        conn.close()


# =========================================================
# 日期工具
# =========================================================

def taiwan_now():
    return datetime.now(TAIWAN_TZ)


def taiwan_today():
    return taiwan_now().date()


def normalize_date(value=None):

    if value is None:
        return taiwan_today()

    if isinstance(value, datetime):
        return value.astimezone(TAIWAN_TZ).date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):

        text = value.strip()

        if text in ["今天", "今日"]:
            return taiwan_today()

        if text in ["昨天", "昨日"]:
            return taiwan_today() - timedelta(days=1)

        if text in ["前天"]:
            return taiwan_today() - timedelta(days=2)

        try:
            return datetime.strptime(
                text,
                "%Y-%m-%d"
            ).date()

        except Exception:
            pass

    return taiwan_today()


# =========================================================
# 自動判斷餐別
# =========================================================

def guess_meal_type(now=None):

    if now is None:
        now = taiwan_now()

    hour = now.hour

    if 5 <= hour < 11:
        return "早餐"

    if 11 <= hour < 15:
        return "午餐"

    if 17 <= hour < 22:
        return "晚餐"

    return "點心"


# =========================================================
# 儲存餐點
# =========================================================

def save_meal(
    user_id,
    data,
    meal_date=None,
    meal_type=None
):

    now = taiwan_now()

    target_date = normalize_date(
        meal_date
        or data.get("meal_date")
    )

    total = data.get(
        "total",
        {}
    ) or {}

    final_meal_type = (
        meal_type
        or data.get("meal_type")
        or guess_meal_type(now)
    )

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO meals (

                    user_id,
                    meal_date,
                    meal_time,

                    meal_type,
                    meal_name,

                    foods,

                    calories,
                    protein,
                    carbs,
                    fat,
                    fiber,
                    sodium,

                    ai_confidence,
                    ai_comment
                )

                VALUES (

                    %s,
                    %s,
                    %s,

                    %s,
                    %s,

                    %s::jsonb,

                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,

                    %s,
                    %s
                )

                RETURNING id;
                """,

                (
                    user_id,
                    target_date,
                    now,

                    final_meal_type,

                    data.get(
                        "meal_name",
                        "這一餐"
                    ),

                    json.dumps(
                        data.get(
                            "foods",
                            []
                        ),
                        ensure_ascii=False
                    ),

                    total.get(
                        "calories",
                        0
                    ),

                    total.get(
                        "protein",
                        0
                    ),

                    total.get(
                        "carbs",
                        0
                    ),

                    total.get(
                        "fat",
                        0
                    ),

                    total.get(
                        "fiber",
                        0
                    ),

                    total.get(
                        "sodium",
                        0
                    ),

                    data.get("confidence"),
                    data.get("comment")
                )
            )

            result = cursor.fetchone()

        conn.commit()

        return result["id"]

    finally:
        conn.close()


# =========================================================
# 取得單一餐點
# =========================================================

def get_meal(
    meal_id,
    user_id=None
):

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            if user_id:

                cursor.execute(
                    """
                    SELECT *
                    FROM meals

                    WHERE
                        id = %s
                        AND user_id = %s;
                    """,
                    (
                        meal_id,
                        user_id
                    )
                )

            else:

                cursor.execute(
                    """
                    SELECT *
                    FROM meals

                    WHERE id = %s;
                    """,
                    (
                        meal_id,
                    )
                )

            return cursor.fetchone()

    finally:
        conn.close()


# =========================================================
# 取得上一餐
# =========================================================

def get_last_meal(user_id):

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT *
                FROM meals

                WHERE user_id = %s

                ORDER BY
                    meal_date DESC,
                    meal_time DESC

                LIMIT 1;
                """,
                (
                    user_id,
                )
            )

            return cursor.fetchone()

    finally:
        conn.close()


# =========================================================
# 更新餐點內容
# =========================================================

def update_meal(
    meal_id,
    data
):

    total = data.get(
        "total",
        {}
    ) or {}

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                UPDATE meals

                SET
                    meal_name = %s,
                    foods = %s::jsonb,

                    calories = %s,
                    protein = %s,
                    carbs = %s,
                    fat = %s,
                    fiber = %s,
                    sodium = %s,

                    ai_confidence = %s,
                    ai_comment = %s,

                    corrected = TRUE,
                    updated_at = NOW()

                WHERE id = %s;
                """,

                (
                    data.get(
                        "meal_name",
                        "這一餐"
                    ),

                    json.dumps(
                        data.get(
                            "foods",
                            []
                        ),
                        ensure_ascii=False
                    ),

                    total.get(
                        "calories",
                        0
                    ),

                    total.get(
                        "protein",
                        0
                    ),

                    total.get(
                        "carbs",
                        0
                    ),

                    total.get(
                        "fat",
                        0
                    ),

                    total.get(
                        "fiber",
                        0
                    ),

                    total.get(
                        "sodium",
                        0
                    ),

                    data.get(
                        "confidence"
                    ),

                    data.get(
                        "comment"
                    ),

                    meal_id
                )
            )

        conn.commit()

    finally:
        conn.close()


# =========================================================
# V4：修改餐別
# =========================================================

def update_meal_type(
    meal_id,
    user_id,
    meal_type
):

    valid_types = {
        "早餐",
        "午餐",
        "晚餐",
        "點心"
    }

    if meal_type not in valid_types:
        return False

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                UPDATE meals

                SET
                    meal_type = %s,
                    updated_at = NOW()

                WHERE
                    id = %s
                    AND user_id = %s

                RETURNING id;
                """,
                (
                    meal_type,
                    meal_id,
                    user_id
                )
            )

            result = cursor.fetchone()

        conn.commit()

        return bool(result)

    finally:
        conn.close()


# =========================================================
# V4：修改餐點日期
# =========================================================

def update_meal_date(
    meal_id,
    user_id,
    meal_date
):

    target_date = normalize_date(
        meal_date
    )

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                UPDATE meals

                SET
                    meal_date = %s,
                    updated_at = NOW()

                WHERE
                    id = %s
                    AND user_id = %s

                RETURNING id;
                """,
                (
                    target_date,
                    meal_id,
                    user_id
                )
            )

            result = cursor.fetchone()

        conn.commit()

        return bool(result)

    finally:
        conn.close()


# =========================================================
# 刪除單一餐點
# =========================================================

def delete_meal(
    meal_id,
    user_id
):

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                DELETE FROM meals

                WHERE
                    id = %s
                    AND user_id = %s

                RETURNING id;
                """,
                (
                    meal_id,
                    user_id
                )
            )

            result = cursor.fetchone()

        conn.commit()

        return bool(result)

    finally:
        conn.close()


# =========================================================
# V4：重置指定日期
#
# 只刪餐點！
# 不刪個人資料
# 不刪食物記憶
# 不刪體重
# =========================================================

def reset_day(
    user_id,
    target_date=None
):

    target_date = normalize_date(
        target_date
    )

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                DELETE FROM meals

                WHERE
                    user_id = %s
                    AND meal_date = %s

                RETURNING id;
                """,
                (
                    user_id,
                    target_date
                )
            )

            deleted = cursor.fetchall()

        conn.commit()

        return len(deleted)

    finally:
        conn.close()


def reset_today(user_id):

    return reset_day(
        user_id,
        taiwan_today()
    )


# =========================================================
# 取得指定日期所有餐點
# =========================================================

def get_meals_by_date(
    user_id,
    target_date=None
):

    target_date = normalize_date(
        target_date
    )

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT *
                FROM meals

                WHERE
                    user_id = %s
                    AND meal_date = %s

                ORDER BY
                    meal_time ASC,
                    id ASC;
                """,
                (
                    user_id,
                    target_date
                )
            )

            return cursor.fetchall()

    finally:
        conn.close()


# =========================================================
# 今天所有餐點
# =========================================================

def get_today_meals(user_id):

    return get_meals_by_date(
        user_id,
        taiwan_today()
    )


# =========================================================
# 指定日期營養總計
# =========================================================

def get_totals_by_date(
    user_id,
    target_date=None
):

    target_date = normalize_date(
        target_date
    )

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT

                    COUNT(*) AS meal_count,

                    COALESCE(
                        SUM(calories),
                        0
                    ) AS calories,

                    COALESCE(
                        SUM(protein),
                        0
                    ) AS protein,

                    COALESCE(
                        SUM(carbs),
                        0
                    ) AS carbs,

                    COALESCE(
                        SUM(fat),
                        0
                    ) AS fat,

                    COALESCE(
                        SUM(fiber),
                        0
                    ) AS fiber,

                    COALESCE(
                        SUM(sodium),
                        0
                    ) AS sodium

                FROM meals

                WHERE
                    user_id = %s
                    AND meal_date = %s;
                """,
                (
                    user_id,
                    target_date
                )
            )

            return cursor.fetchone()

    finally:
        conn.close()


# =========================================================
# 今日總計
# =========================================================

def get_today_totals(user_id):

    return get_totals_by_date(
        user_id,
        taiwan_today()
    )


# =========================================================
# V4：取得月份所有餐點
# =========================================================

def get_month_meals(
    user_id,
    year=None,
    month=None
):

    now = taiwan_now()

    year = year or now.year
    month = month or now.month

    start_date = date(
        int(year),
        int(month),
        1
    )

    if month == 12:

        end_date = date(
            int(year) + 1,
            1,
            1
        )

    else:

        end_date = date(
            int(year),
            int(month) + 1,
            1
        )

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT *
                FROM meals

                WHERE
                    user_id = %s
                    AND meal_date >= %s
                    AND meal_date < %s

                ORDER BY
                    meal_date ASC,
                    meal_time ASC;
                """,
                (
                    user_id,
                    start_date,
                    end_date
                )
            )

            return cursor.fetchall()

    finally:
        conn.close()


# =========================================================
# V4：每月每日統計
# =========================================================

def get_month_daily_totals(
    user_id,
    year=None,
    month=None
):

    now = taiwan_now()

    year = year or now.year
    month = month or now.month

    start_date = date(
        int(year),
        int(month),
        1
    )

    if month == 12:

        end_date = date(
            int(year) + 1,
            1,
            1
        )

    else:

        end_date = date(
            int(year),
            int(month) + 1,
            1
        )

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT

                    meal_date,

                    COUNT(*) AS meal_count,

                    COALESCE(
                        SUM(calories),
                        0
                    ) AS calories,

                    COALESCE(
                        SUM(protein),
                        0
                    ) AS protein,

                    COALESCE(
                        SUM(carbs),
                        0
                    ) AS carbs,

                    COALESCE(
                        SUM(fat),
                        0
                    ) AS fat,

                    COALESCE(
                        SUM(fiber),
                        0
                    ) AS fiber,

                    COALESCE(
                        SUM(sodium),
                        0
                    ) AS sodium

                FROM meals

                WHERE
                    user_id = %s
                    AND meal_date >= %s
                    AND meal_date < %s

                GROUP BY meal_date

                ORDER BY meal_date ASC;
                """,
                (
                    user_id,
                    start_date,
                    end_date
                )
            )

            return cursor.fetchall()

    finally:
        conn.close()


# =========================================================
# V4：月份摘要
# =========================================================

def get_month_summary(
    user_id,
    year=None,
    month=None
):

    daily_rows = get_month_daily_totals(
        user_id,
        year,
        month
    )

    if not daily_rows:

        return {
            "recorded_days": 0,
            "meal_count": 0,
            "avg_calories": 0,
            "avg_protein": 0,
            "avg_carbs": 0,
            "avg_fat": 0,
            "avg_fiber": 0,
            "total_calories": 0,
            "highest_calories": 0,
            "lowest_calories": 0,
            "days": []
        }

    recorded_days = len(
        daily_rows
    )

    meal_count = sum(
        int(
            row.get(
                "meal_count",
                0
            )
            or 0
        )
        for row in daily_rows
    )

    total_calories = sum(
        float(
            row.get(
                "calories",
                0
            )
            or 0
        )
        for row in daily_rows
    )

    total_protein = sum(
        float(
            row.get(
                "protein",
                0
            )
            or 0
        )
        for row in daily_rows
    )

    total_carbs = sum(
        float(
            row.get(
                "carbs",
                0
            )
            or 0
        )
        for row in daily_rows
    )

    total_fat = sum(
        float(
            row.get(
                "fat",
                0
            )
            or 0
        )
        for row in daily_rows
    )

    total_fiber = sum(
        float(
            row.get(
                "fiber",
                0
            )
            or 0
        )
        for row in daily_rows
    )

    calorie_values = [
        float(
            row.get(
                "calories",
                0
            )
            or 0
        )
        for row in daily_rows
    ]

    return {
        "recorded_days":
            recorded_days,

        "meal_count":
            meal_count,

        "avg_calories":
            round(
                total_calories
                / recorded_days,
                1
            ),

        "avg_protein":
            round(
                total_protein
                / recorded_days,
                1
            ),

        "avg_carbs":
            round(
                total_carbs
                / recorded_days,
                1
            ),

        "avg_fat":
            round(
                total_fat
                / recorded_days,
                1
            ),

        "avg_fiber":
            round(
                total_fiber
                / recorded_days,
                1
            ),

        "total_calories":
            round(
                total_calories,
                1
            ),

        "highest_calories":
            round(
                max(
                    calorie_values
                ),
                1
            ),

        "lowest_calories":
            round(
                min(
                    calorie_values
                ),
                1
            ),

        "days":
            daily_rows
    }


# =========================================================
# 個人資料欄位
# =========================================================

PROFILE_FIELDS = {

    "height_cm",
    "weight_kg",
    "age",
    "sex",

    "activity_level",
    "goal",

    "bmr",
    "tdee",

    "calorie_target",
    "protein_target",
    "carbs_target",
    "fat_target",
    "fiber_target",

    "custom_calorie_target",
    "custom_protein_target",
    "custom_carbs_target",
    "custom_fat_target",
    "custom_fiber_target",

    "use_custom_targets",

    "inbody",
}


# =========================================================
# 取得個人資料
# =========================================================

def get_profile(user_id):

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT *
                FROM user_profiles

                WHERE user_id = %s;
                """,
                (
                    user_id,
                )
            )

            return cursor.fetchone()

    finally:
        conn.close()


# =========================================================
# 部分更新個人資料
# =========================================================

def update_profile_fields(
    user_id,
    updates
):

    if not updates:

        return get_profile(
            user_id
        )

    clean_updates = {}

    for key, value in updates.items():

        if (
            key in PROFILE_FIELDS
            and value is not None
        ):

            clean_updates[
                key
            ] = value

    if not clean_updates:

        return get_profile(
            user_id
        )

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO user_profiles (
                    user_id
                )

                VALUES (%s)

                ON CONFLICT (user_id)
                DO NOTHING;
                """,
                (
                    user_id,
                )
            )

        conn.commit()

    finally:
        conn.close()

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            set_parts = []
            values = []

            for key, value in clean_updates.items():

                if key == "inbody":

                    set_parts.append(
                        "inbody = %s::jsonb"
                    )

                    values.append(
                        json.dumps(
                            value or {},
                            ensure_ascii=False
                        )
                    )

                else:

                    set_parts.append(
                        f"{key} = %s"
                    )

                    values.append(
                        value
                    )

            set_parts.append(
                "updated_at = NOW()"
            )

            values.append(
                user_id
            )

            sql = (
                "UPDATE user_profiles "
                "SET "
                + ", ".join(
                    set_parts
                )
                + " WHERE user_id = %s "
                + "RETURNING *;"
            )

            cursor.execute(
                sql,
                tuple(values)
            )

            result = cursor.fetchone()

        conn.commit()

        return result

    finally:
        conn.close()


# =========================================================
# 儲存個人資料
# =========================================================

def save_profile(
    user_id,
    profile
):

    return update_profile_fields(
        user_id,
        profile
    )


# =========================================================
# 尚缺哪些個人資料
# =========================================================

def get_missing_profile_fields(
    user_id
):

    profile = get_profile(
        user_id
    )

    required_fields = [
        "height_cm",
        "weight_kg",
        "age",
        "sex",
        "activity_level",
        "goal",
    ]

    if not profile:
        return required_fields

    missing = []

    for field in required_fields:

        value = profile.get(
            field
        )

        if (
            value is None
            or value == ""
        ):

            missing.append(
                field
            )

    return missing


# =========================================================
# 個人資料是否完整
# =========================================================

def is_profile_complete(
    user_id
):

    return (
        len(
            get_missing_profile_fields(
                user_id
            )
        )
        == 0
    )


# =========================================================
# 清除系統自動計算目標
# =========================================================

def clear_profile_targets(
    user_id
):

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                UPDATE user_profiles

                SET
                    bmr = NULL,
                    tdee = NULL,

                    calorie_target = NULL,
                    protein_target = NULL,
                    carbs_target = NULL,
                    fat_target = NULL,

                    updated_at = NOW()

                WHERE user_id = %s

                RETURNING *;
                """,
                (
                    user_id,
                )
            )

            result = cursor.fetchone()

        conn.commit()

        return result

    finally:
        conn.close()


# =========================================================
# V4：設定永久自訂營養目標
# =========================================================

def set_custom_targets(
    user_id,
    calorie_target=None,
    protein_target=None,
    carbs_target=None,
    fat_target=None,
    fiber_target=None
):

    updates = {
        "use_custom_targets": True
    }

    if calorie_target is not None:

        updates[
            "custom_calorie_target"
        ] = float(
            calorie_target
        )

    if protein_target is not None:

        updates[
            "custom_protein_target"
        ] = float(
            protein_target
        )

    if carbs_target is not None:

        updates[
            "custom_carbs_target"
        ] = float(
            carbs_target
        )

    if fat_target is not None:

        updates[
            "custom_fat_target"
        ] = float(
            fat_target
        )

    if fiber_target is not None:

        updates[
            "custom_fiber_target"
        ] = float(
            fiber_target
        )

    return update_profile_fields(
        user_id,
        updates
    )


# =========================================================
# V4：關閉永久自訂目標
# =========================================================

def reset_custom_targets(
    user_id
):

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                UPDATE user_profiles

                SET
                    use_custom_targets = FALSE,

                    custom_calorie_target = NULL,
                    custom_protein_target = NULL,
                    custom_carbs_target = NULL,
                    custom_fat_target = NULL,
                    custom_fiber_target = NULL,

                    updated_at = NOW()

                WHERE user_id = %s

                RETURNING *;
                """,
                (
                    user_id,
                )
            )

            result = cursor.fetchone()

        conn.commit()

        return result

    finally:
        conn.close()


# =========================================================
# V4：設定「某一天」營養目標
#
# 例如：
# 今天低碳
# 蛋白質 80
# 碳水 80
# 脂肪 45
#
# 不影響明天
# =========================================================

def set_daily_targets(
    user_id,
    target_date=None,
    calorie_target=None,
    protein_target=None,
    carbs_target=None,
    fat_target=None,
    fiber_target=None,
    mode_name=None
):

    target_date = normalize_date(
        target_date
    )

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO daily_targets (

                    user_id,
                    target_date,

                    calorie_target,
                    protein_target,
                    carbs_target,
                    fat_target,
                    fiber_target,

                    mode_name
                )

                VALUES (
                    %s,
                    %s,

                    %s,
                    %s,
                    %s,
                    %s,
                    %s,

                    %s
                )

                ON CONFLICT (
                    user_id,
                    target_date
                )

                DO UPDATE SET

                    calorie_target =
                        COALESCE(
                            EXCLUDED.calorie_target,
                            daily_targets.calorie_target
                        ),

                    protein_target =
                        COALESCE(
                            EXCLUDED.protein_target,
                            daily_targets.protein_target
                        ),

                    carbs_target =
                        COALESCE(
                            EXCLUDED.carbs_target,
                            daily_targets.carbs_target
                        ),

                    fat_target =
                        COALESCE(
                            EXCLUDED.fat_target,
                            daily_targets.fat_target
                        ),

                    fiber_target =
                        COALESCE(
                            EXCLUDED.fiber_target,
                            daily_targets.fiber_target
                        ),

                    mode_name =
                        COALESCE(
                            EXCLUDED.mode_name,
                            daily_targets.mode_name
                        ),

                    updated_at = NOW()

                RETURNING *;
                """,

                (
                    user_id,
                    target_date,

                    calorie_target,
                    protein_target,
                    carbs_target,
                    fat_target,
                    fiber_target,

                    mode_name
                )
            )

            result = cursor.fetchone()

        conn.commit()

        return result

    finally:
        conn.close()


# =========================================================
# V4：取得單日自訂目標
# =========================================================

def get_daily_targets(
    user_id,
    target_date=None
):

    target_date = normalize_date(
        target_date
    )

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT *
                FROM daily_targets

                WHERE
                    user_id = %s
                    AND target_date = %s;
                """,
                (
                    user_id,
                    target_date
                )
            )

            return cursor.fetchone()

    finally:
        conn.close()


# =========================================================
# V4：刪除單日自訂目標
# =========================================================

def clear_daily_targets(
    user_id,
    target_date=None
):

    target_date = normalize_date(
        target_date
    )

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                DELETE FROM daily_targets

                WHERE
                    user_id = %s
                    AND target_date = %s

                RETURNING id;
                """,
                (
                    user_id,
                    target_date
                )
            )

            result = cursor.fetchone()

        conn.commit()

        return bool(result)

    finally:
        conn.close()


# =========================================================
# V4：取得「真正要使用」的營養目標
#
# 優先順序：
#
# 1. 今天單日設定
# 2. 永久自訂設定
# 3. 系統自動計算
# =========================================================

def get_effective_targets(
    user_id,
    target_date=None
):

    target_date = normalize_date(
        target_date
    )

    profile = get_profile(
        user_id
    )

    if not profile:
        return None

    result = {
        "calorie_target":
            profile.get(
                "calorie_target"
            ),

        "protein_target":
            profile.get(
                "protein_target"
            ),

        "carbs_target":
            profile.get(
                "carbs_target"
            ),

        "fat_target":
            profile.get(
                "fat_target"
            ),

        "fiber_target":
            profile.get(
                "fiber_target"
            )
            or 25,

        "source":
            "system",

        "mode_name":
            None
    }

    # -----------------------------------------------------
    # 永久自訂
    # -----------------------------------------------------

    if profile.get(
        "use_custom_targets"
    ):

        mapping = {
            "calorie_target":
                "custom_calorie_target",

            "protein_target":
                "custom_protein_target",

            "carbs_target":
                "custom_carbs_target",

            "fat_target":
                "custom_fat_target",

            "fiber_target":
                "custom_fiber_target",
        }

        for normal_key, custom_key in mapping.items():

            custom_value = profile.get(
                custom_key
            )

            if custom_value is not None:

                result[
                    normal_key
                ] = custom_value

        result[
            "source"
        ] = "custom"

    # -----------------------------------------------------
    # 單日設定優先級最高
    # -----------------------------------------------------

    daily = get_daily_targets(
        user_id,
        target_date
    )

    if daily:

        for key in [
            "calorie_target",
            "protein_target",
            "carbs_target",
            "fat_target",
            "fiber_target",
        ]:

            if daily.get(
                key
            ) is not None:

                result[
                    key
                ] = daily[
                    key
                ]

        result[
            "source"
        ] = "daily"

        result[
            "mode_name"
        ] = daily.get(
            "mode_name"
        )

    return result


# =========================================================
# V4：記錄體重
# =========================================================

def save_weight(
    user_id,
    weight_kg,
    log_date=None
):

    log_date = normalize_date(
        log_date
    )

    weight_kg = float(
        weight_kg
    )

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO weight_logs (

                    user_id,
                    log_date,
                    weight_kg
                )

                VALUES (
                    %s,
                    %s,
                    %s
                )

                ON CONFLICT (
                    user_id,
                    log_date
                )

                DO UPDATE SET

                    weight_kg =
                        EXCLUDED.weight_kg,

                    updated_at = NOW()

                RETURNING *;
                """,
                (
                    user_id,
                    log_date,
                    weight_kg
                )
            )

            result = cursor.fetchone()

        conn.commit()

    finally:
        conn.close()

    # 同時更新個人資料目前體重
    update_profile_fields(
        user_id,
        {
            "weight_kg":
                weight_kg
        }
    )

    return result


# =========================================================
# V4：取得體重歷史
# =========================================================

def get_weight_logs(
    user_id,
    limit=60
):

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT *
                FROM weight_logs

                WHERE user_id = %s

                ORDER BY log_date DESC

                LIMIT %s;
                """,
                (
                    user_id,
                    limit
                )
            )

            return cursor.fetchall()

    finally:
        conn.close()


# =========================================================
# V4：取得月份體重
# =========================================================

def get_month_weight_logs(
    user_id,
    year=None,
    month=None
):

    now = taiwan_now()

    year = year or now.year
    month = month or now.month

    start_date = date(
        int(year),
        int(month),
        1
    )

    if month == 12:

        end_date = date(
            int(year) + 1,
            1,
            1
        )

    else:

        end_date = date(
            int(year),
            int(month) + 1,
            1
        )

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT *
                FROM weight_logs

                WHERE
                    user_id = %s
                    AND log_date >= %s
                    AND log_date < %s

                ORDER BY log_date ASC;
                """,
                (
                    user_id,
                    start_date,
                    end_date
                )
            )

            return cursor.fetchall()

    finally:
        conn.close()


# =========================================================
# 新增食物記憶
# =========================================================

def add_food_memory(
    user_id,
    memory_text,
    food_name=None,
    data=None
):

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO food_memories (

                    user_id,
                    memory_text,
                    food_name,
                    data
                )

                VALUES (
                    %s,
                    %s,
                    %s,
                    %s::jsonb
                )

                RETURNING id;
                """,

                (
                    user_id,

                    memory_text,

                    food_name,

                    json.dumps(
                        data or {},
                        ensure_ascii=False
                    )
                )
            )

            result = cursor.fetchone()

        conn.commit()

        return result["id"]

    finally:
        conn.close()


# =========================================================
# 取得食物記憶
# =========================================================

def get_food_memories(
    user_id,
    limit=12
):

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT *
                FROM food_memories

                WHERE user_id = %s

                ORDER BY updated_at DESC

                LIMIT %s;
                """,
                (
                    user_id,
                    limit
                )
            )

            return cursor.fetchall()

    finally:
        conn.close()

# =========================================================
# V5.2：飲水系統
# =========================================================

def get_default_water_target(user_id):
    profile = get_profile(user_id) or {}
    weight = profile.get("weight_kg")
    if weight is None:
        return 2000
    try:
        weight = float(weight)
    except Exception:
        return 2000

    target = round(weight * 30 / 50) * 50
    return int(max(1500, min(target, 3500)))


def get_water_target(user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT target_ml FROM water_targets WHERE user_id = %s;",
                (user_id,)
            )
            row = cursor.fetchone()

        if row and row.get("target_ml") is not None:
            return int(round(float(row["target_ml"])))
        return get_default_water_target(user_id)
    finally:
        conn.close()


def set_water_target(user_id, target_ml):
    target_ml = float(target_ml)
    if target_ml < 500 or target_ml > 6000:
        raise ValueError("飲水目標請設定在 500～6000 mL 之間。")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO water_targets (user_id, target_ml)
                VALUES (%s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET
                    target_ml = EXCLUDED.target_ml,
                    updated_at = NOW()
                RETURNING *;
                """,
                (user_id, target_ml)
            )
            result = cursor.fetchone()
        conn.commit()
        return result
    finally:
        conn.close()


def reset_water_target(user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM water_targets WHERE user_id = %s RETURNING user_id;",
                (user_id,)
            )
            result = cursor.fetchone()
        conn.commit()
        return bool(result)
    finally:
        conn.close()


def add_water(user_id, amount_ml, log_date=None):
    target_date = normalize_date(log_date)
    amount_ml = float(amount_ml)
    if amount_ml <= 0 or amount_ml > 5000:
        raise ValueError("單次飲水量請輸入 1～5000 mL。")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO water_logs (user_id, log_date, amount_ml)
                VALUES (%s, %s, %s)
                RETURNING *;
                """,
                (user_id, target_date, amount_ml)
            )
            result = cursor.fetchone()
        conn.commit()
        return result
    finally:
        conn.close()


def get_water_total(user_id, target_date=None):
    target_date = normalize_date(target_date)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS log_count,
                       COALESCE(SUM(amount_ml), 0) AS total_ml
                FROM water_logs
                WHERE user_id = %s AND log_date = %s;
                """,
                (user_id, target_date)
            )
            row = cursor.fetchone() or {}
    finally:
        conn.close()

    total_ml = float(row.get("total_ml") or 0)
    target_ml = float(get_water_target(user_id))
    return {
        "date": target_date,
        "log_count": int(row.get("log_count") or 0),
        "total_ml": round(total_ml),
        "target_ml": round(target_ml),
        "remaining_ml": round(max(target_ml - total_ml, 0)),
        "percent": round((total_ml / target_ml * 100) if target_ml else 0, 1),
        "reached": total_ml >= target_ml,
    }


def get_today_water(user_id):
    return get_water_total(user_id, taiwan_today())


def delete_last_water(user_id, target_date=None):
    target_date = normalize_date(target_date)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM water_logs
                WHERE id = (
                    SELECT id FROM water_logs
                    WHERE user_id = %s AND log_date = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                )
                RETURNING *;
                """,
                (user_id, target_date)
            )
            result = cursor.fetchone()
        conn.commit()
        return result
    finally:
        conn.close()


def reset_water_day(user_id, target_date=None):
    target_date = normalize_date(target_date)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM water_logs
                WHERE user_id = %s AND log_date = %s
                RETURNING id;
                """,
                (user_id, target_date)
            )
            deleted = cursor.fetchall()
        conn.commit()
        return len(deleted)
    finally:
        conn.close()


def get_month_water_daily_totals(user_id, year=None, month=None):
    now = taiwan_now()
    year = int(year or now.year)
    month = int(month or now.month)
    start_date = date(year, month, 1)
    end_date = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT log_date, COALESCE(SUM(amount_ml), 0) AS total_ml
                FROM water_logs
                WHERE user_id = %s
                  AND log_date >= %s
                  AND log_date < %s
                GROUP BY log_date
                ORDER BY log_date ASC;
                """,
                (user_id, start_date, end_date)
            )
            return cursor.fetchall()
    finally:
        conn.close()


def get_month_water_summary(user_id, year=None, month=None):
    rows = get_month_water_daily_totals(user_id, year, month)
    target_ml = float(get_water_target(user_id))
    if not rows:
        return {
            "recorded_days": 0, "avg_ml": 0, "total_ml": 0,
            "target_ml": round(target_ml), "reached_days": 0,
            "reached_rate": 0, "days": []
        }

    totals = [float(row.get("total_ml") or 0) for row in rows]
    reached_days = sum(1 for value in totals if value >= target_ml)
    return {
        "recorded_days": len(rows),
        "avg_ml": round(sum(totals) / len(totals)),
        "total_ml": round(sum(totals)),
        "target_ml": round(target_ml),
        "reached_days": reached_days,
        "reached_rate": round(reached_days / len(rows) * 100, 1),
        "days": rows,
    }


# =========================================================
# V5.2：昨日摘要每天只主動顯示一次
# =========================================================

def should_show_yesterday_summary(user_id):
    today = taiwan_today()
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT yesterday_summary_shown
                FROM daily_interaction_state
                WHERE user_id = %s AND state_date = %s;
                """,
                (user_id, today)
            )
            row = cursor.fetchone()
        return not bool(row and row.get("yesterday_summary_shown"))
    finally:
        conn.close()


def mark_yesterday_summary_shown(user_id):
    today = taiwan_today()
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO daily_interaction_state
                    (user_id, state_date, yesterday_summary_shown, updated_at)
                VALUES (%s, %s, TRUE, NOW())
                ON CONFLICT (user_id, state_date)
                DO UPDATE SET
                    yesterday_summary_shown = TRUE,
                    updated_at = NOW()
                RETURNING *;
                """,
                (user_id, today)
            )
            result = cursor.fetchone()
        conn.commit()
        return result
    finally:
        conn.close()


def get_yesterday_snapshot(user_id):
    yesterday = taiwan_today() - timedelta(days=1)
    return {
        "date": yesterday,
        "totals": get_totals_by_date(user_id, yesterday) or {},
        "meals": get_meals_by_date(user_id, yesterday) or [],
        "targets": get_effective_targets(user_id, yesterday) or {},
        "water": get_water_total(user_id, yesterday),
    }
