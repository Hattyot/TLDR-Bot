import discord
import os
import aiohttp
import re
import traceback
from modules import database
from discord.ext import commands
from config import BOT_TOKEN, DEFAULT_EMBED_COLOUR, DEFAULT_PREFIX as prefix

db = database.Connection()
paused = False


async def get_prefix(bot, message):
    return commands.when_mentioned_or(prefix)(bot, message)


class TLDR(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=get_prefix, case_insensitive=True, help_command=None)

        self.session = aiohttp.ClientSession(loop=self.loop)

        # Load Cogs
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                self.load_extension(f'cogs.{filename[:-3]}')
                print(f'{filename[:-3]} is now loaded')

    async def on_command_error(self, ctx, exception):
        trace = exception.__traceback__
        verbosity = 4
        lines = traceback.format_exception(type(exception), exception, trace, verbosity)
        traceback_text = ''.join(lines)

        print(traceback_text)
        print(exception)

        # Returns if bot isn't main bot
        if self.user.id != 669877023753109524:
            return

        # send error message to certain channel in a guild if error happens during bot run
        guild = self.get_guild(669640013666975784)
        if guild is not None:
            channel = self.get_channel(671991712800964620)
            embed_colour = DEFAULT_EMBED_COLOUR
            embed = discord.Embed(colour=embed_colour, title=f'{ctx.command.name} - Command Error', description=f'```{exception}\n{traceback_text}```')
            return await channel.send(embed=embed)

    async def on_message(self, message):
        if message.author.bot:
            return

        # just checks if message was sent in pms
        if message.guild is None:
            pm_cog = self.get_cog('PrivateMessages')
            return await pm_cog.process_pm(message)

        # checks if bot was mentioned, if was invoke help command
        regex = re.compile(rf'<@!?{self.user.id}>')
        match = re.findall(regex, message.content)

        if match:
            ctx = await self.get_context(message)
            utility_cog = self.get_cog('Utility')
            return await utility_cog.help(ctx)

        if message.content.startswith(prefix):
            return await self.process_commands(message)

        # Starts leveling process
        levels_cog = self.get_cog('Levels')
        await levels_cog.process_message(message)

        honours_channels = db.get_levels('honours_channels', message.guild.id)
        if message.channel.id in honours_channels:
            await levels_cog.process_hp_message(message)

    async def process_commands(self, message):
        ctx = await self.get_context(message)
        utils_cog = self.get_cog('Utils')
        clearance = await utils_cog.get_user_clearance(message.guild.id, message.author.id)
        if ctx.command.clearance not in clearance:
            return

        await self.invoke(ctx)

    async def on_ready(self):
        bot_game = discord.Game(f'@me')
        await self.change_presence(activity=bot_game)

        print(f'{self.user} is ready')

        # Run old timers
        timer_cog = self.get_cog('Timer')
        await timer_cog.run_old_timers()

    async def on_member_update(self, before, after):
        # Invalidates clearance cache if user roles changed
        if before.roles != after.roles:
            utils_cog = self.get_cog('Utils')
            utils_cog.get_user_clearance.invalidate(after.guild.id, after.id)

    async def on_member_remove(self, member):
        db.levels.update_one({'guild_id': member.guild.id}, {'$unset': {f'users.{member.id}': ''}})

    async def close(self):
        await super().close()
        await self.session.close()

    def run(self):
        super().run(BOT_TOKEN, reconnect=False)


def main():
    TLDR().run()


if __name__ == '__main__':
    main()
