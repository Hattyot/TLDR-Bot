import discord
import config
from datetime import datetime
from time import time
from random import randint
from discord.ext import commands
from modules import database, command, embed_maker

db = database.Connection()


class Levels(commands.Cog):

    def __init__(self, bot):

        # Cooldown objects for parliamentary and honours
        self.pp_cooldown = {}
        self.hp_cooldown = {}

        # Cooldown objects for giving and receiving reactions
        self.receive_cooldown = {}
        self.give_cooldown = {}

        self.bot = bot

    @commands.command(help='See current leveling route', usage='leveling_route', examples=['leveling_route'], clearance='User', cls=command.Command)
    async def leveling_route(self, ctx):
        lvl_routes = db.get_levels('leveling_routes', ctx.guild.id)
        embed_colour = config.DEFAULT_EMBED_COLOUR

        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_author(name='Leveling Routes', icon_url=ctx.guild.icon_url)
        embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)

        value = ''
        for i, role in enumerate(lvl_routes['parliamentary']):
            role = discord.utils.find(lambda r: r.name == role[0], ctx.guild.roles)
            if role is None:
                role = await ctx.guild.create_role(name=role[0])
            value += f'\n**#{i + 1}:** <@&{role.id}> - Max Level: {role[1]}'

        embed.add_field(name=f'>Parliamentary', value=value, inline=False)
        return await ctx.send(embed=embed)

    @commands.command(help='Shows the leveling leaderboard on the server', usage='leaderboard', examples=['leaderboard'], clearance='User', cls=command.Command)
    async def leaderboard(self, ctx):
        # if branch is None:
        #    return await embed_maker.command_error(ctx)

        # branch = 'honours' if branch == 'h' else 'parliamentary'
        branch = 'parliamentary'
        pre = 'p'

        doc = db.levels.find_one({'guild_id': ctx.guild.id})
        sorted_users = sorted(doc['users'].items(), key=lambda x: x[1][f'{pre}p'], reverse=True)
        embed_colour = config.DEFAULT_EMBED_COLOUR
        page_message = ''

        for i, u in enumerate(sorted_users):
            if i == 10:
                break

            user_id, user_values = u
            member = ctx.guild.get_member(user_id)
            if member is None:
                member = await ctx.guild.fetch_member(user_id)

            role_level = await self.user_role_level(ctx, branch, member)
            user_role_name = user_values[f'{pre}_role']
            if user_role_name == '':
                continue
            user_role = discord.utils.find(lambda r: r.name == user_role_name, ctx.guild.roles)
            page_message = f'**#{i + 1}** - <@{user_id}> | **Level {role_level}** <@&{user_role.id}>'

        if page_message == '':
            description = 'Damn, this place is empty'
        else:
            description = page_message

        lboard_embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=description)
        lboard_embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
        lboard_embed.set_author(name=f'{branch.title()} Leaderboard', icon_url=ctx.guild.icon_url)

        await ctx.send(embed=lboard_embed)

    @commands.command(help='Shows your (or someone else\'s) rank and level', usage='rank (@member)', examples=['rank', 'rank @Hattyot'], clearance='User', cls=command.Command)
    async def rank(self, ctx, member=None):
        if member and ctx.message.mentions:
            member = ctx.message.mentions[0]
        else:
            member = ctx.author

        if member.bot:
            return

        member_p_level = await self.user_role_level(ctx, 'parliamentary', member)
        # member_h_level = await self.user_role_level(ctx, 'honours', member)

        p_role_name = db.get_levels('p_role', ctx.guild.id, member.id)
        # h_role_name = db.get_levels('h_role', ctx.guild.id, member.id)
        member_p_role = discord.utils.find(lambda r: r.name == p_role_name, ctx.guild.roles)
        # member_h_role = discord.utils.find(lambda r: r.name == h_role_name, ctx.guild.roles)

        p_rank = self.calculate_user_rank('pp', ctx.guild.id, member.id)
        # h_rank = self.calculate_user_rank('hp', ctx.guild.id, member.id)

        if member_p_role is None:
            member_p_role = await ctx.guild.create_role(name=p_role_name)
            await member.add_roles(member_p_role)

        sp_value = f'**#{p_rank}** | **Level** {member_p_level} <@&{member_p_role.id}>'

        # if h_role_name == '':
        #     hp_value = f'**Level** {member_h_level}'
        # else:
        #     if member_h_role is None:
        #         member_h_role = await ctx.guild.create_role(name=h_role_name)
        #         await member.add_roles(member_h_role)
        #
        #     hp_value = f'**#{h_rank}** | **Level** {member_h_level} <@&{member_h_role.id}>'

        embed_colour = config.DEFAULT_EMBED_COLOUR
        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
        embed.set_author(name=f'{member.name} - Rank', icon_url=ctx.guild.icon_url)
        embed.add_field(name='>Parliamentary', value=sp_value, inline=False)
        # embed.add_field(name='>Honours', value=hp_value, inline=False)

        return await ctx.send(embed=embed)

    def calculate_user_rank(self, branch, guild_id, user_id):
        doc = db.levels.find_one({'guild_id': guild_id})
        sorted_users = sorted(doc['users'].items(), key=lambda x: x[1][branch], reverse=True)
        for i, u in enumerate(sorted_users):
            u_id, _ = u
            if u_id == str(user_id):
                return i + 1

    def cooldown_expired(self, cooldown_dict, guild_id, member_id, cooldown_time):
        if guild_id not in cooldown_dict:
            cooldown_dict[guild_id] = {}
        # Checks if cooldown expired
        if member_id in cooldown_dict[guild_id]:
            if round(time()) >= cooldown_dict[guild_id][member_id]:
                del cooldown_dict[guild_id][member_id]
            else:
                return False

        cooldown_expire = round(time()) + cooldown_time
        cooldown_dict[guild_id][member_id] = cooldown_expire
        return True

    async def process_message(self, message):
        if self.cooldown_expired(self.pp_cooldown, message.guild.id, message.author.id, 60):
            pp_add = randint(15, 25)
            user_pp = db.get_levels('pp', message.guild.id, message.author.id)
            new_pp = user_pp + pp_add
            print(new_pp)
            db.levels.update_one({'guild_id': message.guild.id}, {'$set': {f'users.{message.author.id}.pp': new_pp}})
            db.get_levels.invalidate('pp', message.guild.id, message.author.id)

            await self.level_up(message, message.author, 'parliamentary', new_pp)

    async def level_up(self, message, member, branch, new_value):
        # if branch == 'honours':
        #     pre = 'h_'
        #     lvl_up, lvls_up = hpi(ctx.guild.id, member.id, new_value)
        # else:
        pre = 'p_'
        lvl_up, lvls_up = ppi(message.guild.id, member.id, new_value)

        if not lvl_up:
            return

        user_role = db.get_levels(f'{pre}role', message.guild.id, member.id)
        user_role_level = await self.user_role_level(message, branch, member, lvls_up)

        if user_role_level < 0:
            # Get next role
            leveling_routes = db.get_levels('leveling_routes', message.guild.id)
            roles = leveling_routes[branch]
            role_index = self.get_role_index(branch, message.guild.id, user_role)
            new_role = roles[role_index + abs(user_role_level)][0]

            new_role_obj = await self.check_for_role(message.guild, member, new_role)

            db.levels.update_one({'guild_id': message.guild.id}, {'$set': {f'users.{member.id}.{pre}role': new_role}})
            db.get_levels.invalidate(f'{pre}role', message.guild.id, member.id)

            user_role_level = await self.user_role_level(message, branch, member, lvls_up)
            reward_text = f'Congrats <@{member.id}> you\'ve advanced to a level **{user_role_level}** <@&{new_role_obj.id}>'

        else:
            role = await self.check_for_role(message.guild, member, user_role)
            reward_text = f'Congrats <@{member.id}> you\'ve become a level **{user_role_level}** <@&{role.id}>'

        if branch == 'honours':
            reward_text += ' due to your contributions!'
        else:
            reward_text += '!'

        await self.level_up_message(message, member, reward_text)

        db.levels.update_one({'guild_id': message.guild.id}, {'$inc': {f'users.{member.id}.{pre}level': lvls_up}})
        db.get_levels.invalidate(f'{pre}level', message.guild.id, member.id)

    async def level_up_message(self, message, member, text):
        embed_colour = config.DEFAULT_EMBED_COLOUR
        embed = discord.Embed(colour=embed_colour, description=text, timestamp=datetime.now())
        embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
        embed.set_author(name='Level Up!', icon_url=message.guild.icon_url)

        channel_id = db.get_levels('level_up_channel', message.guild.id)
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            await message.channel.send(embed=embed)
        else:
            await channel.send(embed=embed)

    async def user_role_level(self, message, branch, member, lvl_add=0):
        if branch == 'honours':
            pre = 'h_'
        else:
            pre = 'p_'

        user_level = db.get_levels(f'{pre}level', message.guild.id, member.id)
        user_role = db.get_levels(f'{pre}role', message.guild.id, member.id)
        user_level = int(user_level + lvl_add)

        leveling_routes = db.get_levels('leveling_routes', message.guild.id)
        all_roles = leveling_routes[branch]

        role_index = self.get_role_index(branch, message.guild.id, user_role)

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
                return -(user_level - current_level_total)

    @staticmethod
    def get_role_index(branch, guild_id, user_role):
        leveling_routes = db.get_levels('leveling_routes', guild_id)
        all_roles = leveling_routes[branch]

        for i, role in enumerate(all_roles):
           if role[0] == user_role:
                return i
        else:
            return 0

    # Checks if role exists
    async def check_for_role(self, guild, member, role_name):
        role = discord.utils.find(lambda r: r.name == role_name, guild.roles)

        if role is None:
            role = await guild.create_role(name=role_name)
            await member.add_roles(role)

        return role


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


def setup(bot):
    bot.add_cog(Levels(bot))
