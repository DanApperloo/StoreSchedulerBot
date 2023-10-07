import json
import typing

from util.time import MeridiemTime, TimeTick
from util.exception import SingletonExist, SingletonNotExist, ConfigError
from util.consts import DAYS_OF_THE_WEEK

DEFAULT_CONFIG = 'default.schedule'


class WeeklyConfig:
    def __init__(self,
                 config: dict[str, typing.Any] = None):
        if not config:
            self.enabled = False
            return

        run_day = config['run_day'].strip().lower()
        if run_day not in DAYS_OF_THE_WEEK:
            raise ValueError(f'Invalid day {run_day} in Weekly Config')

        self.enabled = True
        self.run_time: MeridiemTime = MeridiemTime(config['run_time'].strip())
        self.run_day: str = run_day
        self.verbose: bool = bool(config['verbose'])


class NightlyConfig:
    def __init__(self,
                 config: dict[str, typing.Any] = None):
        if not config:
            self.enabled = False
            return

        self.enabled = True
        self.run_time: MeridiemTime = MeridiemTime(config['run_time'].strip())
        self.open_ahead: int = int(config['open_ahead'])
        self.close_behind: int = int(config['close_behind'])
        self.clean_behind: int = int(config['clean_behind'])
        self.verbose: bool = bool(config['verbose'])


class DayConfig:
    def __init__(self,
                 config: dict[str, typing.Any] = None):
        if not config:
            raise ValueError(f'{self.__class__.__name__} cannot be initialized from {config}')

        self.tables: int = int(config['tables'])
        self.start_time: MeridiemTime = MeridiemTime(config['start_time'].strip())
        self.end_time: MeridiemTime = MeridiemTime(config['end_time'].strip())
        self.slot_duration: TimeTick = TimeTick(config['slot_duration'].strip())


class ScheduleConfig:
    def __new__(cls, **kwargs):
        if not hasattr(cls, 'instance') or not isinstance(getattr(cls, 'instance'), cls):
            cls.instance = super(ScheduleConfig, cls).__new__(cls)
        return cls.instance  # noqa

    @classmethod
    def singleton(cls):
        if not hasattr(cls, 'instance') or not isinstance(getattr(cls, 'instance'), cls):
            raise SingletonNotExist(f'{cls.__name__} is an uninitialized Singleton')
        return cls.instance  # noqa

    def __init__(self,
                 config_file: str = DEFAULT_CONFIG):

        if hasattr(self, 'initialized'):
            raise SingletonExist(f'{self.__class__.__name__} is an already initialized Singleton')

        self.__config_name = config_file
        with open(config_file, "rb") as store_file:
            self._config = json.load(store_file)

        # Required Elements will raise Exceptions
        try:
            self._validate()

            # Construct Day Configs
            self.open_days = [str(k).lower() for k in self._config['schedule']['days'].keys()]
            self.day_configs = dict()
            for day in self.open_days:
                self.day_configs[day] = DayConfig(
                    config=self._config['schedule']['days'][day]
                )

            # Construct Nightly Config - Optional
            self.nightly_config = NightlyConfig(
                config=self._config['schedule'].get('nightly', None)
            )

            # Construct Weekly Config - Optional
            self.weekly_config = WeeklyConfig(
                config=self._config['schedule'].get('weekly', None)
            )

            # Construct Activities - Optional
            self._activities = self._config['schedule'].get('activities', [])

        except (KeyError, TypeError, ValueError) as e:
            print(f'Invalid config: {self.__config_name}')
            raise ConfigError(e)

        self.initialized = True

    def _validate(self):
        _ = self._config['schedule']
        _ = self._config['schedule']['days']
        days = self._config['schedule']['days'].keys()
        for day in days:
            if day.lower() not in DAYS_OF_THE_WEEK:
                raise KeyError(f'Invalid day {day}')

    @property
    def activities(self) -> list[str]:
        return self._activities

    @staticmethod
    def get_activities() -> list[str]:
        self = ScheduleConfig.singleton()
        return self.activities

    @staticmethod
    def open_days() -> list[str]:
        self = ScheduleConfig.singleton()
        return self.open_days

    @staticmethod
    def get_day(day: str) -> DayConfig:
        self = ScheduleConfig.singleton()
        day = day.lower()
        if day not in self.open_days:
            raise ValueError(f'{day} is not a valid Day in Schedule')
        return self.day_configs[day]

    @staticmethod
    def get_nightly() -> NightlyConfig:
        self = ScheduleConfig.singleton()
        return self.nightly_config

    @staticmethod
    def get_weekly() -> WeeklyConfig:
        self = ScheduleConfig.singleton()
        return self.weekly_config
