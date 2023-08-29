import pytest
from freezegun import freeze_time

from test.fixture import *

from util.time import MeridiemTime, TimeTick
from model.schedule import ScheduleSlot, ScheduleSlotRange, ScheduleTable, Schedule


def test_scheduleslot_basic(default_scheduleconfig, default_datetranslator, destroy_singletons):
    valid_empty = \
        "11:00am: "

    x = ScheduleSlot.deserialize(valid_empty)
    assert str(x) == "11:00am:"
    assert not x.has_participant("test_player_a")
    assert x.is_free()

    valid_single_allocation = \
        "1:30pm: %test_player_a%"

    x = ScheduleSlot.deserialize(valid_single_allocation)
    assert str(x) == "1:30pm: %test_player_a%"
    assert x.has_participant("test_player_a")
    assert not x.has_participant("test_player_b")
    assert not x.is_free()

    valid_game_allocation = \
        "1:30pm: (Game A)"

    x = ScheduleSlot.deserialize(valid_game_allocation)
    assert str(x) == "1:30pm: (Game A)"
    assert x.info == "Game A"
    assert not x.has_participant("test_player_a")
    assert not x.is_free()

    valid_double_allocation = \
        "9:00am: test_player_a vs. test_player_b"

    x = ScheduleSlot.deserialize(valid_double_allocation, escape_token=None)
    assert str(x) == "9:00am: test_player_a, test_player_b"
    assert x.has_participant("test_player_a")
    assert x.has_participant("test_player_b")
    assert not x.is_free()

    valid_multi_allocation = \
        "9:00am: %test_player_a%, %test_player_b%, %test_player_c%"

    x = ScheduleSlot.deserialize(valid_multi_allocation, escape_token=None)
    assert str(x) == "9:00am: %test_player_a%, %test_player_b%, %test_player_c%"
    assert x.has_participant("%test_player_a%")
    assert x.has_participant("%test_player_b%")
    assert x.has_participant("%test_player_c%")
    assert not x.is_free()

    valid_multi_allocation_with_info = \
        "9:00am: %test_player_a%, %test_player_b%, %test_player_c% (Game A)"

    x = ScheduleSlot.deserialize(valid_multi_allocation_with_info)
    assert str(x) == "9:00am: %test_player_a%, %test_player_b%, %test_player_c% (Game A)"
    assert x.has_participant("test_player_a")
    assert x.has_participant("test_player_b")
    assert x.has_participant("test_player_c")
    assert x.info == "Game A"
    assert not x.is_free()

    x.free()
    assert str(x) == "9:00am:"
    assert x.is_free()
    assert not x.info
    assert not x.participants

    invalid_bad_second_player = \
        "11:00am: player_a against player_b"

    with pytest.raises(ValueError):
        ScheduleSlot.deserialize(invalid_bad_second_player)

    valid_time = MeridiemTime("12:00pm")
    x = ScheduleSlot(valid_time,
                     "player_a",
                     escape_token='$')
    assert str(x) == "12:00pm: $player_a$"
    assert x.has_participant("player_a")
    assert not x.is_free()


def test_scheduleslotrange_basic(default_scheduleconfig, default_datetranslator, destroy_singletons):
    valid_range = "11:00am - 3:00pm"

    x = ScheduleSlotRange.deserialize(valid_range)
    assert str(x.start_time) == "11:00am"
    assert str(x.end_time) == "3:00pm"
    assert str(x) == "11:00am-3:00pm"
    assert not x.is_indeterminate()

    valid_range = "11:00am-3:00pm"

    x = ScheduleSlotRange.deserialize(valid_range)
    assert str(x.start_time) == "11:00am"
    assert str(x.end_time) == "3:00pm"
    assert str(x) == "11:00am-3:00pm"
    assert not x.is_indeterminate()

    no_end = "2:00am"

    x = ScheduleSlotRange.deserialize(no_end, default_end=MeridiemTime("6:00am"))
    assert str(x.start_time) == "2:00am"
    assert str(x.end_time) == "6:00am"
    assert str(x) == "2:00am-6:00am"
    assert not x.is_indeterminate()

    x = ScheduleSlotRange.deserialize(no_end, default_interval=TimeTick("2hr"))
    assert str(x.start_time) == "2:00am"
    assert str(x.end_time) == "4:00am"
    assert str(x) == "2:00am-4:00am"
    assert not x.is_indeterminate()

    x = ScheduleSlotRange.deserialize(no_end)
    assert str(x.start_time) == "2:00am"
    assert str(x) == "2:00am"
    assert x.is_indeterminate()

    bad_range_with_sep = "11:00am-badinput"

    with pytest.raises(ValueError):
        ScheduleSlotRange.deserialize(bad_range_with_sep)

    bad_range_no_sep = "11:00am3:00pm"

    with pytest.raises(ValueError):
        ScheduleSlotRange.deserialize(bad_range_no_sep)

    with pytest.raises(ValueError):
        ScheduleSlotRange(start_time=MeridiemTime("2:00pm"),
                          end_time=MeridiemTime("1:00pm"))


def test_scheduletable_basic(default_scheduleconfig, default_datetranslator, destroy_singletons):
    valid_table = \
        "**Table 1 (until 6:00pm)**\n" \
        "- 1:00pm: %player_a% (Game A)\n" \
        "- 3:00pm: %player_b%, %player_c%\n"

    a = ScheduleTable.deserialize(valid_table)
    assert a.number == 1
    assert str(a.closing) == "6:00pm"
    assert a.timeslots["1:00pm"].info == "Game A"
    assert a.timeslots["1:00pm"].has_participant("player_a")
    assert not a.timeslots["1:00pm"].has_participant("player_b")
    assert not a.timeslots["3:00pm"].info
    assert not a.timeslots["3:00pm"].has_participant("player_a")
    assert a.timeslots["3:00pm"].has_participant("player_b")
    assert a.timeslots["3:00pm"].has_participant("player_c")
    assert str(a) == valid_table.strip()
    assert a.infer_interval() == TimeTick("2hr")


@freeze_time("2023-09-24 12:21:34")
def test_schedule_basic(default_scheduleconfig, default_datetranslator, destroy_singletons):
    valid_schedule_open = \
        "### Schedule Sunday - 09/24/2023\n" \
        "**Table 1 (until 6:00pm)**\n" \
        "- 1:00pm: %player_a% (Game A)\n" \
        "- 3:00pm: %player_b%, %player_c%\n\n" \
        "**Table 2 (until 6:00pm)**\n" \
        "- 1:00pm: %player_d% (Game B)\n" \
        "- 3:00pm:\n"

    a = Schedule.deserialize(valid_schedule_open)
    assert a.open
    assert str(a.date) == "09/24/2023"
    assert a.day == "Sunday"
    assert a.tables[1].number == 1
    assert str(a.tables[1].closing) == "6:00pm"
    assert a.tables[1].timeslots["1:00pm"].info == "Game A"
    assert a.tables[1].timeslots["1:00pm"].has_participant("player_a")
    assert not a.tables[1].timeslots["1:00pm"].has_participant("player_b")
    assert not a.tables[1].timeslots["3:00pm"].info
    assert not a.tables[1].timeslots["3:00pm"].has_participant("player_a")
    assert a.tables[1].timeslots["3:00pm"].has_participant("player_b")
    assert a.tables[1].timeslots["3:00pm"].has_participant("player_c")
    assert a.tables[2].number == 2
    assert a.tables[2].timeslots["1:00pm"].info == "Game B"
    assert a.tables[2].timeslots["1:00pm"].has_participant("player_d")
    assert not a.tables[2].timeslots["3:00pm"].info
    assert not a.tables[2].timeslots["3:00pm"].participants
    assert str(a) == valid_schedule_open.strip()

    valid_schedule_closed = \
        "### Schedule Saturday - 09/23/2023 - CLOSED\n"

    a = Schedule.deserialize(valid_schedule_closed)
    assert not a.open
    assert str(a.date) == "09/23/2023"
    assert a.day == "Saturday"
    assert not a.tables
    assert str(a) == valid_schedule_closed.strip()
