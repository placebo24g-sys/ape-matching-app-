import itertools
import os
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PushMessageRequest,
    TextMessage,
)
from pydantic import BaseModel
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    BigInteger,
    or_,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
import stripe

# ==========================================
# 0. 外部サービス・環境変数設定
# ==========================================
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_xxx")
stripe.api_key = STRIPE_SECRET_KEY

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_ID = os.getenv("LINE_CHANNEL_ID")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ape_secret_pass_2026")

AI_BOOKING_WEBHOOK_URL = os.getenv("AI_BOOKING_WEBHOOK_URL", "")
AI_BOOKING_API_KEY = os.getenv("AI_BOOKING_API_KEY", "")

# ==========================================
# 1. データベース設定 (Supabase / PostgreSQL対応)
# ==========================================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ape_app.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine_args = {}
if DATABASE_URL.startswith("postgresql"):
    engine_args = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
else:
    engine_args = {
        "connect_args": {"check_same_thread": False}
    }

engine = create_engine(DATABASE_URL, **engine_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

class UserModel(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    email: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True, index=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True)
    gender: Mapped[str] = mapped_column(String, default="other")
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_warning: Mapped[bool] = mapped_column(Boolean, default=False)
    has_canceled_first_free: Mapped[bool] = mapped_column(Boolean, default=False)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
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

class BlacklistModel(Base):
    __tablename__ = "blacklists"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    reason: Mapped[Optional[str]] = mapped_column(String, default="規約違反・自動判定")
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

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==========================================
# 2. 外部通知・連携機能 (LINE / AI予約Webhook)
# ==========================================
def verify_liff_token(access_token: str) -> dict:
    url = "https://api.line.me/v2/profile"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(url, headers=headers, timeout=5)
    
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無効なLINEアクセストークンです。"
        )
    return resp.json()

def send_line_notification(to_user_id: str, message_text: str) -> bool:
    if not LINE_CHANNEL_ACCESS_TOKEN or not to_user_id.startswith("U"):
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

def notify_ai_booking_server(booking_data: dict):
    if not AI_BOOKING_WEBHOOK_URL:
        return
    try:
        headers = {"Content-Type": "application/json"}
        if AI_BOOKING_API_KEY:
            headers["Authorization"] = f"Bearer {AI_BOOKING_API_KEY}"
        requests.post(AI_BOOKING_WEBHOOK_URL, json=booking_data, headers=headers, timeout=5)
    except Exception as e:
        print(f"[Webhook Error] AI予約サーバーへの送信に失敗しました: {e}")

# ==========================================
# 3. マッチングコアスコアリング機能
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
        if m.group_id:
            groups[m.group_id].add(m.user_id)

    for g_users in groups.values():
        if len(set(u_ids).intersection(g_users)) >= 2:
            return True
    return False

# ==========================================
# 4. FastAPI アプリケーション定義
# ==========================================
app = FastAPI(title="類人猿マッチング API (ブラウザ・LINE両対応)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

class LiffAuthRequest(BaseModel):
    access_token: Optional[str] = None

class BookingCreateLIFF(BaseModel):
    access_token: Optional[str] = None
    name: str
    gender: str
    age: Optional[int] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    area: str
    datetime: str
    area_2: Optional[str] = None
    datetime_2: Optional[str] = None
    primary_type: Optional[str] = "gorilla"
    extraversion_score: Optional[int] = 0
    achievement_score: Optional[int] = 0

class ApeProfileCreate(BaseModel):
    user_id: Optional[str] = None
    primary_type: str
    score_chimpanzee: Optional[int] = 0
    score_bonobo: Optional[int] = 0
    score_gorilla: Optional[int] = 0
    score_orangutan: Optional[int] = 0
    extraversion_score: Optional[int] = 0
    achievement_score: Optional[int] = 0

class CardRegisterRequest(BaseModel):
    user_id: str
    payment_method_id: str

class CancelBookingRequest(BaseModel):
    user_id: str

class BlacklistCreateRequest(BaseModel):
    user_id: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    ip_address: Optional[str] = None
    reason: Optional[str] = "管理者による手動登録"

class ManualMatchRequest(BaseModel):
    booking_ids: List[str]

class AIWebhookReceiveRequest(BaseModel):
    event_type: str
    booking_id: str
    status: Optional[str] = None
    group_id: Optional[str] = None
    message: Optional[str] = None

def verify_admin(x_admin_password: Optional[str] = Header(None, alias="X-Admin-Password")):
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="パスワードが正しくありません")
    return True

# ==========================================
# 5. API エンドポイント
# ==========================================

@app.get("/")
def read_root():
    return {"status": "ok", "service": "APE Matching API with Browser & LINE support"}

@app.post("/api/auth/liff")
def authenticate_liff_user(req: LiffAuthRequest, db: Session = Depends(get_db)):
    user_id = None
    display_name = "ゲストユーザー"

    if req.access_token and req.access_token != "dummy_token":
        try:
            line_user = verify_liff_token(req.access_token)
            user_id = line_user.get("userId")
            display_name = line_user.get("displayName", display_name)
        except Exception:
            pass

    if not user_id:
        return {"status": "success", "is_registered": False, "line_profile": {"user_id": None, "display_name": display_name}}

    user = db.scalar(select(UserModel).where(UserModel.user_id == user_id))
    if user:
        if user.is_blacklisted:
            raise HTTPException(status_code=403, detail="このアカウントは利用が制限されています。")
        return {
            "status": "success",
            "is_registered": True,
            "user": {
                "user_id": user.user_id,
                "name": user.name,
                "gender": user.gender,
                "email": user.email,
                "phone_number": user.phone_number
            }
        }
    else:
        return {
            "status": "success",
            "is_registered": False,
            "line_profile": {
                "user_id": user_id,
                "display_name": display_name
            }
        }

@app.post("/api/bookings/liff", status_code=status.HTTP_201_CREATED)
def create_booking_via_liff(booking: BookingCreateLIFF, db: Session = Depends(get_db)):
    user_id = None

    if booking.access_token and booking.access_token != "dummy_token":
        try:
            line_user = verify_liff_token(booking.access_token)
            user_id = line_user.get("userId")
        except Exception:
            pass

    if not user_id:
        if booking.email:
            existing_user = db.scalar(select(UserModel).where(UserModel.email == booking.email))
            if existing_user:
                user_id = existing_user.user_id
        
        if not user_id:
            user_id = f"web_{uuid.uuid4().hex[:10]}"

    conditions = [BlacklistModel.user_id == user_id]
    if booking.email:
        conditions.append(BlacklistModel.email == booking.email)
    if booking.phone_number:
        conditions.append(BlacklistModel.phone_number == booking.phone_number)

    blacklisted_entry = db.scalar(select(BlacklistModel).where(or_(*conditions)))
    if blacklisted_entry:
        raise HTTPException(status_code=403, detail="現在、このアカウントからのご予約・操作は受け付けることができません。")

    user = db.scalar(select(UserModel).where(UserModel.user_id == user_id))
    if user:
        if user.is_blacklisted:
            raise HTTPException(status_code=403, detail="現在、このアカウントからのご予約・操作は受け付けることができません。")
        user.name = booking.name
        user.gender = booking.gender
        if booking.email: user.email = booking.email
        if booking.phone_number: user.phone_number = booking.phone_number
    else:
        user = UserModel(
            user_id=user_id,
            name=booking.name,
            gender=booking.gender,
            email=booking.email,
            phone_number=booking.phone_number
        )
        db.add(user)

    booking_id = f"bk_{uuid.uuid4().hex[:8]}"
    new_booking = BookingModel(
        booking_id=booking_id,
        user_id=user_id,
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
        raise HTTPException(status_code=500, detail=f"予約処理に失敗しました: {str(e)}")

    if user_id.startswith("U"):
        msg = f"【予約受付完了】\n{booking.name} 様\n\nご予約を受け付けました。\n■ エリア: {booking.area}\n■ 希望日時: {booking.datetime.replace('T', ' ')}\n\nマッチングが完了次第、こちらに通知いたします。"
        send_line_notification(user_id, msg)

    notify_ai_booking_server({
        "event_type": "new_booking",
        "booking_id": booking_id,
        "user_id": user_id,
        "name": booking.name,
        "gender": booking.gender,
        "area": booking.area,
        "preferred_datetime": booking.datetime
    })

    return {"status": "success", "booking_id": booking_id, "user_id": user_id, "message": "予約が完了しました"}

@app.post("/api/ai/webhook")
def receive_ai_webhook(payload: AIWebhookReceiveRequest, db: Session = Depends(get_db)):
    booking = db.scalar(select(BookingModel).where(BookingModel.booking_id == payload.booking_id))
    if not booking:
        raise HTTPException(status_code=404, detail="対象の予約が見つかりません")

    if payload.status:
        booking.status = payload.status
    if payload.group_id:
        booking.group_id = payload.group_id

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB更新エラー: {str(e)}")

    if payload.message and booking.user_id:
        send_line_notification(booking.user_id, payload.message)

    return {"status": "success", "booking_id": payload.booking_id, "updated_status": booking.status}

@app.post("/api/ape-profiles", status_code=status.HTTP_201_CREATED)
def create_ape_profile(profile: ApeProfileCreate, db: Session = Depends(get_db)):
    profile_id = f"prof_{uuid.uuid4().hex[:8]}"
    new_profile = ApeProfileModel(
        profile_id=profile_id,
        user_id=profile.user_id,
        primary_type=profile.primary_type,
        score_chimpanzee=profile.score_chimpanzee,
        score_bonobo=profile.score_bonobo,
        score_gorilla=profile.score_gorilla,
        score_orangutan=profile.score_orangutan,
        extraversion_score=profile.extraversion_score,
        achievement_score=profile.achievement_score
    )
    try:
        db.add(new_profile)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"診断プロフィールの保存に失敗しました: {str(e)}")
        
    return {"status": "success", "profile_id": profile_id}

@app.post("/api/users/register-card")
def register_card(req: CardRegisterRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(UserModel).where(UserModel.user_id == req.user_id))
    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    
    if user.is_blacklisted:
        raise HTTPException(status_code=403, detail="このアカウントではカードを登録できません")

    try:
        pm = stripe.PaymentMethod.retrieve(req.payment_method_id)
        card_fingerprint = pm.card.fingerprint if pm.card else None
        if not card_fingerprint:
            raise HTTPException(status_code=400, detail="カード情報の取得に失敗しました")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Stripeエラー: {str(e)}")

    existing_cards = db.scalars(
        select(UserCardFingerprintModel).where(UserCardFingerprintModel.card_fingerprint == card_fingerprint)
    ).all()

    for record in existing_cards:
        assoc_user = db.scalar(select(UserModel).where(UserModel.user_id == record.user_id))
        if assoc_user and assoc_user.is_blacklisted:
            user.is_blacklisted = True
            db.commit()
            raise HTTPException(status_code=403, detail="過去に規約違反があったカードのため受付できません")

    already_registered = any(r.user_id == user.user_id for r in existing_cards)
    if not already_registered:
        try:
            new_card_record = UserCardFingerprintModel(user_id=user.user_id, card_fingerprint=card_fingerprint)
            db.add(new_card_record)
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"カード情報登録エラー: {str(e)}")
        
    return {"status": "success", "card_fingerprint": card_fingerprint}

@app.post("/api/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: str, req: CancelBookingRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(UserModel).where(UserModel.user_id == req.user_id))
    booking = db.scalar(select(BookingModel).where(BookingModel.booking_id == booking_id))

    if not booking or booking.user_id != req.user_id:
        raise HTTPException(status_code=404, detail="該当の予約が見つかりません")

    if user and user.gender == "female" and not user.has_canceled_first_free:
        user.has_canceled_first_free = True
        booking.status = "cancelled"
        
        history = CancellationHistoryModel(
            user_id=user.user_id,
            booking_id=booking.booking_id,
            fee_amount=0,
            is_exempted=True
        )
        try:
            db.add(history)
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(e))
            
        return {"status": "cancelled", "fee": 0, "message": "初回のキャンセル料免除が適用されました"}

    cancellation_fee = 3000
    booking.status = "cancelled"
    
    history = CancellationHistoryModel(
        user_id=req.user_id,
        booking_id=booking.booking_id,
        fee_amount=cancellation_fee,
        is_exempted=False
    )
    try:
        db.add(history)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "cancelled", "fee": cancellation_fee, "message": f"キャンセル料 {cancellation_fee}円が発生しました"}

@app.get("/api/bookings")
def get_bookings(db: Session = Depends(get_db), _: bool = Depends(verify_admin)):
    bookings = db.scalars(select(BookingModel).order_by(BookingModel.created_at.desc())).all()
    return [{
        "booking_id": b.booking_id, "user_id": b.user_id, "name": b.name,
        "gender": b.gender, "age": b.age, "area": b.area, "datetime": b.preferred_datetime,
        "area_2": b.area_2, "datetime_2": b.datetime_2, "primary_type": b.primary_type,
        "status": b.status, "group_id": b.group_id,
        "created_at": b.created_at.strftime("%Y-%m-%d %H:%M") if b.created_at else None
    } for b in bookings]

@app.get("/api/matchings")
def get_matchings(db: Session = Depends(get_db), _: bool = Depends(verify_admin)):
    matched_bookings = db.scalars(select(BookingModel).where(
        BookingModel.status == "matched", BookingModel.group_id.isnot(None)
    )).all()
    
    groups_dict = defaultdict(list)
    for b in matched_bookings:
        if b.group_id:
            groups_dict[b.group_id].append({
                "booking_id": b.booking_id, "user_id": b.user_id, "name": b.name,
                "gender": b.gender, "age": b.age, "area": b.area, "datetime": b.preferred_datetime,
                "primary_type": b.primary_type
            })
    return [{"group_id": g_id, "members": members} for g_id, members in groups_dict.items()]

@app.post("/api/matchings/run")
def run_matching(match_mode: str = "AUTO", _: bool = Depends(verify_admin), db: Session = Depends(get_db)):
    pending_users = db.scalars(select(BookingModel).where(BookingModel.status == "pending")).all()
    if not pending_users:
        return {"status": "success", "created_groups": 0, "message": "対象予約がありません"}

    created_groups_count, notified_users_count = 0, 0
    used_booking_ids = set()

    def process_slots(users_list: List[BookingModel], is_second_choice: bool = False):
        nonlocal created_groups_count, notified_users_count, used_booking_ids
        slots = defaultdict(list)
        for u in users_list:
            if u.booking_id in used_booking_ids or u.status != "pending": continue
            target_area = u.area_2 if is_second_choice else u.area
            target_dt = u.datetime_2 if is_second_choice else u.preferred_datetime
            if not target_area or not target_dt: continue
            
            raw_dt = target_dt.replace('T', ' ')
            slots[(target_area, raw_dt[:13] if len(raw_dt) >= 13 else raw_dt)].append(u)

        for (area, dt_hour), pool in slots.items():
            active_pool = [u for u in pool if u.booking_id not in used_booking_ids and u.status == "pending"]
            males, females = [u for u in active_pool if u.gender == "male"], [u for u in active_pool if u.gender == "female"]
            if len(males) < 2 or len(females) < 2: continue

            possible_groups = []
            for m_pair in itertools.combinations(males, 2):
                for f_pair in itertools.combinations(females, 2):
                    candidate = list(m_pair) + list(f_pair)
                    if has_met_before(db, candidate): continue
                    score, label = calculate_hybrid_score(candidate, mode=match_mode)
                    if score > 0:
                        possible_groups.append({"score": score, "label": label, "members": candidate, "b_ids": [m.booking_id for m in candidate]})

            possible_groups.sort(key=lambda x: x["score"], reverse=True)
            
            for g in possible_groups:
                if any(b_id in used_booking_ids for b_id in g["b_ids"]): continue
                group_id = f"grp_{uuid.uuid4().hex[:8]}"
                for m in g["members"]:
                    m.status, m.group_id = "matched", group_id
                    used_booking_ids.add(m.booking_id)
                db.commit()
                created_groups_count += 1

                for m in g["members"]:
                    msg = f"🎉 【マッチング成立のお知らせ】\n\n{m.name} 様\nお食事会のマッチングが成立しました！\n■ 日時: {dt_hour}:00 頃\n■ エリア: {area}\n■ グループID: {group_id}"
                    if send_line_notification(m.user_id, msg): notified_users_count += 1

    process_slots(pending_users, is_second_choice=False)
    remaining_users = db.scalars(select(BookingModel).where(BookingModel.status == "pending")).all()
    if remaining_users: process_slots(remaining_users, is_second_choice=True)

    return {"status": "success", "created_groups": created_groups_count, "notified_users": notified_users_count}

@app.post("/api/matchings/manual")
def create_manual_matching(req: ManualMatchRequest, db: Session = Depends(get_db), _: bool = Depends(verify_admin)):
    bookings = db.scalars(select(BookingModel).where(or_(BookingModel.booking_id.in_(req.booking_ids), BookingModel.user_id.in_(req.booking_ids)))).all()
    if not bookings: raise HTTPException(status_code=404, detail="対象が見つかりません")
    new_group_id = f"grp_{uuid.uuid4().hex[:8]}"
    for b in bookings: b.status, b.group_id = "matched", new_group_id
    db.commit()
    return {"status": "success", "group_id": new_group_id}

@app.delete("/api/matchings/{group_id}")
def cancel_matching_group(group_id: str, db: Session = Depends(get_db), _: bool = Depends(verify_admin)):
    bookings = db.scalars(select(BookingModel).where(BookingModel.group_id == group_id)).all()
    if not bookings: raise HTTPException(status_code=404, detail="グループが見つかりません")
    for b in bookings: b.status, b.group_id = "pending", None
    db.commit()
    return {"status": "success", "message": "グループを解散しました"}

@app.get("/api/admin/blacklists")
def get_blacklists(db: Session = Depends(get_db), _: bool = Depends(verify_admin)):
    items = db.scalars(select(BlacklistModel).order_by(BlacklistModel.created_at.desc())).all()
    return [{"id": i.id, "user_id": i.user_id, "email": i.email, "phone_number": i.phone_number, "reason": i.reason} for i in items]

@app.post("/api/admin/blacklists", status_code=status.HTTP_201_CREATED)
def add_to_blacklist(req: BlacklistCreateRequest, db: Session = Depends(get_db), _: bool = Depends(verify_admin)):
    entry = BlacklistModel(user_id=req.user_id, email=req.email, phone_number=req.phone_number, ip_address=req.ip_address, reason=req.reason)
    if req.user_id:
        u = db.scalar(select(UserModel).where(UserModel.user_id == req.user_id))
        if u: u.is_blacklisted = True
    db.add(entry)
    db.commit()
    return {"status": "success", "id": entry.id}

@app.delete("/api/admin/blacklists/{user_or_id}")
def remove_from_blacklist(user_or_id: str, db: Session = Depends(get_db), _: bool = Depends(verify_admin)):
    stmt = select(BlacklistModel).where(or_(BlacklistModel.id == int(user_or_id), BlacklistModel.user_id == user_or_id)) if user_or_id.isdigit() else select(BlacklistModel).where(BlacklistModel.user_id == user_or_id)
    entry = db.scalar(stmt)
    if not entry: raise HTTPException(status_code=404, detail="データが見つかりません")
    if entry.user_id:
        u = db.scalar(select(UserModel).where(UserModel.user_id == entry.user_id))
        if u: u.is_blacklisted = False
    db.delete(entry)
    db.commit()
    return {"status": "success"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
