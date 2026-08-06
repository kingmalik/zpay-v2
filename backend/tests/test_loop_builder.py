"""Loop Builder engine tests — pure function, no DB fixtures needed."""
import pytest

from backend.services.loop_builder import (
    ALL_WEEKDAYS,
    Leg,
    build_loops,
    day_part,
    day_signature,
    parse_time_minutes,
    requires_profile,
    student_key,
)


def _leg(ride_id, direction="IB", school="Rose Hill MS", number="01", **kw):
    defaults = dict(
        source="firstalt",
        pickup_city="Kirkland",
        dropoff_city="Redmond",
        pickup_time="08:00",
        dropoff_time="08:30",
    )
    defaults.update(kw)
    return Leg(ride_id=ride_id, direction=direction, school=school, number=number, **defaults)


# ---------------------------------------------------------------------------
# parse_time_minutes
# ---------------------------------------------------------------------------

def test_parses_24h_time():
    assert parse_time_minutes("08:30") == 510.0


def test_parses_12h_time_with_meridiem():
    assert parse_time_minutes("7:45 AM") == 465.0
    assert parse_time_minutes("2:15 PM") == 855.0
    assert parse_time_minutes("12:05 am") == 5.0
    assert parse_time_minutes("12:30 PM") == 750.0


def test_returns_none_for_junk_times():
    assert parse_time_minutes(None) is None
    assert parse_time_minutes("") is None
    assert parse_time_minutes("about 8") is None
    assert parse_time_minutes("25:00") is None


# ---------------------------------------------------------------------------
# classification helpers
# ---------------------------------------------------------------------------

def test_ib_is_am_ob_is_pm_odt_is_mid():
    assert day_part(_leg(1, direction="IB")) == "AM"
    assert day_part(_leg(2, direction="OB")) == "PM"
    assert day_part(_leg(3, direction="IB", is_odt=True)) == "MID"


def test_day_signature_defaults_to_full_week():
    assert day_signature(_leg(1)) == ALL_WEEKDAYS
    assert day_signature(_leg(2, days="  ")) == ALL_WEEKDAYS


def test_day_signature_normalizes_order_and_dupes():
    assert day_signature(_leg(1, days="F,M,M")) == ("M", "F")


def test_same_student_shares_key_across_directions():
    ib = _leg(1, direction="IB")
    ob = _leg(2, direction="OB")
    assert student_key(ib) == student_key(ob)
    assert student_key(_leg(3, number="02")) != student_key(ib)
    assert student_key(_leg(4, is_odt=True)) != student_key(ib)


def test_requires_profile_unions_true_flags():
    legs = [
        _leg(1, requires={"wheelchair": True}),
        _leg(2, requires={"booster": True, "monitor": False}),
    ]
    assert requires_profile(legs) == {"wheelchair": True, "booster": True}


# ---------------------------------------------------------------------------
# chaining
# ---------------------------------------------------------------------------

def test_opposite_corridor_rides_chain_into_one_loop():
    # Arrange: drop in Redmond 08:30, next pickup Redmond 09:15 — feasible.
    a = _leg(1, school="Rose Hill MS", number="01")
    b = _leg(2, school="Juanita HS", number="07",
             pickup_city="Redmond", dropoff_city="Kirkland",
             pickup_time="09:15", dropoff_time="09:45")
    # Act
    result = build_loops([a, b])
    # Assert
    assert len(result.loops) == 1
    assert result.loops[0].ride_ids == [1, 2]
    assert result.loops[0].slack_minutes == [25.0]  # 555 - (510 + 10 + 10)


def test_infeasible_timing_splits_into_two_loops():
    a = _leg(1)
    b = _leg(2, school="Juanita HS", number="07",
             pickup_city="Redmond", pickup_time="08:35", dropoff_time="09:05")
    result = build_loops([a, b])  # earliest feasible = 08:30+10+10 = 08:50
    assert len(result.loops) == 2


def test_slack_cap_prevents_long_idle_chains():
    a = _leg(1)
    b = _leg(2, school="Juanita HS", number="07",
             pickup_city="Redmond", pickup_time="11:00", dropoff_time="11:30")
    result = build_loops([a, b])  # slack would be ~130 min
    assert len(result.loops) == 2


def test_chain_length_cap_respected():
    legs = [
        _leg(i, school=f"School {i}", number=f"{i:02d}",
             pickup_time=f"{7 + i}:00", dropoff_time=f"{7 + i}:20",
             pickup_city="Kirkland", dropoff_city="Kirkland")
        for i in range(1, 7)
    ]
    result = build_loops(legs, max_legs=4)
    sizes = sorted(len(lp.ride_ids) for lp in result.loops)
    assert sizes == [2, 4]


def test_different_day_signatures_never_chain():
    daily = _leg(1)
    mw_only = _leg(2, school="Juanita HS", number="07", days="M,W",
                   pickup_city="Redmond", pickup_time="09:15", dropoff_time="09:45")
    result = build_loops([daily, mw_only])
    assert len(result.loops) == 2
    day_sets = {lp.days for lp in result.loops}
    assert ("M", "W") in day_sets and ALL_WEEKDAYS in day_sets


def test_requirement_flags_union_onto_loop_profile():
    a = _leg(1, requires={"wheelchair": True})
    b = _leg(2, school="Juanita HS", number="07",
             pickup_city="Redmond", dropoff_city="Kirkland",
             pickup_time="09:15", dropoff_time="09:45",
             requires={"car_seat": True})
    result = build_loops([a, b])
    assert len(result.loops) == 1
    assert result.loops[0].requires_profile == {"wheelchair": True, "car_seat": True}


def test_missing_time_or_city_goes_to_ungroupable_with_reason():
    no_time = _leg(1, pickup_time=None)
    no_city = _leg(2, pickup_city=None, dropoff_city=None)
    ok = _leg(3)
    result = build_loops([no_time, no_city, ok])
    assert [lp.ride_ids for lp in result.loops] == [[3]]
    reasons = dict(result.ungroupable)
    assert "pickup time" in reasons[1]
    assert "city" in reasons[2]


def test_tightest_fit_wins_when_two_chains_are_open():
    # Two open chains ending 08:30 (Redmond) and 08:50 (Redmond); new leg
    # picks up 09:15 in Redmond. Tightest slack = the 08:50 chain.
    a = _leg(1)  # drops 08:30 Redmond
    b = _leg(2, school="Lakeview ES", number="03",
             pickup_time="08:10", dropoff_time="08:50",
             pickup_city="Kirkland", dropoff_city="Redmond")
    c = _leg(3, school="Juanita HS", number="07",
             pickup_city="Redmond", dropoff_city="Kirkland",
             pickup_time="09:15", dropoff_time="09:45")
    result = build_loops([a, b, c])
    chains = {tuple(lp.ride_ids) for lp in result.loops}
    assert (2, 3) in chains
    assert (1,) in chains


def test_am_pm_companion_pairing_by_shared_student():
    am1 = _leg(1, direction="IB", school="Rose Hill MS", number="01")
    am2 = _leg(2, direction="IB", school="Juanita HS", number="07",
               pickup_city="Bellevue", dropoff_city="Bellevue",
               pickup_time="08:05", dropoff_time="08:30")
    pm1 = _leg(3, direction="OB", school="Rose Hill MS", number="01",
               pickup_city="Redmond", dropoff_city="Kirkland",
               pickup_time="15:30", dropoff_time="16:00")
    result = build_loops([am1, am2, pm1])
    by_ids = {tuple(lp.ride_ids): i for i, lp in enumerate(result.loops)}
    am_with_student = result.loops[by_ids[(1,)]]
    pm_loop = result.loops[by_ids[(3,)]]
    assert am_with_student.companion_index == by_ids[(3,)]
    assert pm_loop.companion_index == by_ids[(1,)]
    assert result.loops[by_ids[(2,)]].companion_index is None


def test_deterministic_output_across_runs():
    legs = [
        _leg(1),
        _leg(2, school="Juanita HS", number="07", pickup_city="Redmond",
             dropoff_city="Kirkland", pickup_time="09:15", dropoff_time="09:45"),
        _leg(3, direction="OB", school="Rose Hill MS", number="01",
             pickup_city="Redmond", dropoff_city="Kirkland",
             pickup_time="15:30", dropoff_time="16:00"),
    ]
    r1 = build_loops(list(legs))
    r2 = build_loops(list(reversed(legs)))
    assert [lp.ride_ids for lp in r1.loops] == [lp.ride_ids for lp in r2.loops]
    assert [lp.label for lp in r1.loops] == [lp.label for lp in r2.loops]


def test_injected_drive_time_function_is_used():
    a = _leg(1)
    b = _leg(2, school="Juanita HS", number="07",
             pickup_city="Redmond", pickup_time="09:15", dropoff_time="09:45")

    def slow_everywhere(_a, _b):
        return 60.0  # earliest feasible becomes 09:40 — chain must split

    result = build_loops([a, b], drive_minutes=slow_everywhere)
    assert len(result.loops) == 2


def test_day_signature_normalizes_thursday_aliases():
    # Intake parser emits "Th"; sheets may say "Thu"/"Thurs" — all must land
    # on the engine's "R" instead of silently dropping Thursday.
    assert day_signature(_leg(1, days="M,T,W,Th,F")) == ALL_WEEKDAYS
    assert day_signature(_leg(2, days="Thu")) == ("R",)
    assert day_signature(_leg(3, days="Tue,Thurs")) == ("T", "R")
