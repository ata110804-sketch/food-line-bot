import os
import json
import psycopg2

from psycopg2.extras import RealDictCursor
from datetime import datetime
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
# 初始化資料庫
# =========================================================

def init_database():

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            # -------------------------------------------------
            # 餐點紀錄
            # 保留 V1 原本的結構
            # -------------------------------------------------

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


            # -------------------------------------------------
            # V2：個人資料
            # -------------------------------------------------

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

                    fiber_target DOUBLE PRECISION
                        DEFAULT 25,

                    inbody JSONB
                        DEFAULT '{}'::jsonb,

                    updated_at TIMESTAMPTZ
                        DEFAULT NOW()
                );
                """
            )


            # -------------------------------------------------
            # V2：食物記憶
            # -------------------------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS food_memories (

                    id SERIAL PRIMARY KEY,

                    user_id TEXT NOT NULL,

                    memory_text TEXT NOT NULL,

                    food_name TEXT,

                    data JSONB
                        DEFAULT '{}'::jsonb,

                    use_count INTEGER
                        DEFAULT 1,

                    created_at TIMESTAMPTZ
                        DEFAULT NOW(),

                    updated_at TIMESTAMPTZ
                        DEFAULT NOW()
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

        conn.commit()

        print(
            "DATABASE_V2_READY",
            flush=True
        )

    finally:

        conn.close()


# =========================================================
# 自動判斷早餐 / 午餐 / 晚餐 / 點心
# =========================================================

def guess_meal_type(now=None):

    if now is None:

        now = datetime.now(
            TAIWAN_TZ
        )

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
    data
):

    now = datetime.now(
        TAIWAN_TZ
    )

    total = data.get(
        "total",
        {}
    )

    meal_type = (
        data.get("meal_type")
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

                    now.date(),

                    now,

                    meal_type,

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
                    )
                )
            )

            result = cursor.fetchone()

        conn.commit()

        return result["id"]

    finally:

        conn.close()


# =========================================================
# 取得指定餐點
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

                ORDER BY meal_time DESC

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
# 更新餐點
# =========================================================

def update_meal(
    meal_id,
    data
):

    total = data.get(
        "total",
        {}
    )

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
# 刪除餐點
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
# 取得今天所有餐點
# =========================================================

def get_today_meals(user_id):

    today = datetime.now(
        TAIWAN_TZ
    ).date()

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

                ORDER BY meal_time ASC;
                """,

                (
                    user_id,
                    today
                )
            )

            return cursor.fetchall()

    finally:

        conn.close()


# =========================================================
# 今日營養總計
# =========================================================

def get_today_totals(user_id):

    today = datetime.now(
        TAIWAN_TZ
    ).date()

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
                    today
                )
            )

            return cursor.fetchone()

    finally:

        conn.close()


# =========================================================
# V2：儲存 / 更新個人資料
# =========================================================

def save_profile(
    user_id,
    profile
):

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO user_profiles (

                    user_id,

                    height_cm,
                    weight_kg,
                    age,
                    sex,

                    activity_level,
                    goal,

                    bmr,
                    tdee,

                    calorie_target,
                    protein_target,
                    carbs_target,
                    fat_target,
                    fiber_target,

                    inbody,

                    updated_at
                )

                VALUES (

                    %s,

                    %s,
                    %s,
                    %s,
                    %s,

                    %s,
                    %s,

                    %s,
                    %s,

                    %s,
                    %s,
                    %s,
                    %s,
                    %s,

                    %s::jsonb,

                    NOW()
                )

                ON CONFLICT (user_id)

                DO UPDATE SET

                    height_cm =
                        EXCLUDED.height_cm,

                    weight_kg =
                        EXCLUDED.weight_kg,

                    age =
                        EXCLUDED.age,

                    sex =
                        EXCLUDED.sex,

                    activity_level =
                        EXCLUDED.activity_level,

                    goal =
                        EXCLUDED.goal,

                    bmr =
                        EXCLUDED.bmr,

                    tdee =
                        EXCLUDED.tdee,

                    calorie_target =
                        EXCLUDED.calorie_target,

                    protein_target =
                        EXCLUDED.protein_target,

                    carbs_target =
                        EXCLUDED.carbs_target,

                    fat_target =
                        EXCLUDED.fat_target,

                    fiber_target =
                        EXCLUDED.fiber_target,

                    inbody =
                        EXCLUDED.inbody,

                    updated_at =
                        NOW();
                """,

                (
                    user_id,

                    profile.get(
                        "height_cm"
                    ),

                    profile.get(
                        "weight_kg"
                    ),

                    profile.get(
                        "age"
                    ),

                    profile.get(
                        "sex"
                    ),

                    profile.get(
                        "activity_level"
                    ),

                    profile.get(
                        "goal"
                    ),

                    profile.get(
                        "bmr"
                    ),

                    profile.get(
                        "tdee"
                    ),

                    profile.get(
                        "calorie_target"
                    ),

                    profile.get(
                        "protein_target"
                    ),

                    profile.get(
                        "carbs_target"
                    ),

                    profile.get(
                        "fat_target"
                    ),

                    profile.get(
                        "fiber_target",
                        25
                    ),

                    json.dumps(
                        profile.get(
                            "inbody",
                            {}
                        ),
                        ensure_ascii=False
                    )
                )
            )

        conn.commit()

    finally:

        conn.close()


# =========================================================
# V2：取得個人資料
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
# V2：新增食物記憶
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
# V2：取得使用者食物記憶
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
