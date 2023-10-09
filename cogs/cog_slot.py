import json
import datetime
import logging
import re
import typing
from functools import partial

from pytz import timezone

import discord
from discord.ext import commands, tasks
from discord import app_commands

from core.bot_core import ScheduleBot
from core.util import (
    Channel,
    timeslot_is_free,
    timeslot_mark_as_free,
    timeslot_is_owned_by_author,
    timeslot_mark_as_owned
)
from cogs.util import (
    Slash,
    Prefix,
    ValidationError,
    DateConverter,
    DateTransformer,
    TimeTransformer,
    SlotRangeTransformer,
    DataIdTransformer,
    DateCompleter,
    TimeCompleter,
    ActivityCompleter,
    FreeTimeCompleter,
    AuthorOnlyTimeCompleter,
    FuzzySlotRangeConverter)
from model.schedule import ScheduleSlotRange
from model.schedule_config import ScheduleConfig
from util.date import DateTranslator, CommonDate
from util.time import MeridiemTime


@app_commands.guild_only()
class SlotManager(commands.Cog):
    def __init__(self, bot: ScheduleBot):
        self.bot: ScheduleBot = bot
        self.store_config: ScheduleConfig = ScheduleConfig.singleton()

        if self.store_config.weekly_config.enabled:
            trigger_time = self.store_config.weekly_config.run_time
            weekly_time = datetime.datetime.now(timezone('US/Pacific'))
            weekly_time = weekly_time.replace(
                hour=trigger_time.hour,
                minute=trigger_time.minute,
                second=0,
                microsecond=0)
            weekly_time = weekly_time.astimezone(timezone('UTC')).timetz()

            self.weekly_task.change_interval(time=weekly_time)
            self.weekly_task.start()

        # Context Menus must be handled manually
        self.accept_ctx_menu = app_commands.ContextMenu(
            name='Accept',
            callback=self.context_command_accept,
            guild_ids=[self.bot.GUILD_ID]
        )
        self.accept_ctx_menu.error(self.error_slash_command)
        self.bot.tree.add_command(self.accept_ctx_menu)

    def cog_unload(self) -> None:
        self.weekly_task.cancel()
        # Context Menus must be handled manually
        self.bot.tree.remove_command(
            self.accept_ctx_menu.name,
            type=self.accept_ctx_menu.type)

    @commands.Cog.listener()
    async def on_ready(self):
        await self.bot.unpause_cogs.wait()
        print(f'{self.__class__.__name__} Cog is ready.')

    async def weekly(self):
        print("Performing Weekly")
        await self.bot.request_channel.send(
            content=f'**Reminder:** Use !request to schedule games in the Store!\n'
                    f'\tSee {self.bot.readonly_channel.mention} for available times and confirmation of your request.')

    @commands.command(name="weekly")
    @Prefix.admin_only()
    @Prefix.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def prefix_command_weekly(self, *_):
        await self.weekly()

    @tasks.loop(time=datetime.time(hour=1))  # Time is updated based on Config in Constructor
    async def weekly_task(self):
        if DateTranslator.today().strftime("%A").lower() == self.store_config.weekly_config.run_day.lower():
            await self.weekly()

    @weekly_task.before_loop
    async def before_weekly_task(self):
        await self.bot.wait_until_ready()

    async def request_validate(self,
                               date: CommonDate,
                               timeslot_range: ScheduleSlotRange):
        bound_schedule = await self.bot.find_bound_schedule(date, opened=True)
        if not bound_schedule:
            raise ValidationError(
                f'Cannot request timeslot on Closed Schedule.\n'
                f'See {self.bot.readonly_channel.mention} for available times.')

        try:
            timeslot_range = bound_schedule.schedule.qualify_slotrange(timeslot_range)
        except ValueError:
            raise ValidationError(
                f"Invalid timeslot range, see {self.bot.readonly_channel.mention} for valid timeslots.")

        # Must check if those timeslots are free
        free_slots = [
            table.check(timeslot_range,
                        timeslot_is_free)
            for table in bound_schedule.schedule.tables.values()
        ]
        if not any(free_slots):
            raise ValidationError(
                f'Timeslot is occupied for all Table on Schedule {str(date)}.\n'
                f'See {self.bot.readonly_channel.mention} for available times.')

    async def request_issue(self,
                            message: discord.Message,
                            author: discord.Member,
                            date: CommonDate,
                            timeslot_range: ScheduleSlotRange,
                            opponents: typing.List[discord.Member] = None,
                            game: str = ''):

        if not opponents:
            opponents = []

        opponent_id_blob = ", ".join(["\"{}\"".format(opponent.id) for opponent in opponents])
        opponent_name_blob = ", ".join(["{}".format(opponent.display_name) for opponent in opponents])

        # Store easily parsable blob in the Bot Data channel
        data_message = await self.bot.data_channel.send(
            '{\n\t"action": "request",\n'
            f'\t"date": "{str(date)}",\n'
            f'\t"time": "{str(timeslot_range)}",\n'
            f'\t"game": "{game}",\n'
            '\t"admin": {\n'
            f'\t\t"source_c_id": "{message.channel.id}",\n'
            f'\t\t"source_m_id": "{message.id}",\n'
            f'\t\t"author_id": "{author.id}",\n'
            f'\t\t"opponent_id": [{opponent_id_blob if opponent_id_blob else ""}]\n'
            '\t}\n'
            "}")
        # Forward Request to Admins
        await self.bot.admin_channel.send(
            f'## **Request** from **{author.display_name}**\n'
            f'req_id: {data_message.id}\n'
            f'Date: {str(date)}\n'
            f'Time: {str(timeslot_range)}\n'
            f'Game: {game}\n'
            f'Opponents: {opponent_name_blob if opponent_name_blob else ""}'
        )
        # Add a message with the req_id only, to facilitate mobile copy-paste input
        await self.bot.admin_channel.send(f'req_id: {data_message.id}')

    async def cancel_validate(self,
                              author: discord.Member,
                              date: CommonDate,
                              timeslot_range: ScheduleSlotRange):
        bound_schedule = await self.bot.find_bound_schedule(date, opened=True)
        if not bound_schedule:
            raise ValidationError(
                f'Cannot request timeslot on Closed Schedule.\n'
                f'See {self.bot.readonly_channel.mention} for available times.')

        try:
            timeslot_range = bound_schedule.schedule.qualify_slotrange(timeslot_range)
        except ValueError:
            raise ValidationError(
                f"Invalid timeslot range, see {self.bot.readonly_channel.mention} for valid timeslots.")

        # Must check if those timeslots are owned
        owned_tables = [
            table.check(timeslot_range,
                        partial(timeslot_is_owned_by_author, author, None))
            for table in bound_schedule.schedule.tables.values()
        ]
        if not any(owned_tables):
            raise ValidationError(
                f'Timeslot Range {timeslot_range} is not all owned by requestor for {str(date)}.\n'
                f'See {self.bot.readonly_channel.mention} for allocated times.')

    async def cancel_issue(self,
                           message: discord.Message,
                           author: discord.Member,
                           date: CommonDate,
                           timeslot_range: ScheduleSlotRange):
        # Store easily parsable blob in the Bot Data channel
        data_message = await self.bot.data_channel.send(
            '{\n\t"action": "cancel",\n'
            f'\t"date": "{str(date)}",\n'
            f'\t"time": "{str(timeslot_range)}",\n'
            '\t"admin": {\n'
            f'\t\t"source_c_id": "{message.channel.id}",\n'
            f'\t\t"source_m_id": "{message.id}",\n'
            f'\t\t"author_id": "{author.id}"\n'
            '\t}\n'
            '}')
        # Forward Request to Admins
        await self.bot.admin_channel.send(
            f'## **Cancel** from **{author.display_name}**\n'
            f'req_id: {data_message.id}\n'
            f'Date: {str(date)}\n'
            f'Time: {str(timeslot_range)}'
        )
        # Add a message with the req_id only, to facilitate mobile copy-paste input
        await self.bot.admin_channel.send(f'req_id: {data_message.id}')

    async def accept(self,
                     data_id: int):
        data_message = await self.bot.data_channel.fetch_message(data_id)
        if not data_message:
            raise ValidationError("Original bot data is no longer valid.")

        request = json.loads(data_message.content)
        action = request['action']
        if action != "request" and action != "cancel":
            raise ValidationError("Invalid req_id for action")

        try:
            date = CommonDate.deserialize(request['date'])
        except ValueError:
            raise ValidationError("Invalid date for action")

        try:
            times = ScheduleSlotRange.deserialize(request['time'])
        except ValueError:
            raise ValidationError("Invalid time for action")

        source_channel = await self.bot.fetch_channel(request['admin']['source_c_id'])
        source_message = await source_channel.fetch_message(request['admin']['source_m_id'])
        author = await self.bot.guild.fetch_member(request['admin']['author_id'])

        try:
            game = request['game']
        except KeyError:
            game = None

        try:
            opponents = request['admin']['opponent_id']
        except KeyError:
            opponents = None

        if opponents:
            opponents = [await self.bot.guild.fetch_member(opponent) for opponent in opponents]
        else:
            opponents = None

        # Must check if schedule is open for date
        # Must check if those timeslots are free
        bound_schedule = await self.bot.find_bound_schedule(date, opened=True)
        if not bound_schedule:
            raise ValidationError(f'Cannot modify timeslot on Closed Schedule.')

        if action == "request":
            already_owned_slots = [
                table.check(times,
                            partial(timeslot_is_owned_by_author, author, None))
                for table in bound_schedule.schedule.tables.values()
            ]
            if any(already_owned_slots):
                owned_table = bound_schedule.schedule.tables[[i for i, x in enumerate(already_owned_slots) if x][0] + 1]
                raise ValidationError(
                    f'Timeslot is already owned by {author.display_name} '
                    f'on Table {owned_table.number} for Schedule {str(date)}')

            free_slots = [
                table.check(times,
                            timeslot_is_free)
                for table in bound_schedule.schedule.tables.values()
            ]
            if not any(free_slots):
                raise ValidationError(
                    f'Timeslot has since been occupied for all Tables on Schedule {str(date)}')

            # Mark requested slots as owned by player and opponent
            free_table = bound_schedule.schedule.tables[[i for i, x in enumerate(free_slots) if x][0] + 1]
            free_table.exec(times,
                            partial(timeslot_mark_as_owned, author, opponents, game))

            # Update the schedule
            await bound_schedule.update()

            if source_message:
                await source_message.reply(
                    f'Store confirmed request for {str(date)} {times} onto Table {free_table.number}')

        else:
            owned_tables = [
                table.check(times,
                            partial(timeslot_is_owned_by_author, author, None))
                for table in bound_schedule.schedule.tables.values()
            ]
            if not any(owned_tables):
                raise ValidationError(
                    f'Timeslot Range {times} is no longer owned by requestor for {str(date)})')

            # Remove ownership from timeslot range
            owned_table = bound_schedule.schedule.tables[[i for i, x in enumerate(owned_tables) if x][0] + 1]
            owned_table.exec(times,
                             timeslot_mark_as_free)

            # Update the schedule
            await bound_schedule.update()

            if source_message:
                await source_message.reply(
                    f'Store cancelled request for {str(date)} {times} from Table {owned_table.number}')

    async def add(self,
                  date: CommonDate,
                  timeslot_range: ScheduleSlotRange,
                  author: discord.Member,
                  opponents: typing.List[discord.Member] = None,
                  game: str = ''):
        if not opponents:
            opponents = []

        bound_schedule = await self.bot.find_bound_schedule(date, opened=True)
        if not bound_schedule:
            raise ValidationError(
                f'Cannot request timeslot on Closed Schedule.\n'
                f'See {self.bot.readonly_channel.mention} for available times.')

        try:
            timeslot_range = bound_schedule.schedule.qualify_slotrange(timeslot_range)
        except ValueError:
            raise ValidationError(
                f"Invalid timeslot range, see {self.bot.readonly_channel.mention} for valid timeslots")

        # Must check if those timeslots are free
        free_slots = [
            table.check(timeslot_range,
                        timeslot_is_free)
            for table in bound_schedule.schedule.tables.values()
        ]
        if not any(free_slots):
            raise ValidationError(
                f'Timeslot is occupied for all Table on Schedule {str(date)}.\n'
                f'See {self.bot.readonly_channel.mention} for available times.')

        # Mark requested slots as owned by player and opponent
        free_table = bound_schedule.schedule.tables[[i for i, x in enumerate(free_slots) if x][0] + 1]
        free_table.exec(timeslot_range,
                        partial(timeslot_mark_as_owned, author, opponents, game))

        # Update the schedule
        await bound_schedule.update()

    async def remove(self,
                     date: CommonDate,
                     timeslot_range: ScheduleSlotRange,
                     author: discord.Member,
                     opponents: typing.List[discord.Member] = None):
        if not opponents:
            opponents = []

        bound_schedule = await self.bot.find_bound_schedule(date, opened=True)
        if not bound_schedule:
            raise ValidationError(
                f'Cannot request timeslot on Closed Schedule.\n'
                f'See {self.bot.readonly_channel.mention} for available times.')

        try:
            timeslot_range = bound_schedule.schedule.qualify_slotrange(timeslot_range)
        except ValueError:
            raise ValidationError(
                f"Invalid timeslot range, see {self.bot.readonly_channel.mention} for valid timeslots.\n")

        # Must check if those timeslots are owned
        owned_tables = [
            table.check(timeslot_range,
                        partial(timeslot_is_owned_by_author, author, opponents))
            for table in bound_schedule.schedule.tables.values()
        ]
        if not any(owned_tables):
            raise ValidationError(
                f'Timeslot Range {timeslot_range} is not all owned by requestor for {str(date)}.\n'
                f'See {self.bot.readonly_channel.mention} for allocated times.')

        # Remove ownership from timeslot range
        owned_table = bound_schedule.schedule.tables[[i for i, x in enumerate(owned_tables) if x][0] + 1]
        owned_table.exec(timeslot_range,
                         timeslot_mark_as_free)

        # Update the schedule
        await bound_schedule.update()

    @app_commands.command(
        name="request",
        description="Issues a scheduling request for a Store Table at a given date and time")
    @app_commands.describe(
        date="Date or Day to schedule Table",
        timeslot="hr:m{am/pm} for start of reservation",
        timeslot_end="hr:m{am/pm} for end of reservation",
        opponent="(Optional) @mention of Opponent",
        game="(Optional) Game being played")
    @app_commands.autocomplete(
        date=DateCompleter.auto_complete,
        timeslot=FreeTimeCompleter().auto_complete,
        timeslot_end=FreeTimeCompleter(terminus=True, timeslot=TimeTransformer).auto_complete,
        game=ActivityCompleter.auto_complete)
    @Slash.restricted_channel(Channel.SCHEDULE_REQUEST)
    async def slash_command_request(
            self,
            interaction: discord.Interaction,
            date: app_commands.Transform[CommonDate, DateTransformer],
            timeslot: app_commands.Transform[ScheduleSlotRange, SlotRangeTransformer],
            timeslot_end: typing.Optional[app_commands.Transform[MeridiemTime, TimeTransformer]] = None,
            opponent: discord.Member = None,
            game: typing.Optional[str] = ''):

        if opponent:
            opponents = [opponent]
        else:
            opponents = []

        if timeslot_end and timeslot.is_indeterminate():
            timeslot.qualify(timeslot_end)

        # Do second level validation
        await self.request_validate(date, timeslot)

        # Defer to create a response message we can reference
        await interaction.response.defer(ephemeral=False, thinking=True)

        # Issue the request, then update the response to indicate success
        await self.request_issue(
            await interaction.original_response(),
            interaction.user,
            date,
            timeslot,
            opponents,
            game
        )
        await interaction.edit_original_response(
            content=f'{interaction.user.mention} requested: '
                    f'{DateTranslator.day_from_date(date)} ({date}) '
                    f'{timeslot} '
                    f'{", ".join([opponent.mention for opponent in opponents])}{" " if opponents else ""}'
                    f'{"({})".format(game) if game else ""}'.strip())

    @commands.command(name="request")
    @Prefix.restricted_channel(Channel.SCHEDULE_REQUEST)
    async def prefix_command_request(
            self,
            ctx: commands.Context,
            date: CommonDate = commands.parameter(converter=DateConverter),
            timeslot_range: ScheduleSlotRange = commands.parameter(converter=FuzzySlotRangeConverter(depend="date")),
            opponents: commands.Greedy[discord.Member] = None,
            game: typing.Optional[str] = ''):

        if not opponents:
            opponents = []

        # Do second level validation
        await self.request_validate(date, timeslot_range)
        await self.request_issue(
            ctx.message,
            ctx.author,
            date,
            timeslot_range,
            opponents,
            game)
        await ctx.message.add_reaction("📨")

    @app_commands.command(
        name="cancel",
        description="Issues a cancellation request for a Store Table at a given date and time")
    @app_commands.describe(
        date="Date or Day to cancel existing Table reservation",
        timeslot="hr:m{am/pm} for start of reservation",
        timeslot_end="hr:m{am/pm} for end of reservation")
    @app_commands.autocomplete(
        date=DateCompleter.auto_complete,
        timeslot=AuthorOnlyTimeCompleter().auto_complete,
        timeslot_end=AuthorOnlyTimeCompleter(terminus=True, timeslot=TimeTransformer).auto_complete
    )
    @Slash.restricted_channel(Channel.SCHEDULE_REQUEST)
    async def slash_command_cancel(
            self,
            interaction: discord.Interaction,
            date: app_commands.Transform[CommonDate, DateTransformer],
            timeslot: app_commands.Transform[ScheduleSlotRange, SlotRangeTransformer],
            timeslot_end: typing.Optional[app_commands.Transform[MeridiemTime, TimeTransformer]] = None):

        if timeslot_end and timeslot.is_indeterminate():
            timeslot.qualify(timeslot_end)

        # Do second level validation
        await self.cancel_validate(interaction.user, date, timeslot)

        # Defer to create a response message we can reference
        await interaction.response.defer(ephemeral=False, thinking=True)

        # Issue the request, then update the response to indicate success
        await self.cancel_issue(
            await interaction.original_response(),
            interaction.user,
            date,
            timeslot
        )
        await interaction.edit_original_response(
            content=f'{interaction.user.mention} cancelled: '
                    f'{DateTranslator.day_from_date(date)} ({date}) '
                    f'{timeslot}')

    @commands.command(name="cancel")
    @Prefix.restricted_channel(Channel.SCHEDULE_REQUEST)
    async def prefix_command_cancel(
            self,
            ctx: commands.Context,
            date: CommonDate = commands.parameter(converter=DateConverter),
            timeslot_range: ScheduleSlotRange = commands.parameter(
                converter=FuzzySlotRangeConverter(depend="date"))):
        # Do second level validation
        await self.cancel_validate(ctx.author, date, timeslot_range)
        await self.cancel_issue(
            ctx.message,
            ctx.author,
            date,
            timeslot_range)
        await ctx.message.add_reaction("📨")

    @app_commands.command(
        name="accept",
        description="Accepts a scheduling request or cancellation for a Table at a given date and time.")
    @app_commands.describe(
        data_id="Request/Cancellation req_id (can include \"req_id: \" from copy-paste")
    @Slash.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def slash_command_accept(
            self,
            interaction: discord.Interaction,
            data_id: app_commands.Transform[int, DataIdTransformer("req_id: ")]):
        await self.accept(data_id)
        await interaction.response.send_message(
            f'{interaction.user.mention} accepted: {data_id}')

    @Slash.admin_only()
    @Slash.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def context_command_accept(
            self,
            interaction: discord.Interaction,
            message: discord.Message) -> None:

        match = re.search(r'req_id: (\d+)', message.content, flags=re.IGNORECASE)
        if not match:
            raise ValidationError('No "req_id: " found in message')

        data_id = int(match.group(1))
        await self.accept(data_id)
        await interaction.response.send_message(
            f'{interaction.user.mention} accepted: {data_id}')

    @commands.command(name='accept')
    @Prefix.admin_only()
    @Prefix.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def prefix_command_accept(
            self,
            ctx: commands.Context,
            _: typing.Optional[typing.Literal['req_id:']] = None,
            data_id: int = None):
        await self.accept(data_id)
        await ctx.message.add_reaction("👍")

    @app_commands.command(
        name="add",
        description="Manually add a Store Table usage at a given date and time")
    @app_commands.describe(
        date="Date or Day to add Table reservation",
        timeslot="hr:m{am/pm} for start of reservation",
        timeslot_end="hr:m{am/pm} for end of reservation",
        author="@mention of main Player",
        opponent="(Optional) @mention of Opponent",
        game="(Optional) Game being played")
    @app_commands.autocomplete(
        date=DateCompleter.auto_complete,
        timeslot=TimeCompleter().auto_complete,
        timeslot_end=TimeCompleter(terminus=True, timeslot=TimeTransformer).auto_complete,
        game=ActivityCompleter.auto_complete
    )
    @Slash.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def slash_command_add(
            self,
            interaction: discord.Interaction,
            author: discord.Member,
            date: app_commands.Transform[CommonDate, DateTransformer],
            timeslot: app_commands.Transform[ScheduleSlotRange, SlotRangeTransformer],
            timeslot_end: typing.Optional[app_commands.Transform[MeridiemTime, TimeTransformer]] = None,
            opponent: typing.Optional[discord.Member] = None,
            game: typing.Optional[str] = ''):

        if opponent:
            opponents = [opponent]
        else:
            opponents = []

        if timeslot_end and timeslot.is_indeterminate():
            timeslot.qualify(timeslot_end)

        await self.add(date, timeslot, author, opponents, game)

        await interaction.response.send_message(
            content=f'{interaction.user.mention} added: '
                    f'{DateTranslator.day_from_date(date)} ({date}) '
                    f'{timeslot} for {author.display_name} '
                    f'{", ".join([opponent.mention for opponent in opponents])}{" " if opponents else ""}'
                    f'{"({})".format(game) if game else ""}'.strip())

    @commands.command(name="add")
    @Prefix.admin_only()
    @Prefix.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def prefix_command_add(
            self,
            ctx: commands.Context,
            author: discord.Member,
            date: CommonDate = commands.parameter(converter=DateConverter),
            timeslot_range: ScheduleSlotRange = commands.parameter(converter=FuzzySlotRangeConverter(depend="date")),
            opponents: commands.Greedy[discord.Member] = None,
            game: typing.Optional[str] = ''):

        if not opponents:
            opponents = []

        await self.add(date, timeslot_range, author, opponents, game)
        await ctx.message.add_reaction("👍")

    @app_commands.command(
        name="remove",
        description="Manually remove a Store Table usage at a given date and time")
    @app_commands.describe(
        date="Date or Day to add Table reservation",
        timeslot="hr:m{am/pm} for start of reservation",
        timeslot_end="hr:m{am/pm} for end of reservation")
    @app_commands.autocomplete(
        date=DateCompleter.auto_complete,
        timeslot=TimeCompleter().auto_complete,
        timeslot_end=TimeCompleter(terminus=True, timeslot=TimeTransformer).auto_complete
    )
    @Slash.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def slash_command_remove(
            self,
            interaction: discord.Interaction,
            author: discord.Member,
            date: app_commands.Transform[CommonDate, DateTransformer],
            timeslot: app_commands.Transform[ScheduleSlotRange, SlotRangeTransformer],
            timeslot_end: typing.Optional[app_commands.Transform[MeridiemTime, TimeTransformer]] = None,
            opponent: typing.Optional[discord.Member] = None):

        if opponent:
            opponents = [opponent]
        else:
            opponents = []

        if timeslot_end and timeslot.is_indeterminate():
            timeslot.qualify(timeslot_end)

        await self.remove(date, timeslot, author, opponents)

        await interaction.response.send_message(
            content=f'{interaction.user.mention} removed: '
                    f'{DateTranslator.day_from_date(date)} ({date}) '
                    f'{timeslot} for {author.display_name} '
                    f'{", ".join([opponent.mention for opponent in opponents])}{" " if opponents else ""}')

    @commands.command(name="remove")
    @Prefix.admin_only()
    @Prefix.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def prefix_command_remove(
            self,
            ctx: commands.Context,
            author: discord.Member,
            date: CommonDate = commands.parameter(converter=DateConverter),
            timeslot_range: ScheduleSlotRange = commands.parameter(converter=FuzzySlotRangeConverter(depend="date")),
            opponents: commands.Greedy[discord.Member] = None):

        if not opponents:
            opponents = []

        await self.remove(date, timeslot_range, author, opponents)
        await ctx.message.add_reaction("👍")

    @prefix_command_request.error
    @prefix_command_cancel.error
    @prefix_command_accept.error
    @prefix_command_add.error
    @prefix_command_remove.error
    @prefix_command_weekly.error
    async def error_prefix_command(self, ctx: commands.Context, error):
        if isinstance(error, Prefix.RestrictionError) or \
                isinstance(error, commands.ConversionError) or \
                isinstance(error, commands.BadArgument) or \
                isinstance(error, ValidationError) or \
                isinstance(error, commands.CommandInvokeError):
            if isinstance(error, commands.CommandInvokeError) or \
                    isinstance(error, commands.ConversionError):
                msg = str(error.original)
            else:
                msg = str(error)

            await ctx.message.reply(msg)

            logging.getLogger('discord').exception(error.original)
        else:
            raise error

    @slash_command_request.error
    @slash_command_cancel.error
    @slash_command_accept.error
    @slash_command_add.error
    @slash_command_remove.error
    async def error_slash_command(self, interaction: discord.Interaction, error):
        if isinstance(error, Slash.RestrictionError) or \
                isinstance(error, app_commands.TransformerError) or \
                isinstance(error, app_commands.CommandInvokeError) or \
                isinstance(error, ValidationError):
            if isinstance(error, app_commands.CommandInvokeError):
                msg = str(error.original)
            else:
                msg = str(error)

            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.edit_original_response(
                    content=f'Unable to issue {interaction.command.name} with {str(interaction.command.data)}.\n'
                            f'Please report failure to an administrator.')

            logging.getLogger('discord').exception(error.original)
        else:
            raise error


async def setup(bot):
    await bot.add_cog(SlotManager(bot), guild=discord.Object(id=bot.GUILD_ID))
