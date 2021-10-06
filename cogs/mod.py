import datetime
import math
import time
import dateparser
import discord
import functools

from bson import ObjectId
from modules.reaction_menus import BookMenu
from discord.ext.commands import Cog, command, Context, group
from typing import Union
from bot import TLDR
from modules import commands, database, embed_maker, format_time, reaction_menus
from modules.utils import (
    ParseArgs,
    get_guild_role,
    get_member,
    get_member_from_string,
    get_member_by_id
)

db = database.get_connection()


class Mod(Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot

    @staticmethod
    async def construct_cases_embed(ctx: Context, member: discord.Member, cases: dict, case_type: str,
                                    max_page_num: int, page_size_limit: int, *, page: int):
        thirty_days_ago = time.time() - (30 * 24 * 60)
        # cases in the past 30 days
        cases_30_days = [*filter(lambda case: case.created_at > thirty_days_ago, cases)]

        description = f'**Total:** `{len(cases)}`\n' \
                      f'**In the pas 30 days:** `{len(cases_30_days)}`\n\n'

        if len(cases) > 0:
            for i, case in enumerate(cases[page_size_limit * (page - 1):page_size_limit * page]):
                # limit it to 5 per page
                if i == page_size_limit:
                    break

                reason = case.reason
                # if reason is too long, cut it off
                if len(reason) > 300:
                    reason = reason[:300] + '...'

                type_str = f'**Type:** {case.type}\n' if not case_type else ''
                duration_str = f'**Duration:** {format_time.seconds(case.extra["duration"])}\n' if case.type == 'mute' else ''
                description += f'**#{page_size_limit * (page - 1) + i + 1}**\n' \
                               f'`{datetime.datetime.fromtimestamp(case.created_at).strftime("%Y/%m/%d - %H:%M:%S")}`\n' \
                               f'`{format_time.seconds(round(time.time()) - case.created_at, accuracy=3)} Ago`\n' \
                               f'{type_str}' \
                               f'{duration_str}' \
                               f'**By:** <@{case.moderator_id}>\n' \
                               f'**Reason:** {reason}\n\n'
        else:
            description = f'This user has no {case_type if case_type else "case"}s'

        name_switch = {
            'warn': 'Warnings',
            'mute': 'Mutes',
            'ban': 'Bans'
        }

        return await embed_maker.message(
            ctx,
            description=description,
            author={'name': f'{name_switch.get(case_type, "Cases")} - {member}'},
            footer={'text': f'Page {page}/{max_page_num}'}
        )

    async def cases_menu(self, ctx: Context, member: discord.Member, case_type: str, page: int = 1):
        member_cases = self.bot.moderation.cases.get_cases(ctx.guild.id, member_id=member.id, type=case_type)

        page_size_limit = 5
        max_page_num = math.ceil(len(member_cases) / page_size_limit)
        if max_page_num == 0:
            max_page_num = 1

        if page > max_page_num:
            return await embed_maker.error(ctx, 'Exceeded maximum page number')

        page_constructor = functools.partial(
            self.construct_cases_embed,
            ctx,
            member,
            member_cases,
            case_type,
            max_page_num,
            page_size_limit
        )

        embed = await page_constructor(page=page)
        cc_message = await ctx.send(embed=embed)

        menu = reaction_menus.BookMenu(
            cc_message,
            author=ctx.author,
            page=page,
            max_page_num=max_page_num,
            page_constructor=page_constructor,
        )

        self.bot.reaction_menus.add(menu)

    @command(
        help='See the cases (warn/mute/ban) issued to a user',
        usage='cases [member] [case type] (page)',
        examples=['cases hattyot warn', 'warns hattyot ban 2'],
        aliases=['case'],
        cls=commands.Command,
        module_dependency=['reaction_menus', 'moderation']
    )
    async def cases(self, ctx: Context, member_and_case_type: str = None):
        if member_and_case_type is None:
            return await embed_maker.command_error(ctx)

        member, case_type = await get_member_from_string(ctx, member_and_case_type)

        # get page number, if any has been provided
        split_member = case_type.split()
        if len(split_member) > 1:
            case_type = ' '.join(split_member[:-1])

            page = split_member[-1]
            if not page.isdigit():
                page = 1
            else:
                page = int(page)
        else:
            page = 1

        if type(member) == discord.Message:
            return

        return await self.cases_menu(ctx, member, case_type, page)

    @command(
        help='Give a member a warning',
        usage='warn [member] [reason]',
        examples=['warn hattyot broke cg 10 several times'],
        aliases=['warning'],
        cls=commands.Command,
        module_dependency=['moderation']
    )
    async def warn(self, ctx: Context, *, member_and_reason: str = None):
        if member_and_reason is None:
            return await embed_maker.command_error(ctx)

        member, reason = await get_member_from_string(ctx, member_and_reason)

        if member is None:
            return await embed_maker.error(ctx, 'Unable to find member.')

        if reason is None:
            return await embed_maker.error(ctx, 'You need to give a reason for the warning.')

        if member.bot:
            return await embed_maker.error(ctx, 'You can\'t give a warning to a bot. Bots are good lads')

        if member.id == ctx.author.id:
            return await embed_maker.error(ctx, 'You can\'t warn yourself.')

        if ctx.author.roles[-1].position <= member.roles[-1].position:
            return await embed_maker.error(ctx,
                                           'You can\'t warn a member who has a role that is equal or higher than yours.')

        # send user message that they have been warned
        text = f"**{ctx.guild.name}** - You have been warned.:warning:\n**Reason**: {reason}"
        await member.send(text)

        # confirm that user has been warned
        thirty_days_ago = time.time() - (30 * 24 * 60)
        user_warns = self.bot.moderation.cases.get_cases(ctx.guild.id, member_id=member.id, type='warn',
                                                         after=thirty_days_ago)
        await embed_maker.message(
            ctx,
            description=f'{member.mention} has been warned\n'
                        f'They now have {len(user_warns) + 1} warning{"s" if len(user_warns) != 0 else ""} in the last 30 days.',
            colour='green',
            send=True
        )

        # add case to the database
        self.bot.moderation.cases.add_case(ctx.guild.id, 'warn', reason, member, ctx.author)

    @command(
        help='Unmute a member',
        usage='unmute [member] [reason]',
        examples=['unmute hattyot accidental mute'],
        cls=commands.Command
    )
    async def unmute(self, ctx: Context, *, member_and_reason: str = None):
        if member_and_reason is None:
            return await embed_maker.command_error(ctx)

        guild_settings = db.get_guild_settings(ctx.guild.id)
        if guild_settings['mute_role_id'] is None:
            return await embed_maker.message(
                ctx,
                description=f'The mute role has not been set yet.\nYou can set it with `{ctx.prefix}setmuterole [role]`',
                colour='orange',
                send=True
            )

        member, reason = await get_member_from_string(ctx, member_and_reason)

        if member is None:
            return await embed_maker.error(ctx, 'Unable to find member.')

        if reason is None:
            return await embed_maker.error(ctx, 'You need to give a reason for the unmute.')

        if member.bot:
            return await embed_maker.error(ctx, 'You can\'t unmute a bot, they can\'t even be muted smh.')

        if member.id == ctx.author.id:
            return await embed_maker.error(ctx, 'You can\'t unmute yourself, how did you even send this message.')

        if ctx.author.roles[-1].position <= member.roles[-1].position:
            return await embed_maker.error(ctx,
                                           'You can\'t unmute a member who has a role that is equal or higher than yours.')

        mute_timer = db.timers.find_one(
            {'guild_id': ctx.guild.id, 'event': 'automatic_unmute', 'extras': {'member_id': member.id}})
        if not mute_timer:
            return await embed_maker.message(
                ctx,
                description=f'<@{member.id}> is not muted.',
                colour='orange',
                send=True
            )

        await self.unmute_user(ctx.guild.id, member.id, reason)

        time_left = mute_timer['expires'] - round(time.time())
        return await embed_maker.message(
            ctx,
            description=f'<@{member.id}> has been unmuted.\n**Reason**: {reason}Their mute had **{format_time.seconds(time_left)}** left.\n',
            send=True
        )

    @command(
        help='Mute a member',
        usage='mute [member] [duration] [reason]',
        examples=['mute hattyot 7d 5h 10m 50s abused the bot'],
        cls=commands.Command,
        module_dependency=['timers', 'moderation']
    )
    async def mute(self, ctx: Context, *, member_and_duration_and_reason: str = None):
        if member_and_duration_and_reason is None:
            return await embed_maker.command_error(ctx)

        guild_settings = db.get_guild_settings(ctx.guild.id)
        if guild_settings['mute_role_id'] is None:
            return await embed_maker.message(
                ctx,
                description=f'The mute role has not been set yet.\nYou can set it with `{ctx.prefix}setmuterole [role]`',
                colour='orange',
                send=True
            )

        member, duration_and_reason = await get_member_from_string(ctx, member_and_duration_and_reason)
        duration, reason = format_time.parse(duration_and_reason, return_string=True)

        if member is None:
            return await embed_maker.error(ctx, 'Unable to find member.')

        if duration is None:
            return await embed_maker.error(ctx, 'You need to give a duration for the mute')

        if reason is None:
            return await embed_maker.error(ctx, 'You need to give a reason for the mute.')

        if member.bot:
            return await embed_maker.error(ctx, 'You can\'t mute a bot. Bots are good lads')

        if member.id == ctx.author.id:
            return await embed_maker.error(ctx, 'You can\'t mute yourself.')

        if ctx.author.roles[-1].position <= member.roles[-1].position:
            return await embed_maker.error(ctx,
                                           'You can\'t mute a member who has a role that is equal or higher than yours.')

        mute_timer = db.timers.find_one(
            {'guild_id': ctx.guild.id, 'event': 'automatic_unmute', 'extras': {'member_id': member.id}})
        if mute_timer:
            time_left = mute_timer['expires'] - round(time.time())
            return await embed_maker.message(
                ctx,
                description=f'<@{member.id}> is already muted.\nTheir mute will expire in: **{format_time.seconds(time_left)}**',
                colour='orange',
                send=True
            )

        # send user message that they have been muted
        text = f"**{ctx.guild.name}** - You have been muted.:mute:\n**Duration**: {format_time.seconds(duration)}\n**Reason**: {reason}"
        try:
            await member.send(text)
        except:
            return await embed_maker.error(ctx, 'Failed to send mute message to user.')

        # confirm that user has been warned
        thirty_days_ago = time.time() - (30 * 24 * 60)
        user_warns = self.bot.moderation.cases.get_cases(ctx.guild.id, member_id=member.id, type='warn',
                                                         after=thirty_days_ago)
        await embed_maker.message(
            ctx,
            description=f'{member.mention} has been muted for **{format_time.seconds(duration)}**\n'
                        f'**Reason:** {reason}\n'
                        f'They now have **{len(user_warns) + 1}** mute{"s" * (len(user_warns) != 0)} in the last 30 days.',
            colour='green',
            send=True
        )

        # add case to the database
        self.bot.moderation.cases.add_case(ctx.guild.id, 'mute', reason, member, ctx.author,
                                           extra={'duration': duration})

        # add mute role to user
        mute_role = await get_guild_role(ctx.guild, str(guild_settings['mute_role_id']))
        if mute_role is None:
            return await embed_maker.error(ctx, 'Current mute role is not valid.')
        else:
            await member.add_roles(mute_role)

        # start automatic unmute timer
        self.bot.timers.create(
            guild_id=ctx.guild.id,
            expires=round(time.time()) + duration,
            event='automatic_unmute',
            extras={
                'member_id': member.id
            }
        )

    async def unmute_user(self, guild_id: int, member_id: int, reason: str):
        guild = self.bot.get_guild(guild_id)
        member = await get_member_by_id(guild, member_id)

        # send user message that they have been unmuted
        text = f"**{guild.name}** - You have been unmuted.:loud_sound:\n**Reason**: {reason}"
        await member.send(text)

        # remove mute role from member
        mute_role_id = db.get_guild_settings(guild_id=guild_id)['mute_role_id']
        if mute_role_id is None:
            return

        mute_role = await get_guild_role(guild, str(mute_role_id))
        if mute_role is None:
            return

        await member.remove_roles(mute_role)

        # remove mute timer
        db.timers.delete_one({'guild_id': guild.id, 'event': 'automatic_unmute', 'extras': {'member_id': member.id}})

    @Cog.listener()
    async def on_automatic_unmute_timer_over(self, timer: dict):
        guild_id = timer['guild_id']
        member_id = timer['extras']['member_id']
        return await self.unmute_user(guild_id, member_id, 'Mute expired.')

    @command(
        help='Ban a member, their leveling data will be erased',
        usage='ban [member] [reason]',
        examples=['ban hattyot completely ignore cg'],
        cls=commands.Command,
        module_dependency=['moderation']
    )
    async def ban(self, ctx: Context, *, member_and_reason: str = None):
        if member_and_reason is None:
            return await embed_maker.command_error(ctx)

        member, reason = await get_member_from_string(ctx, member_and_reason)

        if member is None:
            return await embed_maker.error(ctx, 'Unable to find member.')

        if reason is None:
            return await embed_maker.error(ctx, 'You need to give a reason for the ban.')

        if member.bot:
            return await embed_maker.error(ctx, 'You can\'t ban a bot, they do too much work.')

        if member.id == ctx.author.id:
            return await embed_maker.error(ctx, 'You can\'t ban yourself, why would you even try this')

        if ctx.author.roles[-1].position <= member.roles[-1].position:
            return await embed_maker.error(ctx,
                                           'You can\'t ban a member who has a role that is equal or higher than yours.')

        # send user message that they have been warned
        text = f"**{ctx.guild.name}** - You have been banned.\n**Reason**: {reason}"
        try:
            await member.send(text)
        except:
            return await embed_maker.error(ctx, 'Failed to send ban message to user.')

        await ctx.guild.ban(member, reason=reason)
        self.bot.dispatch('ban', member)

        await embed_maker.message(
            ctx,
            description=f'{member.mention} has been banned.\n'
                        f'**Reason:** {reason}',
            colour='green',
            send=True
        )

        # add case to the database
        self.bot.moderation.cases.add_case(ctx.guild.id, 'ban', reason, member, ctx.author)

    @group(
        invoke_without_command=True,
        name='watchlist',
        help='Manage the watchlist, which logs all the users message to a channel',
        usage='watchlist (sub command) (args)',
        examples=['watchlist'],
        cls=commands.Group,
        module_dependency=['watchlist']
    )
    async def watchlist(self, ctx: Context):
        if ctx.subcommand_passed is None:
            users_on_list = [d for d in db.watchlist.distinct('user_id', {'guild_id': ctx.guild.id})]

            list_embed = await embed_maker.message(
                ctx,
                author={'name': 'Users on the watchlist'}
            )

            on_list_str = ''
            for i, user_id in enumerate(users_on_list):
                user = ctx.guild.get_member(int(user_id))
                if user is None:
                    try:
                        user = await ctx.guild.fetch_member(int(user_id))
                    except:
                        # remove user from the watchlist if user isnt on the server anymore
                        db.watchlist.delete_one({'guild_id': ctx.guild.id, 'user_id': user_id})
                        continue

                on_list_str += f'`#{i + 1}` - {str(user)}\n'
                watchlist_user = db.watchlist.find_one({'guild_id': ctx.guild.id, 'user_id': user_id}, {'filters': 1})
                if watchlist_user['filters']:
                    on_list_str += 'Filters: ' + " | ".join(f"`{f}`" for f in watchlist_user['filters'])
                on_list_str += '\n\n'

            list_embed.description = 'Currently no users are on the watchlist' if not on_list_str else on_list_str

            return await ctx.send(embed=list_embed)

    @watchlist.command(
        name='add',
        help='add a user to the watchlist, with optionl filters (mathces are found with regex)',
        usage='watchlist add [user] (args)',
        examples=[r'watchlist add hattyot -f hattyot -f \sot\s -f \ssus\s'],
        command_args=[
            (('--filter', '-f', list), 'A regex filter that will be matched against the users message, if a match is found, mods will be @\'d'),
        ],
        cls=commands.Command,
        module_dependency=['watchlist']
    )
    async def watchlist_add(self, ctx: Context, *, args: Union[ParseArgs, dict] = None):
        if not args:
            return await embed_maker.command_error(ctx)

        user_identifier = args['pre']
        filters = args['filter']

        if not user_identifier:
            return await embed_maker.error(ctx, 'Missing user')

        member = await get_member(ctx, user_identifier)
        if type(member) == discord.Message:
            return

        watchlist_user = self.bot.watchlist.get_member(member)
        if watchlist_user:
            return await embed_maker.error(ctx, 'User is already on the watchlist')

        await self.bot.watchlist.add_member(member, filters)

        msg = f'<@{member.id}> has been added to the watchlist'
        if filters:
            msg += f'\nWith these filters: {" or ".join(f"`{f}`" for f in filters)}'

        return await embed_maker.message(ctx, description=msg, colour='green', send=True)

    @watchlist.command(
        name='remove',
        help='remove a user from the watchlist',
        usage='watchlist remove [user]',
        examples=['watchlist remove hattyot'],
        cls=commands.Command,
        module_dependency=['watchlist']
    )
    async def watchlist_remove(self, ctx: Context, *, user: str = None):
        if user is None:
            return await embed_maker.command_error(ctx)

        member = await get_member(ctx, user)
        if type(member) == discord.Message:
            return

        watchlist_user = self.bot.watchlist.get_member(member)
        if not watchlist_user:
            return await embed_maker.error(ctx, 'User is not on the watchlist')

        await self.bot.watchlist.remove_member(member)

        return await embed_maker.message(
            ctx,
            description=f'<@{member.id}> has been removed from the watchlist',
            colour='green',
            send=True
        )

    @watchlist.command(
        name='add_filters',
        help='Add filters to a user on the watchlist, when a user message matches the filter, mods are pinged.',
        usage='watchlist add_filters [user] (args)',
        examples=[r'watchlist add_filters hattyot -f filter 1 -f \sfilter 2\s'],
        command_args=[
            (('--filter', '-f', list), 'A regex filter that will be matched against the users message, if a match is found, mods will be @\'d'),
        ],
        cls=commands.Command,
        module_dependency=['watchlist'],
    )
    async def watchlist_add_filters(self, ctx: Context, *, args: Union[ParseArgs, dict] = None):
        if not args:
            return await embed_maker.command_error(ctx)

        user_identifier = args['pre']
        filters = args['f']

        if not filters:
            return await embed_maker.error(ctx, 'Missing filters')

        if not user_identifier:
            return await embed_maker.error(ctx, 'Missing user')

        member = await get_member(ctx, user_identifier)
        if type(member) == discord.Message:
            return

        watchlist_user = self.bot.watchlist.get_member(member)
        if not watchlist_user:
            return await embed_maker.error(ctx, 'User is not on the watchlist')

        self.bot.watchlist.add_filters(member, filters)

        return await embed_maker.message(
            ctx,
            description=f'if {member} mentions {" or ".join(f"`{f}`" for f in filters)} mods will be @\'d',
            colour='green',
            send=True
        )

    @staticmethod
    async def construct_dd_embed(ctx: Context, daily_debates_data: dict, max_page_num: int, page_size_limit: int, topics: list, *, page: int):
        if not topics:
            topics_str = f'Currently there are no debate topics set up'
        else:
            # generate topics string
            topics_str = '**Topics:**\n'
            for i, topic in enumerate(topics[page_size_limit * (page - 1):page_size_limit * page]):
                if i == 10:
                    break

                topic_str = topic['topic']
                topic_author_id = topic['topic_author_id']
                topic_options = topic['topic_options']

                topic_author = None
                if topic_author_id:
                    topic_author = ctx.guild.get_member(int(topic_author_id))
                    if not topic_author:
                        try:
                            topic_author = await ctx.guild.fetch_member(int(topic_author_id))
                        except Exception:
                            topic_author = None

                topics_str += f'`#{page_size_limit * (page - 1) + i + 1}`: {topic_str}\n'
                if topic_author:
                    topics_str += f'**Topic Author:** {str(topic_author)}\n'

                if topic_options:
                    topics_str += '**Poll Options:**' + ' |'.join(
                        [f' `{o}`' for i, o in enumerate(topic_options.values())]) + '\n'

        dd_time = daily_debates_data['time'] if daily_debates_data['time'] else 'Not set'
        dd_channel = f'<#{daily_debates_data["channel_id"]}>' if daily_debates_data['channel_id'] else 'Not set'
        dd_poll_channel = f'<#{daily_debates_data["poll_channel_id"]}>' if daily_debates_data[
            'poll_channel_id'] else 'Not set'
        dd_role = f'<@&{daily_debates_data["role_id"]}>' if daily_debates_data['role_id'] else 'Not set'
        embed = await embed_maker.message(
            ctx,
            description=topics_str,
            author={'name': 'Daily Debates'},
            footer={'text': f'Page {page}/{max_page_num}'}
        )
        embed.add_field(
            name='Attributes',
            value=f'**Time:** {dd_time}\n**Channel:** {dd_channel}\n**Poll Channel:** {dd_poll_channel}\n**Role:** {dd_role}'
        )
        return embed

    @group(
        invoke_without_command=True,
        help='Daily debate scheduler/manager',
        usage='dailydebates (sub command) (arg(s))',
        aliases=['dd', 'dailydebate'],
        examples=['dailydebates'],
        cls=commands.Group,
        module_dependency=['timers', 'reaction_menus']
    )
    async def dailydebates(self, ctx: Context, page: str = 1):
        if ctx.subcommand_passed is None:
            daily_debates_data = db.get_daily_debates(ctx.guild.id)

            if type(page) == str and page.isdigit():
                page = int(page)
            else:
                page = 1

            page_size_limit = 10

            # List currently set up daily debate topics
            topics = daily_debates_data['topics']

            # calculate max page number
            max_page_num = math.ceil(len(topics) / page_size_limit)
            if max_page_num == 0:
                max_page_num = 1

            if page > max_page_num:
                return await embed_maker.error(ctx, 'Exceeded maximum page number')

            page_constructor = functools.partial(
                self.construct_dd_embed,
                ctx,
                daily_debates_data,
                max_page_num,
                page_size_limit,
                topics
            )

            embed = await page_constructor(page=page)
            dd_message = await ctx.send(embed=embed)

            menu = BookMenu(
                dd_message,
                author=ctx.author,
                page=page,
                max_page_num=max_page_num,
                page_constructor=page_constructor,
            )

            self.bot.reaction_menus.add(menu)

    @dailydebates.command(
        name='disable',
        help='Disable the daily debates system, time will be set to 0',
        usage='dailydebates disable',
        examples=['dailydebates disable'],
        cls=commands.Command,
        module_dependency=['timers']
    )
    async def dailydebates_disable(self, ctx: Context):
        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'time': 0}})

        # cancel timer if active
        daily_debate_timer = db.timers.find_one(
            {'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}}
        )
        if daily_debate_timer:
            db.timers.delete_one({'_id': ObjectId(daily_debate_timer['_id'])})

        return await embed_maker.message(ctx, description='Daily debates have been disabled', send=True)

    @dailydebates.command(
        name='set_poll_options',
        help='Set the poll options for a daily debate topic',
        usage='dailydebates set_poll_options [index of topic] [args]',
        examples=[
            'dailydebates set_poll_options 1 -o yes -o no -o double yes -o double no',
            'dailydebates set_poll_options 1 -o 🇩🇪: Germany -o 🇬🇧: UK'
        ],
        command_args=[
            (('--option', '-o', list), 'Option for the poll'),
        ],
        cls=commands.Command,
        module_dependency=['timers']
    )
    async def dailydebates_set_poll_options(self, ctx: Context, index: str = None, *, args: Union[ParseArgs, dict] = None):
        if index is None:
            return await embed_maker.command_error(ctx)

        if not index.isdigit():
            return await embed_maker.command_error(ctx, '[index of topic]')

        options = args['option']

        if not options:
            return await embed_maker.error(ctx, 'Missing options')

        utility_cog = self.bot.get_cog('Utility')
        emote_options = await utility_cog.parse_poll_options(ctx, options)
        if type(emote_options) == discord.Message:
            return

        daily_debates_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})
        topics = daily_debates_data['topics']

        index = int(index)
        if len(topics) < index:
            return await embed_maker.error(ctx, 'index out of range')

        topic = topics[index - 1]

        topic_obj = {
            'topic': topic['topic'],
            'topic_author_id': topic['topic_author_id'],
            'topic_options': emote_options
        }

        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {f'topics.{index - 1}': topic_obj}})
        options_str = '\n'.join([f'{emote}: {option}' for emote, option in emote_options.items()])
        return await embed_maker.message(
            ctx,
            description=f'Along with the topic: **"{topic["topic"]}"**\nwill be sent a poll with these options: {options_str}',
            send=True
        )

    @dailydebates.command(
        name='add',
        help='add a topic to the list topics along with optional options and topic author',
        usage='dailydebates add [topic] (args)',
        examples=[
            'dailydebates add is ross mega cool? -ta hattyot -o yes -o double yes -o triple yes'
        ],
        command_args=[
            (('--topic_author', '-ta', str), 'Original author of the topic, that will be mentioned when the dd is sent, they will also be given a 15% boost for 6 hours'),
            (('--option', '-o', list), 'Option for the poll'),
        ],
        cls=commands.Command,
        module_dependency=['timers']
    )
    async def dailydebates_add(self, ctx: Context, *, args: Union[ParseArgs, dict] = None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = await self.parse_dd_args(ctx, args)
        if type(args) == discord.Message:
            return

        topic = args['pre']
        topic_author = args['topic_author']
        topic_options = args['option']

        topic_obj = {
            'topic': topic,
            'topic_author_id': topic_author,
            'topic_options': topic_options
        }
        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$push': {'topics': topic_obj}})

        daily_debate_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})
        await embed_maker.message(
            ctx,
            description=f'`{topic}` has been added to the list of daily debate topics'
                        f'\nThere are now **{len(daily_debate_data["topics"])}** topics on the list',
            send=True
        )

        daily_debate_timer = db.timers.find_one(
            {'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}}
        )
        if not daily_debate_timer:
            return await self.start_daily_debate_timer(ctx.guild.id, daily_debate_data['time'])

    @dailydebates.command(
        name='insert',
        help='insert a topic into the first place on the list of topics along with optional options and topic author',
        usage='dailydebates insert [topic] (args)',
        examples=['dailydebates insert is ross mega cool? -ta hattyot -o yes | double yes | triple yes'],
        command_args=[
            (('--topic_author', '-ta', str), 'Original author of the topic, that will be mentioned when the dd is sent, they will also be given a 15% boost for 6 hours'),
            (('--option', '-o', list), 'Option for the poll'),
        ],
        cls=commands.Command,
        module_dependency=['timers']
    )
    async def _dailydebates_insert(self, ctx: Context, *, args: Union[ParseArgs, dict] = None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = await self.parse_dd_args(ctx, args)
        if type(args) == discord.Message:
            return

        topic = args['pre']
        topic_author = args['topic_author']
        topic_options = args['option']

        topic_obj = {
            'topic': topic,
            'topic_author_id': topic_author,
            'topic_options': topic_options
        }
        db.daily_debates.update_one(
            {'guild_id': ctx.guild.id},
            {'$push': {'topics': {'$each': [topic_obj], '$position': 0}}}
        )

        daily_debate_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})
        await embed_maker.message(
            ctx,
            description=f'`{topic}` has been inserted into first place in the list of daily debate topics'
                        f'\nThere are now **{len(daily_debate_data["topics"])}** topics on the list',
            send=True
        )

        daily_debate_timer = db.timers.find_one(
            {'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}}
        )
        if not daily_debate_timer:
            return await self.start_daily_debate_timer(ctx.guild.id, daily_debate_data['time'])

    @dailydebates.command(
        name='remove',
        help='remove a topic from the topic list',
        usage='dailydebates remove [topic index]',
        examples=['dailydebates remove 2'],
        cls=commands.Command,
        module_dependency=['timers']
    )
    async def dailydebates_remove(self, ctx: Context, index: str = None):
        if index is None:
            return await embed_maker.command_error(ctx)

        if not index.isdigit():
            return await embed_maker.error(ctx, 'Invalid index')

        daily_debate_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})

        index = int(index)
        if index > len(daily_debate_data['topics']):
            return await embed_maker.error(ctx, 'Index too big')

        if index < 1:
            return await embed_maker.error(ctx, 'Index cant be smaller than 1')

        topic_to_delete = daily_debate_data['topics'][index - 1]
        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$pull': {'topics': topic_to_delete}})

        return await embed_maker.message(
            ctx,
            description=f'`{topic_to_delete["topic"]}` has been removed from the list of daily debate topics'
                        f'\nThere are now **{len(daily_debate_data["topics"]) - 1}** topics on the list',
            send=True
        )

    @dailydebates.command(
        name='set_time',
        help='set the time when topics are announced',
        usage='dailydebates set_time [time]',
        examples=['dailydebates set_time 14:00 GMT+1'],
        cls=commands.Command,
        module_dependency=['timers']
    )
    async def dailydebates_set_time(self, ctx: Context, *, time_str: str = None):
        if time_str is None:
            return await embed_maker.command_error(ctx)

        parsed_time = dateparser.parse(time_str, settings={'RETURN_AS_TIMEZONE_AWARE': True})
        if not parsed_time:
            return await embed_maker.error(ctx, 'Invalid time')

        parsed_dd_time = dateparser.parse(
            time_str,
            settings={
                'PREFER_DATES_FROM': 'future',
                'RETURN_AS_TIMEZONE_AWARE': True,
                'RELATIVE_BASE': datetime.datetime.now(parsed_time.tzinfo)
            }
        )
        time_diff = parsed_dd_time - datetime.datetime.now(parsed_dd_time.tzinfo)
        time_diff_seconds = round(time_diff.total_seconds())

        if time_diff_seconds < 0:
            return await embed_maker.error(ctx, 'Invalid time')

        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'time': time_str}})
        await embed_maker.message(ctx, description=f'Daily debates will now be announced every day at {time_str}', send=True)

        # cancel old timer
        db.timers.delete_many({'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}})

        return await self.start_daily_debate_timer(ctx.guild.id, time_str)

    @dailydebates.command(
        name='set_channel',
        help=f'set the channel where topics are announced',
        usage='dailydebates set_channel [#set_channel]',
        examples=['dailydebates set_channel #daily-debates'],
        cls=commands.Command,
        module_dependency=['timers']
    )
    async def dailydebates_set_channel(self, ctx: Context, channel: discord.TextChannel = None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'channel_id': channel.id}})
        return await embed_maker.message(
            ctx,
            description=f'Daily debates will now be announced every day at <#{channel.id}>',
            send=True
        )

    @dailydebates.command(
        name='set_role',
        help=f'set the role that will be @\'d when topics are announced, disable @\'s by setting the role to `None`',
        usage='dailydebates set_role [role]',
        examples=['dailydebates set_role Debater'],
        cls=commands.Command,
        module_dependency=['timers']
    )
    async def dailydebates_set_role(self, ctx: Context, *, role: Union[discord.Role, str] = None):
        if role is None:
            return await embed_maker.command_error(ctx)

        if type(role) == str and role.lower() == 'none':
            db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'role_id': 0}})
            return await embed_maker.message(ctx, description='daily debates role has been disabled', send=True)
        elif type(role) == str:
            return await embed_maker.command_error(ctx, '[role]')

        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'role_id': role.id}})
        return await embed_maker.message(
            ctx,
            description=f'Daily debates will now be announced every day to <@&{role.id}>',
            send=True
        )

    @dailydebates.command(
        name='set_poll_channel',
        help=f'Set the poll channel where polls will be sent, disable polls by setting poll channel to `None``',
        usage='dailydebates set_poll_channel [#channel]',
        examples=['dailydebates set_poll_channel #daily_debate_polls'],
        cls=commands.Command,
        module_dependency=['timers']
    )
    async def dailydebates_set_poll_channel(self, ctx: Context, channel: Union[discord.TextChannel, str] = None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        if type(channel) == str and channel.lower() == 'none':
            db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'role_id': 0}})
            return await embed_maker.message(ctx, description='daily debates poll channel has been disabled', send=True)

        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'poll_channel_id': channel.id}})
        return await embed_maker.message(
            ctx,
            description=f'Daily debate polls will now be sent every day to <#{channel.id}>',
            send=True
        )

    async def parse_dd_args(self, ctx: Context, args: dict):
        if not args['pre']:
            return await embed_maker.error(ctx, 'Missing topic')

        utility_cog = self.bot.get_cog('Utility')
        args['option'] = await utility_cog.parse_poll_options(ctx, args['option']) if args['option'] else ''
        if type(args['option']) == discord.Message:
            return

        if args['topic_author']:
            member = await get_member(ctx, args['topic_author'])
            if type(member) == discord.Message:
                return member

            args['topic_author'] = member.id

        return args

    async def start_daily_debate_timer(self, guild_id, dd_time):
        # delete old timer
        db.timers.delete_many({'guild_id': guild_id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}})

        # creating first parsed_dd_time to grab timezone info
        parsed_dd_time = dateparser.parse(dd_time, settings={'RETURN_AS_TIMEZONE_AWARE': True})

        # second one for actual use
        parsed_dd_time = dateparser.parse(dd_time, settings={'PREFER_DATES_FROM': 'future', 'RETURN_AS_TIMEZONE_AWARE': True, 'RELATIVE_BASE': datetime.datetime.now(parsed_dd_time.tzinfo)})

        time_diff = parsed_dd_time - datetime.datetime.now(parsed_dd_time.tzinfo)
        time_diff_seconds = round(time_diff.total_seconds())

        # -1h so mods can be warned when there are no daily debate topics set up
        timer_expires = round(time.time()) + time_diff_seconds - 3600  # one hour
        self.bot.timers.create(guild_id=guild_id, expires=timer_expires, event='daily_debate', extras={})


def setup(bot):
    bot.add_cog(Mod(bot))
