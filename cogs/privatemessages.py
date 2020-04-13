import discord
import asyncio
import config
import re
from datetime import date, datetime
from discord.ext import commands
from modules import command, embed_maker

open_tickets = {}

class PrivateMessages(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.help = self.pm_help
        self.commands = ['help', 'report_user', 'report_issue']

    async def process_pm(self, message):
        cmd, args = self.parse_msg(message)
        try:
            called_cmd = self.__getattribute__(cmd)
            return await called_cmd(message, args)
        except AttributeError:
            if message.content.startswith(config.DEFAULT_PREFIX):
                return await self.pm_help(message, args)

    def parse_msg(self, message):
        content = message.content
        content_list = content.split(' ')
        cmd = content_list[0].replace(config.DEFAULT_PREFIX, '')
        args = ' '.join(content_list[1:])
        return cmd, args

    @commands.command(dm_only=True, help='get some pm help smh. Displays all pm commands or info about a specific pm command', usage='pm_help (command)', examples=['pm_help', 'pm_help report'], cls=command.Command)
    async def pm_help(self, ctx, help_cmd=None):
        embed_colour = config.DEFAULT_EMBED_COLOUR
        all_commands = self.commands

        # Check if user wants to know about a specific command
        if not help_cmd:
            # Returns list of all pm commands
            embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=f'**Prefix** : `{config.DEFAULT_PREFIX}`\nFor additional info on a command, type `{config.DEFAULT_PREFIX}help [command]`')
            embed.set_author(name=f'Help', icon_url=self.bot.user.avatar_url)
            embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
            embed.add_field(name=f'>Pm Commands', value=" \| ".join(f'`{cmd}`' for cmd in all_commands), inline=False)

            return await ctx.author.send(embed=embed)
        else:
            if help_cmd in all_commands:
                cmd = getattr(self, help_cmd)
                examples = f' | '.join(cmd.examples)
                cmd_help = f"""
                        **Description:** {cmd.help}
                        **Usage:** {cmd.usage}
                        **Examples:** {examples}
                        """
                embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=cmd_help)
                embed.set_author(name=f'Help - {cmd.name}', icon_url=self.bot.user.avatar_url)
                embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
                return await ctx.author.send(embed=embed)
            else:
                embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=f'{help_cmd} is not a valid command')
                return await ctx.author.send(embed=embed)

    @commands.command(dm_only=True, help='Starts the process of reporting a user', usage='report_user', examples=['report_user'], cls=command.Command)
    async def report_user(self, ctx, _=''):
        embed_colour = config.DEFAULT_EMBED_COLOUR

        # Gets the user id's of users that person wants to report
        async def users():
            def user_check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

            users_embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=f'What user(s) do you want to report?')
            users_embed.set_author(name=f'User(s)', icon_url=self.bot.user.avatar_url)
            users_embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
            users_embed.add_field(name=f'>Valid input', value='User id. If multiple, separate them by commas.', inline=False)
            await ctx.author.send(embed=users_embed)

            # wait for message from user
            try:
                user_message = await self.bot.wait_for('message', check=user_check, timeout=90)
            except asyncio.TimeoutError:
                err_msg = 'Report user function timed out'
                err_embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=err_msg)
                err_embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
                await ctx.author.send(embed=err_embed)
                return None

            # checks if user ids are valid, if not, returns false
            u_ids = user_message.content.replace(' ', '').split(',')
            for i in u_ids:
                if not i.isdigit():
                    return False
                u = self.bot.get_user(int(i))
                if u is None:
                    return False
            else:
                return u_ids

        # gets issue(s) from person
        async def issues():
            def issues_check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

            issues_embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=f'Why are you reporting them?')
            issues_embed.set_author(name=f'Issue(s)', icon_url=self.bot.user.avatar_url)
            issues_embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
            await ctx.author.send(embed=issues_embed)

            # waits for message from user for 3 minutes
            try:
                issues_message = await self.bot.wait_for('message', check=issues_check, timeout=3*60)
            except asyncio.TimeoutError:
                err_msg = 'Report user function timed out'
                err_embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=err_msg)
                err_embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
                await ctx.author.send(embed=issues_embed)
                return None

            issues_txt = issues_message.content
            return issues_txt

        # gets user ids and returns error msg to user if one of them is invalid
        user_ids = await users()
        if user_ids is None:
            return
        if not user_ids:
            error_msg = 'One or more of the user ids are invalid'
            embed = discord.Embed(colour=discord.Colour.red(), timestamp=datetime.now(), description=error_msg)
            embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
            return await ctx.author.send(embed=embed)

        # gets issue string nad return error to user if issue is too long
        issues_str = await issues()
        if issues_str is None:
            return
        if len(issues_str) > 1500:
            error_msg = 'The issues you typed out were too long, sorry about that, please shorten it and wait for mods to ask for more detail.'
            embed = discord.Embed(colour=discord.Colour.red(), timestamp=datetime.now(), description=error_msg)
            embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
            return await ctx.author.send(embed=embed)

        main_guild = self.bot.get_guild(config.MAIN_SERVER)
        ticket_embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        ticket_embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
        ticket_embed.set_author(name='New Ticket - Reported User(s)', icon_url=main_guild.icon_url)
        ticket_embed.add_field(name='>Reporter', value=f'<@{ctx.author.id}>', inline=False)
        ticket_embed.add_field(name='>Reported User(s)', value='\n'.join(f'<@{u_id}>' for u_id in user_ids), inline=False)
        ticket_embed.add_field(name='>Issue(s)', value=issues_str, inline=False)

        return await self.send_ticket_embed(ctx, main_guild, ticket_embed)

    @commands.command(dm_only=True, help='Starts the process of reporting an issue', usage='report_issue', examples=['report_issue'], cls=command.Command)
    async def report_issue(self, ctx, _=''):
        # Functions the same way as report_user, but doesnt need user ids
        embed_colour = config.DEFAULT_EMBED_COLOUR

        async def issues():
            def issues_check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

            embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=f'What issue(s) would you like to report?')
            embed.set_author(name=f'Issue(s)', icon_url=self.bot.user.avatar_url)
            embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
            await ctx.author.send(embed=embed)

            try:
                issues_message = await self.bot.wait_for('message', check=issues_check, timeout=3*60)
            except asyncio.TimeoutError:
                error_msg = 'Report user function timed out'
                embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=error_msg)
                embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
                await ctx.author.send(embed=embed)
                return None

            issues_str = issues_message.content
            return issues_str

        issues_str = await issues()
        if issues_str is None:
            return
        if len(issues_str) > 1500:
            error_msg = 'The issues you typed out were too long, sorry about that. If you forgot to copy before you sent it, here\'s a copy'
            embed = discord.Embed(colour=discord.Colour.red(), timestamp=datetime.now(), description=error_msg)
            embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
            await ctx.author.send(embed=embed)
            return await ctx.send(issues_str)

        main_guild = self.bot.get_guild(config.MAIN_SERVER)
        ticket_embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        ticket_embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
        ticket_embed.set_author(name='New Ticket - Reported Issue(s)', icon_url=main_guild.icon_url)
        ticket_embed.add_field(name='>Reporter', value=f'<@{ctx.author.id}>', inline=False)
        ticket_embed.add_field(name='>Issue(s)', value=issues_str, inline=False)

        return await self.send_ticket_embed(ctx, main_guild, ticket_embed)

    async def send_ticket_embed(self, ctx, guild, embed):
        ticket_category = discord.utils.find(lambda c: c.name == 'Open Tickets', guild.categories)

        if ticket_category is None:
            # get all staff roles
            staff_roles = filter(lambda r: r.permissions.manage_messages, guild.roles)

            # staff roles can read channels in category, users cant
            overwrites = dict.fromkeys(staff_roles, discord.PermissionOverwrite(read_messages=True, send_messages=True))
            overwrites[guild.default_role] = discord.PermissionOverwrite(read_messages=False)

            ticket_category = await guild.create_category(name='Open Tickets', overwrites=overwrites)

        today = date.today()
        date_str = today.strftime('%Y-%m-%d')
        ticket_channel = await guild.create_text_channel(f'{date_str}-{ctx.author.name}', category=ticket_category)
        await ticket_channel.send(embed=embed)

        open_tickets[ticket_channel.id] = ctx.author.id

        msg = 'This issue has been forwarded to the moderators'
        embed = discord.Embed(colour=discord.Colour.green(), timestamp=datetime.now(), description=msg)
        embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
        return await ctx.author.send(embed=embed)

    @commands.command(help='Closes the current ticket', usage='close_ticket', examples=['close_ticket'], clearance='Mod', cls=command.Command)
    @commands.has_permissions(manage_messages=True)
    async def close_ticket(self, ctx):
        regex = re.compile(r'(20\d*-\d*-\d*-.*?)')
        match = re.match(regex, ctx.message.channel.name)
        if match:
            await ctx.channel.delete()
        else:
            embed = embed_maker.message(ctx, 'Invalid ticket channel')
            return await ctx.send(embed=embed)

    @commands.command(help='Closes the current ticket', usage='close_ticket', examples=['close_ticket'], clearance='Mod', cls=command.Command)
    async def get_reporter(self, ctx):
        if ctx.channel.id not in open_tickets:
            embed = embed_maker.message(ctx, 'Invalid ticket channel')
            return await ctx.send(embed=embed)

        user_id = open_tickets[ctx.channel.id]
        if user_id:
            user = self.bot.get_user(user_id)
            if user is None:
                user = await self.bot.fetch_user(user_id)
            await ctx.channel.set_permissions(user, read_messages=True, send_messages=True)
            return await ctx.channel.send(f'<@{user.id}>')


def setup(bot):
    bot.add_cog(PrivateMessages(bot))
