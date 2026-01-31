from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field as PydField
from typing import List

from app.features.questions.schemas import QuestionJoinWithSignedUrlOut, QuestionUpdateIn
from app.features.comments.schemas import ThemeCommentListOut

class ThemeCreateIn(BaseModel):
    name: str = PydField(..., description="Nom du thème")
    description: Optional[str] = None
    image_id: Optional[int] = None
    category_id: Optional[int] = None
    is_public: bool = False
    is_ready: bool = False
    # admin uniquement
    valid_admin: Optional[bool] = None
    # admin uniquement : créer pour un autre owner
    owner_id: Optional[int] = None

class ThemeCreateOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    image_id: Optional[int]
    category_id: Optional[int]
    owner_id: int
    is_public: bool
    is_ready: bool
    valid_admin: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ThemeUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    image_id: Optional[int] = None
    category_id: Optional[int] = None
    is_public: Optional[bool] = None
    is_ready: Optional[bool] = None
    # admin uniquement
    valid_admin: Optional[bool] = None
    # admin uniquement
    owner_id: Optional[int] = None

class ThemeOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    image_id: Optional[int]
    category_id: Optional[int]
    owner_id: int
    is_public: bool
    is_ready: bool
    valid_admin: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class ThemeJoinOut(ThemeOut):
    category_name: Optional[str]
    category_color_hex: Optional[str]
    owner_username: str
    questions_count: int
    score_avg: Optional[float] = None
    score_count: int = 0
    plays_count: int = 0

class ThemeWithSignedUrlOut(ThemeOut):
    image_signed_url: Optional[str] = None
    image_signed_expires_in: Optional[int] = None

class ThemeJoinWithSignedUrlOut(ThemeJoinOut):
    image_signed_url: Optional[str] = None
    image_signed_expires_in: Optional[int] = None

class CategoryPublic(BaseModel):
    id: int
    name: str = PydField(..., examples=["Sécurité incendie"])
    color: str = PydField(..., examples=["#FF4D4F"])

class CategoryPublicList(BaseModel):
    items: List[CategoryPublic]

class ThemeDetailJoinWithSignedUrlOut(ThemeJoinWithSignedUrlOut):
    questions: List[QuestionJoinWithSignedUrlOut] = []


class QuestionStatOut(BaseModel):
    question_id: int
    points: int = 0
    positive_answers_count: int = 0
    negative_answers_count: int = 0
    cancelled_answers_count: int = 0


class ThemePreviewOut(ThemeJoinWithSignedUrlOut):
    question_stats: List[QuestionStatOut] = []
    comments: ThemeCommentListOut = ThemeCommentListOut(items=[], total=0)

class ThemeUpdateWithQuestionsIn(ThemeUpdateIn):
    questions: List[QuestionUpdateIn]