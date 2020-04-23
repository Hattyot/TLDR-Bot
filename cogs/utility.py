import time
import discord
import re
import config
from datetime import datetime
from discord.ext import commands
from modules import database, command, embed_maker, format_time

db = database.Connection()


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='Get bot\'s latency', usage='ping', examples=['ping'], clearance='User', cls=command.Command)
    async def ping(self, ctx):
        before = time.monotonic()
        message = await ctx.send("Pong")
        ping = (time.monotonic() - before) * 1000
        await message.edit(content=f"\U0001f3d3 Pong   |   {int(ping)}ms")

    @commands.command(help='End an anon_poll early. This command doesn\'t work on polls that were interrupted by a bot restart/shutdown', usage='end_poll [#Channel] [message id]', examples=['end_poll #polls 673479831719247925'], clearance='Mod', cls=command.Command)
    async def end_poll(self, ctx, channel=None, message_id=None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        if not ctx.message.channel_mentions:
            return await embed_maker.command_error(ctx, '[#Channel]')

        channel = ctx.message.channel_mentions[0]

        if message_id is None:
            return await embed_maker.command_error(ctx, '[#Channel]')

        try:
            message = await channel.fetch_message(int(message_id))
        except discord.NotFound:
            embed = embed_maker.message(ctx, 'I couldn\'t find the message, the message is either deleted, or you put the wrong channel', colour='red')
            return await ctx.send(embed=embed)

        poll = db.get_polls(ctx.guild.id, message_id)
        if poll is None:
            embed = embed_maker.message(ctx, 'That is not a valid poll', colour='red')
            return await ctx.send(embed=embed)

        message_id = message.id

        db.timers.update_one({'guild_id': ctx.guild.id}, {'$pull': {'timers': {'extras.message_id': message_id}}})
        db.polls.update_one({'guild_id': ctx.guild.id}, {'$unset': {f'polls.{message_id}': ''}})
        db.get_polls.invalidate(ctx.guild.id, message_id)

        # Get question from embed
        poll_embed = message.embeds[0]
        description = poll_embed.description
        question_regex = re.compile(r'(\*\*.*\*\*)')
        match = re.findall(question_regex, description)
        if match:
            question = match[0]
        else:
            embed = embed_maker.message(ctx, 'Couldn\'t parse question from that poll, this is weird', colour='red')
            return await ctx.send(embed=embed)

        # Calculate results
        emote_count = poll
        sorted_emote_count = sorted(emote_count.items(), key=lambda x: x[1], reverse=True)
        total_emotes = sum(emote_count.values())
        new_description = question

        if total_emotes == 0:
            description += '\n'.join(f'{emote} **- {emote_count}** | **0%**' for emote, emote_count in sorted_emote_count)
        else:
            description += '\n'.join(f'{emote} **- {emote_count}** | **{(emote_count * 100)/total_emotes}%**' for emote, emote_count in sorted_emote_count)

        poll_embed.description = new_description
        poll_embed.timestamp = datetime.now()
        poll_embed.set_footer(text='Ended at')
        await message.edit(embed=poll_embed)

        menu_cog = self.bot.get_cog('Menu')
        if message_id in menu_cog.no_expire_menus:
            del menu_cog.no_expire_menus[message_id]

        embed = embed_maker.message(ctx, 'Ended poll', colour='green')
        return await ctx.send(embed=embed)

    @commands.command(help='Create an anonymous poll. with options adds numbers as reactions, without it just adds thumbs up and down. after x minutes (default 5) is up, results are displayed',
                      usage='anon_poll [-q question] (-o option1, option2, ...)/(-o [emote: option], [emote: option], ...) (-t [(num)m/h/d\)',
                      examples=['anon_poll -q best food? -o pizza, burger, fish and chips, salad', 'anon_poll -q Do you guys like pizza? -t 2m', 'anon_poll -q Where are you from? -o [🇩🇪: Germany], [🇬🇧: UK] -t 1d'],
                      clearance='Mod', cls=command.Command)
    async def anon_poll(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = self.parse_poll_args(args)
        question = args['q']
        options = args['o']
        poll_time = format_time.parse(args['t'])
        option_emotes = args['o_emotes']

        err = ''
        if poll_time is None:
            err = 'Invalid time arg'

        if option_emotes is None:
            err = 'Error with custom option emotes'

        if question == '' or options == '':
            err = 'Empty arg'

        if len(options) > 9:
            err = 'Too many options'

        if err:
            embed = embed_maker.message(ctx, err, colour='red')
            return await ctx.send(embed=embed)

        description = f'**"{question}"**\n\n'
        colour = config.DEFAULT_EMBED_COLOUR
        embed = discord.Embed(title='Anonymous Poll', colour=colour, description=description, timestamp=datetime.now())
        embed.set_footer(text='Started at', icon_url=ctx.guild.icon_url)

        if not options:
            emotes = ['👍', '👎']
        else:
            if option_emotes:
                emotes = list(option_emotes.keys())
                options = list(option_emotes.values())
            else:
                all_num_emotes = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
                emotes = all_num_emotes[:len(options)]

            description += '\n'.join(f'{e} | **{o}**' for o, e in zip(options, emotes))
            embed.description = description

        poll_msg = await ctx.send(embed=embed)
        voted_users = {}

        async def count(user, msg, emote):
            if msg.id != poll_msg.id:
                return

            if user.id in voted_users:
                if voted_users[user.id]['buffer'] >= 5:
                    return await user.send(f'Don\'t spam please')
                voted_users[user.id]['buffer'] += 1

                previous_emote = voted_users[user.id]['emote']
                if emote == previous_emote:
                    return await user.send(f'Your vote has been already counted towards: {emote}')

                db.polls.update_one({'guild_id': ctx.guild.id},
                                    {'$inc': {f'polls.{msg.id}.{emote}': 1,
                                              f'polls.{msg.id}.{previous_emote}': -1}})

                voted_users[user.id]['emote'] = emote

                return await user.send(f'Your vote has been changed to: {emote}')

            voted_users[user.id] = {
                'emote': emote,
                'buffer': 0  # checking for spammers
            }
            db.polls.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'polls.{msg.id}.{emote}': 1}})

        poll = dict.fromkeys(emotes, 0)
        buttons = dict.fromkeys(emotes, count)

        menu_cog = self.bot.get_cog('Menu')
        timer_cog = self.bot.get_cog('Timer')

        expires = round(time.time()) + round(poll_time)
        await timer_cog.create_timer(expires=expires, guild_id=ctx.guild.id, event='anon_poll', extras={'message_id': poll_msg.id, 'channel_id': poll_msg.channel.id, 'question': question})
        await menu_cog.new_no_expire_menu(poll_msg, buttons)

        db.polls.update_one({'guild_id': ctx.guild.id}, {'$set': {f'polls.{poll_msg.id}': poll}})

        return await ctx.message.delete(delay=5)

    @commands.Cog.listener()
    async def on_anon_poll_timer_over(self, timer):
        message_id = timer['extras']['message_id']
        guild_id = timer['guild_id']
        poll = db.get_polls(guild_id, message_id)
        if not poll:
            return

        db.polls.update_one({'guild_id': guild_id}, {'$unset': {f'polls.{message_id}': ""}})
        db.get_polls.invalidate(guild_id, message_id)

        question = timer['extras']['question']
        emote_count = poll

        channel = self.bot.get_channel(timer['extras']['channel_id'])
        message = await channel.fetch_message(message_id)

        sorted_emote_count = sorted(emote_count.items(), key=lambda x: x[1], reverse=True)
        total_emotes = sum(emote_count.values())
        description = f'**{question}**\n'

        if total_emotes == 0:
            description += '\n'.join(f'{emote} **- {emote_count}** | **0%**' for emote, emote_count in sorted_emote_count)
        else:
            description += '\n'.join(f'{emote} **- {emote_count}** | **{(emote_count * 100)/total_emotes}%**' for emote, emote_count in sorted_emote_count)

        embed = message.embeds[0]
        embed.description = description
        embed.timestamp = datetime.now()
        embed.set_footer(text='Ended at')

        menu_cog = self.bot.get_cog('Menu')
        if message_id in menu_cog.no_expire_menus:
            del menu_cog.no_expire_menus[message_id]

        await message.edit(embed=embed)
        return await message.clear_reactions()

    @commands.command(help='Create a poll. with options adds numbers as reactions, without it just adds thumbs up and down.',
                      usage='poll [-q question] (-o option1, option2, ...)/(-o [emote: option], [emote: option], ...)',
                      examples=['poll -q best food? -o pizza, burger, fish and chips, salad -l 2', 'poll -q Do you guys like pizza?', 'anon_poll -q Where are you from? -o [🇩🇪: Germany], [🇬🇧: UK]'],
                      clearance='Mod', cls=command.Command)
    async def poll(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = self.parse_poll_args(args)
        question = args['q']
        options = args['o']
        option_emotes = args['o_emotes']

        err = ''
        if question == '' or options == '':
            err = 'Empty arg'

        if len(options) > 9:
            err = 'Too many options'

        if err:
            embed = embed_maker.message(ctx, err, colour='red')
            return await ctx.send(embed=embed)

        description = f'**"{question}"**\n\n'
        colour = config.DEFAULT_EMBED_COLOUR
        embed = discord.Embed(title='Poll', colour=colour, description=description, timestamp=datetime.now())
        embed.set_footer(text='Started at', icon_url=ctx.guild.icon_url)

        if not options:
            emotes = ['👍', '👎']
        else:
            if option_emotes:
                emotes = list(option_emotes.keys())
                options = list(option_emotes.values())
            else:
                all_num_emotes = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
                emotes = all_num_emotes[:len(options)]

            description += '\n'.join(f'\n{e} | **{o}**' for e, o in zip(emotes, options))
            embed.description = description

        poll_msg = await ctx.send(embed=embed)
        for e in emotes:
            await poll_msg.add_reaction(e)

        return await ctx.message.delete(delay=5)

    def parse_poll_args(self, args):
        result = {
            'q': '',
            'o': [],
            't': '5m',
            'o_emotes': {}
        }
        split_args = filter(None, args.split('-'))
        for a in split_args:
            key, value = tuple(map(str.strip, a.split(' ', 1)))
            result[key] = value

        if result['o']:
            result['o'] = result['o'].replace(' ', '').split(',')
        else:
            return result

        # check for custom option emotes
        oe_regex = re.compile(r'\[(.*):(.*)\]')
        if re.match(oe_regex, result['o'][0]):
            for option in result['o']:
                oe = re.match(oe_regex, option)
                if oe:
                    e, o = oe.groups()
                    result['o_emotes'][e] = o
                    continue

                result['o_emotes'] = None
                break

        return result

    @commands.command(help='Get help smh', usage='help (command)', examples=['help', 'help ping'], clearance='User', cls=command.Command)
    async def help(self, ctx, _cmd=None):
        embed_colour = config.DEFAULT_EMBED_COLOUR
        prefix = config.DEFAULT_PREFIX
        cmds = self.bot.commands
        help_object = {}

        for cmd in cmds:
            if hasattr(cmd, 'dm_only'):
                continue

            if cmd.cog_name not in help_object:
                help_object[cmd.cog_name] = [cmd]
            else:
                help_object[cmd.cog_name].append(cmd)

        utils = self.bot.get_cog('Utils')
        clearance = await utils.get_user_clearance(ctx.guild.id, ctx.author.id)
        if _cmd is None:
            embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(),
                                  description=f'**Prefix** : `{prefix}`\nFor additional info on a command, type `{prefix}help [command]`')
            embed.set_author(name=f'Help - {clearance[0]}', icon_url=ctx.guild.icon_url)
            embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
            for cat in help_object:
                cat_commands = []
                for cmd in help_object[cat]:
                    if cmd.clearance in clearance:
                        cat_commands.append(f'`{cmd}`')

                if cat_commands:
                    embed.add_field(name=f'>{cat}', value=" \| ".join(cat_commands), inline=False)

            return await ctx.send(embed=embed)
        else:
            if self.bot.get_command(_cmd):
                cmd = self.bot.get_command(_cmd)
                if cmd.hidden:
                    return
                examples = f' | {prefix}'.join(cmd.examples)
                cmd_help = f"""
                **Description:** {cmd.help}
                **Usage:** {prefix}{cmd.usage}
                **Examples:** {prefix}{examples}
                """
                embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=cmd_help)
                embed.set_author(name=f'Help - {cmd}', icon_url=ctx.guild.icon_url)
                embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
                return await ctx.send(embed=embed)
            else:
                embed = embed_maker.message(ctx, f'{_cmd} is not a valid command')
                return await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Utility(bot))
