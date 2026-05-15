from enum import Enum

from pydantic import BaseModel


class PainPointStage(str, Enum):
    PRE = "pre"
    MID = "mid"
    POST = "post"


class PainPoint(BaseModel):
    id: str
    stage: PainPointStage
    label: str


PAIN_POINTS: list[PainPoint] = [
    PainPoint(id="PRE-01", stage=PainPointStage.PRE, label="약관 분량/난이도 압박"),
    PainPoint(id="PRE-02", stage=PainPointStage.PRE, label="혜택-약관 보장 범위 괴리"),
    PainPoint(id="PRE-03", stage=PainPointStage.PRE, label="무료체험 → 자동 유료 전환 미인지"),
    PainPoint(id="PRE-04", stage=PainPointStage.PRE, label="개인정보 활용 범위 불투명"),
    PainPoint(id="MID-01", stage=PainPointStage.MID, label="약관 변경 형식적 고지 (실질 인지 누락)"),
    PainPoint(id="MID-02", stage=PainPointStage.MID, label="의사표시 의제 (무응답 = 동의)"),
    PainPoint(id="POST-01", stage=PainPointStage.POST, label="위약금 미인지"),
    PainPoint(id="POST-02", stage=PainPointStage.POST, label="해지 절차 복잡성"),
    PainPoint(id="POST-03", stage=PainPointStage.POST, label="보장/혜택 청구권 미인지"),
    PainPoint(id="POST-04", stage=PainPointStage.POST, label="면책 광범위 / 손해배상 제한"),
    PainPoint(id="POST-05", stage=PainPointStage.POST, label="분쟁 절차 불투명 / 집단소송 포기"),
]

_BY_ID: dict[str, PainPoint] = {pp.id: pp for pp in PAIN_POINTS}


def get_pain_point(pp_id: str) -> PainPoint | None:
    return _BY_ID.get(pp_id)
