import pytest
import copy
import datetime
from util.time import TimeTick, MeridiemTime


def test_timetick_new_invalid():
    # Invalid Input - None
    with pytest.raises(ValueError):
        TimeTick(None)  # noqa

    # Invalid Input - int
    with pytest.raises(ValueError):
        TimeTick(1)  # noqa

    # Invalid Input - Non-matching String
    with pytest.raises(ValueError):
        TimeTick("Random String")

    # Invalid Input - Incorrect Sequence (too long)
    with pytest.raises(ValueError):
        TimeTick((0, 0, 0)) # noqa

    # Invalid Input - Incorrect Sequence (too short)
    with pytest.raises(ValueError):
        TimeTick([0]) # noqa

    # Invalid Types
    with pytest.raises(TypeError):
        TimeTick(["Monday", "Tuesday"]) # noqa

    # Bad Granularity
    with pytest.raises(ValueError):
        TimeTick("30t")
    with pytest.raises(ValueError):
        TimeTick("3hr10n")

    # Duplicate Granularity
    with pytest.raises(ValueError):
        TimeTick("3hr10hr")

    # Invalid Sign
    with pytest.raises(ValueError):
        TimeTick("=3hr10hr")


def test_timetick_new_valid():
    # Simple Hour
    time_tick: TimeTick = TimeTick("3hr")
    assert time_tick.hours == 3
    assert time_tick.minutes == 0
    assert time_tick.is_negative is False

    # Dual Hour and Minutes - Combined
    time_tick = TimeTick("10hr30m")
    assert time_tick.hours == 10
    assert time_tick.minutes == 30
    assert time_tick.is_negative is False

    # Dual Hour and Minutes - Separate
    time_tick = TimeTick("10hr 30m")
    assert time_tick.hours == 10
    assert time_tick.minutes == 30
    assert time_tick.is_negative is False

    # Large Minutes
    time_tick = TimeTick("125m")
    assert time_tick.hours == 2
    assert time_tick.minutes == 5
    assert time_tick.is_negative is False

    # Explicit Sign - Positive
    time_tick = TimeTick("+125m")
    assert time_tick.hours == 2
    assert time_tick.minutes == 5
    assert time_tick.is_negative is False

    # Explicit Sign - Negative
    time_tick = TimeTick("-20m")
    assert time_tick.hours == 0
    assert time_tick.minutes == 20
    assert time_tick.is_negative is True


def test_timetick_copy_valid():
    time_tick: TimeTick = TimeTick("30m")
    copy_tick: TimeTick = copy.copy(time_tick)

    assert time_tick is not copy_tick
    assert time_tick.hours == copy_tick.hours
    assert time_tick.minutes == copy_tick.minutes
    assert time_tick.is_negative == copy_tick.is_negative

    time_tick: TimeTick = TimeTick("20hr")
    copy_tick: TimeTick = copy.copy(time_tick)

    assert time_tick is not copy_tick
    assert time_tick.hours == copy_tick.hours
    assert time_tick.minutes == copy_tick.minutes
    assert time_tick.is_negative == copy_tick.is_negative

    time_tick: TimeTick = TimeTick("-2hr5m")
    copy_tick: TimeTick = copy.copy(time_tick)

    assert time_tick is not copy_tick
    assert time_tick.hours == copy_tick.hours
    assert time_tick.minutes == copy_tick.minutes
    assert time_tick.is_negative == copy_tick.is_negative


def test_meridiemtime_new_invalid():
    # Invalid Input - None
    with pytest.raises(ValueError):
        MeridiemTime(None)  # noqa

    # Invalid Input - int
    with pytest.raises(ValueError):
        MeridiemTime(1)  # noqa

    # Invalid Input - Non-matching String
    with pytest.raises(ValueError):
        MeridiemTime("Random String")

    # Invalid Input - Incorrect Sequence (too long)
    with pytest.raises(ValueError):
        MeridiemTime((0, 0, 0))  # noqa

    # Invalid Input - Incorrect Sequence (too short)
    with pytest.raises(ValueError):
        MeridiemTime([0])  # noqa

    # Invalid Types
    with pytest.raises(TypeError):
        MeridiemTime(["Monday", "Tuesday"])  # noqa

    # Invalid Input - Unsupported meridiem
    with pytest.raises(ValueError):
        MeridiemTime("2:30fm")


def test_meridiemtime_new_valid():
    # Simple Time
    meridiem_time: MeridiemTime = MeridiemTime("2:31am")
    assert meridiem_time.hour == 2
    assert meridiem_time.minute == 31
    assert meridiem_time.meridiem == "am"

    # Simple Time with space
    meridiem_time = MeridiemTime("11:01 pm")
    assert meridiem_time.hour == 11
    assert meridiem_time.minute == 1
    assert meridiem_time.meridiem == "pm"

    # Simple Time with capital meridiem - AM
    meridiem_time = MeridiemTime("11:01AM")
    assert meridiem_time.hour == 11
    assert meridiem_time.minute == 1
    assert meridiem_time.meridiem == "am"

    # Simple Time with capital meridiem - PM
    meridiem_time = MeridiemTime("11:01PM")
    assert meridiem_time.hour == 11
    assert meridiem_time.minute == 1
    assert meridiem_time.meridiem == "pm"

    # 24-hr Time - AM
    meridiem_time = MeridiemTime("2:31")
    assert meridiem_time.hour == 2
    assert meridiem_time.minute == 31
    assert meridiem_time.meridiem == "am"

    # 24-hr Time - PM
    meridiem_time = MeridiemTime("15:05")
    assert meridiem_time.hour == 3
    assert meridiem_time.minute == 5
    assert meridiem_time.meridiem == "pm"

    # Edge Time - AM
    meridiem_time = MeridiemTime("12:00am")
    assert meridiem_time.hour == 12
    assert meridiem_time.minute == 0
    assert meridiem_time.meridiem == "am"

    # Edge Time - PM
    meridiem_time = MeridiemTime("12:00pm")
    assert meridiem_time.hour == 12
    assert meridiem_time.minute == 0
    assert meridiem_time.meridiem == "pm"

    # Near-edge Time - AM
    meridiem_time = MeridiemTime("11:59am")
    assert meridiem_time.hour == 11
    assert meridiem_time.minute == 59
    assert meridiem_time.meridiem == "am"

    # Near-edge Time - PM
    meridiem_time = MeridiemTime("12:01pm")
    assert meridiem_time.hour == 12
    assert meridiem_time.minute == 1
    assert meridiem_time.meridiem == "pm"

    # Near-edge Time - PM 2
    meridiem_time = MeridiemTime("1:00pm")
    assert meridiem_time.hour == 1
    assert meridiem_time.minute == 0
    assert meridiem_time.meridiem == "pm"


def test_meridiemtime_copy_valid():
    meridiem_time: MeridiemTime = MeridiemTime("12:00pm")
    copy_time: MeridiemTime = copy.copy(meridiem_time)

    assert meridiem_time is not copy_time
    assert meridiem_time.meridiem == copy_time.meridiem
    assert meridiem_time.hour == copy_time.hour
    assert meridiem_time.minute == copy_time.minute
    assert meridiem_time.phase == copy_time.phase
    assert meridiem_time.tzinfo == copy_time.tzinfo


def test_meridiemtime_infer_tick_negative():
    # Invalid Type - Earlier Time
    earlier_time = datetime.time(hour=1)
    later_time = MeridiemTime("1:00pm")

    with pytest.raises(TypeError):
        time_tick = MeridiemTime.infer_tick(earlier_time, later_time)  # noqa

    # Invalid Type - Later Time
    earlier_time = MeridiemTime("11:00am")
    later_time = datetime.time(hour=1)

    with pytest.raises(TypeError):
        time_tick = MeridiemTime.infer_tick(earlier_time, later_time)  # noqa

    # Invalid Type - Both
    earlier_time = datetime.time(hour=1)
    later_time = datetime.time(hour=2)

    with pytest.raises(TypeError):
        time_tick = MeridiemTime.infer_tick(earlier_time, later_time)  # noqa


def test_meridiemtime_infer_tick_positive():
    # Simple Infer Tick
    earlier_time = MeridiemTime("11:00am")
    later_time = MeridiemTime("11:30am")
    time_tick = MeridiemTime.infer_tick(earlier_time, later_time)
    assert time_tick.hours == 0
    assert time_tick.minutes == 30
    assert time_tick.is_negative is False

    # Simple Infer Tick
    earlier_time = MeridiemTime("10:30am")
    later_time = MeridiemTime("11:30am")
    time_tick = MeridiemTime.infer_tick(earlier_time, later_time)
    assert time_tick.hours == 1
    assert time_tick.minutes == 0
    assert time_tick.is_negative is False

    # Crosses Meridiem
    earlier_time = MeridiemTime("11:00am")
    later_time = MeridiemTime("1:00pm")
    time_tick = MeridiemTime.infer_tick(earlier_time, later_time)
    assert time_tick.hours == 2
    assert time_tick.minutes == 0
    assert time_tick.is_negative is False

    # Crosses Day
    earlier_time = MeridiemTime("12:00am", phase=0)
    later_time = MeridiemTime("12:00am", phase=1)
    time_tick = MeridiemTime.infer_tick(earlier_time, later_time)
    assert time_tick.days == 1
    assert time_tick.hours == 0
    assert time_tick.minutes == 0
    assert time_tick.is_negative is False

    # Edge - To PM
    earlier_time = MeridiemTime("11:00am")
    later_time = MeridiemTime("12:00pm")
    time_tick = MeridiemTime.infer_tick(earlier_time, later_time)
    assert time_tick.hours == 1
    assert time_tick.minutes == 0
    assert time_tick.is_negative is False

    # Edge - To AM
    earlier_time = MeridiemTime("11:50pm", phase=0)
    later_time = MeridiemTime("12:00am", phase=1)
    time_tick = MeridiemTime.infer_tick(earlier_time, later_time)
    assert time_tick.hours == 0
    assert time_tick.minutes == 10
    assert time_tick.is_negative is False

    # Negative Tick
    earlier_time = MeridiemTime("11:00am")
    later_time = MeridiemTime("1:00pm")
    time_tick = MeridiemTime.infer_tick(later_time, earlier_time)
    assert time_tick.hours == 2
    assert time_tick.minutes == 0
    assert time_tick.is_negative is True

    # Negative Tick - Large
    earlier_time = MeridiemTime("12:00am", phase=0)
    later_time = MeridiemTime("11:50pm", phase=0)
    time_tick = MeridiemTime.infer_tick(later_time, earlier_time)
    assert time_tick.hours == 23
    assert time_tick.minutes == 50
    assert time_tick.is_negative is True

    # Negative Tick - Day
    earlier_time = MeridiemTime("12:00am", phase=-1)
    later_time = MeridiemTime("12:00am", phase=0)
    time_tick = MeridiemTime.infer_tick(later_time, earlier_time)
    assert time_tick.days == 1
    assert time_tick.hours == 0
    assert time_tick.minutes == 0
    assert time_tick.is_negative is True


def test_meridiemtime_add():
    # Simple Add
    start_time: MeridiemTime = MeridiemTime("11:00am", phase=0)
    tick: TimeTick = TimeTick("30m")
    end_time: MeridiemTime = start_time + tick
    assert end_time.hour == 11
    assert end_time.minute == 30
    assert end_time.meridiem == 'am'
    assert end_time.phase == 0

    # AM - PM Roll-over
    end_time = end_time + tick
    assert end_time.hour == 12
    assert end_time.minute == 0
    assert end_time.meridiem == 'pm'
    assert end_time.phase == 0

    # PM - AM Roll-over
    start_time = MeridiemTime("11:00pm", phase=0)
    tick = TimeTick("1hr")
    end_time = start_time + tick
    assert end_time.hour == 12
    assert end_time.minute == 00
    assert end_time.meridiem == 'am'
    assert end_time.phase == 1

    # Adding a negative
    start_time = MeridiemTime("11:00pm", phase=0)
    tick = TimeTick("-1hr")
    end_time = start_time + tick
    assert end_time.hour == 10
    assert end_time.minute == 00
    assert end_time.meridiem == 'pm'
    assert end_time.phase == 0


def test_meridiemtime_sub():
    # Simple Sub
    start_time: MeridiemTime = MeridiemTime("12:30am", phase=0)
    tick: TimeTick = TimeTick("30m")
    end_time: MeridiemTime = start_time - tick
    assert end_time.hour == 12
    assert end_time.minute == 0
    assert end_time.meridiem == 'am'
    assert end_time.phase == 0

    # AM - PM Roll-over
    end_time = end_time - tick
    assert end_time.hour == 11
    assert end_time.minute == 30
    assert end_time.meridiem == 'pm'
    assert end_time.phase == -1

    # PM - AM Roll-over
    start_time = MeridiemTime("1:00pm", phase=0)
    tick = TimeTick("1hr30m")
    end_time = start_time - tick
    assert end_time.hour == 11
    assert end_time.minute == 30
    assert end_time.meridiem == 'am'
    assert end_time.phase == 0

    # Subtracting a negative
    start_time = MeridiemTime("11:00pm", phase=0)
    tick = TimeTick("-1hr")
    end_time = start_time - tick
    assert end_time.hour == 12
    assert end_time.minute == 00
    assert end_time.meridiem == 'am'
    assert end_time.phase == 1
