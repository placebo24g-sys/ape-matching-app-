from fastapi import FastAPI, HTTPException, status, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
import uuid
from collections import defaultdict

app = FastAPI(title="類人猿マッチング API")

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "ape_app.db"
ADMIN_PASSWORD = "ape_secret_pass_2026"

# DB初期化（テーブル生成 & 自動カラム追加）
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. 診断プロフィールテーブル
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
    
    # 2. 予約申し込みテーブル
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            booking_id TEXT PRIMARY KEY,
            user_id TEXT,
            name TEXT,
            gender TEXT,
            area TEXT,
            preferred_datetime TEXT,
            primary_type TEXT,
            status TEXT DEFAULT 'pending',
            group_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 既存のDBへのカラム追加（すでにテーブルが存在している場合用）
    cursor.execute("PRAGMA table_info(bookings)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'status' not in columns:
        cursor.execute("ALTER TABLE bookings ADD COLUMN status TEXT DEFAULT 'pending'")
    if 'group_id' not in columns:
        cursor.execute("ALTER TABLE bookings ADD COLUMN group_id TEXT")
        
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
            INSERT INTO bookings (booking_id, user_id, name, gender, area, preferred_datetime, primary_type, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
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

# 2. 予約一覧取得 API（管理画面用）
@app.get("/api/bookings")
def get_bookings(x_admin_password: Optional[str] = Header(None)):
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="パスワードが正しくありません")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT booking_id, user_id, name, gender, area, preferred_datetime, primary_type, status, group_id, created_at FROM bookings ORDER BY created_at DESC")
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
            "status": r[7],
            "group_id": r[8],
            "created_at": r[9]
        })
    return bookings

# 3. 自動マッチング実行 API（管理画面用）
@app.post("/api/matchings/run")
def run_matching(x_admin_password: Optional[str] = Header(None)):
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="パスワードが正しくありません")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 未マッチング（pending）のデータを取り出す
    cursor.execute("SELECT booking_id, name, gender, area, preferred_datetime, primary_type FROM bookings WHERE status = 'pending'")
    pending_users = cursor.fetchall()

    if not pending_users:
        conn.close()
        return {"status": "success", "created_groups": 0, "message": "マッチング対象の未処理予約はありません"}

    # エリア×日時 でグループ化
    slots = defaultdict(list)
    for u in pending_users:
        key = (u[3], u[4])  # (area, preferred_datetime)
        slots[key].append({
            "booking_id": u[0],
            "name": u[1],
            "gender": u[2],
            "primary_type": u[5]
        })

    created_groups_count = 0

    # 各枠ごとにマッチング処理
    for (area, dt), users in slots.items():
        # 人数が3人未満ならマッチング成立見送り（次回へ保留）
        if len(users) < 3:
            continue

        # タイプ別にユーザーを整理
        type_buckets = defaultdict(list)
        for u in users:
            type_buckets[u["primary_type"]].append(u)

        remaining_users = list(users)

        while len(remaining_users) >= 3:
            target_size = 4 if len(remaining_users) >= 4 else 3
            group_members = []

            # 異なるタイプから優先的に1人ずつ選出
            for t, bucket in list(type_buckets.items()):
                if bucket and len(group_members) < target_size:
                    selected = bucket.pop(0)
                    group_members.append(selected)
                    remaining_users.remove(selected)

            # タイプ分散だけでは枠が埋まらない場合、残りの人から追加
            while len(group_members) < target_size and remaining_users:
                selected = remaining_users.pop(0)
                group_members.append(selected)
                # バケット側からも取り除く
                if selected in type_buckets[selected["primary_type"]]:
                    type_buckets[selected["primary_type"]].remove(selected)

            # グループID生成 & DB更新
            group_id = f"grp_{uuid.uuid4().hex[:8]}"
            member_ids = [m["booking_id"] for m in group_members]
            
            cursor.execute(
                f"UPDATE bookings SET status = 'matched', group_id = ? WHERE booking_id IN ({','.join(['?']*len(member_ids))})",
                [group_id] + member_ids
            )
            created_groups_count += 1

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "created_groups": created_groups_count,
        "message": f"{created_groups_count} 件のマッチンググループを作成しました"
    }

# 4. マッチング済みグループ一覧取得 API
@app.get("/api/matchings")
def get_matchings(x_admin_password: Optional[str] = Header(None)):
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="パスワードが正しくありません")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT group_id, booking_id, name, gender, area, preferred_datetime, primary_type FROM bookings WHERE status = 'matched' ORDER BY group_id")
    rows = cursor.fetchall()
    conn.close()

    groups = defaultdict(list)
    for r in rows:
        g_id = r[0]
        groups[g_id].append({
            "booking_id": r[1],
            "name": r[2],
            "gender": r[3],
            "area": r[4],
            "datetime": r[5],
            "primary_type": r[6]
        })

    result = [{"group_id": g_id, "members": members} for g_id, members in groups.items()]
    return result
