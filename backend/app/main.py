import os
import uuid
import itertools
from collections import defaultdict
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, status, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from sqlalchemy import create_engine, String, Integer, Column, DateTime, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session

from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, PushMessageRequest, TextMessage
)

# ==========================================
# 1. データベース設定 & モデル定義
# ==========================================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ape_app.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

class ApeProfileModel(Base):
    __tablename__ = "ape_profiles"

    profile_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    primary_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    score_chimpanzee: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    score_bonobo: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    score_gorilla: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    score_orangutan: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    extraversion_score: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    achievement_score: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

class BookingModel(Base):
    __tablename__ = "bookings"

    booking_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    gender: Mapped[str] = mapped_column(String)
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    area: Mapped[str] = mapped_column(String)
    preferred_datetime: Mapped[str] = mapped_column(String)
    
    area_2: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    datetime_2: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    primary_type: Mapped[Optional[str]] = mapped_column(String, default="gorilla")
    extraversion_score: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    achievement_score: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    
    status: Mapped[str] = mapped_column(String, default="pending")
    group_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==========================================
# 2. LINE 通知処理
# ==========================================
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

def send_line_notification(to_user_id: str, message_text: str):
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("[LINE Notice] ACCESS_TOKEN 未設定のためスキップ")
        return False
    try:
        configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            push_message_request = PushMessageRequest(
                to=to_user_id,
                messages=[TextMessage(text=message_text)]
            )
            line_bot_api.push_message(push_message_request)
        return True
    except Exception as e:
        print(f"[LINE Error] 送信失敗 ({to_user_id}): {e}")
        return False

# ==========================================
# 3. マッチングコアスコアリング機能
# ==========================================
def calculate_same_type_score(group: List[BookingModel]) -> int:
    types = [m.primary_type for m in group]
    first_type = types[0]
    
    if not all(t == first_type for t in types):
        return 0
    
    score = 100
    e_scores = [m.extraversion_score or 0 for m in group]
    a_scores = [m.achievement_score or 0 for m in group]
    
    diff_e = max(e_scores) - min(e_scores)
    diff_a = max(a_scores) - min(a_scores)
    
    score -= (diff_e + diff_a) * 5
    return max(score, 1)

def calculate_balance_score(group: List[BookingModel]) -> int:
    type_counts = {"chimpanzee": 0, "bonobo": 0, "gorilla": 0, "orangutan": 0}
    for m in group:
        t = (m.primary_type or "gorilla").lower()
        if t in type_counts:
            type_counts[t] += 1

    unique_types_count = sum(1 for count in type_counts.values() if count > 0)
    score = 0

    if unique_types_count == 4:
        score += 100
    elif unique_types_count == 3:
        score += 70
    elif unique_types_count == 2:
        score += 40
    else:
        score += 10

    if type_counts["chimpanzee"] >= 3:
        score -= 40
    if type_counts["orangutan"] >= 3:
        score -= 40

    if type_counts["bonobo"] >= 1 or type_counts["gorilla"] >= 1:
        score += 20

    # 年齢差ペナルティ（年齢差15歳以上で減点）
    ages = [u.age for u in group if u.age is not None]
    if len(ages) >= 2 and (max(ages) - min(ages)) > 15:
        score -= 50

    return max(score, 0)

def has_met_before(db: Session, candidate_users: List[BookingModel]) -> bool:
    """過去に同じグループでマッチング済みのペアを排除"""
    u_ids = [u.user_id for u in candidate_users]
    stmt = select(BookingModel).where(
        BookingModel.user_id.in_(u_ids),
        BookingModel.status == "matched",
        BookingModel.group_id.isnot(None)
    )
    past_matches = db.scalars(stmt).all()

    groups = defaultdict(set)
    for m in past_matches:
        groups[m.group_id].add(m.user_id)

    for g_users in groups.values():
        if len(set(u_ids).intersection(g_users)) >= 2:
            return True
    return False

# ==========================================
# 4. FastAPI アプリケーション定義
# ==========================================
app = FastAPI(title="類人猿マッチング API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ape_secret_pass_2026")

class BookingCreate(BaseModel):
    user_id: str
    name: str
    gender: str
    age: Optional[int] = None
    area: str
    datetime: str
    area_2: Optional[str] = None
    datetime_2: Optional[str] = None
    primary_type: Optional[str] = "gorilla"
    extraversion_score: Optional[int] = 0
    achievement_score: Optional[int] = 0

# --- エンドポイント ---

@app.post("/api/bookings", status_code=status.HTTP_201_CREATED)
def create_booking(booking: BookingCreate, db: Session = Depends(get_db)):
    booking_id = f"bk_{uuid.uuid4().hex[:8]}"
    
    new_booking = BookingModel(
        booking_id=booking_id,
        user_id=booking.user_id,
        name=booking.name,
        gender=booking.gender,
        age=booking.age,
        area=booking.area,
        preferred_datetime=booking.datetime,
        area_2=booking.area_2,
        datetime_2=booking.datetime_2,
        primary_type=booking.primary_type,
        extraversion_score=booking.extraversion_score,
        achievement_score=booking.achievement_score,
        status="pending"
    )
    
    try:
        db.add(new_booking)
        db.commit()
        db.refresh(new_booking)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
    return {"status": "success", "booking_id": booking_id, "message": "予約が保存されました"}


@app.post("/api/matchings/run")
def run_matching(
    match_mode: str = "BALANCE",
    x_admin_password: Optional[str] = Header(None, alias="X-Admin-Password"), 
    db: Session = Depends(get_db)
):
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="パスワードが正しくありません")

    stmt = select(BookingModel).where(BookingModel.status == "pending")
    pending_users = db.scalars(stmt).all()

    if not pending_users:
        return {"status": "success", "created_groups": 0, "message": "マッチング対象の未処理予約はありません"}

    created_groups_count = 0
    notified_users_count = 0

    # 日時・エリアごとのスロット化処理関数
    def process_slots(users_list: List[BookingModel], is_second_choice: bool = False):
        nonlocal created_groups_count, notified_users_count
        
        slots = defaultdict(list)
        for u in users_list:
            if u.status != "pending":
                continue
            
            target_area = u.area_2 if is_second_choice else u.area
            target_dt = u.datetime_2 if is_second_choice else u.preferred_datetime
            
            if not target_area or not target_dt:
                continue
                
            raw_dt = target_dt.replace('T', ' ')
            dt_hour = raw_dt[:13] if len(raw_dt) >= 13 else raw_dt
            slots[(target_area, dt_hour)].append(u)

        for (area, dt_hour), pool in slots.items():
            active_pool = [u for u in pool if u.status == "pending"]
            males = [u for u in active_pool if u.gender == "male"]
            females = [u for u in active_pool if u.gender == "female"]

            if len(males) < 2 or len(females) < 2:
                continue

            male_pairs = list(itertools.combinations(males, 2))
            female_pairs = list(itertools.combinations(females, 2))

            possible_groups = []
            for m_pair in male_pairs:
                for f_pair in female_pairs:
                    candidate = list(m_pair) + list(f_pair)
                    
                    if has_met_before(db, candidate):
                        continue

                    score = calculate_same_type_score(candidate) if match_mode == "SAME_TYPE" else calculate_balance_score(candidate)
                    
                    if score > 0:
                        possible_groups.append({
                            "score": score,
                            "members": candidate,
                            "b_ids": [m.booking_id for m in candidate]
                        })

            # 高スコア順にソートして確定させる
            possible_groups.sort(key=lambda x: x["score"], reverse=True)
            used_b_ids = set()

            for g in possible_groups:
                # 重複割り当て防止
                if any(b_id in used_b_ids or db.get(BookingModel, b_id).status == "matched" for b_id in g["b_ids"]):
                    continue

                group_id = f"grp_{uuid.uuid4().hex[:8]}"
                for member in g["members"]:
                    member.status = "matched"
                    member.group_id = group_id
                    used_b_ids.add(member.booking_id)

                db.commit()
                created_groups_count += 1

                # LINE通知送信
                for member in g["members"]:
                    msg = (
                        f"🎉 【マッチング成立のお知らせ】\n\n"
                        f"{member.name} 様\n\n"
                        f"お食事会のマッチングが成立しました✨\n\n"
                        f"■ 日時: {dt_hour}:00 頃\n"
                        f"■ エリア: {area}\n"
                        f"■ マッチングタイプ: {'同族重視' if match_mode == 'SAME_TYPE' else 'バランス重視'}\n"
                        f"■ グループID: {group_id}\n\n"
                        f"当日の店舗案内は追ってご連絡いたします。"
                    )
                    if send_line_notification(member.user_id, msg):
                        notified_users_count += 1

    # フェーズ1: 第1希望でマッチング
    process_slots(pending_users, is_second_choice=False)

    # フェーズ2: 未マッチングユーザーを対象に第2希望で再マッチング
    remaining_users = db.scalars(select(BookingModel).where(BookingModel.status == "pending")).all()
    if remaining_users:
        process_slots(remaining_users, is_second_choice=True)

    return {
        "status": "success",
        "created_groups": created_groups_count,
        "notified_users": notified_users_count,
        "message": f"{created_groups_count} 件のグループが作られ、{notified_users_count} 名にLINE通知が送信されました。"
    }
