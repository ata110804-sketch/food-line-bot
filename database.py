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
                CREATE TABLE IF NOT EXISTS record_contexts (
                    user_id TEXT PRIMARY KEY,
                    target_date DATE NOT NULL,
                    record_type TEXT NOT NULL,
                    meal_type TEXT,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )

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

        # =================================================
        # V5.4：運動紀錄＋對話上下文
        # =================================================
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS exercise_logs (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    log_date DATE NOT NULL,
                    exercise_type TEXT NOT NULL,
                    duration_minutes DOUBLE PRECISION,
                    calories_burned DOUBLE PRECISION,
                    intensity TEXT,
                    note TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_exercise_logs_user_date
                ON exercise_logs(user_id, log_date);
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS exercise_plans (
                    id SERIAL PRIMARY KEY, user_id TEXT NOT NULL, plan_date DATE NOT NULL,
                    plan_code TEXT NOT NULL, title TEXT NOT NULL, duration_minutes DOUBLE PRECISION,
                    calories_low DOUBLE PRECISION, calories_high DOUBLE PRECISION,
                    muscle_groups TEXT, exercises JSONB DEFAULT '[]'::jsonb, status TEXT DEFAULT 'recommended',
                    completed_ratio DOUBLE PRECISION DEFAULT 0, created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_exercise_plans_user_date ON exercise_plans(user_id, plan_date);"
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_state (
                    user_id TEXT PRIMARY KEY,
                    context_type TEXT,
                    target_date DATE,
                    meal_type TEXT,
                    last_entity TEXT,
                    state JSONB DEFAULT '{}'::jsonb,
                    expires_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )

        # =================================================
        # V6.0：InBody 歷史
        # =================================================
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS inbody_logs (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    log_date DATE NOT NULL,
                    weight_kg DOUBLE PRECISION,
                    body_fat_pct DOUBLE PRECISION,
                    body_fat_kg DOUBLE PRECISION,
                    skeletal_muscle_kg DOUBLE PRECISION,
                    bmi DOUBLE PRECISION,
                    visceral_fat_level DOUBLE PRECISION,
                    bmr DOUBLE PRECISION,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(user_id, log_date)
                );
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_inbody_logs_user_date
                ON inbody_logs(user_id, log_date);
                """
            )

        conn.commit()

        print(
            "DATABASE_V5_4_READY",
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

# =========================================================
# V5.4：指定日期便利函式
# =========================================================

def get_day_snapshot(user_id, target_date=None):
    target_date = normalize_date(target_date)
    return {
        "date": target_date,
        "meals": get_meals_by_date(user_id, target_date),
        "totals": get_totals_by_date(user_id, target_date),
        "water": get_water_total(user_id, target_date),
        "weight": get_weight_by_date(user_id, target_date),
        "exercise": get_exercise_by_date(user_id, target_date),
    }


def get_weight_by_date(user_id, target_date=None):
    target_date = normalize_date(target_date)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM weight_logs
                WHERE user_id = %s AND log_date = %s
                LIMIT 1;
                """,
                (user_id, target_date),
            )
            return cursor.fetchone()
    finally:
        conn.close()


# =========================================================
# V5.4：運動紀錄
# =========================================================

def save_exercise(
    user_id,
    exercise_type,
    duration_minutes=None,
    calories_burned=None,
    intensity=None,
    note=None,
    log_date=None,
):
    target_date = normalize_date(log_date)
    exercise_type = str(exercise_type or "").strip()
    if not exercise_type:
        raise ValueError("運動類型不能是空白。")

    if duration_minutes is not None:
        duration_minutes = float(duration_minutes)
        if duration_minutes <= 0 or duration_minutes > 1440:
            raise ValueError("運動時間請輸入 1～1440 分鐘。")

    if calories_burned is not None:
        calories_burned = float(calories_burned)
        if calories_burned < 0 or calories_burned > 10000:
            raise ValueError("運動消耗熱量數值不合理。")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO exercise_logs (
                    user_id, log_date, exercise_type, duration_minutes,
                    calories_burned, intensity, note
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *;
                """,
                (
                    user_id, target_date, exercise_type, duration_minutes,
                    calories_burned, intensity, note,
                ),
            )
            result = cursor.fetchone()
        conn.commit()
        return result
    finally:
        conn.close()


def get_exercise_by_date(user_id, target_date=None):
    target_date = normalize_date(target_date)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM exercise_logs
                WHERE user_id = %s AND log_date = %s
                ORDER BY created_at ASC, id ASC;
                """,
                (user_id, target_date),
            )
            return cursor.fetchall()
    finally:
        conn.close()


def get_exercise_totals(user_id, target_date=None):
    target_date = normalize_date(target_date)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS exercise_count,
                    COALESCE(SUM(duration_minutes), 0) AS duration_minutes,
                    COALESCE(SUM(calories_burned), 0) AS calories_burned
                FROM exercise_logs
                WHERE user_id = %s AND log_date = %s;
                """,
                (user_id, target_date),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def delete_last_exercise(user_id, target_date=None):
    target_date = normalize_date(target_date)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM exercise_logs
                WHERE id = (
                    SELECT id FROM exercise_logs
                    WHERE user_id = %s AND log_date = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                )
                RETURNING *;
                """,
                (user_id, target_date),
            )
            result = cursor.fetchone()
        conn.commit()
        return result
    finally:
        conn.close()


# =========================================================
# V5.4：短期對話上下文
# =========================================================

def set_conversation_state(
    user_id,
    context_type=None,
    target_date=None,
    meal_type=None,
    last_entity=None,
    state=None,
    ttl_minutes=30,
):
    resolved_date = normalize_date(target_date) if target_date is not None else None
    expires_at = taiwan_now() + timedelta(minutes=max(1, int(ttl_minutes)))
    payload = state or {}

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO conversation_state (
                    user_id, context_type, target_date, meal_type,
                    last_entity, state, expires_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    context_type = EXCLUDED.context_type,
                    target_date = EXCLUDED.target_date,
                    meal_type = EXCLUDED.meal_type,
                    last_entity = EXCLUDED.last_entity,
                    state = EXCLUDED.state,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = NOW()
                RETURNING *;
                """,
                (
                    user_id, context_type, resolved_date, meal_type, last_entity,
                    json.dumps(payload, ensure_ascii=False), expires_at,
                ),
            )
            result = cursor.fetchone()
        conn.commit()
        return result
    finally:
        conn.close()


def get_conversation_state(user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM conversation_state
                WHERE user_id = %s
                  AND (expires_at IS NULL OR expires_at > NOW())
                LIMIT 1;
                """,
                (user_id,),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def clear_conversation_state(user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM conversation_state WHERE user_id = %s RETURNING user_id;",
                (user_id,),
            )
            result = cursor.fetchone()
        conn.commit()
        return bool(result)
    finally:
        conn.close()


# =========================================================
# V5.6：互動式運動方案 / 歷史
# =========================================================
def save_exercise_plan(user_id, plan_code, title, duration_minutes, calories_low, calories_high, muscle_groups, exercises, plan_date=None):
    target_date = normalize_date(plan_date)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO exercise_plans (user_id, plan_date, plan_code, title, duration_minutes,
                    calories_low, calories_high, muscle_groups, exercises, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,'recommended') RETURNING *;
            """, (user_id,target_date,plan_code,title,duration_minutes,calories_low,calories_high,
                  muscle_groups,json.dumps(exercises,ensure_ascii=False)))
            row=cursor.fetchone()
        conn.commit(); return row
    finally: conn.close()

def get_latest_exercise_plan(user_id, plan_code=None, target_date=None):
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            sql="SELECT * FROM exercise_plans WHERE user_id=%s"; vals=[user_id]
            if plan_code: sql += " AND plan_code=%s"; vals.append(plan_code)
            if target_date is not None: sql += " AND plan_date=%s"; vals.append(normalize_date(target_date))
            sql += " ORDER BY created_at DESC,id DESC LIMIT 1"
            cursor.execute(sql,tuple(vals)); return cursor.fetchone()
    finally: conn.close()

def mark_exercise_plan(user_id, plan_id, status='completed', completed_ratio=1.0):
    ratio=max(0,min(1,float(completed_ratio)))
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""UPDATE exercise_plans SET status=%s,completed_ratio=%s,updated_at=NOW()
                WHERE id=%s AND user_id=%s RETURNING *""",(status,ratio,int(plan_id),user_id)); row=cursor.fetchone()
        conn.commit(); return row
    finally: conn.close()

def get_exercise_range(user_id, start_date, end_date):
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""SELECT * FROM exercise_logs WHERE user_id=%s AND log_date BETWEEN %s AND %s
                ORDER BY log_date DESC,created_at DESC,id DESC""",(user_id,normalize_date(start_date),normalize_date(end_date)))
            return cursor.fetchall()
    finally: conn.close()

def get_unfinished_exercise_plans(user_id, days=7):
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""SELECT * FROM exercise_plans WHERE user_id=%s AND status IN ('recommended','started')
                AND plan_date >= %s ORDER BY plan_date DESC,created_at DESC LIMIT 5""",
                (user_id, normalize_date(taiwan_now().date()-timedelta(days=days))))
            return cursor.fetchall()
    finally: conn.close()


# =========================================================
# V6.0：圖表 / 趨勢 / InBody
# =========================================================

def get_meal_range(user_id, start_date, end_date):
    start_date = normalize_date(start_date)
    end_date = normalize_date(end_date)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT meal_date,
                          COALESCE(SUM(calories),0) calories,
                          COALESCE(SUM(protein),0) protein,
                          COALESCE(SUM(carbs),0) carbs,
                          COALESCE(SUM(fat),0) fat,
                          COALESCE(SUM(fiber),0) fiber,
                          COALESCE(SUM(sodium),0) sodium,
                          COUNT(*) meal_count
                   FROM meals
                   WHERE user_id=%s AND meal_date BETWEEN %s AND %s
                   GROUP BY meal_date ORDER BY meal_date ASC""",
                (user_id,start_date,end_date)
            )
            return cursor.fetchall()
    finally:
        conn.close()

def save_inbody(user_id, data, log_date=None):
    log_date = normalize_date(log_date)
    fields = ["weight_kg","body_fat_pct","body_fat_kg","skeletal_muscle_kg",
              "bmi","visceral_fat_level","bmr"]
    vals = [data.get(k) for k in fields]
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """INSERT INTO inbody_logs
                   (user_id,log_date,weight_kg,body_fat_pct,body_fat_kg,skeletal_muscle_kg,bmi,visceral_fat_level,bmr)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(user_id,log_date) DO UPDATE SET
                     weight_kg=COALESCE(EXCLUDED.weight_kg,inbody_logs.weight_kg),
                     body_fat_pct=COALESCE(EXCLUDED.body_fat_pct,inbody_logs.body_fat_pct),
                     body_fat_kg=COALESCE(EXCLUDED.body_fat_kg,inbody_logs.body_fat_kg),
                     skeletal_muscle_kg=COALESCE(EXCLUDED.skeletal_muscle_kg,inbody_logs.skeletal_muscle_kg),
                     bmi=COALESCE(EXCLUDED.bmi,inbody_logs.bmi),
                     visceral_fat_level=COALESCE(EXCLUDED.visceral_fat_level,inbody_logs.visceral_fat_level),
                     bmr=COALESCE(EXCLUDED.bmr,inbody_logs.bmr),
                     updated_at=NOW()
                   RETURNING *""",
                (user_id,log_date,*vals)
            )
            row=cursor.fetchone()
        conn.commit()
        if data.get("weight_kg") is not None:
            save_weight(user_id, data["weight_kg"], log_date)
        return row
    finally:
        conn.close()

def get_inbody_logs(user_id, limit=30):
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM inbody_logs WHERE user_id=%s ORDER BY log_date DESC LIMIT %s",
                (user_id,limit)
            )
            return cursor.fetchall()
    finally:
        conn.close()

# =========================================================
# V6.1: Neon history / food catalog / pending meal helpers
# =========================================================

def save_weight_history(user_id, weight_kg, log_date=None, note=None, sync_current=True):
    target_date = normalize_date(log_date)
    weight_kg = float(weight_kg)
    if not 20 <= weight_kg <= 400:
        raise ValueError("體重數值不合理。")
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""INSERT INTO weight_logs(user_id,log_date,weight_kg,note)
                VALUES(%s,%s,%s,%s) ON CONFLICT(user_id,log_date) DO UPDATE
                SET weight_kg=EXCLUDED.weight_kg,note=EXCLUDED.note RETURNING *""",
                (user_id,target_date,weight_kg,note))
            row = cursor.fetchone()
            if sync_current:
                cursor.execute("SELECT log_date,weight_kg FROM weight_logs WHERE user_id=%s ORDER BY log_date DESC,id DESC LIMIT 1",(user_id,))
                latest = cursor.fetchone()
                if latest and latest['log_date'] == target_date:
                    cursor.execute("INSERT INTO user_profiles(user_id,weight_kg,updated_at) VALUES(%s,%s,NOW()) ON CONFLICT(user_id) DO UPDATE SET weight_kg=EXCLUDED.weight_kg,updated_at=NOW()",(user_id,latest['weight_kg']))
        conn.commit(); return row
    finally: conn.close()

def delete_weight_history(user_id, log_date):
    target_date=normalize_date(log_date); conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM weight_logs WHERE user_id=%s AND log_date=%s RETURNING *",(user_id,target_date)); row=cursor.fetchone()
            cursor.execute("SELECT weight_kg FROM weight_logs WHERE user_id=%s ORDER BY log_date DESC,id DESC LIMIT 1",(user_id,)); latest=cursor.fetchone()
            if latest: cursor.execute("UPDATE user_profiles SET weight_kg=%s,updated_at=NOW() WHERE user_id=%s",(latest['weight_kg'],user_id))
        conn.commit(); return row
    finally: conn.close()

def get_weight_history(user_id, start_date=None, end_date=None, limit=180):
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            if start_date or end_date:
                start=normalize_date(start_date) if start_date else date(2000,1,1); end=normalize_date(end_date) if end_date else taiwan_today()
                cursor.execute("SELECT * FROM weight_logs WHERE user_id=%s AND log_date BETWEEN %s AND %s ORDER BY log_date ASC,id ASC",(user_id,start,end))
            else:
                cursor.execute("SELECT * FROM weight_logs WHERE user_id=%s ORDER BY log_date DESC,id DESC LIMIT %s",(user_id,limit))
            return cursor.fetchall()
    finally: conn.close()

def save_water_history(user_id, amount_ml, log_date=None, beverage_type='water', note=None):
    target_date=normalize_date(log_date); amount_ml=float(amount_ml)
    if not 0 < amount_ml <= 10000: raise ValueError('飲水量數值不合理。')
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO water_logs(user_id,log_date,amount_ml,beverage_type,note) VALUES(%s,%s,%s,%s,%s) RETURNING *",(user_id,target_date,amount_ml,beverage_type,note)); row=cursor.fetchone()
        conn.commit(); return row
    finally: conn.close()

def get_water_history(user_id, log_date=None):
    target_date=normalize_date(log_date); conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM water_logs WHERE user_id=%s AND log_date=%s ORDER BY created_at,id",(user_id,target_date)); return cursor.fetchall()
    finally: conn.close()

def delete_water_entry(user_id, entry_id):
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM water_logs WHERE id=%s AND user_id=%s RETURNING *",(entry_id,user_id)); row=cursor.fetchone()
        conn.commit(); return row
    finally: conn.close()

def get_water_range(user_id,start_date,end_date):
    start=normalize_date(start_date); end=normalize_date(end_date); conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT log_date,COALESCE(SUM(amount_ml),0) total_ml,COUNT(*) entry_count FROM water_logs WHERE user_id=%s AND log_date BETWEEN %s AND %s GROUP BY log_date ORDER BY log_date",(user_id,start,end)); return cursor.fetchall()
    finally: conn.close()

def create_pending_meal(user_id, foods, meal_type=None, meal_date=None, source_images=None, duplicate_keys=None):
    target_date=normalize_date(meal_date); foods=foods or []
    total=lambda k: sum(float(x.get(k) or 0) for x in foods)
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE pending_meals SET status='cancelled',updated_at=NOW() WHERE user_id=%s AND status='pending' AND created_at < NOW()-INTERVAL '2 hours'",(user_id,))
            cursor.execute("""INSERT INTO pending_meals(user_id,meal_date,meal_type,foods,source_images,calories,protein,carbs,fat,fiber,sugar,sodium,duplicate_keys)
                VALUES(%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (user_id,target_date,meal_type,json.dumps(foods,ensure_ascii=False),json.dumps(source_images or [],ensure_ascii=False),total('calories'),total('protein'),total('carbs'),total('fat'),total('fiber'),total('sugar'),total('sodium'),duplicate_keys or [])); row=cursor.fetchone()
        conn.commit(); return row
    finally: conn.close()

def get_pending_meal(user_id, pending_id=None):
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            if pending_id: cursor.execute("SELECT * FROM pending_meals WHERE id=%s AND user_id=%s AND status='pending'",(pending_id,user_id))
            else: cursor.execute("SELECT * FROM pending_meals WHERE user_id=%s AND status='pending' ORDER BY created_at DESC LIMIT 1",(user_id,))
            return cursor.fetchone()
    finally: conn.close()

def update_pending_meal(user_id,pending_id,foods,source_images=None,duplicate_keys=None):
    foods=foods or []; total=lambda k: sum(float(x.get(k) or 0) for x in foods)
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""UPDATE pending_meals SET foods=%s::jsonb,source_images=COALESCE(%s::jsonb,source_images),calories=%s,protein=%s,carbs=%s,fat=%s,fiber=%s,sugar=%s,sodium=%s,duplicate_keys=%s,updated_at=NOW() WHERE id=%s AND user_id=%s AND status='pending' RETURNING *""",
            (json.dumps(foods,ensure_ascii=False),json.dumps(source_images,ensure_ascii=False) if source_images is not None else None,total('calories'),total('protein'),total('carbs'),total('fat'),total('fiber'),total('sugar'),total('sodium'),duplicate_keys or [],pending_id,user_id)); row=cursor.fetchone()
        conn.commit(); return row
    finally: conn.close()

def cancel_pending_meal(user_id,pending_id):
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE pending_meals SET status='cancelled',updated_at=NOW() WHERE id=%s AND user_id=%s AND status='pending' RETURNING *",(pending_id,user_id)); row=cursor.fetchone()
        conn.commit(); return row
    finally: conn.close()

def confirm_pending_meal(user_id,pending_id):
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM pending_meals WHERE id=%s AND user_id=%s AND status='pending' FOR UPDATE",(pending_id,user_id)); p=cursor.fetchone()
            if not p: return None
            for food in (p.get('foods') or []):
                cursor.execute("""INSERT INTO meals(user_id,meal_type,meal_date,food_name,calories,protein,carbs,fat,fiber,sodium,sugar,source_type,source_ref,pending_meal_id)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (user_id,p.get('meal_type') or '其他',p['meal_date'],food.get('food_name') or food.get('name') or '未命名食物',float(food.get('calories') or 0),float(food.get('protein') or 0),float(food.get('carbs') or 0),float(food.get('fat') or 0),float(food.get('fiber') or 0),float(food.get('sodium') or 0),float(food.get('sugar') or 0),food.get('source_type') or 'ai',str(food.get('source_ref') or ''),pending_id))
            cursor.execute("UPDATE pending_meals SET status='confirmed',updated_at=NOW() WHERE id=%s RETURNING *",(pending_id,)); row=cursor.fetchone()
        conn.commit(); return row
    except: conn.rollback(); raise
    finally: conn.close()

def get_active_meals_by_date(user_id,target_date=None,meal_type=None):
    target_date=normalize_date(target_date); conn=get_connection()
    try:
        with conn.cursor() as cursor:
            if meal_type: cursor.execute("SELECT * FROM meals WHERE user_id=%s AND meal_date=%s AND meal_type=%s AND deleted_at IS NULL ORDER BY created_at,id",(user_id,target_date,meal_type))
            else: cursor.execute("SELECT * FROM meals WHERE user_id=%s AND meal_date=%s AND deleted_at IS NULL ORDER BY created_at,id",(user_id,target_date))
            return cursor.fetchall()
    finally: conn.close()

def soft_delete_meal(user_id,meal_id):
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE meals SET deleted_at=NOW() WHERE id=%s AND user_id=%s AND deleted_at IS NULL RETURNING *",(meal_id,user_id)); row=cursor.fetchone()
        conn.commit(); return row
    finally: conn.close()

def soft_delete_meal_group(user_id,target_date,meal_type):
    target_date=normalize_date(target_date); conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE meals SET deleted_at=NOW() WHERE user_id=%s AND meal_date=%s AND meal_type=%s AND deleted_at IS NULL RETURNING id",(user_id,target_date,meal_type)); rows=cursor.fetchall()
        conn.commit(); return len(rows)
    finally: conn.close()

def restore_meal(user_id,meal_id):
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE meals SET deleted_at=NULL WHERE id=%s AND user_id=%s RETURNING *",(meal_id,user_id)); row=cursor.fetchone()
        conn.commit(); return row
    finally: conn.close()

def search_food_catalog(query,brand=None,limit=12):
    q=str(query or '').strip(); conn=get_connection()
    try:
        with conn.cursor() as cursor:
            sql="""SELECT * FROM food_catalog WHERE active=TRUE AND (LOWER(product_name) LIKE LOWER(%s) OR EXISTS(SELECT 1 FROM unnest(aliases) a WHERE LOWER(a) LIKE LOWER(%s)))"""; params=[f'%{q}%',f'%{q}%']
            if brand: sql+=' AND LOWER(brand)=LOWER(%s)'; params.append(brand)
            sql+=' ORDER BY verified DESC,product_name ASC LIMIT %s'; params.append(limit)
            cursor.execute(sql,tuple(params)); return cursor.fetchall()
    finally: conn.close()

def upsert_food_catalog(item):
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""INSERT INTO food_catalog(brand,category,product_name,aliases,serving_description,serving_grams,calories,protein,carbs,fat,saturated_fat,sugar,fiber,sodium,source_type,source_name,source_url,verified,data_date)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(brand,product_name,serving_description) DO UPDATE SET aliases=EXCLUDED.aliases,serving_grams=EXCLUDED.serving_grams,calories=EXCLUDED.calories,protein=EXCLUDED.protein,carbs=EXCLUDED.carbs,fat=EXCLUDED.fat,saturated_fat=EXCLUDED.saturated_fat,sugar=EXCLUDED.sugar,fiber=EXCLUDED.fiber,sodium=EXCLUDED.sodium,source_type=EXCLUDED.source_type,source_name=EXCLUDED.source_name,source_url=EXCLUDED.source_url,verified=EXCLUDED.verified,data_date=EXCLUDED.data_date,updated_at=NOW() RETURNING *""",
            (item.get('brand'),item.get('category') or '一般食品',item['product_name'],item.get('aliases') or [],item.get('serving_description'),item.get('serving_grams'),item.get('calories'),item.get('protein'),item.get('carbs'),item.get('fat'),item.get('saturated_fat'),item.get('sugar'),item.get('fiber'),item.get('sodium'),item.get('source_type') or 'curated',item.get('source_name'),item.get('source_url'),bool(item.get('verified')),item.get('data_date'))); row=cursor.fetchone()
        conn.commit(); return row
    finally: conn.close()

def set_record_context(user_id,target_date,record_type,meal_type=None):
    target_date=normalize_date(target_date); conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""INSERT INTO record_contexts(user_id,target_date,record_type,meal_type,updated_at)
                VALUES(%s,%s,%s,%s,NOW())
                ON CONFLICT(user_id) DO UPDATE SET target_date=EXCLUDED.target_date,record_type=EXCLUDED.record_type,meal_type=EXCLUDED.meal_type,updated_at=NOW()
                RETURNING *""",(user_id,target_date,record_type,meal_type)); row=cursor.fetchone()
        conn.commit(); return row
    finally: conn.close()

def get_record_context(user_id,max_age_minutes=30):
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""SELECT * FROM record_contexts WHERE user_id=%s
                AND updated_at >= NOW()-(%s || ' minutes')::interval""",(user_id,str(int(max_age_minutes))))
            return cursor.fetchone()
    finally: conn.close()

def clear_record_context(user_id):
    conn=get_connection()
    try:
        with conn.cursor() as cursor: cursor.execute("DELETE FROM record_contexts WHERE user_id=%s",(user_id,))
        conn.commit()
    finally: conn.close()

def save_body_measurement(user_id,log_date=None,**values):
    target_date=normalize_date(log_date); conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""INSERT INTO body_measurement_logs(user_id,log_date,waist_cm,hip_cm,chest_cm,thigh_cm,arm_cm,note) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(user_id,log_date) DO UPDATE SET waist_cm=COALESCE(EXCLUDED.waist_cm,body_measurement_logs.waist_cm),hip_cm=COALESCE(EXCLUDED.hip_cm,body_measurement_logs.hip_cm),chest_cm=COALESCE(EXCLUDED.chest_cm,body_measurement_logs.chest_cm),thigh_cm=COALESCE(EXCLUDED.thigh_cm,body_measurement_logs.thigh_cm),arm_cm=COALESCE(EXCLUDED.arm_cm,body_measurement_logs.arm_cm),note=COALESCE(EXCLUDED.note,body_measurement_logs.note),updated_at=NOW() RETURNING *""",
            (user_id,target_date,values.get('waist_cm'),values.get('hip_cm'),values.get('chest_cm'),values.get('thigh_cm'),values.get('arm_cm'),values.get('note'))); row=cursor.fetchone()
        conn.commit(); return row
    finally: conn.close()

def get_body_measurements(user_id,limit=90):
    conn=get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM body_measurement_logs WHERE user_id=%s ORDER BY log_date DESC LIMIT %s",(user_id,limit)); return cursor.fetchall()
    finally: conn.close()
