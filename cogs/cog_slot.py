import json
import datetime
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
    TimeConverter,
    SlotRangeConverter,
    DateTransformer,
    TimeTransformer,
    SlotRangeTransformer,
    DateCompleter,
    TimeCompleter)
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

    def cog_unload(self) -> None:
        self.weekly_task.cancel()

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
                            opponent: discord.Member):
        # Forward Request to Admins
        await self.bot.admin_channel.send(
            f'## **Request** from **{author.display_name}**\n'
            f'Date: {str(date)}\n'
            f'Time: {str(timeslot_range)}\n'
            f'Opponent: {"{}".format(opponent.display_name) if opponent else ""}'
        )
        data_message = await self.bot.data_channel.send(
            '{\n\t"action": "request",\n'
            f'\t"name": "{author.name}",\n'
            f'\t"date": "{str(date)}",\n'
            f'\t"time": "{str(timeslot_range)}",\n'
            f'\t"opponent": "{opponent.name if opponent else ""}",\n'
            '\t"admin": {\n'
            f'\t\t"source_c_id": "{message.channel.id}",\n'
            f'\t\t"source_m_id": "{message.id}",\n'
            f'\t\t"author_id": "{author.id}",\n'
            f'\t\t"opponent_id": "{opponent.id if opponent else ""}"\n'
            '\t}\n'
            "}")
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
        # Forward Request to Admins
        await self.bot.admin_channel.send(
            f'## **Cancel** from **{author.display_name}**\n'
            f'Date: {str(date)}\n'
            f'Time: {str(timeslot_range)}'
        )
        data_message = await self.bot.data_channel.send(
            '{\n\t"action": "cancel",\n'
            f'\t"name": "{author.name}",\n'
            f'\t"date": "{str(date)}",\n'
            f'\t"time": "{str(timeslot_range)}",\n'
            '\t"admin": {\n'
            f'\t\t"source_c_id": "{message.channel.id}",\n'
            f'\t\t"source_m_id": "{message.id}",\n'
            f'\t\t"author_id": "{author.id}"\n'
            '\t}\n'
            '}')
        await self.bot.admin_channel.send(f'req_id: {data_message.id}')

    async def accept(self,
                     ctx: commands.Context,
                     data_id: int):
        data_message = await self.bot.data_channel.fetch_message(data_id)
        if not data_message:
            await ctx.send("Original bot data is no longer valid.")
            return

        request = json.loads(data_message.content)
        action = request['action']
        if action != "request" and action != "cancel":
            await ctx.send("Invalid req_id for action")
            return

        try:
            date = CommonDate.deserialize(request['date'])
        except ValueError:
            await ctx.send("Invalid date for action")
            return

        try:
            times = ScheduleSlotRange.deserialize(request['time'])
        except ValueError:
            await ctx.send("Invalid time for action")
            return

        source_channel = await self.bot.fetch_channel(request['admin']['source_c_id'])
        source_message = await source_channel.fetch_message(request['admin']['source_m_id'])
        author = await self.bot.guild.fetch_member(request['admin']['author_id'])

        try:
            opponent = request['admin']['opponent_id']
        except KeyError:
            opponent = None

        if opponent:
            opponent = await self.bot.guild.fetch_member(opponent)
        else:
            opponent = None

        # Must check if schedule is open for date
        # Must check if those timeslots are free
        bound_schedule = await self.bot.find_bound_schedule(date, opened=True)
        if not bound_schedule:
            await ctx.send(f'Cannot modify timeslot on Closed Schedule.')
            return

        if action == "request":
            already_owned_slots = [
                table.check(times,
                            partial(timeslot_is_owned_by_author, author, None))
                for table in bound_schedule.schedule.tables.values()
            ]
            if any(already_owned_slots):
                owned_table = bound_schedule.schedule.tables[[i for i, x in enumerate(already_owned_slots) if x][0] + 1]
                await ctx.send(
                    f'Timeslot is already owned by {author.display_name} '
                    f'on Table {owned_table.number} for Schedule {str(date)}')
                return

            free_slots = [
                table.check(times,
                            timeslot_is_free)
                for table in bound_schedule.schedule.tables.values()
            ]
            if not any(free_slots):
                await ctx.send(f'Timeslot has since been occupied for all Tables on Schedule {str(date)}')
                return

            # Mark requested slots as owned by player and opponent
            free_table = bound_schedule.schedule.tables[[i for i, x in enumerate(free_slots) if x][0] + 1]
            free_table.exec(times,
                            partial(timeslot_mark_as_owned, author, opponent))

            await bound_schedule.message.edit(
                content=self.bot.externalize_payload(
                    str(bound_schedule.schedule),
                    self.bot.ESCAPE_TOKEN
                ))
            await ctx.message.add_reaction("👍")

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
                await ctx.send(f'Timeslot Range {times} is no longer owned by requestor for {str(date)})')
                return

            # Remove ownership from timeslot range
            owned_table = bound_schedule.schedule.tables[[i for i, x in enumerate(owned_tables) if x][0] + 1]
            owned_table.exec(times,
                             timeslot_mark_as_free)

            await bound_schedule.message.edit(
                content=self.bot.externalize_payload(
                    str(bound_schedule.schedule),
                    self.bot.ESCAPE_TOKEN
                ))
            await ctx.message.add_reaction("👍")

            if source_message:
                await source_message.reply(
                    f'Store cancelled request for {str(date)} {times} from Table {owned_table.number}')

    async def add(self,
                  ctx: commands.Context,
                  date: CommonDate,
                  timeslot_range: ScheduleSlotRange,
                  author: discord.Member,
                  opponent: discord.Member):
        bound_schedule = await self.bot.find_bound_schedule(date, opened=True)
        if not bound_schedule:
            await ctx.send(f'Cannot request timeslot on Closed Schedule.\n'
                           f'See {self.bot.readonly_channel.mention} for available times.')
            return

        try:
            timeslot_range = bound_schedule.schedule.qualify_slotrange(timeslot_range)
        except ValueError:
            await ctx.send(f"Invalid timeslot range, see {self.bot.readonly_channel.mention} for valid timeslots.\n"
                           f"See usage details by using \"!add -h\"")
            return

        # Must check if those timeslots are free
        free_slots = [
            table.check(timeslot_range,
                        timeslot_is_free)
            for table in bound_schedule.schedule.tables.values()
        ]
        if not any(free_slots):
            await ctx.send(f'Timeslot is occupied for all Table on Schedule {str(date)}.\n'
                           f'See {self.bot.readonly_channel.mention} for available times.')
            return

        # Mark requested slots as owned by player and opponent
        free_table = bound_schedule.schedule.tables[[i for i, x in enumerate(free_slots) if x][0] + 1]
        free_table.exec(timeslot_range,
                        partial(timeslot_mark_as_owned, author, opponent))

        await bound_schedule.message.edit(
            content=self.bot.externalize_payload(
                str(bound_schedule.schedule),
                self.bot.ESCAPE_TOKEN
            ))
        await ctx.message.add_reaction("👍")

    async def remove(self,
                     ctx: commands.Context,
                     date: CommonDate,
                     timeslot_range: ScheduleSlotRange,
                     author: discord.Member,
                     opponent: discord.Member):
        bound_schedule = await self.bot.find_bound_schedule(date, opened=True)
        if not bound_schedule:
            await ctx.send(f'Cannot request timeslot on Closed Schedule.\n'
                           f'See {self.bot.readonly_channel.mention} for available times.')
            return

        try:
            timeslot_range = bound_schedule.schedule.qualify_slotrange(timeslot_range)
        except ValueError:
            await ctx.send(f"Invalid timeslot range, see {self.bot.readonly_channel.mention} for valid timeslots.\n"
                           f"See usage details by using \"!remove -h\"")
            return

        # Must check if those timeslots are owned
        owned_tables = [
            table.check(timeslot_range,
                        partial(timeslot_is_owned_by_author, author, opponent))
            for table in bound_schedule.schedule.tables.values()
        ]
        if not any(owned_tables):
            await ctx.send(f'Timeslot Range {timeslot_range} is not all owned by requestor for {str(date)}.\n'
                           f'See {self.bot.readonly_channel.mention} for allocated times.')
            return

        # Remove ownership from timeslot range
        owned_table = bound_schedule.schedule.tables[[i for i, x in enumerate(owned_tables) if x][0] + 1]
        owned_table.exec(timeslot_range,
                         timeslot_mark_as_free)

        await bound_schedule.message.edit(
            content=self.bot.externalize_payload(
                str(bound_schedule.schedule),
                self.bot.ESCAPE_TOKEN
            ))
        await ctx.message.add_reaction("👍")

    @app_commands.command(
        name="request",
        description="Issues a scheduling request for a Store Table at a given date and time")
    @app_commands.describe(
        date="Date or Day to schedule Table",
        timeslot="hr:m{am/pm} for start of reservation",
        timeslot_end="hr:m{am/pm} for end of reservation",
        opponent="(Optional) @mention of Opponent")
    @app_commands.autocomplete(
        date=DateCompleter.auto_complete,
        timeslot=TimeCompleter().auto_complete,
        timeslot_end=TimeCompleter(timeslot=TimeTransformer).auto_complete)
    @Slash.restricted_channel(Channel.SCHEDULE_REQUEST)
    async def slash_command_request(
            self,
            interaction: discord.Interaction,
            date: app_commands.Transform[CommonDate, DateTransformer],
            timeslot: app_commands.Transform[ScheduleSlotRange, SlotRangeTransformer],
            timeslot_end: typing.Optional[app_commands.Transform[MeridiemTime, TimeTransformer]] = None,
            opponent: typing.Optional[discord.Member] = None):

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
            opponent
        )
        await interaction.edit_original_response(
            content=f'{interaction.user.mention} requested: '
                    f'{DateTranslator.day_from_date(date)} ({date}) '
                    f'{timeslot} {opponent.mention if opponent else ""}'.strip())

    @commands.command(name="request")
    @Prefix.restricted_channel(Channel.SCHEDULE_REQUEST)
    async def prefix_command_request(
            self,
            ctx: commands.Context,
            date: CommonDate = commands.parameter(converter=DateConverter),
            timeslot_range: ScheduleSlotRange = commands.parameter(converter=SlotRangeConverter),
            opponent: typing.Optional[discord.Member] = None):
        # Do second level validation
        await self.request_validate(date, timeslot_range)
        await self.request_issue(
            ctx.message,
            ctx.author,
            date,
            timeslot_range,
            opponent)

    @app_commands.command(
        name="cancel",
        description="Issues a cancellation request for a Store Table at a given date and time")
    @app_commands.describe(
        date="Date or Day to cancel existing Table reservation",
        timeslot="hr:m{am/pm} for start of reservation",
        timeslot_end="hr:m{am/pm} for end of reservation")
    @app_commands.autocomplete(
        date=DateCompleter.auto_complete,
        timeslot=TimeCompleter().auto_complete,
        timeslot_end=TimeCompleter(timeslot=TimeTransformer).auto_complete
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
            timeslot_range: ScheduleSlotRange = commands.parameter(converter=SlotRangeConverter)):
        # Do second level validation
        await self.cancel_validate(ctx.author, date, timeslot_range)
        await self.cancel_issue(
            ctx.message,
            ctx.author,
            date,
            timeslot_range)

    @commands.command(name='accept')
    @Prefix.admin_only()
    @Prefix.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def prefix_command_accept(
            self,
            ctx: commands.Context,
            _: typing.Optional[typing.Literal['req_id:']] = None,
            data_id: int = None):
        # args: req_id
        await self.accept(ctx, data_id)

    @commands.command(name="add")
    @Prefix.admin_only()
    @Prefix.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def prefix_command_add(
            self,
            ctx: commands.Context,
            date: CommonDate = commands.parameter(converter=DateConverter),
            timeslot_range: ScheduleSlotRange = commands.parameter(converter=SlotRangeConverter),
            author: discord.Member = None,
            opponent: typing.Optional[discord.Member] = None):
        # args: Date and Timeslot Range, Player 1 (Name), [Player 2 (Name)]
        await self.add(ctx, date, timeslot_range, author, opponent)

    @commands.command(name="remove")
    @Prefix.admin_only()
    @Prefix.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def prefix_command_remove(
            self,
            ctx: commands.Context,
            date: CommonDate = commands.parameter(converter=DateConverter),
            timeslot_range: ScheduleSlotRange = commands.parameter(converter=SlotRangeConverter),
            author: discord.Member = None,
            opponent: typing.Optional[discord.Member] = None):
        # args: Date, Timeslot Range, Requester, [Opponent]
        await self.remove(ctx, date, timeslot_range, author, opponent)

    @prefix_command_request.error
    @prefix_command_cancel.error
    @prefix_command_accept.error
    @prefix_command_add.error
    @prefix_command_remove.error
    @prefix_command_weekly.error
    async def error_prefix_command(self, ctx: commands.Context, error):
        if isinstance(error, Prefix.RestrictionError) or \
                isinstance(error, commands.BadArgument) or \
                isinstance(error, ValidationError):
            await ctx.send(str(error))
        else:
            raise error

    @slash_command_request.error
    @slash_command_cancel.error
    async def error_slash_command(self, interaction: discord.Interaction, error):
        if isinstance(error, Slash.RestrictionError) or \
                isinstance(error, app_commands.TransformerError) or \
                isinstance(error, ValidationError):
            if not interaction.response.is_done():
                await interaction.response.send_message(str(error), ephemeral=True)
            else:
                await interaction.edit_original_response(
                    content=f'Unable to issue {interaction.command.name} with {str(interaction.command.data)}.\n'
                            f'Please report failure to an administrator.')
                print(f'{str(error)}')
        else:
            raise error


async def setup(bot):
    await bot.add_cog(SlotManager(bot), guild=discord.Object(id=bot.GUILD_ID))
