import re
import copy
import typing

from typing import TypeVar
from datetime import timedelta, time

from util.type import is_not_numerical, is_sequence_but_not_str


TTimeTick = TypeVar("TTimeTick", bound="TimeTick")


class TimeTick(timedelta):
    MATCHER = r'([-+])?(\d+)([a-z|A-Z]+)\s*(?:(\d+)([a-z|A-Z]+))?'

    __GRANULARITY = ['hr', 'm']
    __ROLL_TRIGGER = 60

    def __new__(cls,
                duration: typing.Union[re.Match, str, timedelta]
                ) -> TTimeTick:
        """

        :param duration:
        """
        if isinstance(duration, timedelta):
            self = super().__new__(cls,
                                   days=duration.days,
                                   seconds=duration.seconds,
                                   microseconds=duration.microseconds)
            return self

        if isinstance(duration, str):
            duration = re.match(TimeTick.MATCHER, duration)

        if not isinstance(duration, re.Match):
            raise ValueError(f'Cannot create {cls.__name__} from {type(duration)}:{duration}')

        params = dict()

        if duration.group(1) and duration.group(1) == '-':
            negative = True
        else:
            negative = False

        gran = duration.group(3).strip().lower()
        if gran not in cls.__GRANULARITY:
            raise ValueError(f'Unsupported granularity {gran}')
        params[gran] = int(duration.group(2).strip())

        try:
            gran = duration.group(5).strip().lower()
            if gran:
                if gran not in cls.__GRANULARITY:
                    raise ValueError(f'Unsupported granularity {gran}')
                if gran in params:
                    raise ValueError(f'Duplicate granularity {gran}')
                params[gran] = int(duration.group(4).strip())

        except AttributeError:
            pass

        minutes = params.get(cls.__GRANULARITY[1], 0)
        hours, minutes = divmod(minutes, cls.__ROLL_TRIGGER)
        hours += params.get(cls.__GRANULARITY[0], 0)

        self = super().__new__(cls,
                               hours=-hours if negative else hours,
                               minutes=-minutes if negative else minutes)
        return self

    def __copy__(self) -> TTimeTick:
        return TimeTick(self)

    def __deepcopy__(self, memo) -> TTimeTick:
        result = self.__copy__()
        memo[id(self)] = result
        return result

    @property
    def scalar_seconds(self) -> int:
        """

        :return: 0 - 59
        """
        return abs(self).seconds % 60

    @property
    def scalar_minutes(self) -> int:
        """

        :return: 0 - 59
        """
        return (abs(self).seconds // 60) % 60

    @property
    def scalar_hours(self) -> int:
        """

        :return: 0 - 23
        """
        return ((abs(self).seconds // 60) // 60) % 24

    @property
    def scalar_days(self) -> int:
        """

        :return: 0 - 23
        """
        return abs(self).days

    @property
    def is_negative(self) -> bool:
        return self.days < 0

    def __neg__(self) -> TTimeTick:
        return type(self)(super().__neg__())

    def as_scalar(self) -> float:
        total = abs(self).total_seconds()
        sign = -1 if self.is_negative else 1
        return total * sign

    def __int__(self) -> int:
        return int(self.as_scalar())

    def __float__(self) -> float:
        return self.as_scalar()

    def __repr__(self) -> str:
        return f'{"-" if self.is_negative else ""}' + \
               f'{"{}hr".format(self.scalar_hours) if self.scalar_hours else ""}' + \
               f'{self.scalar_minutes:02}m'


TMeridiemTime = TypeVar("TMeridiemTime", bound="MeridiemTime")


class MeridiemTime(time):
    MATCHER = r'(\d{1,2}):(\d{1,2})\s*([a-z|A-Z][a-z|A-Z])?'

    __MERIDIEM = ["am", "pm"]
    __OFFSET_MAX = [12, 59, 1]

    def __new__(cls,
                meridiem_time: typing.Union[re.Match, str, time, tuple[int, int]],
                tzinfo=None,
                *,
                phase: int = 0) -> TMeridiemTime:
        if is_sequence_but_not_str(meridiem_time) and len(meridiem_time) == 2:
            if is_not_numerical(meridiem_time[0]):
                raise TypeError(f'Invalid input type in sequence[0]={type(meridiem_time[0])}')
            if is_not_numerical(meridiem_time[1]):
                raise TypeError(f'Invalid input type in sequence[1]={type(meridiem_time[1])}')

            self = super().__new__(cls,
                                   hour=meridiem_time[0],
                                   minute=meridiem_time[1],
                                   tzinfo=tzinfo)
            self._phase = phase
            return self

        if isinstance(meridiem_time, str):
            meridiem_time = re.match(cls.MATCHER, meridiem_time)

        if not isinstance(meridiem_time, re.Match):
            raise ValueError(f'Cannot create {cls.__name__} from {type(meridiem_time)}:{meridiem_time}')

        m = int(meridiem_time.group(2).strip())
        h = int(meridiem_time.group(1).strip())

        try:
            meridiem = meridiem_time.group(3).strip().lower()
            if meridiem not in cls.__MERIDIEM:
                raise ValueError(f'Unsupported meridiem {meridiem}')

            # Convert hour to 24hr clock
            if h != 12:
                h += cls.__MERIDIEM.index(meridiem) * 12
            else:
                if cls.__MERIDIEM.index(meridiem) == 0:
                    h = 0

        except AttributeError:
            # No meridiem, therefore must be a 24-hour input
            pass

        self = super().__new__(cls,
                               hour=h,
                               minute=m,
                               tzinfo=tzinfo)
        self._phase = phase
        return self

    def __copy__(self) -> TMeridiemTime:
        return MeridiemTime(str(self), tzinfo=self.tzinfo, phase=self.phase)

    def __deepcopy__(self, memo) -> TMeridiemTime:
        result = self.__copy__()
        memo[id(self)] = result
        return result

    def __hash__(self) -> int:
        return hash((self._phase, self.hour, self.minute, self.meridiem, self.tzinfo))

    @property
    def hour(self) -> int:
        h = super().hour  # Limited to range 0-23
        if h == 0:
            h = 12
        else:
            if h > 12:
                h -= 12
        return h

    @property
    def minute(self) -> int:
        return super().minute  # Limited to 0-59

    @property
    def meridiem(self) -> str:
        return self.__MERIDIEM[int(super().hour // 12)]

    @property
    def phase(self) -> int:
        return self._phase

    def __eq__(self, other) -> bool:
        if self._phase == other._phase:
            return super().__eq__(other)
        return False

    def __repr__(self) -> str:
        return f'{self.hour}:{self.minute:02}{self.meridiem}'
    
    __str__ = __repr__
    
    def __le__(self, other) -> bool:
        if self._phase == other._phase:
            return super().__le__(other)
        else:
            return self._phase <= other._phase

    def __lt__(self, other) -> bool:
        if self._phase == other._phase:
            return super().__lt__(other)
        else:
            return self._phase < other._phase

    def __gt__(self, other) -> bool:
        if self._phase == other._phase:
            return super().__gt__(other)
        else:
            return self._phase > other._phase

    def __ge__(self, other) -> bool:
        if self._phase == other._phase:
            return super().__gt__(other)
        else:
            return self._phase >= other._phase

    def __add_tick(self, tick: TimeTick) -> TMeridiemTime:
        roll, minute = divmod(super().minute + tick.scalar_minutes, 60)
        hour = super().hour + roll
        roll, hour = divmod(hour + tick.scalar_hours, 24)
        phase = self._phase + roll

        return MeridiemTime(
            (hour, minute),
            tzinfo=self.tzinfo,
            phase=phase)

    def __sub_tick(self, tick: TimeTick) -> TMeridiemTime:
        phase = self._phase
        hour = super().hour - tick.scalar_hours
        minute = super().minute - tick.scalar_minutes

        if minute < 0:
            roll_sub, minute = divmod(minute, 60)  # noqa
            hour += roll_sub  # Negative returned from divmod

        if hour < 0:
            roll_sub, hour = divmod(hour, 24)  # noqa
            phase += roll_sub  # Negative returned from divmod

        assert hour >= 0
        assert minute >= 0

        return MeridiemTime(
            (hour, minute),
            tzinfo=self.tzinfo,
            phase=phase)

    def __sub_time(self, other: TMeridiemTime) -> TimeTick:
        t1 = self
        t2 = other

        t1_p = t1.phase
        t2_p = t2.phase

        if t1_p < 0 or t2_p < 0:
            phase_shift = abs(min(t1_p, t2_p))
            t1_p += phase_shift
            t2_p += phase_shift

        # Use 24hr clock for math simplicity
        t1_h = super(MeridiemTime, t1).hour + (t1.phase * 24)
        t2_h = super(MeridiemTime, t2).hour + (t2.phase * 24)

        t1_m = t1.minute + (t1_h * 60)
        t2_m = t2.minute + (t2_h * 60)

        return TimeTick(f'{t1_m - t2_m}m')

    def __add__(self, other: typing.Any) -> TMeridiemTime:
        if isinstance(other, TimeTick):
            tick: TimeTick = other
            if tick.is_negative:
                return self.__sub_tick(tick)
            else:
                return self.__add_tick(tick)

        raise NotImplementedError

    def __sub__(self, other: typing.Any) -> typing.Union[TMeridiemTime, TimeTick]:
        if isinstance(other, TimeTick):
            tick: TimeTick = other

            if tick.is_negative:
                return self.__add_tick(tick)
            else:
                return self.__sub_tick(tick)

        if isinstance(other, MeridiemTime):
            return self.__sub_time(other)

        raise NotImplementedError

    @staticmethod
    def infer_tick(earlier_time: TMeridiemTime, later_time: TMeridiemTime) -> TimeTick:
        if not isinstance(earlier_time, MeridiemTime):
            raise TypeError(f'Cannot infer tick from {earlier_time.__class__.__name__}')

        if not isinstance(later_time, MeridiemTime):
            raise TypeError(f'Cannot infer tick from {later_time.__class__.__name__}')

        return later_time - earlier_time


class MeridiemTimeIterator:
    def __init__(self, start_time: MeridiemTime, end_time: MeridiemTime, tick: TimeTick):
        self._start = start_time
        self._end = end_time
        self._tick = tick
        self._current = None

    def __iter__(self):
        return self

    def __next__(self) -> MeridiemTime:
        if not self._current:
            self._current = copy.copy(self._start)

        now = copy.copy(self._current)
        self._current += self._tick

        if self._current <= self._end:
            return now
        else:
            raise StopIteration
