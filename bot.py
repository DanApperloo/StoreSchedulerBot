import asyncio
import logging
import argparse
import os
import re

from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler

import discord
from discord.ext import commands

from model.schedule_config import ScheduleConfig
from util.date import DateTranslator
from core.bot_core import ScheduleBot

########################################################################################################################
# Bot Configuration and Initialization
########################################################################################################################
parser = argparse.ArgumentParser()
group = parser.add_argument_group()
group.add_argument('-e', '--env', dest='env', default='.env',
                   help="Environment file for dotenv")
group.add_argument('-s', '--store', dest='store', default='default.store',
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
    bot.remove_command('help')

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

        await bot.initialize_direct_channels()
        # Register Slash commands in the valid guilds
        await bot.tree.sync(guild=discord.Object(id=bot.GUILD_ID))
        bot.unpause_cogs.set()

    @bot.command(name="list", aliases=["ls", "help"])
    async def list_commands(ctx: commands.Context, _=None):
        header = "### General Commands"
        public_commands = [
            "**!list** - List Commands",
            "**!request** - Request a Table Slot",
            "**!cancel** - Cancel a Table Slot"
        ]
        footer = "Use \"!<command> -h\" for per-command help."

        if not bot.is_admin_user(ctx.author.name):
            await ctx.send(
                header + '\n' + '\n'.join(public_commands) + '\n\n' + footer
            )
            return

        admin_header = "### Admin Commands"
        admin_commands = [
            "**!accept** - Accept an Admin Request",
            "**!add** - Add a Table Slot reservation",
            "**!remove** - Remove a Table Slot reservation",
            "**!open** - Open a Schedule",
            "**!close**- Close a Schedule",
            "**!clean** - Delete a Schedule",
            "**!nightly** - Manually nightly Schedule maintenance"
        ]

        await ctx.send(
            content=header + '\n' + '\n'.join(public_commands) + '\n\n' + admin_header + '\n' + '\n'.join(
                    admin_commands) + '\n\n' + footer,
            delete_after=60  # Delete after 60s
        )

    await load_extensions(bot)
    await bot.start(bot.TOKEN)


if __name__ == '__main__':
    asyncio.run(main())
