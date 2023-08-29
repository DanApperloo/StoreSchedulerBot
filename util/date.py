import datetime
import typing

from typing import TypeVar
from pytz import timezone
from tzlocal import get_localzone
from datetime import datetime as dt
from datetime import timedelta

from util.consts import DAYS_OF_THE_WEEK, DAY_SHORTCUT
from util.exception import SingletonExist, SingletonNotExist

DEFAULT_DATE_FORMAT = '%m/%d/%Y'

TCommonDate = TypeVar("TCommonDate", bound="CommonDate")


class CommonDate(datetime.date):

    __slots__ = '_format'

    def __new__(cls,
                year: typing.Union[datetime.date, int],
                month: int = None,
                day: int = None,
                *,
                default_format: str = '') -> TCommonDate:
        if isinstance(year, datetime.date):
            date = year
            self = super().__new__(cls, date.year, date.month, date.day)

            if isinstance(date, CommonDate):
                self._format = date.default_format
            else:
                self._format = default_format
            return self

        self = super().__new__(cls, year, month, day)
        self._format = default_format
        return self

    def __repr__(self) -> str:
        return str(self) + f' ({self._format})' if self._format else str(self)

    def __str__(self) -> str:
        return self.strftime(self._format) if self._format else super().__str__()

    def __copy__(self) -> TCommonDate:
        return CommonDate(self, default_format=self.default_format)

    def __deepcopy__(self, memo) -> TCommonDate:
        result = self.__copy__()
        memo[id(self)] = result
        return result

    def __add__(self, other):
        """Add a date to a timedelta."""
        if isinstance(other, timedelta):
            o = self.toordinal() + other.days
            if 0 < o <= datetime.date.max.toordinal():
                a = type(self).fromordinal(o, self.default_format)
                return a
            raise OverflowError("result out of range")
        return NotImplemented

    __radd__ = __add__

    def __sub__(self, other):
        """Subtract two dates, or a date and a timedelta."""
        if isinstance(other, timedelta):
            return self + timedelta(-other.days)
        if isinstance(other, datetime.date):
            days1 = self.toordinal()
            days2 = other.toordinal()
            return timedelta(days1 - days2)
        return NotImplemented

    @classmethod
    def fromordinal(cls, n, default_format=''):
        return cls(datetime.date.fromordinal(n), default_format=default_format)

    @property
    def default_format(self):
        return self._format

    @staticmethod
    def deserialize(raw: str):
        # Translate valid raw string Day, Shortcut and Date into a CommonDate object
        if not raw:
            raise ValueError(f'{CommonDate.__name__} requires input')

        if DateTranslator.is_valid_shortcut(raw):
            date = DateTranslator.date_from_shortcut(raw)
        elif DateTranslator.is_valid_day(raw):
            date = DateTranslator.date_from_day(raw)
        elif DateTranslator.is_valid_date(raw):
            date = CommonDate(dt.strptime(raw, DateTranslator.get_date_format()).date(),
                              default_format=DateTranslator.get_date_format())
        else:
            raise ValueError(f'{CommonDate.__name__} unable to deserialize {raw}')

        return date


class DateTranslator:
    def __new__(cls, **kwargs):
        if not hasattr(cls, 'instance') or not isinstance(getattr(cls, 'instance'), cls):
            cls.instance = super(DateTranslator, cls).__new__(cls)
        return cls.instance  # noqa

    @classmethod
    def singleton(cls):
        if not hasattr(cls, 'instance') or not isinstance(getattr(cls, 'instance'), cls):
            raise SingletonNotExist(f'{cls.__name__} is an uninitialized Singleton')
        return cls.instance  # noqa

    def __init__(self,
                 date_format: str = DEFAULT_DATE_FORMAT):

        if hasattr(self, 'initialized'):
            raise SingletonExist(f'{self.__class__.__name__} is an already initialized Singleton')

        self._date_format = date_format

        self.initialized = True

    @staticmethod
    def get_date_format() -> str:
        return DateTranslator.singleton()._date_format

    @staticmethod
    def today() -> CommonDate:
        local = get_localzone()
        pst = timezone('US/Pacific')
        local_time = dt.now(local)
        return CommonDate(local_time.astimezone(pst).date(),
                          default_format=DateTranslator.get_date_format())

    @staticmethod
    def is_valid_date(raw: str) -> bool:
        try:
            _ = dt.strptime(raw, DateTranslator.get_date_format())
            return True
        except (ValueError, TypeError):
            return False

    @staticmethod
    def is_valid_day(raw: str) -> bool:
        return raw.lower() in DAYS_OF_THE_WEEK

    @staticmethod
    def is_valid_shortcut(raw: str) -> bool:
        raw = raw.lower()
        if raw not in DAY_SHORTCUT:
            return False
        return True

    @staticmethod
    def date_from_day(day: str) -> CommonDate:
        today = DateTranslator.today()

        day_offset = DAYS_OF_THE_WEEK.index(day.lower())
        today_day_offset = DAYS_OF_THE_WEEK.index(today.strftime("%A").lower())

        if day_offset != today_day_offset:
            if day_offset < today_day_offset:
                add = day_offset + (len(DAYS_OF_THE_WEEK) - today_day_offset)
            else:
                add = day_offset - today_day_offset
        else:
            add = 0

        return CommonDate(today + timedelta(days=add),
                          default_format=DateTranslator.get_date_format())

    @staticmethod
    def date_from_shortcut(short: str) -> CommonDate:
        short = short.lower()
        today = DateTranslator.today()
        short_index = DAY_SHORTCUT.index(short)
        return CommonDate(today + timedelta(days=short_index),
                          default_format=DateTranslator.get_date_format())

    @staticmethod
    def day_from_shortcut(short: str) -> str:
        return DateTranslator.date_from_shortcut(short).strftime("%A")

    @staticmethod
    def day_from_date(date: CommonDate) -> str:
        return date.strftime('%A')
