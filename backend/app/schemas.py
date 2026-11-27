"""Pydantic schemas for API request and response bodies."""

from typing import Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


def _normalize_email(value: object) -> object:
    """Normalize email values before Pydantic validates them."""
    if isinstance(value, str):
        return value.strip().lower()
    return value


class RegisterRequest(BaseModel):
    """Request body for creating a new account."""

    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        """Trim whitespace and lowercase the email before validation."""
        return _normalize_email(value)


class LoginRequest(BaseModel):
    """Request body for logging in."""

    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        """Trim whitespace and lowercase the email before validation."""
        return _normalize_email(value)


class TokenResponse(BaseModel):
    """Access token returned after a successful login."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"


class UserPublic(BaseModel):
    """Public user information; never includes credentials."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr


Difficulty = Literal["Easy", "Medium", "Hard"]
QuestionCount = Literal[5, 10, 15]
OptionKey = Literal["A", "B", "C", "D"]


class _NormalizedTextModel(BaseModel):
    """Trim text values before validation so blank inputs are easy to reject."""

    @model_validator(mode="before")
    @classmethod
    def normalize_text(cls, values: object) -> object:
        """Strip surrounding whitespace from string values in quiz schemas."""
        if not isinstance(values, dict):
            return values
        return {
            key: value.strip() if isinstance(value, str) else value
            for key, value in values.items()
        }


class TopicQuizRequest(_NormalizedTextModel):
    """Request body for generating a quiz from a chosen topic."""

    topic: str = Field(min_length=1)
    difficulty: Difficulty
    question_count: QuestionCount


class UploadedQuizRequest(_NormalizedTextModel):
    """Request body for generating a quiz from uploaded study material."""

    upload_id: str = Field(min_length=1)
    difficulty: Difficulty
    question_count: QuestionCount


class _QuestionBase(_NormalizedTextModel):
    """Fields shared by every question shown to a learner."""

    model_config = ConfigDict(extra="forbid")

    position: int = Field(gt=0)
    question_text: str = Field(min_length=1)
    option_a: str = Field(min_length=1)
    option_b: str = Field(min_length=1)
    option_c: str = Field(min_length=1)
    option_d: str = Field(min_length=1)
    source_snippet: Optional[str] = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_distinct_options(self) -> "_QuestionBase":
        """Require four different answer options for every question."""
        options = (self.option_a, self.option_b, self.option_c, self.option_d)
        if len(set(options)) != len(options):
            raise ValueError("Each question must have four distinct answer options.")
        return self


class GeneratedQuizQuestion(_QuestionBase):
    """A validated question produced by the quiz generation service."""

    correct_option: OptionKey
    explanation: str = Field(min_length=1)


class QuizQuestionView(_QuestionBase):
    """A question shown while answering; it hides correct answers and explanations."""

    pass


class QuizResponse(_NormalizedTextModel):
    """A generated quiz response that a learner can answer."""

    quiz_id: str = Field(min_length=1)
    difficulty: Difficulty
    question_count: QuestionCount
    questions: list[QuizQuestionView]


class AnswerSelection(BaseModel):
    """One learner answer to a single question position."""

    position: int = Field(gt=0)
    selected_option: OptionKey


class SubmitQuizRequest(_NormalizedTextModel):
    """Request body for submitting all answers for one quiz."""

    quiz_id: str = Field(min_length=1)
    answers: list[AnswerSelection]

    @model_validator(mode="after")
    def validate_unique_positions(self) -> "SubmitQuizRequest":
        """Do not allow the same question position to be answered twice."""
        positions = [answer.position for answer in self.answers]
        if len(positions) != len(set(positions)):
            raise ValueError(
                "A quiz submission cannot contain duplicate question positions."
            )
        return self


class QuizResultItem(_QuestionBase):
    """One answered question with the correct answer and review explanation."""

    correct_option: OptionKey
    selected_option: OptionKey
    is_correct: bool
    explanation: str = Field(min_length=1)


class QuizResultResponse(_NormalizedTextModel):
    """Score and review details returned after a quiz is submitted."""

    quiz_id: str = Field(min_length=1)
    score: int = Field(ge=0)
    total_questions: QuestionCount
    percentage: float = Field(ge=0, le=100)
    results: list[QuizResultItem]

    @model_validator(mode="after")
    def validate_score_range(self) -> "QuizResultResponse":
        """Keep the score inside the valid range for this quiz."""
        if self.score > self.total_questions:
            raise ValueError("Score must be between 0 and total_questions.")
        return self
