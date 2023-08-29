import re
import copy
import typing

from collections import OrderedDict

from model.schedule_config import ScheduleConfig
from util.type import *
from util.time import MeridiemTime, TimeTick, MeridiemTimeIterator
from util.date import DateTranslator, CommonDate
from util.consts import DAYS_OF_THE_WEEK

DEFAULT_ESCAPE_TOKEN = '%'


class ScheduleSlot:
    MATCHER = r'(?:-[ \t]*)?(.*):[ \t]?([^\n\t ,]+)?[ \t]?(?:(?:vs\.|,)[ \t]*([^\(\n\r]*)|[ \t]*)[ \t]?(?:\((.*)\))?[ \t]*(?:\n|$)'  # noqa
    MATCHER_FLAGS = re.MULTILINE | re.IGNORECASE

    def __init__(self,
                 time: MeridiemTime,
                 primary: str = None,
                 secondaries: typing.Union[str, list[str]] = None,
                 info: str = None,
                 *,
                 escape_token: str = DEFAULT_ESCAPE_TOKEN):
        if not time:
            raise ValueError(f'Must supply valid time to {self.__class__.__name__}')

        if not primary and secondaries:
            raise ValueError(f'Must supply primary participant if supplying secondaries')

        self.time = time

        self._participants = list()
        self.set_participants(primary, secondaries)

        if info:
            self.info = info.strip()
        else:
            self.info = None

        if escape_token:
            self.token = escape_token
        else:
            self.token = ''

    def __tokenize(self, val: str) -> str:
        return f'{self.token}{str(val)}{self.token}'

    @staticmethod
    def _detokenize(val: str, token: typing.Union[str, None]):
        if not token or len(token) > 1 or not val or len(val) < 2:
            return val

        if val[0] == token and val[-1] == token:
            return val[1:-1]

    def __str__(self) -> str:
        if self._participants:
            player_str = f' {", ".join([self.__tokenize(x) for x in self._participants])}'
        else:
            player_str = ''

        if self.info:
            info_str = f' ({self.info})'
        else:
            info_str = ''

        return f'{str(self.time)}:{player_str}{info_str}'.strip()

    def serialize(self) -> str:
        return str(self)

    @staticmethod
    def deserialize(raw: typing.Union[re.Match, str],
                    *,
                    escape_token: typing.Union[str, None] = DEFAULT_ESCAPE_TOKEN):
        if not raw:
            raise ValueError(f'Invalid data for {ScheduleSlot.__name__}')

        if isinstance(raw, str):
            match = re.match(ScheduleSlot.MATCHER, raw, flags=ScheduleSlot.MATCHER_FLAGS)
            if not match:
                raise ValueError(f'Invalid input for {ScheduleSlot.__name__}')
        else:
            match = raw

        time = MeridiemTime(match.group(1).strip())
        primary_participant = ScheduleSlot._detokenize(match.group(2), escape_token)
        secondary_participants = match.group(3)
        slot_info = match.group(4)

        if secondary_participants:
            secondary_participants = secondary_participants.split(',')
            secondary_participants = [ScheduleSlot._detokenize(x.strip(), escape_token) for x in secondary_participants]

        schedule_slot = ScheduleSlot(time,
                                     primary_participant,
                                     secondary_participants,
                                     slot_info,
                                     escape_token=escape_token)
        return schedule_slot

    def has_participant(self, participant: str) -> bool:
        return str(participant) in self._participants

    @property
    def participants(self) -> list[str]:
        return self._participants

    def set_participants(self, primary: str = None, secondaries: typing.Union[str, list[str]] = None):
        if secondaries and not primary:
            raise ValueError(f'Cannot set Secondary participants without a Primary')

        if primary:
            self._participants = [primary]
        else:
            self._participants = list()

        if is_sequence_but_not_str(secondaries):
            self._participants.extend([str(x) for x in secondaries if x])
        else:
            if secondaries:
                self._participants.extend([secondaries])

    def free(self):
        self.info = None
        self._participants = list()

    def is_free(self):
        return not self.info and not any(self.participants)


class ScheduleSlotRange:
    MATCHER = r'(\d{1,2}:\d{1,2}\w\w)[\t ]*(-[\t ]*)?(\d{1,2}:\d{1,2}\w\w)?'

    def __init__(self,
                 start_time: MeridiemTime,
                 end_time: typing.Union[MeridiemTime, None]):
        if not start_time:
            raise ValueError(f'Invalid start_time for {self.__class__.__name__}')

        if end_time is not None and end_time <= start_time:
            raise ValueError(f'{self.__class__.__name__} must be a positive range '
                             f'(Error: {str(start_time)}-{str(end_time)})')

        self._start_time = start_time
        self._end_time = end_time

    def __str__(self) -> str:
        return f'{str(self._start_time)}{"-{}".format(str(self._end_time)) if self._end_time else ""}'

    @property
    def start_time(self) -> MeridiemTime:
        return self._start_time

    @property
    def end_time(self) -> MeridiemTime:
        if self._end_time is None:
            raise AttributeError(f'Accessing end_time on indeterminate {self.__class__.__name__}')
        return self._end_time

    def is_indeterminate(self) -> bool:
        return self._end_time is None

    def qualify(self, end_time: MeridiemTime):
        if not self.is_indeterminate():
            raise RuntimeError(f'Cannot re-qualify {self.__class__.__name__}')

        if end_time <= self.start_time:
            raise ValueError(f'{self.__class__.__name__} must be a positive range '
                             f'(Error: {str(self.start_time)}-{str(end_time)})')

        self._end_time = end_time

    def serialize(self) -> str:
        return str(self)

    @staticmethod
    def deserialize(raw: typing.Union[re.Match, str],
                    *,
                    default_end: MeridiemTime = None,
                    default_interval: TimeTick = None):
        if not raw:
            raise ValueError(f'Invalid data for {ScheduleSlotRange.__name__}')

        if default_end and default_interval:
            raise ValueError(f'Cannot have default end and default interval data for {ScheduleSlotRange.__name__}')

        if isinstance(raw, str):
            match = re.match(ScheduleSlotRange.MATCHER, raw)
            if not match:
                raise ValueError(f'Invalid data for {ScheduleSlotRange.__name__}')
        else:
            match = raw

        closed_range_detect = [match.group(2), match.group(3)]
        if any(closed_range_detect) and not all(closed_range_detect):
            raise ValueError(f'Invalid seperator detected without end time: {match.group(0)}')

        start_time = MeridiemTime(match.group(1))

        try:
            end_time = MeridiemTime(match.group(3))
        except ValueError:
            if default_interval:
                end_time = copy.deepcopy(start_time)
                end_time += default_interval
            else:
                end_time = default_end

        schedule_slot_range = ScheduleSlotRange(start_time,
                                                end_time)
        return schedule_slot_range


class ScheduleTable:
    MATCHER = r'(?:\*\*[ \t]*)?Table[ \t](\d*)[ \t]\(until[ \t](\d{1,2}:\d{1,2}\w\w)\)[ \t]*\*\*((?:.|[\r\n])*?)(?:(?=\*\*)|$)'  # noqa
    MATCHER_FLAGS = re.IGNORECASE

    def __init__(self,
                 number: int,
                 timeslots: OrderedDict[str, ScheduleSlot],
                 closing: MeridiemTime):
        if number is None:
            raise ValueError(f'{self.__class__.__name__} requires a number')

        if not timeslots:
            raise ValueError(f'{self.__class__.__name__} requires TimeSlots')

        if not closing:
            raise ValueError(f'{self.__class__.__name__} requires Closing time')

        self.number = number
        self.timeslots = timeslots
        self.closing = closing

    def __str__(self) -> str:
        text = f'**Table {str(self.number)} (until {str(self.closing)})**\n'
        for timeslot in self.timeslots.values():
            text += f'- {str(timeslot)}\n'
        return text.rstrip('\n')

    def serialize(self) -> str:
        return str(self)

    @staticmethod
    def deserialize(raw: typing.Union[re.Match, str],
                    *,
                    escape_token: typing.Union[str, None] = DEFAULT_ESCAPE_TOKEN):
        if isinstance(raw, str):
            match = re.match(ScheduleTable.MATCHER, raw, flags=ScheduleTable.MATCHER_FLAGS)

        else:
            match = raw

        number = int(match.group(1).strip())
        closing = MeridiemTime(match.group(2).strip())
        body = match.group(3).strip() if match.group(3) else ''

        timeslots = OrderedDict()
        for time_match in re.finditer(
                ScheduleSlot.MATCHER,
                body,
                flags=ScheduleSlot.MATCHER_FLAGS):
            timeslot = ScheduleSlot.deserialize(time_match,
                                                escape_token=escape_token)
            timeslots[str(timeslot.time)] = timeslot

        table = ScheduleTable(number,
                              timeslots,
                              closing)
        return table

    def has_time(self, time: MeridiemTime) -> bool:
        valid_times = [str(k) for k in self.timeslots.keys()]
        valid_times.extend([str(self.closing)])
        return str(time) in valid_times

    def infer_interval(self) -> TimeTick:
        if len(self.timeslots) == 1:
            return MeridiemTime.infer_tick(list(self.timeslots.values())[0].time, self.closing)
        else:
            list_slots = list(self.timeslots.values())
            return MeridiemTime.infer_tick(list_slots[0].time, list_slots[1].time)

    def check(self, slot_range: ScheduleSlotRange, predicate) -> bool:
        result = []
        time_iterator = MeridiemTimeIterator(start_time=slot_range.start_time,
                                             end_time=slot_range.end_time,
                                             tick=self.infer_interval())

        for time in time_iterator:
            result.append(predicate(self.timeslots[str(time)]))

        return all(result)

    def exec(self, slot_range: ScheduleSlotRange, action) -> bool:
        result = []
        time_iterator = MeridiemTimeIterator(start_time=slot_range.start_time,
                                             end_time=slot_range.end_time,
                                             tick=self.infer_interval())

        for time in time_iterator:
            result.append(action(self.timeslots[str(time)]))

        return all(result)


class Schedule:
    HEADER_MATCHER = r'^###[^\n-]*-[ \t]?([^-\n]+)([\t ]*- CLOSED)?$'
    HEADER_MATCHER_FLAGS = re.MULTILINE | re.IGNORECASE

    def __init__(self,
                 date: CommonDate,
                 tables: OrderedDict[int, ScheduleTable] = None,
                 is_open: bool = True):

        if not date:
            raise ValueError(f'{self.__class__.__name__} requires a date')

        day = DateTranslator.day_from_date(date)
        if not DateTranslator.is_valid_day(day):
            raise ValueError(f"Invalid day, must be in {', '.join(DAYS_OF_THE_WEEK)}")

        self.open = is_open
        self.day = day
        self.date = date

        if not tables and self.open:
            self.tables = OrderedDict()

            # Populate Table from Config
            day_config = ScheduleConfig.get_day(day)
            for i in range(0, day_config.tables):
                table = ScheduleTable(number=i + 1,
                                      timeslots=self.generate_slots(self.day),
                                      closing=day_config.end_time)
                self.tables[table.number] = table
        else:
            self.tables = tables

    def __str__(self) -> str:
        text = f'### Schedule {self.day} - {str(self.date)}{" - CLOSED" if not self.open else ""}\n'
        if self.open:
            for table in self.tables.values():
                text += f'{str(table)}\n\n'
        return text.rstrip('\n ')

    def serialize(self) -> str:
        return str(self)

    @staticmethod
    def deserialize(raw: str,
                    *,
                    escape_token: typing.Union[str, None] = DEFAULT_ESCAPE_TOKEN):
        if not isinstance(raw, str):
            raise ValueError(f'Cannot deserialize {Schedule.__name__} from {type(raw)}')

        header_match = re.match(Schedule.HEADER_MATCHER,
                                raw,
                                flags=Schedule.HEADER_MATCHER_FLAGS)
        if not header_match:
            raise ValueError(f'Invalid {Schedule.__name__} input')

        date = CommonDate.deserialize(header_match.group(1).strip())
        is_open = False if header_match.group(2) else True
        tables = OrderedDict()

        if is_open:
            for table_match in re.finditer(
                    ScheduleTable.MATCHER,
                    raw,
                    flags=ScheduleTable.MATCHER_FLAGS):
                table = ScheduleTable.deserialize(table_match.group(0).strip(),
                                                  escape_token=escape_token)
                tables[table.number] = table

        schedule = Schedule(date=date,
                            tables=tables,
                            is_open=is_open)
        return schedule

    @staticmethod
    def generate_slots(day: str,
                       *,
                       escape_token: typing.Union[str, None] = DEFAULT_ESCAPE_TOKEN) \
            -> OrderedDict[str, ScheduleSlot]:
        day_config = ScheduleConfig.get_day(day)
        output = OrderedDict()
        for time in MeridiemTimeIterator(
                day_config.start_time,
                day_config.end_time,
                day_config.slot_duration):
            output[str(time)] = ScheduleSlot(time,
                                             escape_token=escape_token)
        return output

    def qualify_slotrange(self, timeslot_range: ScheduleSlotRange) -> ScheduleSlotRange:
        if timeslot_range.is_indeterminate():
            end_time = copy.deepcopy(timeslot_range.start_time)
            end_time += list(self.tables.values())[0].infer_interval()
            timeslot_range.qualify(end_time)

        if not self.is_slotrange_valid(timeslot_range):
            raise ValueError(f'Invalid slot range {str(timeslot_range)} for {str(self.date)}')

        return timeslot_range

    def is_slotrange_valid(self, timeslot_range: ScheduleSlotRange) -> bool:
        if not all([table.has_time(timeslot_range.start_time)
                    for table in self.tables.values()]) or \
                not all([table.has_time(timeslot_range.end_time)
                         for table in self.tables.values()]):
            return False
        return True
