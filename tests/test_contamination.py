"""Where a test set's name appears on a model card decides what it means."""

from bench.contamination import FLAGGED, search, strip_front_matter


def test_listed_training_data_is_flagged():
    found = search('["mozilla-foundation/common_voice_17_0"]', "", "")
    assert found["common_voice"][0] == "training" and "training" in FLAGGED


def test_card_prose_is_flagged_for_a_person_to_read():
    found = search("[]", "We fine-tuned on FLEURS Persian for three epochs.", "")
    assert found["fleurs"][0] == "text" and "text" in FLAGGED


def test_evaluation_results_alone_are_noted_not_flagged():
    found = search("[]", "", '[{"results": [{"dataset": {"name": "FLEURS", "type": "google/fleurs"}}]}]')
    assert found["fleurs"][0] == "evaluation" and "evaluation" not in FLAGGED
    assert found["flores"] is None


def test_the_yaml_header_isnt_counted_as_prose():
    body = "---\nmodel-index:\n- results: FLEURS\n---\n# A model\nTrained on our own data."
    assert "FLEURS" not in strip_front_matter(body)
