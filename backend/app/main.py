import os
import uuid
import itertools
import stripe
from collections import defaultdict
from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import FastAPI, HTTPException, status, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from sqlalchemy import create_engine, String, Integer, Column, DateTime, Boolean, ForeignKey, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session

from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, PushMessageRequest, TextMessage
)

# ==========================================
# 0. 外部サービス初期化 (Stripe)
# ==========================================
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_xxx")
stripe.api_key = STRIPE_SECRET_KEY

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

# --- ユーザー情報 ＆ ブラックリスト / キャンセル管理モデル ---
class UserModel(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True)
    gender: Mapped[str] = mapped_column(String)  # 'female', 'male'
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_warning: Mapped[bool] = mapped_column(Boolean, default=False)
    has_canceled_first_free: Mapped[bool] = mapped_column(Boolean, default=False)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

class UserCardFingerprintModel(Base):
    __tablename__ = "user_card_fingerprints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.user_id"), index=True)
    card_fingerprint: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

class CancellationHistoryModel(Base):
    __tablename__ = "cancellation_histories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.user_id"))
    booking_id: Mapped[str] = mapped_column(String, ForeignKey("bookings.booking_id"))
    fee_amount: Mapped[int] = mapped_column(Integer, default=0)
    is_exempted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

# --- マッチング＆プロファイル用モデル ---
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
    
    status: Mapped[str] = mapped_column(String, default="pending")  # 'pending', 'matched', 'cancelled'
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
# 3. マッチングコアスコアリング機能（ハイブリッド化）
# ==========================================
def is_specialist(user: BookingModel) -> bool:
    e_score = user.extraversion_score or 0
    a_score = user.achievement_score or 0
    return (e_score >= 70 or a_score >= 70)

def calculate_same_type_score(group: List[BookingModel]) -> int:
    types = [(m.primary_type or "gorilla").lower() for m in group]
    first_type = types[0]
    
    if not all(t == first_type for t in types):
        return 0
    
    score = 100
    specialist_count = sum(1 for m in group if is_specialist(m))
    score += specialist_count * 10

    e_scores = [m.extraversion_score or 0 for m in group]
    a_scores = [m.achievement_score or 0 for m in group]
    
    diff_e = max(e_scores) - min(e_scores)
    diff_a = max(a_scores) - min(a_scores)
    
    score -= (diff_e + diff_a) * 3
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

    ages = [u.age for u in group if u.age is not None]
    if len(ages) >= 2 and (max(ages) - min(ages)) > 15:
        score -= 50

    return max(score, 0)

def calculate_hybrid_score(group: List[BookingModel], mode: str = "AUTO") -> tuple[int, str]:
    same_score = calculate_same_type_score(group)
    balance_score = calculate_balance_score(group)

    if mode == "SAME_TYPE":
        return same_score, "同族重視"
    elif mode == "BALANCE":
        return balance_score, "バランス重視"
    else:
        if same_score >= 80:
            return same_score, "同族重視"
        elif balance_score >= same_score:
            return balance_score, "バランス重視"
        else:
            return same_score, "同族重視"

def has_met_before(db: Session, candidate_users: List[BookingModel]) -> bool:
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

# --- リクエスト/レスポンススキーマ ---
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

class CardRegisterRequest(BaseModel):
    user_id: str
    payment_method_id: str

class CancelBookingRequest(BaseModel):
    user_id: str

# --- 認証チェック補助関数 ---
def verify_admin(x_admin_password: Optional[str] = Header(None, alias="X-Admin-Password")):
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="パスワードが正しくありません")
    return True

# ==========================================
# 5. API エンドポイント
# ==========================================

# 1. ルートヘルスチェック（Render起動確認用）
@app.get("/")
def read_root():
    return {"status": "ok", "service": "APE Matching API"}

# 2. 予約作成 API
@app.post("/api/bookings", status_code=status.HTTP_201_CREATED)
def create_booking(booking: BookingCreate, db: Session = Depends(get_db)):
    # ユーザーがブラックリスト化されていないか事前検証
    user = db.scalar(select(UserModel).where(UserModel.user_id == booking.user_id))
    if user and user.is_blacklisted:
        raise HTTPException(status_code=403, detail="規約違反により予約を受け付けられません")

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

# 3. Stripe カード登録 ＆ 複垢名寄せ・ブラックリストチェック API
@app.post("/api/users/register-card")
def register_card(req: CardRegisterRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(UserModel).where(UserModel.user_id == req.user_id))
    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    
    if user.is_blacklisted:
        raise HTTPException(status_code=403, detail="このアカウントではカードを登録できません")

    try:
        pm = stripe.PaymentMethod.retrieve(req.payment_method_id)
        card_fingerprint = pm.card.fingerprint
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Stripeエラー: {str(e)}")

    # 同一カードが過去にブラックリストユーザーで使われていないかチェック
    existing_cards = db.scalars(
        select(UserCardFingerprintModel).where(UserCardFingerprintModel.card_fingerprint == card_fingerprint)
    ).all()

    for record in existing_cards:
        assoc_user = db.scalar(select(UserModel).where(UserModel.user_id == record.user_id))
        if assoc_user and assoc_user.is_blacklisted:
            user.is_blacklisted = True
            db.commit()
            raise HTTPException(status_code=403, detail="過去に規約違反があったカードのため受付できません")

    # 正常登録
    new_card_record = UserCardFingerprintModel(user_id=user.user_id, card_fingerprint=card_fingerprint)
    db.add(new_card_record)
    db.commit()
    return {"status": "success", "card_fingerprint": card_fingerprint}

# 4. 予約キャンセル ＆ 女性初回免除処理 API
@app.post("/api/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: str, req: CancelBookingRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(UserModel).where(UserModel.user_id == req.user_id))
    booking = db.scalar(select(BookingModel).where(BookingModel.booking_id == booking_id))

    if not booking or booking.user_id != req.user_id:
        raise HTTPException(status_code=404, detail="該当の予約が見つかりません")

    # 女性 ＆ 初回キャンセル免除の適用判断
    if user and user.gender == "female" and not user.has_canceled_first_free:
        user.has_canceled_first_free = True
        booking.status = "cancelled"
        
        history = CancellationHistoryModel(
            user_id=user.user_id,
            booking_id=booking.booking_id,
            fee_amount=0,
            is_exempted=True
        )
        db.add(history)
        db.commit()
        return {"status": "cancelled", "fee": 0, "message": "初回のキャンセル料免除が適用されました"}

    # 通常キャンセル料処理 (例: 3,000円)
    cancellation_fee = 3000
    booking.status = "cancelled"
    
    history = CancellationHistoryModel(
        user_id=req.user_id,
        booking_id=booking.booking_id,
        fee_amount=cancellation_fee,
        is_exempted=False
    )
    db.add(history)
    db.commit()

    return {"status": "cancelled", "fee": cancellation_fee, "message": f"キャンセル料 {cancellation_fee}円が発生しました"}

# 5. 管理画面用：予約一覧取得 API
@app.get("/api/bookings")
def get_bookings(db: Session = Depends(get_db), _: bool = Depends(verify_admin)):
    stmt = select(BookingModel).order_by(BookingModel.created_at.desc())
    bookings = db.scalars(stmt).all()
    
    result = []
    for b in bookings:
        result.append({
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
            "extraversion_score": b.extraversion_score,
            "achievement_score": b.achievement_score,
            "status": b.status,
            "group_id": b.group_id,
            "created_at": b.created_at.strftime("%Y-%m-%d %H:%M") if b.created_at else None
        })
    return result

# 6. 管理画面用：成立グループ一覧取得 API
@app.get("/api/matchings")
def get_matchings(db: Session = Depends(get_db), _: bool = Depends(verify_admin)):
    stmt = select(BookingModel).where(
        BookingModel.status == "matched",
        BookingModel.group_id.isnot(None)
    )
    matched_bookings = db.scalars(stmt).all()

    groups_dict = defaultdict(list)
    for b in matched_bookings:
        groups_dict[b.group_id].append({
            "booking_id": b.booking_id,
            "user_id": b.user_id,
            "name": b.name,
            "gender": b.gender,
            "age": b.age,
            "area": b.area,
            "datetime": b.preferred_datetime,
            "primary_type": b.primary_type
        })

    result = []
    for group_id, members in groups_dict.items():
        result.append({
            "group_id": group_id,
            "members": members
        })
    return result

# 7. マッチング実行 API
@app.post("/api/matchings/run")
def run_matching(
    match_mode: str = "AUTO",
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    stmt = select(BookingModel).where(BookingModel.status == "pending")
    pending_users = db.scalars(stmt).all()

    if not pending_users:
        return {"status": "success", "created_groups": 0, "message": "マッチング対象の未処理予約はありません"}

    created_groups_count = 0
    notified_users_count = 0

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

                    score, matched_type_label = calculate_hybrid_score(candidate, mode=match_mode)
                    
                    if score > 0:
                        possible_groups.append({
                            "score": score,
                            "matched_type_label": matched_type_label,
                            "members": candidate,
                            "b_ids": [m.booking_id for m in candidate]
                        })

            possible_groups.sort(key=lambda x: x["score"], reverse=True)
            used_b_ids = set()

            for g in possible_groups:
                if any(b_id in used_b_ids or db.get(BookingModel, b_id).status == "matched" for b_id in g["b_ids"]):
                    continue

                group_id = f"grp_{uuid.uuid4().hex[:8]}"
                for member in g["members"]:
                    member.status = "matched"
                    member.group_id = group_id
                    used_b_ids.add(member.booking_id)

                db.commit()
                created_groups_count += 1

                for member in g["members"]:
                    msg = (
                        f"🎉 【マッチング成立のお知らせ】\n\n"
                        f"{member.name} 様\n\n"
                        f"お食事会のマッチングが成立しました✨\n\n"
                        f"■ 日時: {dt_hour}:00 頃\n"
                        f"■ エリア: {area}\n"
                        f"■ マッチングタイプ: {g['matched_type_label']}\n"
                        f"■ グループID: {group_id}\n\n"
                        f"当日の店舗案内は追ってご連絡いたします。"
                    )
                    if send_line_notification(member.user_id, msg):
                        notified_users_count += 1

    process_slots(pending_users, is_second_choice=False)

    remaining_users = db.scalars(select(BookingModel).where(BookingModel.status == "pending")).all()
    if remaining_users:
        process_slots(remaining_users, is_second_choice=True)

    return {
        "status": "success",
        "created_groups": created_groups_count,
        "notified_users": notified_users_count,
        "message": f"{created_groups_count} 件のグループが作られ、{notified_users_count} 名にLINE通知が送信されました。"
    }
