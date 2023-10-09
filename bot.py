import asyncio
import logging
import argparse
import os
import re

from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler

import discord
from discord.ext import commands

from cogs.util import Restriction, Prefix
from model.schedule_config import ScheduleConfig, DEFAULT_CONFIG
from util.date import DateTranslator
from core.bot_core import ScheduleBot
from core.util import Channel

########################################################################################################################
# Bot Configuration and Initialization
########################################################################################################################
parser = argparse.ArgumentParser()
group = parser.add_argument_group()
group.add_argument('-e', '--env', dest='env', default='.env',
                   help="Environment file for dotenv")
group.add_argument('-s', '--store', dest='store', default=DEFAULT_CONFIG,
                   help="Json file for Store Config")
cmd_args = parser.parse_args()

if not os.path.isfile(cmd_args.env):
    raise FileNotFoundError(cmd_args.env)

if not os.path.isfile(cmd_args.store):
    raise FileNotFoundError(cmd_args.store)

# Prep environment for private configuration
load_dotenv(dotenv_path=cmd_args.env)

# Support Singletons
store_config = ScheduleConfig(config_file=cmd_args.store)
date_translator = DateTranslator()

# Prep the Bot Logging
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
logging.getLogger('discord.http').setLevel(logging.INFO)

handler = logging.handlers.RotatingFileHandler(
    filename='discord.log',
    encoding='utf-8',
    maxBytes=32 * 1024 * 1024,  # 32 MiB
    backupCount=5,  # Rotate through 5 files
)
formatter = logging.Formatter(
    '[{asctime}] [{levelname:<8}] {name}: {message}',
    '%Y-%m-%d %H:%M:%S',
    style='{')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Prep the Bot
intents = discord.Intents.default()
intents.members = True
intents.message_content = True


########################################################################################################################
# Application Trigger
########################################################################################################################
async def load_extensions(bot: ScheduleBot):
    for filename in os.listdir(os.path.join(".", "cogs")):
        if (re.match(r'^cog.*', filename, flags=re.IGNORECASE) and
                filename.endswith(".py")):
            # cut off the .py from the file name
            await bot.load_extension(f"cogs.{filename[:-3]}")


async def main():
    bot = ScheduleBot(command_prefix='!', intents=intents)

    @bot.event
    async def on_guild_join(guild: discord.Guild):
        if guild.id != bot.GUILD_ID:
            print(f'Unexpected Server {guild.name}:{guild.id}, disconnecting.')
            await guild.leave()
        else:
            print(f'Joined Server {guild.name}:{guild.id}')

    @bot.event
    async def on_ready():
        await bot.wait_until_ready()

        for guild in bot.guilds:
            print(
                f'{bot.user} is connected to the following Server:\n'
                f'{guild.name}(id: {guild.id})'
            )

            if guild.id != bot.GUILD_ID:
                print(f'Unexpected Server {guild.name}:{guild.id}, disconnecting.')
                await guild.leave()

        # Translate Channels and Internal Caches
        await bot.translate_config()
        await bot.regenerate_schedule_cache()

        # Configure Cog Restrictions
        Restriction.set_admin(bot.admins)
        Restriction.set_channel(Channel.SCHEDULE_ADMIN, bot.admin_channel)
        Restriction.set_channel(Channel.SCHEDULE_REQUEST, bot.request_channel)

        # Start Command Processing
        bot.unpause_cogs.set()

    @bot.event
    async def on_command_error(ctx: commands.Context, error):
        if isinstance(error, commands.CommandNotFound):
            await ctx.message.reply(str(error))
            return

        command = ctx.command
        if command and command.has_error_handler():
            return

        cog = ctx.cog
        if cog and cog.has_error_handler():
            return

        logger.error('Ignoring exception in command %s', command, exc_info=error)

    @bot.command(name="sync")
    @Prefix.admin_only()
    @Prefix.restricted_channel(Channel.SCHEDULE_ADMIN)
    async def sync(ctx: commands.Context):
        # Sync Slash Commands
        await bot.tree.sync(guild=discord.Object(id=bot.GUILD_ID))
        await ctx.message.add_reaction("👍")

    await load_extensions(bot)
    await bot.start(bot.TOKEN)


if __name__ == '__main__':
    asyncio.run(main())
