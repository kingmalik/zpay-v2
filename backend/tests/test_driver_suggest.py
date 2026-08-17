"""Unit tests for the pure driver-suggestion ranking engine."""
from backend.services.driver_suggest import (
    CandidateDriver,
    LoopShape,
    RideShape,
    has_schedule_conflict,
    suggest_drivers,
    suggest_for_ride,
)


def _loop(**overrides) -> LoopShape:
    base = dict(
        day_part="AM",
        days="M,T,W,R,F",
        requires_wheelchair=False,
        first_pickup_city="Kirkland",
        leg_cities=("Kirkland", "Bellevue"),
    )
    base.update(overrides)
    return LoopShape(**base)


def _driver(pid=1, name="Driver A", **overrides) -> CandidateDriver:
    base = dict(
        person_id=pid,
        name=name,
        home_address=None,
        wheelchair_vehicle=False,
        confirmed_loops=(),
    )
    base.update(overrides)
    return CandidateDriver(**base)


class TestWheelchairGate:
    def test_wheelchair_loop_excludes_non_wc_drivers(self):
        drivers = [
            _driver(1, "No Van"),
            _driver(2, "WC Van", wheelchair_vehicle=True),
        ]
        out = suggest_drivers(_loop(requires_wheelchair=True), drivers)
        assert [s.person_id for s in out] == [2]
        assert "wheelchair vehicle" in out[0].reasons[0]

    def test_regular_loop_ignores_wheelchair_capability(self):
        out = suggest_drivers(_loop(), [_driver(1, "No Van")])
        assert len(out) == 1


class TestScheduleConflict:
    def test_same_day_part_overlapping_day_conflicts(self):
        d = _driver(confirmed_loops=(("AM", "M,T"),))
        assert has_schedule_conflict(d, _loop(days="T,W"))

    def test_different_day_part_never_conflicts(self):
        d = _driver(confirmed_loops=(("PM", "M,T,W,R,F"),))
        assert not has_schedule_conflict(d, _loop(days="M,T,W,R,F"))

    def test_disjoint_days_no_conflict(self):
        d = _driver(confirmed_loops=(("AM", "F"),))
        assert not has_schedule_conflict(d, _loop(days="M,T,W,R"))

    def test_none_days_means_mon_fri(self):
        d = _driver(confirmed_loops=(("AM", None),))
        assert has_schedule_conflict(d, _loop(days="W"))

    def test_conflicting_driver_excluded_from_suggestions(self):
        drivers = [
            _driver(1, "Busy", confirmed_loops=(("AM", "M,T,W,R,F"),)),
            _driver(2, "Free"),
        ]
        out = suggest_drivers(_loop(), drivers)
        assert [s.person_id for s in out] == [2]


class TestRanking:
    def test_first_pickup_proximity_beats_leg_proximity(self):
        drivers = [
            _driver(1, "Near Dropoff", home_address="1 Main St, Bellevue WA"),
            _driver(2, "Near Pickup", home_address="2 Oak Ave, Kirkland WA"),
            _driver(3, "Far Away", home_address="3 Elm Rd, Tacoma WA"),
        ]
        out = suggest_drivers(_loop(), drivers)
        assert [s.person_id for s in out] == [2, 1, 3]
        assert any("first pickup" in r for r in out[0].reasons)

    def test_load_balance_breaks_ties(self):
        drivers = [
            _driver(1, "Loaded", confirmed_loops=(("PM", "M"), ("MID", "M"))),
            _driver(2, "Fresh"),
        ]
        out = suggest_drivers(_loop(), drivers)
        assert out[0].person_id == 2
        assert "no loops assigned yet" in out[0].reasons

    def test_top_n_cap(self):
        drivers = [_driver(i, f"D{i}") for i in range(1, 10)]
        assert len(suggest_drivers(_loop(), drivers)) == 3

    def test_no_city_data_still_returns_ranked_list(self):
        out = suggest_drivers(
            _loop(first_pickup_city=None, leg_cities=()),
            [_driver(1, "A"), _driver(2, "B")],
        )
        assert len(out) == 2

    def test_prior_route_history_boosts_and_explains(self):
        # B drove this route before; A merely exists. B should rank first
        # with a human-readable reason including the ride count.
        out = suggest_drivers(
            _loop(first_pickup_city=None, leg_cities=()),
            [_driver(1, "A"), _driver(2, "B")],
            prior_route_rides={2: 52},
        )
        assert out[0].person_id == 2
        assert any("drove this route before (52 rides)" in r for r in out[0].reasons)

    def test_proximity_outranks_pure_familiarity(self):
        # Efficiency first: near-first-pickup (3.0) beats familiarity alone (2.0).
        near = _driver(1, "Near", home_address="123 St, Kirkland, WA")
        familiar = _driver(2, "Familiar")
        out = suggest_drivers(
            _loop(first_pickup_city="Kirkland"),
            [near, familiar],
            prior_route_rides={2: 10},
        )
        assert out[0].person_id == 1


class TestSuggestForRide:
    """Single-ride mode: fairness is a hard tier, not a score weight."""

    @staticmethod
    def _ride(**overrides) -> RideShape:
        base = dict(
            day_part="AM",
            days="M,T,W,R,F",
            requires_wheelchair=False,
            pickup_city="Kirkland",
            dropoff_city="Bellevue",
        )
        base.update(overrides)
        return RideShape(**base)

    def test_fewest_rides_wins_over_proximity_and_familiarity(self):
        loaded_but_local = _driver(1, "Loaded Local", home_address="123 Main St, Kirkland WA")
        fresh = _driver(2, "Fresh Driver")
        out = suggest_for_ride(
            self._ride(), [loaded_but_local, fresh],
            assigned_ride_counts={1: 1},
            prior_route_rides={1: 10},
        )
        assert [s.person_id for s in out] == [2, 1]
        assert out[0].reasons[0] == "no rides yet"
        assert out[1].reasons[0] == "1 ride already"

    def test_proximity_breaks_ties_within_same_ride_count(self):
        far = _driver(1, "Far Driver")
        near = _driver(2, "Near Driver", home_address="9 Lake Ave, Kirkland WA")
        out = suggest_for_ride(self._ride(), [far, near], assigned_ride_counts={})
        assert out[0].person_id == 2
        assert any("lives near pickup" in r for r in out[0].reasons)

    def test_wheelchair_ride_excludes_non_wc_drivers(self):
        drivers = [_driver(1, "No Van"), _driver(2, "WC Van", wheelchair_vehicle=True)]
        out = suggest_for_ride(
            self._ride(requires_wheelchair=True), drivers, assigned_ride_counts={},
        )
        assert [s.person_id for s in out] == [2]
        assert out[0].reasons[0] == "wheelchair vehicle"

    def test_same_day_part_commitment_excludes_driver(self):
        busy = _driver(1, "Busy AM", confirmed_loops=(("AM", "M,T,W,R,F"),))
        free = _driver(2, "Free")
        out = suggest_for_ride(self._ride(), [busy, free], assigned_ride_counts={1: 1})
        assert [s.person_id for s in out] == [2]

    def test_thursday_alias_conflicts_with_canonical_r(self):
        # Intake maps Thursday -> "Th" (not "R"); the ride below is on "R".
        # Without alias normalization these never overlap and the conflict
        # is silently missed.
        busy_on_th = _driver(1, "Busy Thu", confirmed_loops=(("AM", "Th"),))
        free = _driver(2, "Free")
        out = suggest_for_ride(
            self._ride(days="R"), [busy_on_th, free], assigned_ride_counts={1: 1},
        )
        assert [s.person_id for s in out] == [2]

    def test_familiarity_breaks_ties_when_neither_lives_near(self):
        rookie = _driver(1, "Rookie")
        veteran = _driver(2, "Veteran")
        out = suggest_for_ride(
            self._ride(), [rookie, veteran],
            assigned_ride_counts={},
            prior_route_rides={2: 4},
        )
        assert out[0].person_id == 2
        assert any("drove this route before (4 rides)" in r for r in out[0].reasons)
