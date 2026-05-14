from schemas.common import Citation, FieldValue, Uncertainty


def test_uncertainty_enum_values():
    assert Uncertainty.CONFIRMED.value == "confirmed"
    assert Uncertainty.INFERRED.value == "inferred"
    assert Uncertainty.AMBIGUOUS.value == "ambiguous"
    assert Uncertainty.NOT_SPECIFIED.value == "not_specified"


def test_citation_minimal():
    c = Citation(page=1, quote="자동 갱신됩니다")
    assert c.page == 1
    assert c.section is None
    assert c.bbox is None
    assert c.pain_point_id is None


def test_citation_full():
    c = Citation(
        page=3,
        section="제5조",
        bbox=(100.0, 200.0, 300.0, 250.0),
        quote="해지 시 위약금이 발생합니다",
        pain_point_id="POST-01",
    )
    assert c.bbox == (100.0, 200.0, 300.0, 250.0)
    assert c.pain_point_id == "POST-01"


def test_fieldvalue_int_confirmed():
    fv = FieldValue[int](
        value=9900,
        uncertainty=Uncertainty.CONFIRMED,
        citation=Citation(page=1, quote="월 9,900원"),
    )
    assert fv.value == 9900
    assert fv.uncertainty == Uncertainty.CONFIRMED
    assert fv.citation is not None
    assert fv.citation.page == 1


def test_fieldvalue_not_specified():
    fv = FieldValue[bool](
        value=None,
        uncertainty=Uncertainty.NOT_SPECIFIED,
        citation=None,
    )
    assert fv.value is None
    assert fv.uncertainty == Uncertainty.NOT_SPECIFIED
    assert fv.citation is None
