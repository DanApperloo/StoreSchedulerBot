import typing
import inspect
from datetime import timedelta
from functools import partial

import discord
from discord.ext import commands
from discord import app_commands

from core.bot_core import ScheduleBot
from core.util import Channel
from model.schedule import ScheduleSlotRange
from util.type import *
from util.date import CommonDate, DateTranslator
from util.time import MeridiemTime


class ValidationError(Exception):
    pass


class Restriction:
    ADMIN: list[discord.Member] = []
    CHANNELS: dict[Channel, discord.TextChannel] = dict()

    @classmethod
    def set_admin(cls, admin: typing.Union[list[discord.Member], discord.Member]):
        if is_sequence_but_not_str(admin):
            cls.ADMIN = admin
        else:
            cls.ADMIN = [admin]

    @classmethod
    def set_channel(cls, channel: Channel, _id: discord.TextChannel):
        cls.CHANNELS[channel] = _id

    @classmethod
    def is_admin(cls, admin: discord.Member) -> bool:
        return admin.id in [x.id for x in cls.ADMIN]

    @classmethod
    def is_restricted_channel(cls, expected: Channel, current: discord.TextChannel) -> bool:
        """Defaults to True if channel can't be translated to ID"""
        return cls.CHANNELS[expected].id == current.id if cls.CHANNELS.get(expected, None) else True


class Slash(Restriction):
    class RestrictionError(app_commands.CheckFailure):
        pass

    @classmethod
    def admin_only(cls):
        def _predicate(interaction: discord.Interaction) -> bool:
            if not cls.is_admin(interaction.user):
                print(f'User {interaction.user.name}:{interaction.user.id} is not an Admin')
                raise Slash.RestrictionError(f'User {interaction.user.mention} is not an Admin')
            return True

        return app_commands.check(_predicate)

    @classmethod
    def restricted_channel(cls, channel: Channel):
        async def _predicate(_channel: Channel, interaction: discord.Interaction) -> bool:
            if not cls.is_restricted_channel(_channel, interaction.channel):
                raise Slash.RestrictionError(
                    f'Command is not allowed in {interaction.channel.mention}, only {cls.CHANNELS[_channel].mention}')
            return True

        return app_commands.check(partial(_predicate, channel))


class Prefix(Restriction):
    class RestrictionError(commands.CheckFailure):
        pass

    @classmethod
    def admin_only(cls):
        async def _predicate(ctx: commands.Context) -> bool:
            if not cls.is_admin(ctx.author):
                print(f'User {ctx.author.name}:{ctx.author.id} is not an Admin')
                raise Prefix.RestrictionError(f'User {ctx.author.mention} is not an Admin')
            return True

        return commands.check(_predicate)

    @classmethod
    def restricted_channel(cls, channel: Channel):
        async def _predicate(_channel: Channel, ctx: commands.Context) -> bool:
            if not cls.is_restricted_channel(_channel, ctx.channel):
                raise Prefix.RestrictionError(
                    f'Command is not allowed in {ctx.channel.mention}, only {cls.CHANNELS[_channel].mention}')
            return True

        return commands.check(partial(_predicate, channel))


class DateConverter(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str) -> CommonDate:
        try:
            date = CommonDate.deserialize(argument.strip() if argument else argument)
        except ValueError:
            raise commands.BadArgument(f'Cannot convert {argument} to Date')
        return date


class TimeConverter(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str) -> MeridiemTime:
        try:
            time = MeridiemTime(argument.strip() if argument else argument)
        except (ValueError, TypeError):
            raise commands.BadArgument(f'Cannot convert {argument} to Time')
        return time


class SlotRangeConverter(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str) -> ScheduleSlotRange:
        try:
            timeslot_range = ScheduleSlotRange.deserialize(argument.strip() if argument else argument)
        except ValueError:
            raise commands.BadArgument(f'Cannot convert {argument} to SlotRange')
        return timeslot_range


class ForceConverter(commands.Converter):
    def __init__(self, match='-f'):
        self.__match = match

    async def convert(self, ctx: commands.Context, argument: str):
        if argument and argument.strip() == self.__match:
            return True
        return False


class DateTransformer(app_commands.Transformer):
    async def transform(self, interaction: discord.Interaction, value: str) -> CommonDate:
        try:
            date = CommonDate.deserialize(value.strip() if value else value)
        except ValueError:
            raise app_commands.TransformerError(value, self.type, self)
        return date


class TimeTransformer(app_commands.Transformer):
    async def transform(self, interaction: discord.Interaction, value: str) -> MeridiemTime:
        try:
            time = MeridiemTime(value.strip() if value else value)
        except (ValueError, TypeError):
            raise app_commands.TransformerError(value, self.type, self)
        return time


class SlotRangeTransformer(app_commands.Transformer):
    async def transform(self, interaction: discord.Interaction, value: str) -> ScheduleSlotRange:
        try:
            timeslot_range = ScheduleSlotRange.deserialize(value.strip() if value else value)
        except ValueError:
            raise app_commands.TransformerError(value, self.type, self)
        return timeslot_range


class NamespaceCheck:
    @classmethod
    def valid(cls,
              name: str,
              transformer: typing.Union[typing.Type[app_commands.Transformer], app_commands.Transformer]):
        if inspect.isclass(transformer):
            t = transformer()
        else:
            t = transformer

        async def _predicate(
                _name: str,
                _transformer: app_commands.Transformer,
                interaction: discord.Interaction) -> bool:
            if _name not in interaction.namespace:
                return False
            try:
                _ = await _transformer.transform(interaction, interaction.namespace[_name])
            except app_commands.TransformerError:
                return False
            return True

        return app_commands.check(partial(_predicate, name, t))


class DateCompleter:
    @classmethod
    async def auto_complete(
            cls,
            _: discord.Interaction,
            current: str
    ) -> typing.List[app_commands.Choice[str]]:
        bot: ScheduleBot = ScheduleBot.singleton()

        def get_cached_dates() -> list[str]:
            return [x for x in bot.schedule_cache]

        def get_cached_days() -> list[str]:
            full_week = DateTranslator.today() + timedelta(days=7)
            return [DateTranslator.day_from_date(x.date).lower()
                    for x in list(bot.schedule_cache.values()) if DateTranslator.today() <= x.date < full_week]

        if not current:
            # Present all predicted open schedule days
            values = get_cached_days()
        else:
            if current[0].isdigit():
                # Recommend all predicted open schedule dates
                values = [date for date in get_cached_dates() if date.startswith(current.lower())]
            else:
                # Recommend all predicted open schedule days
                values = [day for day in get_cached_days() if day.startswith(current.lower())]

        return [app_commands.Choice(name=x.capitalize(), value=x) for x in values if x]


class TimeCompleter:
    def __init__(self,
                 **depend: typing.Union[typing.Type[app_commands.Transformer], app_commands.Transformer]):
        if depend:
            if len(depend) > 1:
                raise ValueError("Can only depend on 1 other Time variable")

            self.depend = list(depend.items())[0]
        else:
            self.depend = list()

    @NamespaceCheck.valid(name="date", transformer=DateTransformer)
    async def auto_complete(
            self,
            interaction: discord.Interaction = None,
            current: str = ''
    ) -> typing.List[app_commands.Choice[str]]:
        date = await DateTransformer().transform(interaction, interaction.namespace["date"])

        # Detect if we must be after a time
        after = None
        if self.depend:
            time_transformer = self.depend[1]() if inspect.isclass(self.depend[1]) else self.depend[1]
            try:
                after = await time_transformer.transform(interaction, interaction.namespace[self.depend[0]])
            except app_commands.TransformerError:
                return []

        key = str(date)
        bot: ScheduleBot = ScheduleBot.singleton()
        values = []
        if key in bot.schedule_cache:
            schedule = bot.schedule_cache[key]
            tables = list(schedule.tables.values())
            if tables:
                timeslots = list(tables[0].timeslots.values())
                if timeslots:
                    for slot in timeslots:
                        if not after or slot.time > after:
                            value = str(slot.time)
                            if current and not value.startswith(current):
                                continue
                            values.append(value)

        return [app_commands.Choice(name=x, value=x) for x in values if x]
