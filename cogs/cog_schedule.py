import datetime
import logging
import typing

from datetime import timedelta
from pytz import timezone

import discord
from discord.ext import commands, tasks
from discord import app_commands

from util.date import DateTranslator, CommonDate
from core.bot_core import ScheduleBot
from cogs.util import (
    Channel,
    Slash,
    Prefix,
    DateConverter,
    ForceConverter,
    ValidationError,
    DateTransformer,
    ExistingDateCompleter,
    GenericDateCompleter)
from model.schedule_config import ScheduleConfig


@app_commands.guild_only()
class ScheduleManager(commands.Cog):
    def __init__(self, bot: ScheduleBot):
        self.bot: ScheduleBot = bot
        self.store_config: ScheduleConfig = ScheduleConfig.singleton()

        if self.store_config.nightly_config.enabled:
            trigger_time = self.store_config.nightly_config.run_time
            nightly_time = datetime.datetime.now(timezone('US/Pacific'))
            nightly_time = nightly_time.replace(
                hour=trigger_time.hour,
                minute=trigger_time.minute,
                second=0,
                microsecond=0)
            nightly_time = nightly_time.astimezone(timezone('UTC')).timetz()

            self.nightly_task.change_interval(time=nightly_time)
            self.nightly_task.start()

    def cog_unload(self) -> None:
        self.nightly_task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.bot.unpause_cogs.wait()
        print(f'{self.__class__.__name__} Cog is ready.')

    async def nightly_open(self, end_date: CommonDate):
        print("Creating the schedules")
        await self.bot.open_until(end_date, state=None)

    async def nightly_close(self, start_date: CommonDate):
        print("Closing the schedules")
        await self.bot.close_until(start_date)

    async def nightly_clean(self, clean_date: CommonDate):
        print("Cleaning the schedules")
        await self.bot.clean_until(clean_date)

    async def nightly(self):
        date_format = DateTranslator.get_date_format()

        today = DateTranslator.today()
        end_date = today + timedelta(days=self.store_config.nightly_config.open_ahead)
        start_date = today - timedelta(days=self.store_config.nightly_config.close_behind)
        clean_date = today - timedelta(days=self.store_config.nightly_config.clean_behind)

        print("Starting Nightly")

        await self.nightly_open(end_date)
        await self.nightly_close(start_date)
        await self.nightly_clean(clean_date)

        # Update Schedule cache due to activity
        await self.bot.regenerate_schedule_cache()

        bot_action_log = f'Nightly managed schedules:\n' \
                         f'Open until: {end_date.strftime(date_format)}\n' \
                         f'Closed until: {start_date.strftime(date_format)}\n' \
                         f'Cleaned until: {clean_date.strftime(date_format)}'

        if self.store_config.nightly_config.verbose:
            await self.bot.admin_channel.send(
                bot_action_log,
                delete_after=24*60*60)  # Delete after 24hr

        print(bot_action_log)

    @tasks.loop(time=datetime.time(hour=1))  # Time is updated based on Config in Constructor
    async def nightly_task(self):
        await self.nightly()

    @nightly_task.before_loop
    async def before_nightly_task(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="nightly",
        description="Perform Nightly maintenance activity")
    @Slash.admin_only()
    @Slash.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def slash_command_nightly(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False, thinking=True)
        await self.nightly()
        await interaction.edit_original_response(
            content=f'{interaction.user.mention} completed Nightly maintenance.')

    @commands.command(name="nightly")
    @Prefix.admin_only()
    @Prefix.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def prefix_command_nightly(self, ctx: commands.Context):
        await self.nightly()
        await ctx.message.add_reaction("👍")

    @app_commands.command(
        name="open",
        description="Manually create a date in the Schedule and set it to OPEN")
    @app_commands.describe(
        date="Date or Day to OPEN",
        force="(Optional) Force OPEN if the Day exists and has been CLOSED")
    @app_commands.autocomplete(
        date=GenericDateCompleter.auto_complete
    )
    @Slash.admin_only()
    @Slash.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def slash_command_open(
            self,
            interaction: discord.Interaction,
            date: app_commands.Transform[CommonDate, DateTransformer],
            force: typing.Optional[bool] = False):

        await interaction.response.defer(ephemeral=False, thinking=True)
        bound_schedule = await self.bot.open_given(date, force=force)
        if bound_schedule:
            await interaction.edit_original_response(
                content=f'{interaction.user.mention} Opened schedule for '
                        f'{bound_schedule.schedule.day} - {str(bound_schedule.schedule.date)}.')
        else:
            await interaction.edit_original_response(
                content=f'Cannot open due to existing Open Schedule.\n'
                        f'Use the \'force\' option to overwrite with a fresh Schedule.')

        await self.bot.regenerate_schedule_cache()

    @commands.command(name="open")
    @Prefix.admin_only()
    @Prefix.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def prefix_command_open(
            self,
            ctx: commands.Context,
            until: typing.Optional[typing.Literal['until']] = None,
            date: CommonDate = commands.parameter(converter=DateConverter),
            force: typing.Optional[bool] = commands.parameter(converter=ForceConverter)):
        # args: Date, Force (optional)
        # Must check if schedule is open for date
        # If so, error unless -f is specified, if so overwrite with new
        # else, open the new schedule
        if until:
            await self.bot.open_until(date, force=force)
            await ctx.send(f'Opened schedules until {str(date)}')

        else:
            bound_schedule = await self.bot.open_given(date, force=force)
            if bound_schedule:
                await ctx.send(
                    f'Opened schedule for {bound_schedule.schedule.day} - {str(bound_schedule.schedule.date)}')
            else:
                await ctx.send(
                    f'Cannot open due to existing Open Schedule.\n' +
                    f'Use -f to overwrite.')

        await self.bot.regenerate_schedule_cache()

    @app_commands.command(
        name="close",
        description="Manually set a date in the Schedule to OPEN")
    @app_commands.describe(
        date="Date or Day to set to CLOSE")
    @app_commands.autocomplete(
        date=ExistingDateCompleter.auto_complete
    )
    @Slash.admin_only()
    @Slash.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def slash_command_close(
            self,
            interaction: discord.Interaction,
            date: app_commands.Transform[CommonDate, DateTransformer]):

        await interaction.response.defer(ephemeral=False, thinking=True)
        await self.bot.close_given(date)
        await interaction.edit_original_response(
            content=f'{interaction.user.mention} Closed schedule {DateTranslator.day_from_date(date)} - {str(date)}.')
        
        await self.bot.regenerate_schedule_cache()

    @commands.command(name="close")
    @Prefix.admin_only()
    @Prefix.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def prefix_command_close(
            self,
            ctx: commands.Context,
            until: typing.Optional[typing.Literal['until']] = None,
            date: CommonDate = commands.parameter(converter=DateConverter)):
        # args: Date
        # Walk all schedule channel messages and mark ones behind date as closed
        if until:
            await self.bot.close_until(date)
            await ctx.send(f'Closed schedules until {DateTranslator.day_from_date(date)} - {str(date)}')

        else:
            await self.bot.close_given(date)
            await ctx.send(f'Closed schedule {DateTranslator.day_from_date(date)} - {str(date)}')

        await self.bot.regenerate_schedule_cache()

    @app_commands.command(
        name="clean",
        description="Clean (remove) a date in the Schedule")
    @app_commands.describe(
        date="Date or Day to set to remove")
    @app_commands.autocomplete(
        date=ExistingDateCompleter.auto_complete
    )
    @Slash.admin_only()
    @Slash.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def slash_command_clean(
            self,
            interaction: discord.Interaction,
            date: app_commands.Transform[CommonDate, DateTransformer]):

        await interaction.response.defer(ephemeral=False, thinking=True)
        still_open = await self.bot.clean_given(date)
        if still_open:
            response_message = f'Unable to clean {DateTranslator.day_from_date(date)} - {str(date)} as it is OPEN'
        else:
            response_message = f'Cleaned schedule {DateTranslator.day_from_date(date)} - {str(date)}'

        await interaction.edit_original_response(
            content=f'{interaction.user.mention} {response_message}.')

        await self.bot.regenerate_schedule_cache()

    @commands.command(name="clean")
    @Prefix.admin_only()
    @Prefix.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def prefix_command_clean(
            self,
            ctx: commands.Context,
            until: typing.Optional[typing.Literal['until']] = None,
            date: CommonDate = commands.parameter(converter=DateConverter)):
        # args: Date
        # Walk all schedule channel messages and mark ones behind date as closed
        if until:
            open_schedules = []
            await self.bot.clean_until(date, open_schedules)

            response_message = f'Cleaned schedules until {DateTranslator.day_from_date(date)} - {str(date)}'
            if open_schedules:
                response_message += f'\n**Except:**\n'
                for bound_schedule in open_schedules:
                    response_message += \
                        f'{"OPEN" if bound_schedule.schedule.open else "CLOSED"}' \
                        f' - {str(bound_schedule.schedule.date)}\n'

            await ctx.send(response_message.rstrip('\n '))

        else:
            still_open = await self.bot.clean_given(date)

            if still_open:
                response_message = f'Unable to clean {DateTranslator.day_from_date(date)} - {str(date)} as it is OPEN'
            else:
                response_message = f'Cleaned schedule {DateTranslator.day_from_date(date)} - {str(date)}'

            await ctx.send(response_message)

        await self.bot.regenerate_schedule_cache()

    @prefix_command_open.error
    @prefix_command_close.error
    @prefix_command_clean.error
    @prefix_command_nightly.error
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

    @slash_command_open.error
    @slash_command_close.error
    @slash_command_clean.error
    @slash_command_nightly.error
    async def error_slash_command(self, interaction: discord.Interaction, error):
        if isinstance(error, Slash.RestrictionError) or \
                isinstance(error, app_commands.CommandInvokeError) or \
                isinstance(error, app_commands.TransformerError):
            if isinstance(error, app_commands.CommandInvokeError):
                msg = str(error.original)
            else:
                msg = str(error)

            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.edit_original_response(
                    content=f'Unable to issue {interaction.command.name} with {str(interaction.namespace)}.\n'
                            f'Please report failure to an administrator.')

            logging.getLogger('discord').exception(error.original)
        else:
            raise error


async def setup(bot):
    await bot.add_cog(ScheduleManager(bot), guild=discord.Object(id=bot.GUILD_ID))
