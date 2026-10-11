from snap import SIM_CALLSIGNS, core, distance, load_roster, similarity, snap


def test_roster_has_sim_and_real_regs():
    roster = load_roster()
    assert set(SIM_CALLSIGNS) <= set(roster)
    assert "N38BL" in roster and "N761NY" in roster
    assert len(roster) > 20


def test_exact_snap():
    res = snap("2646X")
    assert res.snapped_to == "N2646X" and res.snap_score == 1.0 and res.ambiguous_with == []


def test_n_prefix_ignored():
    assert core("N312LM") == "312LM" and core("2646X") == "2646X"
    assert snap("N312LM").snapped_to == "N312LM"


def test_truncated_callsign_snaps():
    res = snap("312L")
    assert res.snapped_to == "N312LM" and res.snap_score >= 0.8


def test_similar_callsigns_are_ambiguous_when_garbled():
    """Scenario S4: '...six four X-ray' fits both 2646X and 2464X."""
    res = snap("64X", SIM_CALLSIGNS)
    assert res.ambiguous_with, res
    assert {res.snapped_to, *res.ambiguous_with} == {"N2646X", "N2464X"}


def test_full_similar_callsigns_not_ambiguous():
    assert snap("2464X", SIM_CALLSIGNS).ambiguous_with == []
    assert snap("2646X", SIM_CALLSIGNS).ambiguous_with == []


def test_no_match_returns_none():
    res = snap("999ZZ", SIM_CALLSIGNS)
    assert res.snapped_to is None


def test_sound_alike_substitution_is_cheaper_than_other_substitution():
    assert distance("5", "9") < distance("5", "2")
    assert similarity("2646M", "N2646N") > similarity("2646M", "N2646X")


def test_empty_input():
    assert snap(None).snapped_to is None
