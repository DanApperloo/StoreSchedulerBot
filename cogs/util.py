import logging
import typing
import inspect
from collections import OrderedDict
from datetime import timedelta
from functools import partial

import discord
from discord.ext import commands
from discord import app_commands

from core.bot_core import ScheduleBot
from core.util import Channel
from model.schedule import ScheduleSlotRange, ScheduleSlot
from model.schedule_config import ScheduleConfig
from util.type import *
from util.consts import DAYS_OF_THE_WEEK
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


class DataIdTransformer(app_commands.Transformer):
    def __init__(self, prefix):
        self.prefix = prefix

    async def transform(self, interaction: discord.Interaction, value: str) -> int:
        try:
            return int(value)
        except ValueError:
            if not value.startswith(self.prefix):
                raise app_commands.TransformerError(value, self.type, self)

            try:
                return int(value[len(self.prefix):])
            except (ValueError, IndexError):
                raise app_commands.TransformerError(value, self.type, self)


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
        try:
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

            return [app_commands.Choice(name=x.capitalize(), value=x) for x in
                    sorted(values, key=lambda z: DAYS_OF_THE_WEEK.index(z.lower())) if x]

        except Exception as e:
            logging.getLogger('discord').exception(e)
            return []


class TimeCompleter:
    def __init__(self,
                 terminus: bool = False,
                 **depend: typing.Union[typing.Type[app_commands.Transformer], app_commands.Transformer]):
        self.terminus = terminus

        if depend:
            if len(depend) > 1:
                raise ValueError("Can only depend on 1 other Time variable")

            self.depend = list(depend.items())[0]
        else:
            self.depend = list()

    @staticmethod
    def process_terminus(
            ordered_dict: typing.Dict[typing.Tuple[str, MeridiemTime], typing.List[ScheduleSlot]]
    ) -> typing.Dict[typing.Tuple[str, MeridiemTime], typing.List[ScheduleSlot]]:
        # For Author-owned, we need to use the previous slots ownership when determining ownership
        #   For example, if I own 3:00pm and 5:00pm, my cancel ends at either 5:00pm-7:00pm (or to closing)
        # For Free-only, we need to use the previous slots ownership when determining ownership
        #   For example, if 3:00pm is taken, I can still reserve 1:00pm to 3:00pm
        if len(ordered_dict) == 1:
            return ordered_dict

        result = OrderedDict()
        i = iter(ordered_dict.items())
        key, prev = next(i)
        result[key] = prev

        for key, cur in i:
            result[key] = prev
            prev = cur

        return result

    def process_slots(
            self,
            interaction: discord.Interaction,
            slot_info: typing.Dict[typing.Tuple[str, MeridiemTime], typing.List[ScheduleSlot]],
            current: str = '',
    ) -> typing.Set[typing.Tuple[str, MeridiemTime]]:
        values = set()
        # Return all slots, regardless of state
        for name, value in slot_info.keys():
            if current and not name.startswith(current):
                continue

            values.add((name, value))
        return values

    @NamespaceCheck.valid(name="date", transformer=DateTransformer)
    async def auto_complete(
            self,
            interaction: discord.Interaction,
            current: str = ''
    ) -> typing.List[app_commands.Choice[str]]:
        try:
            date_obj = await DateTransformer().transform(interaction, interaction.namespace["date"])

            # Detect if we must be after a time
            after: typing.Union[MeridiemTime, None] = None
            if self.depend:
                time_transformer = self.depend[1]() if inspect.isclass(self.depend[1]) else self.depend[1]

                try:
                    after = await time_transformer.transform(interaction, interaction.namespace[self.depend[0]])
                    if not isinstance(after, MeridiemTime):
                        app_commands.TransformerError(after, time_transformer.type, time_transformer)

                except app_commands.TransformerError:
                    return []

            date = str(date_obj)
            bot: ScheduleBot = ScheduleBot.singleton()
            values = set()
            if date in bot.schedule_cache:
                schedule = bot.schedule_cache[date]
                tables = list(schedule.tables.values())
                if tables:
                    # Create a timeslot dict that indexes per table info by slot
                    slot_dict: typing.Dict[typing.Tuple[str, MeridiemTime], typing.List[ScheduleSlot]] = OrderedDict()
                    for table in tables:
                        timeslots = list(table.timeslots.values())
                        if timeslots:
                            for slot in timeslots:
                                slot_dict.setdefault((str(slot.time), slot.time), list()).append(slot)

                        if self.terminus:
                            closing_slot = table.closing_timeslot

                            if not after or closing_slot.time > after:
                                slot_dict.setdefault(
                                    (f'{str(closing_slot.time)} (Closing)', closing_slot.time),
                                    list()
                                ).append(closing_slot)

                    if self.terminus:
                        slot_dict = self.process_terminus(slot_dict)

                    if after:
                        keys = [key for key in slot_dict.keys()]
                        for key in keys:
                            if key[1] <= after:
                                del slot_dict[key]

                    values = self.process_slots(interaction, slot_dict, current)

            return [app_commands.Choice(name=x, value=str(y)) for x, y in
                    sorted(list(values), key=lambda z: z[1]) if x and y]

        except Exception as e:
            logging.getLogger('discord').exception(e)
            return []


class AuthorOnlyTimeCompleter(TimeCompleter):
    def process_slots(
            self,
            interaction: discord.Interaction,
            slot_info: typing.Dict[typing.Tuple[str, str], typing.List[ScheduleSlot]],
            current: str = ''
    ) -> typing.Set[typing.Tuple[str, str]]:
        values = set()
        # Return only times which the author owns at least 1 slot
        for key, slots in slot_info.items():
            if current and not key[0].startswith(current):
                continue

            owners = set().union(*[set(slot.participants) for slot in slots])
            if str(interaction.user.id) not in owners:
                continue

            values.add(key)
        return values


class FreeTimeCompleter(TimeCompleter):
    def process_slots(
            self,
            interaction: discord.Interaction,
            slot_info: typing.Dict[typing.Tuple[str, str], typing.List[ScheduleSlot]],
            current: str = '',
            terminus: bool = False
    ) -> typing.Set[typing.Tuple[str, str]]:
        values = set()
        # Return only times which have at least 1 free slot
        for key, slots in slot_info.items():
            if current and not key[0].startswith(current):
                continue

            if all([not slot.is_free() for slot in slots]):
                continue

            values.add(key)
        return values


class ActivityCompleter:
    @classmethod
    async def auto_complete(
            cls,
            _: discord.Interaction,
            current: str
    ) -> typing.List[app_commands.Choice[str]]:
        try:
            activities = ScheduleConfig.get_activities()

            if current:
                return [app_commands.Choice(name=x, value=x) for x in activities if x.startswith(current)]
            else:
                return [app_commands.Choice(name=x, value=x) for x in activities]

        except Exception as e:
            logging.getLogger('discord').exception(e)
            return []
