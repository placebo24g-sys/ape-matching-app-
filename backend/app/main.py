import datetime
import uuid
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware  # ★CORS設定を追加
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, String, Integer, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# ローカルモジュールのインポート
from app.matching_algorithm import generate_matches
from app.shop_recommender import recommend_shop_and_course

# ==========================================
# 1. データベース接続設定 (SQLite / PostgreSQL)
# ==========================================
DATABASE_URL = "sqlite:///./ape_app.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ==========================================
# 2. DBモデル定義 (ape_profiles テーブル)
# ==========================================
class ApeProfileModel(Base):
    __tablename__ = "ape_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=False)
    primary_type = Column(String(20), nullable=False)
    score_chimpanzee = Column(Integer, nullable=False)
    score_bonobo = Column(Integer, nullable=False)
    score_gorilla = Column(Integer, nullable=False)
    score_orangutan = Column(Integer, nullable=False)
    extraversion_score = Column(Integer, nullable=False)
    achievement_score = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==========================================
# 3. Pydantic スキーマ定義
# ==========================================

# --- 診断結果保存用 ---
class DiagnosticResultCreate(BaseModel):
    user_id: str = Field(..., example="usr_12345")
    primary_type: str = Field(..., example="chimpanzee")
    score_chimpanzee: int = Field(..., ge=0, le=100)
    score_bonobo: int = Field(..., ge=0, le=100)
    score_gorilla: int = Field(..., ge=0, le=100)
    score_orangutan: int = Field(..., ge=0, le=100)
    extraversion_score: int = Field(..., ge=0, le=6)
    achievement_score: int = Field(..., ge=0, le=6)

# --- マッチング生成用 ---
class ApplicationMemberInput(BaseModel):
    app_id: str = Field(..., example="app_001")
    user_id: str = Field(..., example="usr_123")
    name: str = Field(..., example="田中 太郎")
    gender: str = Field(..., example="male", description="'male' または 'female'")
    primary_type: str = Field(..., example="gorilla")
    extraversion_score: int = Field(..., ge=0, le=6, example=2)
    achievement_score: int = Field(..., ge=0, le=6, example=1)

class MatchGenerateRequest(BaseModel):
    match_mode: str = Field("BALANCE", example="BALANCE", description="'BALANCE' または 'SAME_TYPE'")
    applications: List[ApplicationMemberInput]

# ==========================================
# 4. FastAPI アプリケーション初期化 ＆ CORS設定
# ==========================================
app = FastAPI(
    title="Ape Matching System API",
    description="類人猿診断結果の保存および4人マッチング＆店舗レコメンド統合API",
    version="1.0.0"
)

# ★ フロントエンド（HTML/JS）からのクロスオリジン通信を許可するミドルウェア
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 開発時はすべてのドメインからのリクエストを許可
    allow_credentials=True,
    allow_methods=["*"],  # POST, GET, OPTIONS 等の全メソッドを許可
    allow_headers=["*"],
)

# ==========================================
# 5. エンドポイント実装
# ==========================================

# --- 【機能1】診断結果の保存 API ---
@app.post("/api/ape-profiles", status_code=Status.HTTP_201_CREATED, tags=["Diagnostic"])
def create_ape_profile(data: DiagnosticResultCreate, db: Session = Depends(get_db)):
    """
    フロントエンドの診断画面から送信されたユーザーのスコア結果をDBに保存します。
    """
    try:
        new_profile = ApeProfileModel(
            user_id=data.user_id,
            primary_type=data.primary_type,
            score_chimpanzee=data.score_chimpanzee,
            score_bonobo=data.score_bonobo,
            score_gorilla=data.score_gorilla,
            score_orangutan=data.score_orangutan,
            extraversion_score=data.extraversion_score,
            achievement_score=data.achievement_score
        )
        db.add(new_profile)
        db.commit()
        db.refresh(new_profile)
        return {"status": "success", "profile_id": new_profile.id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# --- 【機能2】マッチング生成＆店舗レコメンド API ---
@app.post("/api/matches/generate", status_code=Status.HTTP_201_CREATED, tags=["Matching"])
def generate_matches_and_recommendations(payload: MatchGenerateRequest):
    """
    応募者一覧を受け取り、性別バランスを満たす4人組マッチングと最適店舗のレコメンドを一括生成します。
    """
    if not payload.applications:
        raise HTTPException(status_code=400, detail="応募者データが空です。")

    apps_dict = [app.dict() for app in payload.applications]

    try:
        # マッチング計算
        matched_groups = generate_matches(apps_dict, match_mode=payload.match_mode)
        
        response_groups = []
        for idx, group in enumerate(matched_groups, 1):
            members = group["members"]
            # 店舗レコメンド計算
            shop_proposal = recommend_shop_and_course(members)

            response_groups.append({
                "group_id": str(uuid.uuid4()),
                "match_score": group["score"],
                "members": members,
                "recommended_shop": shop_proposal["recommendation"]
            })

        return {
            "status": "success",
            "total_matched_groups": len(response_groups),
            "groups": response_groups
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Matching process error: {str(e)}")
