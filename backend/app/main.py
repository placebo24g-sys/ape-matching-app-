from fastapi import FastAPI, HTTPException, status, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import sqlite3
import uuid

app = FastAPI(title="類人猿マッチング API")

# CORS設定（GitHub Pages等からのアクセスを許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "ape_app.db"

# 管理画面アクセス用のパスワード（お好みの文字列に変更してください）
ADMIN_PASSWORD = "ape_secret_pass_2026"

# DB初期化（テーブル生成）
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # 診断プロフィールテーブル
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ape_profiles (
            profile_id TEXT PRIMARY KEY,
            user_id TEXT,
            primary_type TEXT,
            score_chimpanzee INTEGER,
            score_bonobo INTEGER,
            score_gorilla INTEGER,
            score_orangutan INTEGER,
            extraversion_score INTEGER,
            achievement_score INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 予約申し込みテーブル
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            booking_id TEXT PRIMARY KEY,
            user_id TEXT,
            name TEXT,
            gender TEXT,
            area TEXT,
            preferred_datetime TEXT,
            primary_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- リクエスト/レスポンスの型定義 ---
class BookingCreate(BaseModel):
    user_id: str
    name: str
    gender: str
    area: str
    datetime: str
    primary_type: Optional[str] = "gorilla"

# --- API エンドポイント ---

# 1. 予約の保存 API（ユーザーフロント用）
@app.post("/api/bookings", status_code=status.HTTP_201_CREATED)
def create_booking(booking: BookingCreate):
    booking_id = f"bk_{uuid.uuid4().hex[:8]}"
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO bookings (booking_id, user_id, name, gender, area, preferred_datetime, primary_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            booking_id,
            booking.user_id,
            booking.name,
            booking.gender,
            booking.area,
            booking.datetime,
            booking.primary_type
        ))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
    
    return {"status": "success", "booking_id": booking_id, "message": "予約が保存されました"}

# 2. 予約一覧取得 API（管理画面用・パスワード認証付き）
@app.get("/api/bookings")
def get_bookings(x_admin_password: Optional[str] = Header(None)):
    # パスワードの検証
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="パスワードが正しくありません"
        )

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT booking_id, user_id, name, gender, area, preferred_datetime, primary_type, created_at FROM bookings ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()

    bookings = []
    for r in rows:
        bookings.append({
            "booking_id": r[0],
            "user_id": r[1],
            "name": r[2],
            "gender": r[3],
            "area": r[4],
            "datetime": r[5],
            "primary_type": r[6],
            "created_at": r[7]
        })
    return bookings
