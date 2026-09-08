import pytest

from scripts.evaluate_v512_real_retrospective import aggregate, event_score


def test_missing_real_labels_keep_full_denominator():
    shard = {"ranking": [{"sheet": "S", "cell": "D1"}, {"sheet": "S", "cell": "D2"}]}
    event = {"instance_id": "e", "case_id": "c", "source_cells": "S!D2;S!D3"}
    row = event_score(shard, event)
    assert row["reciprocal_rank"] == .5
    assert row["ap_full_label_denominator"] == .25
    assert row["ap_rankable_label_denominator"] == .5
    assert row["missing_formula_labels"] == [("S", "D3")]
    assert not row["fully_rankable"]


def test_unrankable_event_gets_zero_not_silently_dropped():
    row = event_score({"ranking": []}, {"instance_id": "e", "case_id": "c", "source_cell": "S!D1"})
    result = aggregate([row])
    assert result["events"] == 1
    assert result["reciprocal_rank"] == 0
    assert result["ap_full_label_denominator"] == 0


def test_multicell_event_is_one_macro_observation():
    ranking = [{"sheet": "S", "cell": f"D{i}"} for i in range(1, 5)]
    row = event_score({"ranking": ranking}, {"instance_id": "e", "case_id": "c", "source_cells": "S!D2;S!D4"})
    assert row["fully_rankable"]
    assert row["ap_full_label_denominator"] == .5
    assert aggregate([row])["events"] == 1


def test_empty_labels_fail():
    with pytest.raises(ValueError, match="no source labels"):
        event_score({"ranking": []}, {"source_cells": ""})
