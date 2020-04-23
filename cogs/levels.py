import discord
import config
from datetime import datetime
from time import time
from random import randint
from discord.ext import commands
from modules import database, command, embed_maker, context

db = database.Connection()
pp_cooldown = {}
hp_cooldown = {}
# Cooldown objects for giving and receiving reactions
receive_cooldown = {}
give_cooldown = {}


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='Add a role to a leveling route (honours/parliamentary)',
                      usage='add_role -b [branch] -r [role name] -l [max level]',
                      examples=['add_role -b honours -r Lord -l 5'], clearance='Admin', cls=command.Command)
    async def add_role(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        parsed_args = self.parse_role_args(args)
        branch = parsed_args['b']
        role_name = parsed_args['r']
        role_level = parsed_args['l']

        leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
        if branch not in leveling_routes:
            embed = embed_maker.message(ctx, 'That is not a valid branch. (honours/parliamentary)', colour='red')
            return await ctx.send(embed=embed)

        if not role_name or not role_level:
            embed = embed_maker.message(ctx, 'One or more of the args is invalid', colour='red')
            return await ctx.send(embed=embed)

        new_role = discord.utils.find(lambda r: r.name == role_name, ctx.guild.roles)
        if new_role is None:
            try:
                new_role = await ctx.guild.create_role(name=role_name)
            except discord.Forbidden:
                return await ctx.send('failed to create role, missing permissions')

        new_role_route_list = leveling_routes[branch][:]
        new_role_route_list.insert(len(leveling_routes[branch]), (new_role.name, round(int(role_level))))

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'leveling_routes.{branch}': new_role_route_list}})
        db.get_levels.invalidate('leveling_routes', ctx.guild.id)

        await ctx.send(f'added {new_role.name} to {branch} route')
        await self.leveling_routes(ctx, True)

        prev_role_name = ''
        for i, r in enumerate(new_role_route_list):
            if r[0] == new_role.name:
                prev_role_name = new_role_route_list[i - 1][0]
                break

        prev_role = discord.utils.find(lambda r: r.name == prev_role_name, ctx.guild.roles)
        pre = 'p' if branch.lower() == 'parliamentary' else 'h'
        for m in prev_role.members:
            user_role_level = await self.user_role_level(ctx, branch, m, 0)

            if user_role_level < 0:
                # Get next role
                role_index = self.get_role_index(branch, ctx.guild.id, prev_role_name)
                new_role = new_role_route_list[role_index + abs(user_role_level)][0]

                role = discord.utils.find(lambda r: r.name == new_role, ctx.guild.roles)
                if role is None:
                    role = await ctx.guild.create_role(name=new_role)

                await m.add_roles(role)
                db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{m.id}.{pre}_role': role.name}})
                db.get_levels.invalidate(f'{pre}_role', ctx.guild.id, m.id)

                user_role_level = await self.user_role_level(ctx, branch, m, 0)
                reward_text = f'Congrats <@{m.id}> you\'ve advanced to a level **{user_role_level}** <@&{role.id}>'

                return await self.level_up_message(ctx, m, reward_text)

    @commands.command(help='Add a channel to the list of channels, in which honours points can be gained', usage='add_honours_channels [#channel]', examples=['add_honours_channels #court'], clearance='Admin', cls=command.Command)
    async def add_honours_channel(self, ctx, channel=None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        channel_list = db.get_levels('honours_channels', ctx.guild.id)

        if ctx.message.channel_mentions:
            channel = ctx.message.channel_mentions[0]
            if channel.id in channel_list:
                embed = embed_maker.message(ctx, f'That channel is already on the list', colour='red')
                return await ctx.send(embed=embed)
            db.levels.update_one({'guild_id': ctx.guild.id}, {'$push': {f'honours_channels': channel.id}})
            db.get_levels.invalidate('honours_channels', ctx.guild.id)

            embed = embed_maker.message(ctx, f'<#{channel.id}> has been added to the list', colour='green')
            await ctx.send(embed=embed)
        else:
            return await embed_maker.command_error(ctx, '[#channel]')

    @commands.command(help='Remove a channel from the list of channels, in which honours points can be gained', usage='add_honours_channels [#channel]', examples=['add_honours_channels #court'], clearance='Admin', cls=command.Command)
    async def remove_honours_channel(self, ctx, channel=None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        channel_list = db.get_levels('honours_channels', ctx.guild.id)

        if ctx.message.channel_mentions:
            channel = ctx.message.channel_mentions[0]
            if channel.id not in channel_list:
                embed = embed_maker.message(ctx, f'That channel is not on the list', colour='red')
                return await ctx.send(embed=embed)
            db.levels.update_one({'guild_id': ctx.guild.id}, {'$pull': {f'honours_channels': channel.id}})
            db.get_levels.invalidate('honours_channels', ctx.guild.id)

            embed = embed_maker.message(ctx, f'<#{channel.id}> has been removed from the list', colour='green')
            await ctx.send(embed=embed)
        else:
            return await embed_maker.command_error(ctx, '[#channel]')

    @commands.command(help='See the current list of channels where honours points can be earned', usage='honours_channel_list', examples=['honours_channel_list'], clearance='Mod', cls=command.Command)
    async def honours_channel_list(self, ctx):
        channel_list = db.get_levels('honours_channels', ctx.guild.id)
        channel_list_str = '\n'.join(f'<#{i}>\n' for i in channel_list) if channel_list else 'None'

        embed = embed_maker.message(ctx, channel_list_str)
        return await ctx.send(embed=embed)

    @commands.command(help='Edit attributes of a role',
                      usage='edit_role -b [branch] -r [role name] -nr [new role name] -nl [new max level]',
                      examples=['edit_role -b parliamentary -r Member -nr Citizen -nl 5'], clearance='Admin', cls=command.Command)
    async def edit_role(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        parsed_args = self.parse_role_args(args)
        branch = parsed_args['b']
        role_name = parsed_args['r']
        new_role_name = parsed_args['nr']
        new_role_level = parsed_args['nl']

        leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
        if branch not in leveling_routes:
            embed = embed_maker.message(ctx, 'That is not a valid branch. (honours/parliamentary)', colour='red')
            return await ctx.send(embed=embed)

        if not role_name:
            embed = embed_maker.message(ctx, 'Role arg is empty', colour='red')
            return await ctx.send(embed=embed)

        for r in leveling_routes[branch]:
            if r[0] == role_name:
                break
        else:
            error_embed = embed_maker.message(ctx, f'{role_name} is not a valid role', colour='red')
            return await ctx.send(embed=error_embed)

        if not new_role_name and not new_role_level:
            embed = embed_maker.message(ctx, 'Neither a new role name nor a new max level is defined', colour='red')
            return await ctx.send(embed=embed)

        new_role_list = leveling_routes[branch][:]
        for i, _role in enumerate(leveling_routes[branch]):
            old_role_name, old_role_level = _role
            if old_role_name == role_name:
                role_level = new_role_level if new_role_level else old_role_level

                if new_role_name:
                    role_name = new_role_name
                    role = discord.utils.find(lambda r: r.name == old_role_name, ctx.guild.roles)
                    await role.edit(name=role_name)

                    # Update users in db
                    await self.update_user_roles(ctx, branch, role)
                else:
                    role_name = old_role_name

                new_role_list[i] = (role_name, round(int(role_level)))

                db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'leveling_routes.{branch}': new_role_list}})
                db.get_levels.invalidate('leveling_routes', ctx.guild.id)

                await ctx.send(f'Edited {role_name}')
                return await self.leveling_routes(ctx, True)

    async def update_user_roles(self, ctx, branch, role):
        pre = 'p_' if branch.lower() == 'parliamentary' else 'h_'
        for m in role.members:
            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{m.id}.{pre}role': role.name}})
            db.get_levels.invalidate(f'{pre}role', ctx.guild.id, m.id)

    def parse_role_args(self, args):
        result = dict.fromkeys(['b', 'r', 'l', 'nr', 'nl'], '')

        split_args = filter(None, args.split('-'))
        for a in split_args:
            match = tuple(map(str.strip, a.split(' ', 1)))
            if len(match) < 2:
                return result
            key, value = match
            result[key] = value

        return result

    @commands.command(help='See current leveling routes', usage='leveling_routes', examples=['leveling_routes'], clearance='User', cls=command.Command)
    async def leveling_routes(self, ctx, new=False):
        lvl_routes = db.get_levels('leveling_routes', ctx.guild.id)
        embed_colour = config.DEFAULT_EMBED_COLOUR

        if new:
            embed_colour = embed_maker.get_colour('green')
            author = 'New Leveling Routes'
        else:
            author = 'Leveling Routes'

        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_author(name=author, icon_url=ctx.guild.icon_url)
        embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)

        for branch in lvl_routes:
            value = ''
            if branch == 'honours':
                continue
            for i, _role in enumerate(lvl_routes[branch]):
                role = discord.utils.find(lambda r: r.name == _role[0], ctx.guild.roles)
                if role is None:
                    role = await ctx.guild.create_role(name=_role[0])
                value += f'\n**#{i + 1}:** <@&{role.id}> - Max Level: {_role[1]}'
            embed.add_field(name=f'>{branch.title()}', value=value, inline=False)
        return await ctx.send(embed=embed)

    @commands.command(help='award someone honours points, for contributing to the server or youtube channels', usage='award [@member] [amount]', examples=['award @Hattyot 500'], clearance='Mod', cls=command.Command)
    async def award(self, ctx, member=None, amount=None):
        if member is None:
            return await embed_maker.command_error(ctx)
        if ctx.message.mentions:
            member = ctx.message.mentions[0]
        else:
            return await embed_maker.command_error(ctx, '[@member]')

        if member.bot:
            embed = embed_maker.message(ctx, 'You can\'t give honours points to bots', colour='red')
            return await ctx.send(embed=embed)
        if member == ctx.author:
            embed = embed_maker.message(ctx, 'You can\'t give honours points to yourself', colour='red')
            return await ctx.send(embed=embed)

        if amount is None:
            return await embed_maker.command_error(ctx, '[amount]')
        if not amount.isdigit():
            return await embed_maker.command_error(ctx, '[amount]')

        amount = round(int(amount))

        user_hp = db.get_levels('hp', ctx.guild.id, member.id)
        new_hp = amount + user_hp

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{member.id}.hp': new_hp}})
        db.get_levels.invalidate('hp', ctx.guild.id, member.id)

        embed = embed_maker.message(ctx, f'<@{member.id}> has been awarded **{amount} honours points**', colour='green')
        await ctx.send(embed=embed)

        if user_hp == 0:
            return await self.hp_init(ctx, member, new_hp)

        return await self.level_up(ctx, member, 'honours', new_hp)

    async def hp_init(self, ctx, member, new_hp):
        leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
        h_role_name = leveling_routes['honours'][0][0]
        h_role = discord.utils.find(lambda r: r.name == h_role_name, ctx.guild.roles)

        if h_role is None:
            h_role = await ctx.guild.create_role(name=h_role_name)

        await member.add_roles(h_role)
        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{member.id}.h_role': h_role.name}})
        db.get_levels.invalidate('h_role', ctx.guild.id, member.id)

        if new_hp < 1000:
            lvl = 0
            reward_text = f'Congrats <@{member.id}> you\'ve advanced to a level **{lvl}** <@&{h_role.id}>, due to your contributions!'
            return await self.level_up_message(ctx, member, reward_text)
        else:
            return await self.level_up(ctx, member, 'honours', new_hp)

    @commands.command(help='Shows the leveling leaderboard on the server', usage='leaderboard', examples=['leaderboard'], clearance='User', cls=command.Command)
    async def leaderboard(self, ctx, user_page=1):
        #if branch is None:
        #    return await embed_maker.command_error(ctx)

        #branch = 'honours' if branch == 'h' else 'parliamentary'
        branch = 'parliamentary'
        """
	if branch == 'honours':
            pre = 'h'
        elif branch == 'parliamentary':
            pre = 'p'
        else:
            return
	"""
        pre = 'p'
        doc = db.levels.find_one({'guild_id': ctx.guild.id})
        sorted_users = sorted(doc['users'].items(), key=lambda x: x[1][f'{pre}p'], reverse=True)
        embed_colour = config.DEFAULT_EMBED_COLOUR
        page_num = 1
        lboard = {page_num: []}

        for i, u in enumerate(sorted_users):
            if i == 10:
                break

            user_id, user_values = u
            member = ctx.guild.get_member(user_id)
            if member is None:
                try:
                    member = await ctx.guild.fetch_member(user_id)
                except:
                    i -= 1
                    continue

            role_level = await self.user_role_level(ctx, branch, member)
            user_role_name = user_values[f'{pre}_role']
            if user_role_name == '':
                continue
            user_role = discord.utils.find(lambda r: r.name == user_role_name, ctx.guild.roles)
            page_message = f'**#{i + 1}** - {member.name} | **Level {role_level}** <@&{user_role.id}>'
            lboard[page_num].append(page_message)

        if not lboard[user_page]:
            description = 'Damn, this place is empty'
        else:
            description = '\n'.join(lboard[user_page])

        lboard_embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=description)
        lboard_embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
        lboard_embed.set_author(name=f'{branch.title()} Leaderboard', icon_url=ctx.guild.icon_url)

        lboard_msg = await ctx.send(embed=lboard_embed)

    @commands.command(help='Shows your (or someone else\'s) rank and level', usage='rank (@member)', examples=['rank', 'rank @Hattyot'], clearance='User', cls=command.Command)
    async def rank(self, ctx, member=None):
        if member and ctx.message.mentions:
            member = ctx.message.mentions[0]
        else:
            member = ctx.author

        if member.bot:
            return

        member_p_level = await self.user_role_level(ctx, 'parliamentary', member)
        member_h_level = await self.user_role_level(ctx, 'honours', member)

        p_role_name = db.get_levels('p_role', ctx.guild.id, member.id)
        h_role_name = db.get_levels('h_role', ctx.guild.id, member.id)
        member_p_role = discord.utils.find(lambda r: r.name == p_role_name, ctx.guild.roles)
        member_h_role = discord.utils.find(lambda r: r.name == h_role_name, ctx.guild.roles)

        p_rank = self.calculate_user_rank('pp', ctx.guild.id, member.id)
        h_rank = self.calculate_user_rank('hp', ctx.guild.id, member.id)

        if member_p_role is None:
            member_p_role = await ctx.guild.create_role(name=p_role_name)
            await member.add_roles(member_p_role)

        sp_value = f'**#{p_rank}** | **Level** {member_p_level} <@&{member_p_role.id}>'

        if h_role_name == '':
            hp_value = f'**Level** {member_h_level}'
        else:
            if member_h_role is None:
                member_h_role = await ctx.guild.create_role(name=h_role_name)
                await member.add_roles(member_h_role)

            hp_value = f'**#{h_rank}** | **Level** {member_h_level} <@&{member_h_role.id}>'

        embed_colour = config.DEFAULT_EMBED_COLOUR
        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
        embed.set_author(name=f'{member.name} - Rank', icon_url=ctx.guild.icon_url)
        embed.add_field(name='>Parliamentary', value=sp_value, inline=False)
#       embed.add_field(name='>Honours', value=hp_value, inline=False)

        return await ctx.send(embed=embed)

    def calculate_user_rank(self, branch, guild_id, user_id):
        doc = db.levels.find_one({'guild_id': guild_id})
        sorted_users = sorted(doc['users'].items(), key=lambda x: x[1][branch], reverse=True)
        for i, u in enumerate(sorted_users):
            u_id, _ = u
            if u_id == str(user_id):
                return i + 1

    async def process_reaction(self, payload):
        guild = self.bot.get_guild(payload.guild_id)
        user = guild.get_member(payload.user_id)
        channel = self.bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        ctx = await self.bot.get_context(message, cls=context.Context)

        # Add pp to user who received reaction
        if self.cooldown_expired(receive_cooldown, guild.id, message.author, 60):
            pp_add = 10
            await self.add_reaction_pp(ctx, message.author, pp_add)

        # Add pp to user who gave reaction
        if self.cooldown_expired(give_cooldown, guild.id, user, 60):
            pp_add = 5
            await self.add_reaction_pp(ctx, user, pp_add)

    async def add_reaction_pp(self, ctx, user, pp_add):
        new_pp = db.get_levels('pp', ctx.guild.id, user.id) + pp_add

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{user.id}.pp': new_pp}})
        db.get_levels.invalidate('pp', ctx.guild.id, user.id)

        await self.level_up(ctx, user, 'parliamentary', new_pp)

    def cooldown_expired(self, cooldown_dict, guild_id, member_id, cooldown_time):
        if guild_id not in cooldown_dict:
            cooldown_dict[guild_id] = {}
        if member_id in cooldown_dict[guild_id]:
            if round(time()) >= cooldown_dict[guild_id][member_id]:
                del cooldown_dict[guild_id][member_id]
            else:
                return False

        cooldown_expire = round(time()) + cooldown_time
        cooldown_dict[guild_id][member_id] = cooldown_expire
        return True

    async def process_hp_message(self, ctx):
        if self.cooldown_expired(hp_cooldown, ctx.guild.id, ctx.author.id, 60):
            hp_add = 5
            user_hp = ctx.author_hp
            new_hp = user_hp + hp_add

            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{ctx.author.id}.hp': new_hp}})
            db.get_levels.invalidate('hp', ctx.guild.id, ctx.author.id)

            if user_hp == 0:
                return await self.hp_init(ctx, ctx.author, new_hp)

            await self.level_up(ctx, ctx.author, 'honours', new_hp)

    async def process_message(self, ctx):
        if self.cooldown_expired(pp_cooldown, ctx.guild.id, ctx.author.id, 60):
            pp_add = randint(15, 25)
            new_pp = ctx.author_pp + pp_add

            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{ctx.author.id}.pp': new_pp}})
            db.get_levels.invalidate('pp', ctx.guild.id, ctx.author.id)

            await self.level_up(ctx, ctx.author, 'parliamentary', new_pp)

    async def level_up(self, ctx, member, branch, new_value):
        if branch == 'honours':
            pre = 'h_'
            lvl_up, lvls_up = hpi(ctx.guild.id, member.id, new_value)
        else:
            pre = 'p_'
            lvl_up, lvls_up = ppi(ctx.guild.id, member.id, new_value)

        if not lvl_up:
            return

        user_role = db.get_levels(f'{pre}role', ctx.guild.id, member.id)
        role = discord.utils.find(lambda r: r.name == user_role, ctx.guild.roles)
        if role is not None and role not in ctx.author.roles:
             await member.add_roles(role)
        user_role_level = await self.user_role_level(ctx, branch, member, lvls_up)

        if user_role_level < 0:
            # Get next role
            leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
            roles = leveling_routes[branch]
            role_index = self.get_role_index(branch, ctx.guild.id, role.name)
            print(role_index, abs(user_role_level))
            new_role = roles[role_index + abs(user_role_level)][0]
            print(new_role)

            new_role_obj = discord.utils.find(lambda r: r.name == new_role, ctx.guild.roles)
            if new_role_obj is None:
                new_role_obj = await ctx.guild.create_role(name=new_role)

            await member.add_roles(new_role_obj)
            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{member.id}.{pre}role': new_role_obj.name}})
            db.get_levels.invalidate(f'{pre}role', ctx.guild.id, member.id)

            user_role_level = await self.user_role_level(ctx, branch, member, lvls_up)
            reward_text = f'Congrats <@{member.id}> you\'ve advanced to a level **{user_role_level}** <@&{new_role_obj.id}>'

        else:
            role = discord.utils.find(lambda r: r.name == user_role, ctx.guild.roles)

            if role is None:
                role = await ctx.guild.create_role(name=user_role)
                await member.add_roles(role)

            reward_text = f'Congrats <@{member.id}> you\'ve become a level **{user_role_level}** <@&{role.id}>'

        if branch == 'honours':
            reward_text += 'due to your contributions!'
        else:
            reward_text += '!'

        await self.level_up_message(ctx, member, reward_text)

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'users.{member.id}.{pre}level': lvls_up}})
        db.get_levels.invalidate(f'{pre}level', ctx.guild.id, member.id)

    async def level_up_message(self, ctx, member, reward_text):
        embed_colour = config.DEFAULT_EMBED_COLOUR
        embed = discord.Embed(colour=embed_colour, description=reward_text, timestamp=datetime.now())
        embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
        embed.set_author(name='Level Up!', icon_url=ctx.guild.icon_url)

        channel_id = db.get_levels('level_up_channel', ctx.guild.id)
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            await ctx.send(embed=embed)
        else:
            await channel.send(embed=embed)

    # Returns the level of current role
    async def user_role_level(self, ctx, branch, member, lvl_add=0):
        if branch == 'honours':
            pre = 'h_'
        else:
            pre = 'p_'

        user_level = db.get_levels(f'{pre}level', ctx.guild.id, member.id)
        user_role = db.get_levels(f'{pre}role', ctx.guild.id, member.id)

        if user_role == '':
            return user_level

        role_obj = discord.utils.find(lambda r: r.name == user_role, ctx.guild.roles)

        if role_obj not in member.roles:
            await member.add_roles(role_obj)

        user_level = int(user_level + lvl_add)

        leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
        all_roles = leveling_routes[branch]

        role_index = self.get_role_index(branch, ctx.guild.id, user_role)
        print(role_index)
        if role_index is None:
            return user_level

        current_level_total = 0
        previous_level_total = 0
        role_amount = len(all_roles)
        for i, role in enumerate(all_roles):
            current_level_total += role[1]
            if role_amount == i + 1:
                return user_level - previous_level_total
            if role_index > i:
                previous_level_total += role[1]
                continue
            if current_level_total > user_level:
                return user_level - previous_level_total
            if current_level_total == user_level:
                return role[1]
            if current_level_total < user_level:
                break

        roles_up = 0
        current_level_total = 0
        previous_level_total = 0
        for i, role in enumerate(all_roles):
            current_level_total += role[1]
            if role_index >= i:
                previous_level_total += role[1]
            if current_level_total < user_level:
                roles_up -= 1
        else:
            roles_up = -1

        return roles_up

    def get_role_index(self, branch, guild_id, user_role):
        if user_role == '':
            return None

        leveling_routes = db.get_levels('leveling_routes', guild_id)
        all_roles = leveling_routes[branch]

        for i, role in enumerate(all_roles):
           if role[0] == user_role:
                return i
        else:
            return 0

# How much pp is needed until level up
def ppi(guild_id, member_id, new_pp):
    user_pp = new_pp
    user_level = db.get_levels('p_level', guild_id, member_id)

    levels_up = 0
    for i in range(1000):
        # total pp needed to gain the next level
        total_pp = 0
        for j in range(int(user_level) + i + 1):
            # the formula to calculate how much pp you need for the next level
            total_pp += (5 * ((j) ** 2) + 50 * (j) + 100)

        if total_pp - user_pp >= 0 and levels_up >= 1:
            print(levels_up)
            return True, levels_up
        elif total_pp - user_pp >= 0:
            return False, levels_up

        levels_up += 1


# How much hp is needed until level up, works the same way as ppi
def hpi(guild_id, member_id, new_hp):
    user_hp = new_hp
    user_level = db.get_levels('h_level', guild_id, member_id)

    levels_up = 0
    for i in range(1000):
        total_hp = 1000 * (user_level + i)
        if total_hp - user_hp >= 0 and levels_up >= 1:
            return True, levels_up
        elif total_hp - user_hp >= 0:
            return False, levels_up

        levels_up += 1


def setup(bot):
    bot.add_cog(Levels(bot))
