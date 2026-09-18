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
# 建立資料表
# =========================================================

def init_database():

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

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

        conn.commit()

        print(
            "DATABASE_READY",
            flush=True
        )

    finally:

        conn.close()


# =========================================================
# 判斷早餐 / 午餐 / 晚餐 / 點心
# =========================================================

def guess_meal_type(now=None):

    if now is None:
        now = datetime.now(TAIWAN_TZ)

    hour = now.hour

    if 5 <= hour < 11:
        return "早餐"

    elif 11 <= hour < 15:
        return "午餐"

    elif 17 <= hour < 22:
        return "晚餐"

    else:
        return "點心"


# =========================================================
# 儲存一餐
# =========================================================

def save_meal(user_id, data):

    now = datetime.now(TAIWAN_TZ)

    total = data.get(
        "total",
        {}
    )

    meal_type = data.get(
        "meal_type"
    ) or guess_meal_type(now)

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
                    %s, %s, %s, %s, %s,
                    %s::jsonb,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s
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
# 更新上一餐
# =========================================================

def update_meal(meal_id, data):

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
# 今日所有餐點
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
