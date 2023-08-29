import json
import datetime
from functools import partial

from pytz import timezone

from discord.ext import commands, tasks

from util.date import DateTranslator, CommonDate
from core.bot_core import ScheduleBot
from core.bot_util import *
from model.schedule import ScheduleSlotRange
from model.schedule_config import ScheduleConfig


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
    async def prefix_command_weekly(self, ctx: commands.Context, *_):
        if not self.bot.is_admin_user(ctx.author.name):
            await ctx.send("Slot Request reminder can only be issued by Store staff.")
            return

        await self.weekly()

    @tasks.loop(time=datetime.time(hour=1))  # Time is updated based on Config in Constructor
    async def weekly_task(self):
        if DateTranslator.today().strftime("%A").lower() == self.store_config.weekly_config.run_day.lower():
            await self.weekly()

    @weekly_task.before_loop
    async def before_weekly_task(self):
        await self.bot.wait_until_ready()

    async def request(self,
                      ctx: commands.Context,
                      date: CommonDate,
                      timeslot_range: ScheduleSlotRange,
                      opponent: discord.Member):
        bound_schedule = await self.bot.find_bound_schedule(date, opened=True)
        if not bound_schedule:
            await ctx.send(f'Cannot request timeslot on Closed Schedule.\n'
                           f'See {self.bot.readonly_channel.mention} for available times.')
            return

        try:
            timeslot_range = bound_schedule.schedule.qualify_slotrange(timeslot_range)
        except ValueError:
            await ctx.send(f"Invalid timeslot range, see {self.bot.readonly_channel.mention} for valid timeslots.")
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

        await self.bot.admin_channel.send(
            f'## **Request** from **{ctx.author.name}'
            f'{" (aka. {})".format(ctx.author.nick) if ctx.author.nick else ""}**\n'
            f'Date: {str(date)}\n'
            f'Time: {str(timeslot_range)}\n'
            f'Opponent: {"{} ({})".format(opponent.nick, opponent.name) if opponent else ""}'
        )
        data_message = await self.bot.data_channel.send(
            '{\n\t"action": "request",\n'
            f'\t"name": "{ctx.author.name}",\n'
            f'\t"date": "{str(date)}",\n'
            f'\t"time": "{str(timeslot_range)}",\n'
            f'\t"opponent": "{opponent.name if opponent else ""}",\n'
            '\t"admin": {\n'
            f'\t\t"source_c_id": "{ctx.channel.id}",\n'
            f'\t\t"source_m_id": "{ctx.message.id}",\n'
            f'\t\t"author_id": "{ctx.author.id}",\n'
            f'\t\t"opponent_id": "{opponent.id if opponent else ""}"\n'
            '\t}\n'
            "}")
        await self.bot.admin_channel.send(f'req_id: {data_message.id}')

    async def cancel(self,
                     ctx: commands.Context,
                     date: CommonDate,
                     timeslot_range: ScheduleSlotRange):
        bound_schedule = await self.bot.find_bound_schedule(date, opened=True)
        if not bound_schedule:
            await ctx.send(f'Cannot request timeslot on Closed Schedule.\n'
                           f'See {self.bot.readonly_channel.mention} for available times.')
            return

        try:
            timeslot_range = bound_schedule.schedule.qualify_slotrange(timeslot_range)
        except ValueError:
            await ctx.send(f"Invalid timeslot range, see {self.bot.readonly_channel.mention} for valid timeslots.")
            return

        # Must check if those timeslots are owned
        owned_tables = [
            table.check(timeslot_range,
                        partial(timeslot_is_owned_by_author, ctx.author, None))
            for table in bound_schedule.schedule.tables.values()
        ]
        if not any(owned_tables):
            await ctx.send(f'Timeslot Range {timeslot_range} is not all owned by requestor for {str(date)}.\n'
                           f'See {self.bot.readonly_channel.mention} for allocated times.')
            return

        await self.bot.admin_channel.send(
            f'## **Cancel** from **{ctx.author.name}'
            f'{" (aka. {})".format(ctx.author.nick) if ctx.author.nick else ""}**\n'
            f'Date: {str(date)}\n'
            f'Time: {str(timeslot_range)}'
        )
        data_message = await self.bot.data_channel.send(
            '{\n\t"action": "cancel",\n'
            f'\t"name": "{ctx.author.name}",\n'
            f'\t"date": "{str(date)}",\n'
            f'\t"time": "{str(timeslot_range)}",\n'
            '\t"admin": {\n'
            f'\t\t"source_c_id": "{ctx.channel.id}",\n'
            f'\t\t"source_m_id": "{ctx.message.id}",\n'
            f'\t\t"author_id": "{ctx.author.id}"\n'
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
                    f'Timeslot is already owned by {author.nick} ({author.name}) '
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

    @commands.command(name="request")
    async def prefix_command_request(self, ctx: commands.Context, *args):
        # args: Date and Timeslot Range, Player 2 (Mention)
        if len(args) == 1 and args[0].strip() == '-h':
            await ctx.send(
                '\n'.join([
                    "!request {date:mm/dd/YYYY or Day} {start-timeslot}[-{end-timeslot}] [opponent-mention]\n",
                    "\tdate: Date or Day to schedule Table",
                    "\tstart-timeslot: hr:m{am/pm} for Timeslot request",
                    "\tend-timeslot: (Optional) hr:m{am/pm} for end of Timeslot request (Not included in request).'",
                    "\t\tWhen not specified, only 1 timeslot will be requested.",
                    "\topponent-mention: (Optional) @mention of Opponent",
                    f'\n\tIssues a scheduling request for a Store Table at a given date and time.'
                ])
            )
            return

        if len(args) > 3 or len(args) < 2:
            await ctx.send("Invalid input. See \"!request -h\" for usage.")
            return

        try:
            date = CommonDate.deserialize(args[0])
        except ValueError:
            await ctx.send(
                f"Invalid date in first parameter, must be in format mm/dd/YYYY or a Day.\n"
                f"See more by using \"!request -h\"")
            return

        try:
            timeslot_range = ScheduleSlotRange.deserialize(args[1].strip())
        except ValueError:
            await ctx.send(
                f"Invalid timeslot in second parameter, start-timeslot[-end-timeslot].\n"
                f"See more by using \"!request -h\"")
            return

        opponent = None
        if len(args) == 3:
            raw_opponent_str = args[2].strip()
            try:
                opponent = await self.bot.guild.fetch_member(ScheduleBot.convert_mention_to_id(raw_opponent_str))
                if not opponent:
                    raise ValueError

            except ValueError:
                print(f'Cannot get User ID from {raw_opponent_str}')
                await ctx.send(f"Opponent mention {raw_opponent_str} is not valid."
                               f"See usage details by using \"!request -h\"")
                return
        # End Raw Input Validation

        await self.request(ctx, date, timeslot_range, opponent)

    @commands.command(name="cancel")
    async def prefix_command_cancel(self, ctx: commands.Context, *args):
        # args: Date and Timeslot Range
        if len(args) == 1 and args[0].strip() == '-h':
            await ctx.send(
                '\n'.join([
                    "!cancel {date:mm/dd/YYYY or Day} {start-timeslot}[-{end-timeslot}]\n",
                    "\tdate: Date or Day to cancel request",
                    "\tstart-timeslot: hr:m{am/pm} for cancel request",
                    "\tend-timeslot: (Optional) hr:m{am/pm} for end of cancel request (Not included in request).'",
                    "\t\tWhen not specified, only 1 timeslot will be canceled.",
                    f'\n\tIssues a scheduling request for a Store Table at a given date and time.'
                ])
            )
            return

        if len(args) != 2:
            await ctx.send("Invalid input. See \"!cancel -h\" for usage.")
            return

        try:
            date = CommonDate.deserialize(args[0])
        except ValueError:
            await ctx.send(
                f"Invalid date in first parameter, must be in format mm/dd/YYYY or a Day.\n"
                f"See more by using \"!cancel -h\"")
            return

        try:
            timeslot_range = ScheduleSlotRange.deserialize(args[1].strip())
        except ValueError:
            await ctx.send(
                f"Invalid timeslot in second parameter, start-timeslot[-end-timeslot].\n"
                f"See more by using \"!cancel -h\"")
            return
        # End Raw Input Validation

        await self.cancel(ctx, date, timeslot_range)

    @commands.command(name='accept')
    async def prefix_command_accept(self, ctx: commands.Context, *args):
        # args: req_id
        if not self.bot.is_admin_user(ctx.author.name):
            await ctx.send("Schedule confirmation can only be issued by Store staff.")
            return

        if len(args) == 1 and args[0].strip() == '-h':
            await ctx.send(
                '\n'.join([
                    "!accept [req_id:] {req_id}\n",
                    "\treq_id: Discord Message ID of Bot Data message",
                    f'\n\tAccepts a scheduling request or cancellation for a Store Table at a given date and time.'
                ])
            )
            return

        if len(args) != 1 and len(args) != 2:
            await ctx.send("Invalid input. See \"!accept -h\" for usage.")
            return

        if len(args) == 2:
            if args[0].lower() == 'req_id:':
                data_id = args[1]
            else:
                await ctx.send("Invalid input. See \"!accept -h\" for usage.")
                return
        else:
            data_id = args[0]
        # End Raw Input Validation

        await self.accept(ctx, data_id)

    @commands.command(name="add")
    async def prefix_command_add(self, ctx: commands.Context, *args):
        # args: Date and Timeslot Range, Player 1 (Name), [Player 2 (Name)]
        if not self.bot.is_admin_user(ctx.author.name):
            await ctx.send("Schedule can only be modified directly by Store staff.")
            return

        if len(args) == 1 and args[0].strip() == '-h':
            await ctx.send(
                '\n'.join([
                    "!add {date:mm/dd/YYYY or Day} {start-timeslot}[-{end-timeslot}] {user-name} [opponent-name]\n",
                    "\tdate: Date or Day to schedule Table",
                    "\tstart-timeslot: hr:m{am/pm} for Timeslot request",
                    "\tend-timeslot: (Optional) hr:m{am/pm} for end of Timeslot request (Not included in request).'",
                    "\t\tWhen not specified, only 1 timeslot will be requested.",
                    "\tuser-name: Name (not nickname) of Requester",
                    "\topponent-name: Name (not nickname) of Opponent",
                    f'\n\tIssues a scheduling request for a Store Table at a given date and time.'
                ])
            )
            return

        try:
            date = CommonDate.deserialize(args[0])
        except ValueError:
            await ctx.send(
                f"Invalid date in first parameter, must be in format mm/dd/YYYY or a Day.\n"
                f"See more by using \"!add -h\"")
            return

        try:
            timeslot_range = ScheduleSlotRange.deserialize(args[1].strip())
        except ValueError:
            await ctx.send(
                f"Invalid timeslot in second parameter, start-timeslot[-end-timeslot].\n"
                f"See more by using \"!add -h\"")
            return

        members = [member async for member in self.bot.guild.fetch_members()]
        author = discord.utils.get(members, name=args[2].strip())

        opponent = None
        if len(args) == 4:
            raw_opponent_str = args[3].strip()
            try:
                opponent = discord.utils.get(members, name=raw_opponent_str)
                if not opponent:
                    raise ValueError

            except ValueError:
                print(f'Cannot get User ID from {raw_opponent_str}')
                await ctx.send(f"Opponent mention {raw_opponent_str} is not valid."
                               f"See usage details by using \"!add -h\"")
                return
        # End Raw Input Validation

        await self.add(ctx, date, timeslot_range, author, opponent)

    @commands.command(name="remove")
    async def prefix_command_remove(self, ctx: commands.Context, *args):
        # args: Date, Timeslot Range, Requester, [Opponent]
        if not self.bot.is_admin_user(ctx.author.name):
            await ctx.send("Schedule can only be modified directly by Store staff.")
            return

        if len(args) == 1 and args[0].strip() == '-h':
            await ctx.send(
                '\n'.join([
                    "!add {date:mm/dd/YYYY or Day} {start-timeslot}[-{end-timeslot}] {user-name} [opponent-name]\n",
                    "\tdate: Date or Day to schedule Table",
                    "\tstart-timeslot: hr:m{am/pm} for Timeslot request",
                    "\tend-timeslot: (Optional) hr:m{am/pm} for end of Timeslot request (Not included in request).'",
                    "\t\tWhen not specified, only 1 timeslot will be requested."
                    "\tuser-name: Name (not nickname) of Requester",
                    "\topponent-name: Name (not nickname) of Opponent",
                    f'\n\tRemoves a scheduling request for a Store Table at a given date and time.'
                ])
            )
            return

        try:
            date = CommonDate.deserialize(args[0])
        except ValueError:
            await ctx.send(
                f"Invalid date in first parameter, must be in format mm/dd/YYYY or a Day.\n"
                f"See more by using \"!remove -h\"")
            return

        try:
            timeslot_range = ScheduleSlotRange.deserialize(args[1].strip())
        except ValueError:
            await ctx.send(
                f"Invalid timeslot in second parameter, start-timeslot[-end-timeslot].\n"
                f"See more by using \"!remove -h\"")
            return

        members = [member async for member in self.bot.guild.fetch_members()]
        author = discord.utils.get(members, name=args[2].strip())

        opponent = None
        if len(args) == 4:
            raw_opponent_str = args[3].strip()
            try:
                opponent = discord.utils.get(members, name=raw_opponent_str)
                if not opponent:
                    raise ValueError

            except ValueError:
                print(f'Cannot get User ID from {raw_opponent_str}')
                await ctx.send(f"Opponent mention {raw_opponent_str} is not valid."
                               f"See usage details by using \"!remove -h\"")
                return
        # End Raw Input Validation

        await self.remove(ctx, date, timeslot_range, author, opponent)


async def setup(bot):
    await bot.add_cog(SlotManager(bot))
