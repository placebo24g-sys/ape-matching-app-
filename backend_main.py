# main.py
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, String, Integer, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import datetime
import uuid

# --- 1. データベース接続設定 (例: SQLite / PostgreSQL) ---
DATABASE_URL = "sqlite:///./ape_app.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- 2. DBモデル定義 (ape_profiles テーブル) ---
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

# --- 3. リクエストデータのバリデーション用スキーマ ---
class DiagnosticResultCreate(BaseModel):
    user_id: str = Field(..., example="usr_12345")
    primary_type: str = Field(..., example="chimpanzee")
    score_chimpanzee: int = Field(..., ge=0, le=100)
    score_bonobo: int = Field(..., ge=0, le=100)
    score_gorilla: int = Field(..., ge=0, le=100)
    score_orangutan: int = Field(..., ge=0, le=100)
    extraversion_score: int = Field(..., ge=0, le=6)
    achievement_score: int = Field(..., ge=0, le=6)

# DBセッション取得用
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app = FastAPI(title="Ape Diagnostic API")

# --- 4. 診断結果保存エンドポイント ---
@app.post("/api/ape-profiles", status_code=201)
def create_ape_profile(data: DiagnosticResultCreate, db: Session = Depends(get_db)):
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
