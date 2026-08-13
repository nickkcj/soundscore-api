from app.schemas.review import ReviewUpdate


def test_review_update_distinguishes_missing_text_from_explicit_clear() -> None:
    unchanged = ReviewUpdate(rating=4)
    cleared = ReviewUpdate(text=None)

    assert "text" not in unchanged.model_fields_set
    assert "text" in cleared.model_fields_set
    assert cleared.text is None
