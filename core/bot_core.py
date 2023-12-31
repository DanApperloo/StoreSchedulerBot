import asyncio
import copy
import os
import re
import typing

from functools import partial
from datetime import timedelta

import discord
from discord.ext import commands

from util.date import DateTranslator, CommonDate
from util.exception import SingletonExist, SingletonNotExist
from model.schedule import Schedule


class BoundSchedule:
    def __init__(self, message: discord.Message, shed: Schedule):
        self._bot = ScheduleBot.singleton()
        self.message = message
        self.schedule = shed

    @staticmethod
    async def create(schedule: Schedule):
        _bot = ScheduleBot.singleton()
        message = await _bot.readonly_channel.send(
            content=_bot.externalize_payload(
                str(schedule),
                _bot.ESCAPE_TOKEN
            ))
        self = BoundSchedule(message, schedule)
        _bot.modify_cache(self)
        return self

    async def update(self):
        await self.message.edit(
            content=self._bot.externalize_payload(
                str(self.schedule),
                self._bot.ESCAPE_TOKEN
            ))
        self._bot.modify_cache(self)

    async def delete(self):
        await self.message.delete()
        self._bot.modify_cache(self, remove=True)


class ScheduleBot(commands.Bot):
    ESCAPE_TOKEN = '%'
    
    def __new__(cls, **kwargs):
        if not hasattr(cls, 'instance') or not isinstance(getattr(cls, 'instance'), cls):
            cls.instance = super(ScheduleBot, cls).__new__(cls)
        return cls.instance  # noqa

    @classmethod
    def singleton(cls):
        if not hasattr(cls, 'instance') or not isinstance(getattr(cls, 'instance'), cls):
            raise SingletonNotExist(f'{cls.__name__} is an uninitialized Singleton')
        return cls.instance  # noqa

    def __init__(self, **kwargs):
        if hasattr(self, 'initialized'):
            raise SingletonExist(f'{self.__class__.__name__} is an already initialized Singleton')

        super(ScheduleBot, self).__init__(**kwargs)

        self.TOKEN = os.getenv('DISCORD_TOKEN').strip()
        self.GUILD_ID = int(os.getenv('GUILD_ID').strip())
        self.SCHEDULE_READONLY_CHANNEL_ID = int(os.getenv('SCHEDULE_READONLY_CHANNEL_ID').strip())
        self.SCHEDULE_ADMIN_CHANNEL_ID = int(os.getenv('SCHEDULE_ADMIN_CHANNEL_ID').strip())
        self.SCHEDULE_DATA_CHANNEL_ID = int(os.getenv('SCHEDULE_DATA_CHANNEL_ID').strip())
        self.SCHEDULE_REQUEST_CHANNEL_ID = int(os.getenv('SCHEDULE_REQUEST_CHANNEL_ID').strip())
        self.ADMIN_USER_IDS = [int(x) for x in os.getenv('ADMIN_USER_IDS').strip().split(',') if x]

        self.readonly_channel: typing.Union[discord.TextChannel, None] = None
        self.admin_channel: typing.Union[discord.TextChannel, None] = None
        self.data_channel: typing.Union[discord.TextChannel, None] = None
        self.request_channel: typing.Union[discord.TextChannel, None] = None
        self.admins: typing.Union[list[discord.Member], None] = []

        self._schedule_cache = dict()

        self.unpause_cogs = asyncio.Event()

        self.initialized = True

    async def translate_config(self):
        print(f'Connecting to channel {self.SCHEDULE_READONLY_CHANNEL_ID}')
        self.readonly_channel = await self.fetch_channel(self.SCHEDULE_READONLY_CHANNEL_ID)
        print(f'Connected to channel {self.readonly_channel.name}:{self.readonly_channel.id}')
        print(f'Connecting to channel {self.SCHEDULE_ADMIN_CHANNEL_ID}')
        self.admin_channel = await self.fetch_channel(self.SCHEDULE_ADMIN_CHANNEL_ID)
        print(f'Connected to channel {self.admin_channel.name}:{self.admin_channel.id}')
        print(f'Connecting to channel {self.SCHEDULE_DATA_CHANNEL_ID}')
        self.data_channel = await self.fetch_channel(self.SCHEDULE_DATA_CHANNEL_ID)
        print(f'Connected to channel {self.data_channel.name}:{self.data_channel.id}')
        print(f'Connecting to channel {self.SCHEDULE_REQUEST_CHANNEL_ID}')
        self.request_channel = await self.fetch_channel(self.SCHEDULE_REQUEST_CHANNEL_ID)
        print(f'Connected to channel {self.request_channel.name}:{self.request_channel.id}')
        for admin_id in self.ADMIN_USER_IDS:
            try:
                member = await self.guild.fetch_member(admin_id)
            except discord.NotFound:
                print(f'Could not find admin with ID {admin_id}')
                continue
            self.admins.append(member)

    @property
    def guild(self) -> discord.Guild:
        return self.guilds[0]

    @property
    def schedule_cache(self) -> dict[str, Schedule]:
        return self._schedule_cache

    async def regenerate_schedule_cache(self):
        async def _cache(_bound_schedule: BoundSchedule):
            key = str(_bound_schedule.schedule.date)
            if key not in self.schedule_cache:
                print(f'Cached schedule {_bound_schedule.schedule.day} - {str(_bound_schedule.schedule.date)}')
                self.schedule_cache[key] = _bound_schedule.schedule
            elif str(_bound_schedule.schedule) != str(self.schedule_cache[key]):
                print(f'Updated cached schedule {_bound_schedule.schedule.day} - {str(_bound_schedule.schedule.date)}')
                self.schedule_cache[key] = _bound_schedule.schedule

        await self.process_schedules(_cache)

    def modify_cache(self, bound_schedule: BoundSchedule, remove: bool = False):
        key = str(bound_schedule.schedule.date)
        if remove:
            if key in self.schedule_cache:
                del self.schedule_cache[key]
        else:
            self.schedule_cache[key] = bound_schedule.schedule

    def is_admin_user(self, _id: int) -> bool:
        return _id in self.ADMIN_USER_IDS

    @staticmethod
    def convert_mention_to_id(mention: str) -> int:
        temp = mention.replace('<', '').replace('>', '')
        return int(temp.replace("@", "").replace("!", ""))
    
    @staticmethod
    def internalize_payload(payload: str, escape_token: typing.Union[str, None]) -> str:
        # For user mentions, it is the user's ID with <@ at the start and > at the end, like this: <@86890631690977280>.
        # If they have a nickname, there will also be a ! after the @.
        return re.sub(r'<@!?(\d*)>', r'{token}\g<1>{token}'.format(token=escape_token), payload)
    
    @staticmethod
    def externalize_payload(payload: str, escape_token: typing.Union[str, None]) -> str:
        # For user mentions, it is the user's ID with <@ at the start and > at the end, like this: <@86890631690977280>.
        # If they have a nickname, there will also be a ! after the @.
        return re.sub(r'{token}(\d*){token}'.format(token=escape_token), r'<@\g<1>>', payload)

    async def find_bound_schedule(self,
                                  date: CommonDate,
                                  opened: typing.Union[bool, None]) -> typing.Union[typing.Any, None]:
        messages_iter = self.readonly_channel.history(limit=None, oldest_first=True)
        result = None

        async for message in messages_iter:
            if message.author.id == self.user.id:
                try:
                    parsed_schedule = Schedule.deserialize(
                        self.internalize_payload(message.content.strip(),
                                                 self.ESCAPE_TOKEN))
                    if (parsed_schedule.open == opened or opened is None) and \
                            parsed_schedule.date == date:
                        result = BoundSchedule(message, parsed_schedule)
                        break

                except ValueError:
                    print(f'Unable to parse message {message.id} as Schedule')
                    continue

        return result

    async def process_schedules(self, action):
        messages_iter = self.readonly_channel.history(limit=None, oldest_first=True)

        async for message in messages_iter:
            if message.author.id == self.user.id:
                try:
                    parsed_schedule = Schedule.deserialize(
                        self.internalize_payload(message.content.strip(),
                                                 self.ESCAPE_TOKEN))
                    await action(BoundSchedule(message, parsed_schedule))

                except ValueError:
                    print(f'Unable to parse message {message.id} as Schedule')
                    continue

    async def open_given(self,
                         date: CommonDate,
                         *,
                         force: bool = False,
                         state: typing.Union[bool, None] = True) -> typing.Union[BoundSchedule, None]:
        bound_schedule: BoundSchedule = await self.find_bound_schedule(date, opened=state)
        if bound_schedule:
            if bound_schedule.schedule.open:
                print(
                    f'Found Open Schedule: '
                    f'{bound_schedule.schedule.day} - {str(bound_schedule.schedule.date)}')
            else:
                print(
                    f'Found Closed Schedule: '
                    f'{bound_schedule.schedule.day} - {str(bound_schedule.schedule.date)}')

            if not force:
                return None

            bound_schedule.schedule = Schedule(date=date)
            await bound_schedule.update()

            print(f'Force updated schedule for {bound_schedule.schedule.day} - {str(bound_schedule.schedule.date)}')

        else:
            bound_schedule = await BoundSchedule.create(Schedule(date=date))
            print(f'Created new Schedule: {bound_schedule.schedule.day} - {str(bound_schedule.schedule.date)}')

        return bound_schedule

    async def open_until(self,
                         date: CommonDate,
                         *,
                         force: bool = False,
                         state: typing.Union[bool, None] = True):
        today_date = DateTranslator.today()
        date_iter = copy.deepcopy(today_date)
        end_date = date

        while date_iter <= end_date:
            await self.open_given(date_iter, force=force, state=state)
            date_iter = date_iter + timedelta(days=1)
    
    async def close_until(self, date: CommonDate):
        async def _close_until(_date: CommonDate, _bound_schedule: BoundSchedule):
            if _bound_schedule.schedule.open and _bound_schedule.schedule.date <= _date:
                _bound_schedule.schedule.open = False
                await _bound_schedule.update()
                print(f'Closed schedule message {_bound_schedule.message.id} '
                      f'for {_bound_schedule.schedule.day} - {str(_bound_schedule.schedule.date)}')

        await self.process_schedules(partial(_close_until, date))

    async def close_given(self, date: CommonDate):
        async def _close(_date: CommonDate, _bound_schedule: BoundSchedule):
            if _bound_schedule.schedule.open and _bound_schedule.schedule.date == _date:
                _bound_schedule.schedule.open = False
                await _bound_schedule.update()
                print(f'Closed schedule message {_bound_schedule.message.id} '
                      f'for {_bound_schedule.schedule.day} - {str(_bound_schedule.schedule.date)}')

        await self.process_schedules(partial(_close, date))
    
    async def clean_until(self, date: CommonDate, skipped: typing.Union[list, None] = None):
        async def _clean_until(
                _date: CommonDate,
                _open_schedules: typing.Union[list, None],
                _bound_schedule: BoundSchedule):

            if _bound_schedule.schedule.date <= _date:
                if _bound_schedule.schedule.open:
                    if _open_schedules is not None:
                        _open_schedules.append(BoundSchedule(_bound_schedule.message, _bound_schedule.schedule))
                    return

                await _bound_schedule.delete()
                print(f'Cleaned schedule message {_bound_schedule.message.id} for '
                      f'{_bound_schedule.schedule.day} - {str(_bound_schedule.schedule.date)}')

        await self.process_schedules(partial(_clean_until, date, skipped))

    async def clean_given(self, date: CommonDate) -> bool:
        open_still = False
        
        async def _clean(
                _date: CommonDate,
                _still_open: typing.Union[bool, None],
                _bound_schedule: BoundSchedule):

            if _bound_schedule.schedule.date == _date:
                if _bound_schedule.schedule.open:
                    if _still_open is not None:
                        _still_open = True
                    return

                await _bound_schedule.delete()
                print(f'Cleaned schedule message {_bound_schedule.message.id} '
                      f'for {_bound_schedule.schedule.day} - {str(_bound_schedule.schedule.date)}')

        await self.process_schedules(partial(_clean, date, open_still))
        return open_still
