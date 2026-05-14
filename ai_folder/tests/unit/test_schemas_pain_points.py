from schemas.pain_points import PAIN_POINTS, PainPointStage, get_pain_point


def test_pain_point_count():
    assert len(PAIN_POINTS) == 11


def test_pain_point_ids_unique():
    ids = [pp.id for pp in PAIN_POINTS]
    assert len(ids) == len(set(ids))


def test_get_pain_point_by_id():
    pp = get_pain_point("MID-02")
    assert pp is not None
    assert pp.stage == PainPointStage.MID
    assert "의사표시 의제" in pp.label


def test_get_pain_point_unknown_id_returns_none():
    assert get_pain_point("XYZ-99") is None


def test_stages_distribution():
    by_stage = {s: 0 for s in PainPointStage}
    for pp in PAIN_POINTS:
        by_stage[pp.stage] += 1
    assert by_stage[PainPointStage.PRE] == 4
    assert by_stage[PainPointStage.MID] == 2
    assert by_stage[PainPointStage.POST] == 5
