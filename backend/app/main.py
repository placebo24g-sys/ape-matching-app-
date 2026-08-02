from fastapi import FastAPI, HTTPException, status, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import os
import uuid
from collections import defaultdict
import itertools

from sqlalchemy import create_engine, String, Integer, Column, DateTime, func, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session

# ------------------------------------------
# LINE SDK インポート
# ------------------------------------------
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    TextMessage
)

# ==========================================
# 1. データベース設定 (SQLAlchemy 2.0)
# ==========================================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ape_app.db")

# Renderの postgres:// を postgresql:// に置換
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

# テーブルモデル定義
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
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True) # 追加: 年齢
    
    # 第1希望
    area: Mapped[str] = mapped_column(String)
    preferred_datetime: Mapped[str] = mapped_column(String)
    
    # 第2希望 (追加)
    area_2: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    datetime_2: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    primary_type: Mapped[Optional[str]] = mapped_column(String, default="gorilla")
    status: Mapped[str] = mapped_column(String, default="pending")
    group_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

# テーブル作成
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==========================================
# 2. LINE Messaging API 設定
# ==========================================
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

def send_line_notification(to_user_id: str, message_text: str):
    """LINEユーザーに個別メッセージをプッシュ送信"""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("[LINE Notice] LINE_CHANNEL_ACCESS_TOKEN が未設定のため通知をスキップしました")
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
# 3. FastAPI アプリケーション設定 & Pydantic
# ==========================================
app = FastAPI(title="類人猿マッチング API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ape_secret_pass_2026")

class BookingCreate(BaseModel):
    user_id: str
    name: str
    gender: str
    age: Optional[int] = None                  # 追加: 年齢
    area: str
    datetime: str
    area_2: Optional[str] = None               # 追加: 第2希望エリア
    datetime_2: Optional[str] = None           # 追加: 第2希望日時
    primary_type: Optional[str] = "gorilla"

# ==========================================
# 4. マッチング判定用ヘルパー関数
# ==========================================
def has_met_before(db: Session, candidate_users: List[BookingModel]) -> bool:
    """過去に同じ group_id でマッチング済みのペアが紛れていないか判定"""
    u_ids = [u.user_id for u in candidate_users]
    
    # 過去にマッチング成立済みのデータを取得
    stmt = select(BookingModel).where(
        BookingModel.user_id.in_(u_ids),
        BookingModel.status == "matched",
        BookingModel.group_id.isnot(None)
    )
    past_matches = db.scalars(stmt).all()

    # グループIDごとにユーザーIDを集計
    groups = defaultdict(set)
    for m in past_matches:
        groups[m.group_id].add(m.user_id)

    # 候補者の中に過去の同一グループ構成員が2人以上被っていれば True (同席NG)
    for g_users in groups.values():
        if len(set(u_ids).intersection(g_users)) >= 2:
            return True
    return False

def is_group_balanced(candidate_users: List[BookingModel]) -> bool:
    """性別比・年齢差のバランス判定"""
    # 1. 性別比チェック (4人の場合: 男3人女1人・男1人女3人などの極端な偏りを回避)
    genders = [u.gender for u in candidate_users]
    males = genders.count("male")
    females = genders.count("female")
    
    if len(candidate_users) == 4 and (males == 3 and females == 1):
        return False
    if len(candidate_users) == 4 and (males == 1 and females == 3):
        return False

    # 2. 年齢差チェック (入力者の中で最大差が15歳以上の場合はスキップ)
    ages = [u.age for u in candidate_users if u.age is not None]
    if len(ages) >= 2:
        if (max(ages) - min(ages)) > 15:
            return False

    return True

# ==========================================
# 5. API エンドポイント
# ==========================================

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

@app.get("/api/bookings")
def get_bookings(x_admin_password: Optional[str] = Header(None), db: Session = Depends(get_db)):
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="パスワードが正しくありません")

    stmt = select(BookingModel).order_by(BookingModel.created_at.desc())
    bookings = db.scalars(stmt).all()

    return [{
        "booking_id": b.booking_id,
        "user_id": b.user_id,
        "name": b.name,
        "gender": b.gender,
        "age": b.age,
        "area": b.area,
        "datetime": b.preferred_datetime,
        "area_2": b.area_2,
        "datetime_2": b.datetime_2,
        "primary_type": b.primary_type,
        "status": b.status,
        "group_id": b.group_id,
        "created_at": b.created_at.strftime("%Y-%m-%d %H:%M:%S") if b.created_at else None
    } for b in bookings]

@app.post("/api/matchings/run")
def run_matching(x_admin_password: Optional[str] = Header(None), db: Session = Depends(get_db)):
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="パスワードが正しくありません")

    stmt = select(BookingModel).where(BookingModel.status == "pending")
    pending_users = db.scalars(stmt).all()

    if not pending_users:
        return {"status": "success", "created_groups": 0, "message": "マッチング対象の未処理予約はありません"}

    created_groups_count = 0
    notified_users_count = 0

    # ----------------------------------------------------
    # Phase 1: 第1希望のみでスロット化
    # ----------------------------------------------------
    slots_p1 = defaultdict(list)
    for u in pending_users:
        raw_dt = u.preferred_datetime.replace('T', ' ')
        dt_hour = raw_dt[:13] if len(raw_dt) >= 13 else raw_dt
        slots_p1[(u.area, dt_hour)].append(u)

    def process_matching_for_slots(slots_dict):
        nonlocal created_groups_count, notified_users_count
        for (area, dt_hour), users in slots_dict.items():
            # pending状態のユーザーのみを対象に絞り込み
            active_users = [u for u in users if u.status == "pending"]
            if len(active_users) < 3:
                continue

            # 4人組 ➡ 3人組の順でマッチング探索
            for group_size in [4, 3]:
                if len(active_users) < group_size:
                    continue

                for combo in itertools.combinations(active_users, group_size):
                    combo_list = list(combo)
                    
                    # すでに他の組み合わせで確定済みのユーザーが含まれていたらスキップ
                    if any(u.status == "matched" for u in combo_list):
                        continue

                    # ブラックリスト（同席履歴）チェック
                    if has_met_before(db, combo_list):
                        continue

                    # 性別比・年齢差バランスチェック
                    if not is_group_balanced(combo_list):
                        continue

                    # 条件達成！グループ確定
                    group_id = f"grp_{uuid.uuid4().hex[:8]}"
                    for member in combo_list:
                        member.status = "matched"
                        member.group_id = group_id

                    db.commit()
                    created_groups_count += 1

                    # LINE通知
                    for member in combo_list:
                        msg = (
                            f"🎉 【マッチング成立のお知らせ】\n\n"
                            f"{member.name} 様\n\n"
                            f"お待たせいたしました！食事会のマッチングが成立しました✨\n\n"
                            f"■ 日時: {dt_hour}:00 頃\n"
                            f"■ エリア: {area}\n"
                            f"■ グループID: {group_id}\n\n"
                            f"当日の詳細案内や店舗情報は、追ってこちらのトーク画面にてご連絡いたします。"
                        )
                        if send_line_notification(member.user_id, msg):
                            notified_users_count += 1
                    
                    # 確定したメンバーを候補一覧から除外
                    active_users = [u for u in active_users if u.status == "pending"]

    # Phase 1 実行
    process_matching_for_slots(slots_p1)

    # ----------------------------------------------------
    # Phase 2: 残ったユーザーで「第2希望」も含めたスロット化
    # ----------------------------------------------------
    remaining_stmt = select(BookingModel).where(BookingModel.status == "pending")
    remaining_users = db.scalars(remaining_stmt).all()

    if remaining_users:
        slots_p2 = defaultdict(list)
        for u in remaining_users:
            # 第2希望が存在すればスロットにエントリー
            if u.area_2 and u.datetime_2:
                raw_dt_2 = u.datetime_2.replace('T', ' ')
                dt_hour_2 = raw_dt_2[:13] if len(raw_dt_2) >= 13 else raw_dt_2
                slots_p2[(u.area_2, dt_hour_2)].append(u)

        # Phase 2 実行
        process_matching_for_slots(slots_p2)

    return {
        "status": "success",
        "created_groups": created_groups_count,
        "notified_users": notified_users_count,
        "message": f"{created_groups_count} 件のグループを作成し、{notified_users_count} 名にLINE通知を送信しました。"
    }

@app.get("/api/matchings")
def get_matchings(x_admin_password: Optional[str] = Header(None), db: Session = Depends(get_db)):
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="パスワードが正しくありません")

    stmt = select(BookingModel).where(BookingModel.status == "matched").order_by(BookingModel.group_id)
    matched_bookings = db.scalars(stmt).all()

    groups = defaultdict(list)
    for b in matched_bookings:
        groups[b.group_id].append({
            "booking_id": b.booking_id,
            "user_id": b.user_id,
            "name": b.name,
            "gender": b.gender,
            "age": b.age,
            "area": b.area,
            "datetime": b.preferred_datetime,
            "primary_type": b.primary_type
        })

    result = [{"group_id": g_id, "members": members} for g_id, members in groups.items()]
    return result
