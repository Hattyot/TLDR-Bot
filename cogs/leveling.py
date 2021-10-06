import discord
import time
import math
import datetime
import functools
import re
from bot import TLDR
from modules.utils import (
    ParseArgs,
    get_member,
    get_member_from_string
)
from typing import Union, Optional
from modules import embed_maker, commands, database, format_time, leveling
from random import randint
from discord.ext.commands import Cog, command, Context, group
from modules.reaction_menus import BookMenu
db = database.get_connection()


class Cooldown:
    def __init__(self, cooldown_in_seconds: int = 60):
        self.cooldown_in_seconds = cooldown_in_seconds
        self.cooldown_users = {}

    def add_user(self, guild_id: int, user_id: int):
        if guild_id not in self.cooldown_users:
            self.cooldown_users[guild_id] = {}

        now = time.time() + self.cooldown_in_seconds
        self.cooldown_users[guild_id][user_id] = now

    def user_cooldown(self, guild_id: int, user_id: int) -> int:
        if guild_id not in self.cooldown_users:
            self.cooldown_users[guild_id] = {}

        if user_id in self.cooldown_users[guild_id]:
            now = time.time()
            cooldown_time = self.cooldown_users[guild_id][user_id] - now
            if cooldown_time < 0:
                del self.cooldown_users[guild_id][user_id]
                cooldown_time = 0
        else:
            cooldown_time = 0

        if not cooldown_time:
            self.add_user(guild_id, user_id)

        return int(cooldown_time)


class Leveling(Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot

        # parliamentary points earn cooldown
        self.pp_cooldown = Cooldown()
        self.hp_cooldown = Cooldown()

    @command(
        help='Show someone you respect them by giving them a reputation point',
        usage='rep [member] [reason for the rep]',
        examples=['rep @Hattyot for being an excellent example in this text'],
        cls=commands.Command,
        aliases=['reputation'],
        module_dependency=['timers', 'leveling_system']
    )
    async def rep(self, ctx: Context, *, member_reason: str = None):
        # check if user has been in server for more than 7 days
        now_datetime = datetime.datetime.now()
        joined_at = ctx.author.joined_at
        diff = now_datetime - joined_at
        if round(diff.total_seconds()) < 86400 * 7:  # 7 days
            return await embed_maker.error(ctx, f'You need to be on this server for at least 7 days to give rep points')

        # check if user can give rep point
        giving_leveling_member = await self.bot.leveling_system.get_member(ctx.guild.id, ctx.author.id)
        if not giving_leveling_member.rep_timer_expired:
            time_left = giving_leveling_member.rep_time_left
            return await embed_maker.message(
                ctx,
                description=f'You can give someone a reputation point again in:\n'
                            f'**{format_time.seconds(time_left, accuracy=3)}**',
                send=True
            )

        if member_reason is None:
            return await embed_maker.command_error(ctx)

        receiving_member, reason = await get_member_from_string(ctx, member_reason)

        if receiving_member is None:
            return await embed_maker.error(ctx, 'Invalid member')

        if not reason:
            return await embed_maker.command_error(ctx, '[reason for the rep]')

        if receiving_member.id == ctx.author.id:
            return await embed_maker.error(ctx, f'You can\'t give rep points to yourself')

        if receiving_member.bot:
            return await embed_maker.error(ctx, f'You can\'t give rep points to bots')

        # check last rep
        if giving_leveling_member.last_rep == receiving_member.id:
            return await embed_maker.error(ctx, f'You can\'t give rep to the same person twice in a row')

        receiving_leveling_member = await self.bot.leveling_system.get_member(ctx.guild.id, receiving_member.id)

        # set rep_time to 24h so user cant spam rep points
        expire = round(time.time()) + 86400  # 24 hours
        giving_leveling_member.rep_timer = expire
        # log who user gave the rep_point to, so that a person can't rep the same person twice in a row
        giving_leveling_member.last_rep = receiving_member.id

        # give member rep point
        receiving_leveling_member.rp += 1

        await embed_maker.message(ctx, description=f'Gave +1 rep to <@{receiving_member.id}>', send=True)

        # send member rep reason
        msg = f'<@{ctx.author.id}> gave you a reputation point:\n**"{reason}"**'
        embed = await embed_maker.message(
            ctx,
            description=msg,
            author={'name': 'Rep'}
        )

        # try except because bot might not be able to dm member
        try:
            await receiving_member.send(embed=embed)
        except Exception:
            pass

        # start rep timer if giving leveling_member has rep@ enabled
        if giving_leveling_member.settings.rep_at:
            self.bot.timers.create(
                guild_id=ctx.guild.id,
                expires=round(time.time()) + 86400,  # 24 hours
                event='rep_at',
                extras={
                    'member_id': giving_leveling_member.id
                }
            )

        # check if user already has rep boost, if they do, extend it by 30 minutes, otherwise add 10% boost for 6h
        if not receiving_leveling_member.boosts.rep.has_expired():
            boost = receiving_leveling_member.boosts.rep
            # if boost is expired or boost + 30min is bigger than 6 hours set expire to 6 hours
            if boost.expires < round(time.time()) or (boost.expires + 1800) - round(time.time()) > (3600 * 6):
                expires = round(time.time()) + (3600 * 6)
            # otherwise just expand expire by 30 minutes
            else:
                expires = boost.expires + 1800  # 30 min
        else:
            expires = round(time.time()) + (3600 * 6)

        # give boost to to receiving leveling member
        receiving_leveling_member.boosts.rep.expires = expires
        receiving_leveling_member.boosts.rep.multiplier = 0.1

    @group(
        invoke_without_command=True,
        help='See current leveling routes',
        usage='leveling_routes (branch <parliamentary/honours>)',
        examples=[
            'ranks',
            'ranks parliamentary',
            'ranks honours'
        ],
        Admins=commands.Help(
            help='See current leveling routes or add, remove or edit roles',
            usage='ranks (branch) (sub command) (args)',
            examples=['ranks', 'ranks honours'],
        ),
        cls=commands.Group,
        module_dependency=['leveling_system']
    )
    async def ranks(self, ctx: Context, branch: str = 'parliamentary'):
        if ctx.subcommand_passed is None and branch:
            leveling_guild = self.bot.leveling_system.get_guild(ctx.guild.id)
            branch = leveling_guild.get_leveling_route(branch)

            embed = await embed_maker.message(ctx, author={'name': 'Ranks'})

            # Looks up how many people have a role
            count = {
                role.name: db.leveling_users.count({'guild_id': ctx.guild.id, f'{branch.name[0]}_role': role.name, f'{branch.name[0]}p': {'$gt': 0}})
                for role in branch.roles
            }

            value = ''
            for i, role in enumerate(branch.roles):
                guild_role = await role.get_guild_role()
                value += f'\n**#{i + 1}:** <@&{guild_role.id}> - {count[guild_role.name]} ' + ('People' if count[guild_role.name] != 1 else 'Person')

            if not value:
                value = 'This branch currently has no roles'

            amount_of_people = sum(count.values())
            value += f'\n\nTotal: **{amount_of_people} ' + ('People**' if amount_of_people != 1 else 'Person**')
            embed.add_field(name=f'>{branch.name.title()} - Every 5 levels you advance a role', value=value, inline=False)

            return await ctx.send(embed=embed)

    @ranks.command(
        name='add',
        help='Add a role to parliamentary or honours route',
        usage='ranks add [branch] [role name]',
        examples=['ranks add honours Pro', 'ranks add honours Knight 2'],
        cls=commands.Command,
        module_dependency=['leveling_system']
    )
    async def ranks_add(self, ctx: Context, branch: str = None, *, role_name: str = None):
        if branch is None:
            return await embed_maker.command_error(ctx)

        leveling_guild = self.bot.leveling_system.get_guild(ctx.guild.id)
        branch = leveling_guild.get_leveling_route(branch)
        if branch is None:
            branch = leveling_guild.leveling_routes.parliamentary

        if not role_name:
            return await embed_maker.command_error(ctx, '[role name]')

        new_role = {
            'name': role_name,
            'perks': []
        }

        leveling_role = leveling.LevelingRole(ctx.guild, branch, new_role)
        branch.roles.append(leveling_role)

        await embed_maker.message(
            ctx,
            description=f'`{role_name}` has been added to the list of `{branch.name}` roles',
            colour='green',
            send=True
        )

        ctx.invoked_subcommand = ''
        return await self.ranks(ctx, branch.name)

    @ranks.command(
        name='remove',
        help='Remove a role from the list of parliamentary or honours roles',
        usage='ranks remove [branch] [role name]',
        examples=['ranks remove honours Knight'],
        cls=commands.Command,
        module_dependency=['leveling_system']
    )
    async def ranks_remove(self, ctx: Context, branch: str = None, *, role: str):
        if not branch or type(branch) == int:
            return await embed_maker.command_error(ctx)

        leveling_guild = self.bot.leveling_system.get_guild(ctx.guild.id)
        leveling_role = leveling_guild.get_leveling_role(role)

        branch = leveling_guild.get_leveling_route(branch)
        if branch is None:
            branch = leveling_guild.leveling_routes.parliamentary

        if leveling_role is None:
            return await embed_maker.error(ctx, f"Couldn't find a {branch.name} role by the name {role}")

        branch.roles.remove(leveling_role)

        await embed_maker.message(
            ctx,
            description=f'`{leveling_role.name}` has been remove from the list of `{branch.name}` roles',
            colour='green',
            send=True
        )

        ctx.invoked_subcommand = ''
        return await self.ranks(ctx, branch.name)

    @group(
        invoke_without_command=True,
        help='See all the perks that a role has to offer',
        usage='perks (role name)',
        examples=['perks', 'perks Party Member'],
        Moderators=commands.Help(
            help='See all the perks that a role has to offer or add or remove them',
            usage='perks (<sub command/role name>) (args)',
            examples=['perks', 'perks Party Member'],
        ),

        cls=commands.Group,
        module_dependency=['leveling_system']
    )
    async def perks(self, ctx: Context, *, role: str = None):
        if ctx.subcommand_passed is None:
            leveling_guild = self.bot.leveling_system.get_guild(ctx.guild.id)

            leveling_routes = leveling_guild.leveling_routes
            honours_branch = leveling_routes.honours
            parliamentary_branch = leveling_routes.parliamentary

            if role is None:
                # find roles that have perks
                filtered_parliamentary = list(filter(lambda r: r.perks, parliamentary_branch))
                filtered_honours = list(filter(lambda r: r.perks, honours_branch))

                embed = await embed_maker.message(
                    ctx,
                    description=f'To view perks of a role type `{ctx.prefix}perks [role name]`',
                    author={'name': f'List of roles with perks'},
                )

                if filtered_parliamentary:
                    parliamentary_str = '\n'.join(r.name for r in filtered_parliamentary)
                else:
                    parliamentary_str = 'Currently no Parliamentary roles offer any perks'

                if filtered_honours:
                    honours_str = '\n'.join(r.name for r in filtered_honours)
                else:
                    honours_str = 'Currently no Honours roles offer any perks'

                embed.add_field(name='>Parliamentary Roles With Perks', value=parliamentary_str, inline=False)
                embed.add_field(name='>Honours Roles With Perks', value=honours_str, inline=False)

                return await ctx.send(embed=embed)

            if role:
                leveling_role = leveling_guild.get_leveling_role(role)
                if not leveling_role.perks:
                    perks_str = f'**{leveling_role.name}** currently offers no perks'
                else:
                    perks_str = "\n".join([f'`#{i + 1}` - {perk}' for i, perk in enumerate(leveling_role.perks)])

                return await embed_maker.message(
                    ctx,
                    description=perks_str,
                    author={'name': f'{leveling_role.name} - Perks'},
                    send=True
                )

    async def modify_perks(self, ctx: Context, command: str, args: dict, message: str) -> Optional[Union[dict, discord.Message]]:
        if args is None:
            return await embed_maker.command_error(ctx)

        role_name = args['role']
        new_perks = args['perk']

        if not role_name:
            return await embed_maker.error(ctx, "Missing role arg")

        if not new_perks and command != 'pull':
            return await embed_maker.error(ctx, "Missing perks arg")

        leveling_guild = self.bot.leveling_system.get_guild(ctx.guild.id)
        leveling_role = leveling_guild.get_leveling_role(role_name)
        if not leveling_role:
            return await embed_maker.error(ctx, 'Invalid role provided.')

        if command == 'add':
            leveling_role.perks += new_perks
        elif command == 'set':
            leveling_role.perks = new_perks
        elif command == 'remove' and not new_perks:
            leveling_role.perks = []
        elif command == 'remove' and new_perks:
            to_remove = [int(num) - 1 for num in new_perks if num.isdigit() and 0 < int(num) <= len(leveling_role.perks)]
            leveling_role.perks = [perk for i, perk in enumerate(leveling_role.perks) if i not in to_remove]

        await embed_maker.message(
            ctx,
            description=message.format(**{'role': leveling_role}),
            colour='green',
            send=True
        )

        # send embed of role perks
        perks_str = "\n".join([f'`#{i + 1}` - {perk}' for i, perk in enumerate(leveling_role.perks)])

        return await embed_maker.message(
            ctx,
            description=perks_str,
            author={'name': f'{leveling_role.name} - New Perks'},
            send=True
        )

    @perks.command(
        name='set',
        help='set the perks of a role',
        usage='perks set [args]',
        examples=['perks set -r Party Member -p Monthly giveaways -p some cool perk'],
        command_args=[
            (('--role', '-r', str), 'The name of the role you want to set the perks for'),
            (('--perk', '-p', list), 'Perk for the role')
        ],
        cls=commands.Command,
        module_dependency=['leveling_system']
    )
    async def perks_set(self, ctx: Context, *, args: Union[ParseArgs, dict] = None):
        return await self.modify_perks(ctx, 'set', args, 'New perks have been set for role `{role.name}`')

    @perks.command(
        name='add',
        help='Add perks to a role',
        usage='perks add [args]',
        examples=['perks add -r Party Member -p Monthly giveaways -p some cool perk'],
        command_args=[
            (('--role', '-r', str), 'The name of the role you want to add the perks to'),
            (('--perk', '-p', list), 'Perk for the role')
        ],
        cls=commands.Command,
        module_dependency=['leveling_system']
    )
    async def perks_add(self, ctx: Context, *, args: Union[ParseArgs, dict] = None):
        return await self.modify_perks(ctx, 'add', args, 'New perks have been added for role `{role.name}`')

    @perks.command(
        name='remove',
        help='remove perks of a role, or remove only some perks',
        usage='perks remove -r [role name] -p (perk number)',
        examples=[
            'perks remove -r Party Member -p 1 -p 2',
            'perks remove -r Party Member'
        ],
        command_args=[
            (('--role', '-r', str), 'The name of the role you want to remove perks from'),
            (('--perk', '-p', list), 'Index of the perk you want to remove, can be seen by doing >perks [role]')
        ],
        cls=commands.Command,
        module_dependency=['leveling_system']
    )
    async def perks_remove(self, ctx: Context, *, args: Union[ParseArgs, dict] = None):
        return await self.modify_perks(ctx, 'remove', args, 'Perks have been removed from role `{role.name}`')

    @group(
        invoke_without_command=True,
        help='See all the honours channels',
        usage='honours_channel',
        examples=['honours_channels'],

        Admins=commands.Help(
            help='See current honours channels or add or remove them',
            usage='honours_channel (action - <add/remove>) [#channel]',
            examples=['honours_channels', 'honours_channels add #court', 'honours_channels remove #Mods'],
        ),
        cls=commands.Group,
        module_dependency=['leveling_system']
    )
    async def honours_channels(self, ctx: Context):
        if ctx.subcommand_passed is None:
            leveling_guild = self.bot.leveling_system.get_guild(ctx.guild.id)

            # display list of honours channels
            channel_list_str = ', '.join(f'<#{channel}>' for channel in leveling_guild.honours_channels) if leveling_guild.honours_channels else 'None'
            return await embed_maker.message(ctx, description=channel_list_str, send=True)

    @honours_channels.command(
        name='add',
        help='Add an honours channel',
        usage='honours_channels add [#channel]',
        examples=['honours_channels add #Tech-Lobby'],
        cls=commands.Command,
        module_dependency=['leveling_system']
    )
    async def honours_channels_add(self, ctx: Context, channel=None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        if not channel:
            return await embed_maker.command_error(ctx, '[#channel]')

        leveling_guild = self.bot.leveling_system.get_guild(ctx.guild.id)

        if channel.id not in leveling_guild.honours_channels:
            return await embed_maker.message(ctx, description='That channel is not on the list', colour='red', send=True)

        leveling_guild.honours_channels.remove(channel.id)
        msg = f'<#{channel.id}> has been removed from the list of honours channels'
        return await embed_maker.message(ctx, description=msg, colour='green', send=True)

    @honours_channels.command(
        name='remove',
        help='Remove an honours channel',
        usage='honours_channels remove [#channel]',
        examples=['honours_channels remove #Tech-Lobby'],
        cls=commands.Command,
        module_dependency=['leveling_system']
    )
    async def honours_channels_remove(self, ctx: Context, channel=None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        if not channel:
            return await embed_maker.command_error(ctx, '[#channel]')

        leveling_guild = self.bot.leveling_system.get_guild(ctx.guild.id)

        if channel.id in leveling_guild.honours_channels:
            return await embed_maker.message(ctx, description='That channel is already on the list', colour='red', send=True)

        leveling_guild.honours_channels.append(channel.id)
        msg = f'<#{channel.id}> has been added to the list of honours channels'
        return await embed_maker.message(ctx, description=msg, colour='green', send=True)

    @command(
        help='See how many messages you need to send to level up and rank up or see how many messages until you reach a level (dont forget about the 60s cooldown)',
        usage='mlu (level)',
        examples=['mlu', 'mlu 60'],
        cls=commands.Command,
        module_dependency=['leveling_system']
    )
    async def mlu(self, ctx: Context, level: Union[float, str] = None):
        # incase somebody typed something that isnt a level
        if type(level) == str:
            level = None

        leveling_member = await self.bot.leveling_system.get_member(ctx.guild.id, ctx.author.id)
        user_level = leveling_member.parliamentary.level
        points = leveling_member.parliamentary.points
        if not level:
            # points needed until level_up
            pp_till_next_level = round((5 / 6) * (user_level + 1) * (2 * (user_level + 1) * (user_level + 1) + 27 * (user_level + 1) + 91)) - points
            avg_msg_needed = math.ceil(pp_till_next_level / 20)

            # points needed to rank up
            user_rank = leveling_member.user_role_level(leveling_member.parliamentary)
            missing_levels = 6 - user_rank

            rank_up_level = user_level + missing_levels
            pp_needed_rank_up = round((5 / 6) * rank_up_level * (2 * rank_up_level * rank_up_level + 27 * rank_up_level + 91)) - points
            avg_msg_rank_up = math.ceil(pp_needed_rank_up / 20)
            description = f'Messages needed to:\n'\
                          f'Level up: **{avg_msg_needed}**\n'\
                          f'Rank up: **{avg_msg_rank_up}**'
        else:
            pp_needed = round((5 / 6) * level * (2 * level * level + 27 * level + 91)) - points
            avg_msg_needed = math.ceil(pp_needed / 20)
            description = f'Messages needed to reach level `{level}`: **{avg_msg_needed}**'

        return await embed_maker.message(
            ctx,
            description=description,
            author={'name': 'MLU'},
            send=True
        )

    async def construct_lb_str(self, ctx: Context, branch: leveling.LevelingRoute, sorted_users: list, index: int, your_pos: bool = False):
        lb_str = ''
        for i, leveling_user in enumerate(sorted_users):
            leveling_member = await self.bot.leveling_system.get_member(ctx.guild.id, leveling_user['user_id'])
            addition = 0 if your_pos else 1

            member = leveling_member.member
            if leveling_member.id == ctx.author.id:
                lb_str += rf'**`#{index + i + addition}`**\* - {member.display_name}'
            else:
                lb_str += f'`#{index + i + addition}` - {member.display_name}'

            if not your_pos:
                lb_str += f'  [{member}]'

            pre = '\n' if not your_pos else ' | '

            # parliamentary and honours branches need different things from rep
            if branch.name[0] in ['p', 'h']:
                user_branch = leveling_member.parliamentary if branch.name[0] == 'p' else leveling_member.honours
                user_role = await leveling_member.guild.get_leveling_role(user_branch.role).get_guild_role()
                role_level = leveling_member.user_role_level(user_branch)
                progress_percent = leveling_member.percent_till_next_level(user_branch)

                lb_str += f'{pre}**Level {role_level}** <@&{user_role.id}> | Progress: **{progress_percent}%**\n'
                if not your_pos:
                    lb_str += '\n'
            else:
                lb_str += f' | **{leveling_member.rp} Reputation**\n'

        return lb_str

    async def construct_lb_embed(self, ctx: Context, branch: leveling.LevelingRoute, user_index: int, sorted_users: list, page_size_limit: int, max_page_num: int, *, page: int):
        sorted_users_page = sorted_users[page_size_limit * (page - 1):page_size_limit * page]
        leaderboard_str = await self.construct_lb_str(ctx, branch, sorted_users_page, index=page_size_limit * (page - 1))
        description = 'Damn, this place is empty' if not leaderboard_str else leaderboard_str

        leaderboard_embed = await embed_maker.message(
            ctx,
            description=description,
            footer={'text': f'{ctx.author} | Page {page}/{max_page_num}'},
            author={'name': f'{branch.name.title()} Leaderboard'}
        )

        # Displays user position under leaderboard and users above and below them if user is below position 10
        if user_index < len(sorted_users) and not (user_index + 1 <= page * page_size_limit):
            sorted_users_segment = sorted_users[user_index - 1:user_index + 2]
            your_pos_str = await self.construct_lb_str(ctx, branch, sorted_users_segment, user_index, your_pos=True)
            leaderboard_embed.add_field(name='Your Position', value=your_pos_str)

        return leaderboard_embed

    @command(
        help='Shows the leveling leaderboards (parliamentary(p)/honours(h)) on the server',
        usage='leaderboard (branch)',
        aliases=['lb'],
        examples=['leaderboard parliamentary', 'lb honours'],
        cls=commands.Command,
        module_dependency=['reaction_menus', 'leveling_system']
    )
    async def leaderboard(self, ctx: Context, branch: str = 'parliamentary', page: int = 1):
        leveling_guild = self.bot.leveling_system.get_guild(ctx.guild.id)
        leveling_routes = leveling_guild.leveling_routes

        if branch.isdigit():
            page = int(branch)
            branch = leveling_guild.leveling_routes.parliamentary
        else:
            branch_switch = {'p': leveling_routes.parliamentary, 'h': leveling_routes.honours, 'r': leveling_routes.reputation}
            branch = branch_switch.get(branch[0], leveling_routes.parliamentary)

        key = f'{branch.name[0]}p'
        # get list of users sorted by points who have more than 0 points
        sorted_users = [u for u in db.leveling_users.find({'guild_id': ctx.guild.id, key: {'$gt': 0}}).sort(key, -1)]

        page_size_limit = 10

        # calculate max page number
        max_page_num = math.ceil(len(sorted_users) / page_size_limit)
        if max_page_num == 0:
            max_page_num = 1

        if page > max_page_num:
            return await embed_maker.error(ctx, 'Exceeded maximum page number')

        leveling_user = db.get_leveling_user(ctx.guild.id, ctx.author.id)
        user_index = sorted_users.index(leveling_user) if leveling_user in sorted_users else len(sorted_users)

        # create function with all the needed values except page, so the function can be called with only the page kwarg
        page_constructor = functools.partial(
            self.construct_lb_embed,
            ctx,
            branch,
            user_index,
            sorted_users,
            page_size_limit,
            max_page_num
        )

        # make and send initial leaderboard page
        leaderboard_embed = await page_constructor(page=page)
        leaderboard_message = await ctx.send(embed=leaderboard_embed)

        menu = BookMenu(
            leaderboard_message,
            author=ctx.author,
            page=page,
            max_page_num=max_page_num,
            page_constructor=page_constructor,
            extra_back=5,
            extra_forward=5
        )

        self.bot.reaction_menus.add(menu)

    async def branch_rank_str(self, user_branch: leveling.LevelingUserBranch, leveling_member: leveling.LevelingMember, verbose: bool):
        role_level = leveling_member.user_role_level(user_branch)

        # calculate user rank by counting users who have more points than user
        rank = leveling_member.rank(user_branch)

        leveling_role = leveling_member.guild.get_leveling_role(user_branch.role)
        if leveling_role is None:
            return

        guild_role = await leveling_role.get_guild_role()

        progress = leveling_member.percent_till_next_level(user_branch)

        if verbose:
            points_till_next_level = round(5 / 6 * (user_branch.level + 1) * (2 * (user_branch.level + 1) * (user_branch.level + 1) + 27 * (user_branch.level + 1) + 91))
            cooldown_object = self.pp_cooldown

            cooldown = f'{cooldown_object.user_cooldown(leveling_member.guild.id, leveling_member.id)} seconds'

            rank_str = f'**Rank:** `#{rank}`\n' \
                       f'**Role:** <@&{guild_role.id}>\n' \
                       f'**Role Level:** {role_level}\n' \
                       f'**Total Level:** {user_branch.level}\n' \
                       f'**Points:** {user_branch.points}/{points_till_next_level}\n' \
                       f'**Progress:** {progress}%\n' \
                       f'**Cooldown**: {cooldown}'
        else:
            rank_str = f'**#{rank}** | **Level** {role_level} <@&{guild_role.id}> | Progress: **{progress}%**'

        return rank_str

    @staticmethod
    async def rep_rank_str(leveling_member: leveling.LevelingMember, verbose: bool):
        # this is kind of scuffed, but it works
        rank = leveling_member.rank(leveling_member.reputation)
        if verbose:
            rep_time = int(leveling_member.rep_timer) - round(time.time())
            if rep_time < 0:
                rep_time = 0

            rep_time_str = format_time.seconds(rep_time, accuracy=10)

            last_rep = f'<@{leveling_member.last_rep}>' if leveling_member.last_rep else 'None'
            rep_str = f"**Reputation:** {leveling_member.rp}\n" \
                      f"**Rep timer:** {rep_time_str}\n" \
                      f"**Last Rep: {last_rep}**\n"
        else:
            rep_str = f'**#{rank}** | **{leveling_member.rp}** reputation'

        return rep_str

    @command(
        help='Shows your (or someone else\'s) rank and level, add -v too see all the data',
        usage='rank (member) (-v)',
        examples=['rank', 'rank @Hattyot', 'rank Hattyot -v'],
        cls=commands.Command,
        module_dependency=['leveling_system']
    )
    async def rank(self, ctx: Context, *, user_input: str = ''):
        verbose = bool(re.findall(r'(?:\s|^)(-v)(?:\s|$)', user_input))

        user_input = re.sub(r'((\s|^)-v(\s|$))', '', user_input)

        # set member to author if user_input is just -v or user_input isn't provided
        if not user_input:
            member = ctx.author
        else:
            member = await get_member(ctx, user_input)
            if type(member) == discord.Message:
                return

        if member.bot:
            return await embed_maker.error(ctx, 'No bots allowed >:(')

        rank_embed = await embed_maker.message(
            ctx,
            footer={'text': str(member), 'icon_url': member.avatar_url},
            author={'name': f'{member.name} - Rank'}
        )

        leveling_member = await self.bot.leveling_system.get_member(ctx.guild.id, member.id)

        # inform user of boost, if they have it
        boost_multiplier = leveling_member.boosts.get_multiplier()
        if boost_multiplier > 1:
            boost_percent = round((boost_multiplier - 1) * 100, 1)

            if boost_percent.is_integer():
                boost_percent = int(boost_percent)

            rank_embed.description = f'Active boost: **{boost_percent}%** parliamentary points gain!'

        if leveling_member.honours.points > 0:
            user_branch = leveling_member.honours
            hp_str = await self.branch_rank_str(user_branch, leveling_member, verbose)
            rank_embed.add_field(name='>Honours', value=hp_str, inline=False)

        user_branch = leveling_member.parliamentary
        pp_str = await self.branch_rank_str(user_branch, leveling_member, verbose)
        rank_embed.add_field(name='>Parliamentary', value=pp_str, inline=False)

        if leveling_member.rp:
            rep_str = await self.rep_rank_str(leveling_member, verbose)
            rank_embed.add_field(name='>Reputation', value=rep_str, inline=False)

        # add boosts field
        if verbose and leveling_member.boosts:
            boost_str = ''
            for i, boost in enumerate(leveling_member.boosts):
                if boost.has_expired():
                    boost.remove()

                percent = round(boost.multiplier * 100, 1)
                boost_str += f'`#{i + 1}` - {percent}% boost | Expires: {format_time.seconds(boost.expires - round(time.time()), accuracy=5)}'
                boost_str += f' | Type: {boost.boost_type}\n'

            boost_str = 'None' if not boost_str else boost_str
            rank_embed.add_field(name='>Boosts', value=boost_str)

        if verbose:
            rank_embed.add_field(name='>Settings', value=f'**@me:** {leveling_member.settings.at_me}', inline=False)

        return await ctx.send(embed=rank_embed)

    @command(
        help='Toggle the different leveling settings.',
        usage='settings (setting)',
        examples=["settings @me", "settings rep@"],
        cls=commands.Command,
        module_dependency=['leveling_system']
    )
    async def settings(self, ctx: Context, *, setting: str = None):
        embed = await embed_maker.message(ctx, description=f"To toggle a setting, type `{ctx.prefix}settings [setting]`", author={'name': 'Settings'})

        leveling_member = await self.bot.leveling_system.get_member(ctx.guild.id, ctx.author.id)
        if setting is None:
            at_me_value = f'You will {"not" * (not leveling_member.settings.at_me)} be @\' when you level up.'
            embed.add_field(name='| @me', value=f'**{leveling_member.settings.at_me}**\n{at_me_value}', inline=False)

            rep_at_value = f'You will {"not" * (not leveling_member.settings.rep_at)} be messaged when your rep timer expires and you can give someone a rep point again.'
            embed.add_field(name='| rep@', value=f'**{leveling_member.settings.rep_at}**\n{rep_at_value}', inline=False)
            return await ctx.send(embed=embed)
        elif setting not in ['@me', 'rep@']:
            return await embed_maker.error(ctx, f'{setting} is not a valid setting\nValid Settings: `@me` | `rep@`')
        else:
            if setting == '@me':
                leveling_member.settings.toggle_at_me()
                if leveling_member.settings.at_me:
                    msg = 'You will now be @\'d when you level up.'
                    colour = 'green'
                else:
                    msg = 'You will no longer be @\'d when you level up'
                    colour = 'orange'

                return await embed_maker.message(ctx, description=msg, colour=colour, send=True)
            if setting == 'rep@':
                leveling_member.settings.toggle_rep_at()
                if leveling_member.settings.rep_at:
                    msg = 'I will now message you when your rep timer expires.'
                    colour = 'green'
                else:
                    msg = 'I will no longer message you when your rep timer expires.'
                    colour = 'orange'

                return await embed_maker.message(ctx, description=msg, colour=colour, send=True)

    async def process_message(self, message: discord.Message):
        author = message.author
        guild = message.guild

        leveling_member = await self.bot.leveling_system.get_member(guild.id, author.id)

        # level parliamentary route
        if not self.pp_cooldown.user_cooldown(guild.id, author.id):
            pp_add = randint(15, 25)
            await leveling_member.add_points('parliamentary', pp_add)

            branch = leveling_member.guild.get_leveling_route('parliamentary')
            current_role, levels_up, roles_up = await leveling_member.level_up(branch)

            if levels_up:
                current_role = await current_role.get_guild_role()
                await leveling_member.level_up_message(message, leveling_member.parliamentary, current_role, roles_up)

        # level honours route
        if message.channel.id in leveling_member.guild.honours_channels and not self.hp_cooldown.user_cooldown(guild.id, author.id):
            hp_add = randint(7, 12)
            await leveling_member.add_points('honours', hp_add)

            branch = leveling_member.guild.get_leveling_route('honours')
            current_role, levels_up, roles_up = await leveling_member.level_up(branch)

            if levels_up:
                current_role = await current_role.get_guild_role()
                await leveling_member.level_up_message(message, leveling_member.honours, current_role, roles_up)


def setup(bot):
    bot.add_cog(Leveling(bot))
