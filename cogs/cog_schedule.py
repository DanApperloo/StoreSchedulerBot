import datetime
import typing

from typing import Any
from datetime import timedelta
from pytz import timezone
from discord.ext import commands, tasks

from util.date import DateTranslator, CommonDate
from core.bot_core import ScheduleBot
from model.schedule_config import ScheduleConfig


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

        bot_action_log = f'Nightly managed schedules:\n' \
                         f'Open until: {end_date.strftime(date_format)}\n' \
                         f'Closed until: {start_date.strftime(date_format)}\n' \
                         f'Cleaned until: {clean_date.strftime(date_format)}'

        if self.store_config.nightly_config.verbose:
            await self.bot.admin_channel.send(
                bot_action_log,
                delete_after=24*60*60)  # Delete after 24hr

        print(bot_action_log)

    @commands.command(name="nightly")
    async def prefix_command_nightly(self, ctx: commands.Context, *_):
        if not self.bot.is_admin_user(ctx.author.name):
            await ctx.send("Schedule can only be opened by Store staff.")
            return

        await self.nightly()

    @tasks.loop(time=datetime.time(hour=1))  # Time is updated based on Config in Constructor
    async def nightly_task(self):
        await self.nightly()

    @nightly_task.before_loop
    async def before_nightly_task(self):
        await self.bot.wait_until_ready()

    @staticmethod
    async def validate_open_input(ctx, args: list[Any]) -> typing.Union[tuple[CommonDate, bool], tuple[None, None]]:
        if len(args) < 1 or len(args) > 2:
            await ctx.send("Invalid input. See \"!open -h\" for usage.")
            return None, None

        try:
            date = CommonDate.deserialize(args[0])
        except ValueError:
            await ctx.send(
                f"Invalid date in first parameter, must be in format mm/dd/YYYY or a day.\n"
                f"See more by using \"!open -h\"")
            return None, None

        force = False
        if len(args) == 2:
            if args[1] == '-f':
                force = True
            else:
                await ctx.send(
                    "Invalid input. Second parameter may only be '-f'.\n"
                    "See more by using \"!open -h\"")
                return None, None

        return date, force

    @commands.command(name="open")
    async def prefix_command_open(self, ctx: commands.Context, *args):
        # args: Date, Force (optional)
        # Must check if schedule is open for date
        # If so, error unless -f is specified, if so overwrite with new
        # else, open the new schedule
        if not self.bot.is_admin_user(ctx.author.name):
            await ctx.send("Schedule can only be opened by Store staff.")
            return

        if len(args) == 1 and args[0].strip() == '-h':
            await ctx.send(
                '\n'.join([
                    "!open [until] {date:mm/dd/YYYY or Day} [-f]\n",
                    "\tdate: Date or Day of Schedule to Open",
                    "\tf: Force an overwrite of an existing Open schedule for the given date",
                    f'\n\tOpens a Schedules for requests in {self.bot.readonly_channel.mention}'
                ])
            )
            return

        if len(args) >= 1 and args[0].strip().lower() == "until":
            date, force = await self.validate_open_input(ctx, list(args)[1:])
            if not date:
                return

            await self.bot.open_until(date, force=force)
            await ctx.send(f'Opened schedules until {str(date)}')

        else:
            date, force = await self.validate_open_input(ctx, list(args)[:])
            if not date:
                return

            new_schedule = await self.bot.open_given(date, force=force)
            if new_schedule:
                await ctx.send(f'Opened schedule for {new_schedule.day} - {str(new_schedule.date)}')
            else:
                await ctx.send(
                    f'Cannot open due to existing Open Schedule.\n' +
                    f'Use -f to overwrite.')

    @staticmethod
    async def validate_close_input(ctx, args: list[Any]) -> typing.Union[CommonDate, None]:
        if len(args) != 1:
            await ctx.send("Invalid input. \"!close -h\" for usage.")
            return None

        if DateTranslator.is_valid_day(args[0]):
            await ctx.send(
                "!close does not support the Day parameter, must be in format mm/dd/YYYY.\n"
                "See more by using \"!close -h\"")
            return None

        try:
            date = CommonDate.deserialize(args[0])
        except ValueError:
            await ctx.send(
                f"Invalid date in first parameter, must be in format mm/dd/YYYY.\n"
                f"See more by using \"!close -h\"")
            return None

        return date

    @commands.command(name="close")
    async def prefix_command_close(self, ctx: commands.Context, *args):
        # args: Date
        # Walk all schedule channel messages and mark ones behind date as closed
        if not self.bot.is_admin_user(ctx.author.name):
            await ctx.send("Schedule confirmation can only be issued by Store staff.")
            return

        if len(args) == 1 and args[0].strip() == '-h':
            await ctx.send(
                '\n'.join([
                    "!close_until [until] {date:mm/dd/YYYY}\n",
                    "\tuntil: Optional until which closes schedule up to and including date"
                    "\tdate: Date to close Schedules for (Less than and Equal to)",
                    f'\n\tClosing schedules prevents requests to old dates in {self.bot.readonly_channel.mention}'
                ])
            )
            return

        if len(args) >= 1 and args[0].strip().lower() == "until":
            date = await self.validate_close_input(ctx, list(args)[1:])
            if not date:
                return

            await self.bot.close_until(date)
            await ctx.send(f'Closed schedules until {DateTranslator.day_from_date(date)} - {str(date)}')

        else:
            date = await self.validate_close_input(ctx, list(args)[:])
            if not date:
                return

            await self.bot.close_given(date)
            await ctx.send(f'Closed schedule {DateTranslator.day_from_date(date)} - {str(date)}')

    @staticmethod
    async def validate_clean_input(ctx, args: list[Any]) -> typing.Union[CommonDate, None]:
        if len(args) != 1:
            await ctx.send("Invalid input. \"!clean -h\" for usage.")
            return None

        if DateTranslator.is_valid_day(args[0]):
            await ctx.send(
                "!clean does not support the Day parameter, must be in format mm/dd/YYYY.\n"
                "See more by using \"!clean -h\"")
            return None

        try:
            date = CommonDate.deserialize(args[0])
        except ValueError:
            await ctx.send(
                f"Invalid date in first parameter, must be in format mm/dd/YYYY.\n"
                f"See more by using \"!clean -h\"")
            return None

        return date

    @commands.command(name="clean")
    async def prefix_command_clean(self, ctx: commands.Context, *args):
        # args: Date
        # Walk all schedule channel messages and mark ones behind date as closed
        if not self.bot.is_admin_user(ctx.author.name):
            await ctx.send("Schedule confirmation can only be issued by Store staff.")
            return

        if len(args) == 1 and args[0].strip() == '-h':
            await ctx.send(
                '\n'.join([
                    "!clean [until] {date:mm/dd/YYYY}\n",
                    "\tuntil: Optional until which cleans schedule up to and including date"
                    "\tdate: Date to remove Schedules for (Less than and Equal to)",
                    f'\n\tCleaning schedules improves the readability of {self.bot.readonly_channel.mention}'
                ])
            )
            return

        if len(args) >= 1 and args[0].strip().lower() == "until":
            date = await self.validate_clean_input(ctx, list(args)[1:])
            if not date:
                return

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
            date = await self.validate_clean_input(ctx, list(args)[:])
            if not date:
                return

            still_open = await self.bot.clean_given(date)

            if still_open:
                response_message = f'Unable to clean {DateTranslator.day_from_date(date)} - {str(date)} as it is OPEN'
            else:
                response_message = f'Cleaned schedule {DateTranslator.day_from_date(date)} - {str(date)}'

            await ctx.send(response_message)


async def setup(bot):
    await bot.add_cog(ScheduleManager(bot))
