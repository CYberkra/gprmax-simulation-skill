import pytest

import scripts.axes as axes


def test_axis_inventory_complete():
    ids = {axis.id for axis in axes.AXES}
    assert {
        "antenna",
        "sfcw",
        "dispersion",
        "noise",
        "geometry",
        "precision",
    } <= ids


def test_axis_by_id_unknown_raises():
    with pytest.raises(KeyError):
        axes.axis_by_id("nope")


def test_antenna_option_spelling_is_hertzian():
    ids = {option.id for option in axes.axis_by_id("antenna").options}
    assert "ideal_hertzian" in ids
    assert "ideal_herzian" not in ids


def test_recommend_quick_defaults():
    rec = axes.recommend("other", "quick")
    assert rec["antenna"]["option"] == "ideal_hertzian"
    assert rec["geometry"]["option"] == "L1"
    assert rec["noise"]["option"] == "none"
    assert rec["precision"]["option"] == "fp32"


def test_recommend_publication_upgrades():
    rec = axes.recommend("other", "publication")
    assert rec["antenna"]["option"] == "physical"
    assert rec["geometry"]["option"] == "L4"
    assert rec["noise"]["option"] == "awgn"


def test_recommend_deep_scenario_upgrades_geometry():
    rec = axes.recommend("landslide", "quick")
    assert rec["geometry"]["option"] == "L3"


def test_recommend_needs_sfcw_pins_axis():
    rec = axes.recommend("other", "quick", needs_sfcw=True)
    assert rec["sfcw"]["option"] == "on"
    rec = axes.recommend("other", "quick", needs_sfcw=False)
    assert rec["sfcw"]["option"] == "off"


def test_recommend_explicit_wins():
    rec = axes.recommend("other", "quick", explicit={"antenna": "physical"})
    assert rec["antenna"]["option"] == "physical"
    assert rec["antenna"]["rationale"] == "用户明确指定，优先执行"


def test_recommend_explicit_rejects_unknown_option():
    with pytest.raises(ValueError):
        axes.recommend("other", "quick", explicit={"antenna": "not_an_option"})


def test_recommend_explicit_rejects_unknown_axis():
    with pytest.raises(KeyError):
        axes.recommend("other", "quick", explicit={"bogus": "x"})


def test_recommend_rejects_bad_inputs():
    with pytest.raises(ValueError):
        axes.recommend("unknown_scenario", "quick")
    with pytest.raises(ValueError):
        axes.recommend("other", "ultra")


def test_precision_marker_has_no_fixed_constant():
    marker = axes.axis_by_id("precision").marker
    assert marker is not None
    assert "90" not in marker
    assert "110" not in marker
    assert "1.8" not in marker


def test_markers_for_sfcw_on():
    markers = axes.markers_for({"sfcw": "on", "geometry": "L1"})
    assert any("最高频点" in marker for marker in markers)


def test_markers_for_geometry_irregular():
    markers = axes.markers_for({"geometry": "L3", "sfcw": "off"})
    assert any("相干上限" in marker for marker in markers)


def test_markers_empty_for_all_defaults():
    markers = axes.markers_for({"sfcw": "off", "geometry": "L1", "precision": "fp32"})
    assert markers == []


def test_dependencies_of():
    assert "mesh" in axes.dependencies_of("sfcw")
    assert "numerics" in axes.dependencies_of("dispersion")