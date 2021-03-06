import discord
import re
import dateparser
import datetime
import config
from time import time
from bson import ObjectId
from cogs.utils import get_member, get_user_clearance
from modules import command, database, embed_maker, format_time
from discord.ext import commands

db = database.Connection()


class Mod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name='watchlist', help='Manage the watchlist, which logs all the users message to a channel',
                    usage='watchlist (sub command) (args)', examples=['watchlist'],
                    sub_commands=['add', 'remove', 'add_filters'], clearance='Mod', cls=command.Group)
    async def _watchlist(self, ctx):
        users_on_list = [d for d in db.watchlist.distinct('user_id', {'guild_id': ctx.guild.id})]
        if ctx.subcommand_passed is None:
            colour = config.EMBED_COLOUR
            list_embed = discord.Embed(colour=colour, timestamp=datetime.datetime.now())
            list_embed.set_author(name='Users on the watchlist')

            on_list_str = ''
            for i, user_id in enumerate(users_on_list):
                user = ctx.guild.get_member(int(user_id))
                if user is None:
                    try:
                        user = await ctx.guild.fetch_member(int(user_id))
                    except:
                        db.watchlist.delete_one({'guild_id': ctx.guild.id, 'user_id': user_id})
                        continue
                on_list_str += f'`#{i + 1}` - {str(user)}\n'
                watchlist_user = db.watchlist.find_one({'guild_id': ctx.guild.id, 'user_id': user_id}, {'filters': 1})
                if watchlist_user['filters']:
                    on_list_str += 'Filters: ' + " | ".join(f"`{f}`" for f in watchlist_user['filters'])
                on_list_str += '\n\n'

            if not on_list_str:
                list_embed.description = 'Currently no users on the watchlist'
                return await ctx.send(embed=list_embed)
            else:
                list_embed.description = on_list_str
                return await ctx.send(embed=list_embed)

    @_watchlist.command(name='add', help='add a user to the watchlist', usage='watchlist add [user] -f (filter1 | filter2 | filter3)', examples=['watchlist add hattyot -f hat | ot | pp'], clearance='Mod', cls=command.Command)
    async def _watchlist_add(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        _args = list(filter(lambda a: bool(a), re.split(r' ?-(f) ', args)))
        user_identifier = _args[0]
        filters = _args[-1] if len(_args) > 1 else []

        member = await get_member(ctx, self.bot, user_identifier)
        if member is None or isinstance(member, str):
            return await embed_maker.message(ctx, 'Invalid member', colour='red')

        watchlist_user = db.watchlist.find_one({'guild_id': ctx.guild.id, 'user_id': member.id})

        if watchlist_user:
            return await embed_maker.message(ctx, 'User is already on the watchlist', colour='red')

        split_filters = [f.strip() for f in filters.split('|')] if filters else []

        watchlist_category = discord.utils.find(lambda c: c.name == 'Watchlist', ctx.guild.categories)
        if watchlist_category is None:
            # get all staff roles
            staff_roles = filter(lambda r: r.permissions.manage_messages, ctx.guild.roles)

            # staff roles can read channels in category, users cant
            overwrites = dict.fromkeys(staff_roles, discord.PermissionOverwrite(read_messages=True, send_messages=True, read_message_history=True))
            overwrites[ctx.guild.default_role] = discord.PermissionOverwrite(read_messages=False)

            watchlist_category = await ctx.guild.create_category(name='Watchlist', overwrites=overwrites)

        watchlist_channel = await ctx.guild.create_text_channel(f'{member.name}', category=watchlist_category)

        watchlist_doc = {
            'guild_id': ctx.guild.id,
            'user_id': member.id,
            'filters': split_filters,
            'channel_id': watchlist_channel.id
        }
        db.watchlist.insert_one(watchlist_doc)

        msg = f'<@{member.id}> has been added to the watchlist'
        if split_filters:
            msg += f'\nWith these filters: {" or ".join(f"`{f}`" for f in split_filters)}'

        return await embed_maker.message(ctx, msg, colour='green')

    @_watchlist.command(name='remove', help='remove a user from the watchlist', usage='watchlist remove [user]', examples=['watchlist remove hattyot'], clearance='Mod', cls=command.Command)
    async def _watchlist_remove(self, ctx, *, user=None):
        if user is None:
            return await embed_maker.command_error(ctx)

        member = await get_member(ctx, self.bot, user)
        if member is None or isinstance(member, str):
            return await embed_maker.message(ctx, 'Invalid member', colour='red')

        watchlist_user = db.watchlist.find_one({'guild_id': ctx.guild.id, 'user_id': member.id})

        if watchlist_user is None:
            return await embed_maker.message(ctx, 'User is not on the list', colour='red')

        # remove watchlist channel
        channel_id = watchlist_user['channel_id']
        channel = self.bot.get_channel(int(channel_id))
        if channel:
            await channel.delete()

        db.watchlist.delete_one({'guild_id': ctx.guild.id, 'user_id': member.id})

        return await embed_maker.message(ctx, f'<@{member.id}> has been removed from the watchlist', colour='green')

    @_watchlist.command(name='add_filters', help='are filters to a user on the watchlist', usage='watchlist add_filters [user] -f (filter 1 | filter 2)',
                        examples=['watchlist add_filters hattyot -f example 1 | example 2'], clearance='Mod', cls=command.Command)
    async def _watchlist_add_filters(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        _args = list(filter(lambda a: bool(a), re.split(r' ?-(f) ', args)))
        user_identifier = _args[0]
        if len(_args) > 1:
            filters = _args[-1]
        else:
            return await embed_maker.message(ctx, 'Missing filters', colour='red')

        member = await get_member(ctx, self.bot, user_identifier)
        if member is None or isinstance(member, str):
            return await embed_maker.message(ctx, 'Invalid member', colour='red')

        watchlist_user = db.watchlist.find_one({'guild_id': ctx.guild.id, 'user_id': member.id})

        if watchlist_user is None:
            return await embed_maker.message(ctx, 'User is not on the list', colour='red')

        all_filters = watchlist_user['filters']
        split_filters = [f.strip() for f in filters.split('|')] if filters else []
        if all_filters:
            split_filters += all_filters

        db.watchlist.update_one({'guild_id': ctx.guild.id, 'user_id': member.id}, {'$set': {f'filters': split_filters}})

        return await embed_maker.message(ctx, f'if {member} mentions {" or ".join(f"`{f}`" for f in split_filters)} mods will be @\'d', colour='green')

    @commands.group(name='dailydebates', help='Daily debate scheduler/manager',
                    usage='dailydebates (sub command) (arg(s))',
                    clearance='Mod', cls=command.Group, aliases=['dd', 'dailydebate'], examples=['dailydebates'],
                    sub_commands=['add', 'insert', 'remove', 'set_time', 'set_channel', 'set_role', 'set_poll_channel', 'set_poll_options', 'disable'])
    async def _dailydebates(self, ctx):
        daily_debates_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})
        if daily_debates_data is None:
            daily_debates_data = self.bot.add_collections(ctx.guild.id, 'server_data')

        if ctx.subcommand_passed is None:
            # List currently set up daily debate topics
            topics = daily_debates_data['topics']
            if not topics:
                topics_str = f'Currently there are no debate topics set up'
            else:
                # generate topics string
                topics_str = '**Topics:**\n'
                for i, topic_obj in enumerate(topics):
                    topic = topic_obj['topic']
                    topic_author_id = topic_obj['topic_author_id']
                    topic_options = topic_obj['topic_options']
                    topic_author = await ctx.guild.fetch_member(int(topic_author_id)) if topic_author_id else None

                    topics_str += f'`#{i + 1}`: {topic}\n'
                    if topic_options:
                        topics_str += '**Poll Options:**' + ' |'.join(
                            [f' `{o}`' for i, o in enumerate(topic_options)]) + '\n'
                    if topic_author:
                        topics_str += f'**Topic Author:** {str(topic_author)}\n'

            dd_time = daily_debates_data['time'] if daily_debates_data['time'] else 'Not set'
            dd_channel = f'<#{daily_debates_data["channel_id"]}>' if daily_debates_data['channel_id'] else 'Not set'
            dd_poll_channel = f'<#{daily_debates_data["poll_channel_id"]}>' if daily_debates_data['poll_channel_id'] else 'Not set'
            dd_role = f'<@&{daily_debates_data["role_id"]}>' if daily_debates_data['role_id'] else 'Not set'

            embed = discord.Embed(title='Daily Debates', colour=config.EMBED_COLOUR, description=topics_str, timestamp=datetime.datetime.now())
            embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
            embed.add_field(name='Attributes', value=f'Time: {dd_time}\nChannel: {dd_channel}\nPoll Channel: {dd_poll_channel}\nRole: {dd_role}')

            return await ctx.send(embed=embed)

    @_dailydebates.command(name='disable', help='Disable the daily debates system, time will be set to 0', usage='dailydebates disable', examples=['dailydebates disable'], clearance='Mod', cls=command.Command)
    async def _dailydebates_disable(self, ctx):
        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'time': 0}})

        # cancel timer if active
        daily_debate_timer = db.timers.find_one({'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}})
        if daily_debate_timer:
            db.timers.delete_one({'_id': ObjectId(daily_debate_timer['_id'])})

        return await embed_maker.message(ctx, f'Daily debates have been disabled')

    @_dailydebates.command(name='set_poll_options', help='Set the poll options for a daily debate topic',
                           usage='dailydebates set_poll_options [index of topic] [option 1] | [option 2] | (option 3)...',
                           examples=['dailydebates set_poll_options 1 yes | no | double yes | double no'], clearance='Mod', cls=command.Command)
    async def _dailydebates_set_poll_options(self, ctx, index=None, *, options=None):
        if index is None:
            return await embed_maker.command_error(ctx)

        if not index.isdigit():
            return await embed_maker.command_error(ctx, '[index of topic]')

        if options is None:
            return await embed_maker.command_error(ctx, '[options]')

        options = [o.strip() for o in options.split('|')]

        if not options:
            return await embed_maker.command_error(ctx, '[options]')
        if len(options) < 2:
            return await embed_maker.message(ctx, 'not enough options set', colour='red')
        if len(options) > 9:
            return await embed_maker.message(ctx, 'Too many poll options set', colour='red')

        daily_debates_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})
        topics = daily_debates_data['topics']

        index = int(index)
        if len(topics) < index:
            return await embed_maker.message(ctx, 'index out of range', colour='red')

        topic = topics[index - 1]

        topic_obj = {
            'topic': topic['topic'],
            'topic_author_id': topic['topic_author_id'] ,
            'topic_options': options
        }

        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {f'topics.{index - 1}': topic_obj}})
        options_str = ' |'.join([f' `{o}`' for i, o in enumerate(options)])
        return await embed_maker.message(ctx, f'Along with the topic: **"{topic["topic"]}"**\nwill be sent a poll with these options: {options_str}')

    @_dailydebates.command(name='set_poll_channel', help=f'Set the poll channel where polls will be sent, disable polls by setting poll channel to `None``',
                           usage='dailydebates set_poll_channel [#channel]', examples=['dailydebates set_poll_channel #daily_debate_polls'],
                           clearance='Mod', cls=command.Command)
    async def _dailydebates_set_poll_channel(self, ctx, channel=None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        if channel.lower() == 'none':
            db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'role_id': 0}})
            return await embed_maker.message(ctx, f'daily debates poll channel has been disabled')

        if not ctx.message.channel_mentions:
            return await embed_maker.message(ctx, 'Invalid channel mention', colour='red')

        channel_id = ctx.message.channel_mentions[0].id
        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'poll_channel_id': channel_id}})
        return await embed_maker.message(ctx, f'Daily debate polls will now be sent every day to <#{channel_id}>')

    @_dailydebates.command(name='set_role', help=f'set the role that will be @\'d when topics are announced, disable @\'s by setting the role to `None`',
                           usage='dailydebates set_role [role]', examples=['dailydebates set_role Debater'], clearance='Mod', cls=command.Command)
    async def _dailydebates_set_role(self, ctx, *, role_name=None):
        if role_name is None:
            return await embed_maker.command_error(ctx)

        if role_name.lower() == 'none':
            db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'role_id': 0}})
            return await embed_maker.message(ctx, f'daily debates role has been disabled')

        role = discord.utils.find(lambda r: r.name.lower() == role_name.lower(), ctx.guild.roles)
        if not role:
            return await embed_maker.message(ctx, 'Invalid role name', colour='red')

        role_id = role.id
        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'role_id': role_id}})
        return await embed_maker.message(ctx, f'Daily debates will now be announced every day to <@&{role_id}>')

    @_dailydebates.command(name='set_channel', help=f'set the channel where topics are announced',
                           usage='dailydebates set_channel [#set_channel]', examples=['dailydebates set_channel #daily-debates'],
                           clearance='Mod', cls=command.Command)
    async def _dailydebates_set_channel(self, ctx, channel=None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        if not ctx.message.channel_mentions:
            return await embed_maker.message(ctx, 'Invalid channel mention', colour='red')

        channel_id = ctx.message.channel_mentions[0].id
        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'channel_id': channel_id}})
        return await embed_maker.message(ctx, f'Daily debates will now be announced every day at <#{channel_id}>')

    @_dailydebates.command(name='set_time', help='set the time when topics are announced',
                           usage='dailydebates set_time [time]', examples=['dailydebates set_time 14:00 GMT+1'],
                           clearance='Mod', cls=command.Command)
    async def _dailydebates_set_time(self, ctx, *, time=None):
        if time is None:
            return await embed_maker.command_error(ctx)

        parsed_time = dateparser.parse(time, settings={'RETURN_AS_TIMEZONE_AWARE': True})
        if not parsed_time:
            return await embed_maker.message(ctx, 'Invalid time', colour='red')

        parsed_dd_time = dateparser.parse(time, settings={'PREFER_DATES_FROM': 'future', 'RETURN_AS_TIMEZONE_AWARE': True, 'RELATIVE_BASE': datetime.datetime.now(parsed_time.tzinfo)})
        time_diff = parsed_dd_time - datetime.datetime.now(parsed_dd_time.tzinfo)
        time_diff_seconds = round(time_diff.total_seconds())

        if time_diff_seconds < 0:
            return await embed_maker.message(ctx, 'Invalid time', colour='red')

        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'time': time}})
        await embed_maker.message(ctx, f'Daily debates will now be announced every day at {time}')

        # cancel old timer
        db.timers.delete_many({'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}})

        return await self.start_daily_debate_timer(ctx.guild.id, time)

    @_dailydebates.command(name='remove', help='remove a topic from the topic list',
                           usage='dailydebates remove [topic index]', examples=['dailydebates remove 2'],
                           clearance='Mod', cls=command.Command)
    async def _dailydebates_remove(self, ctx, index=None):
        if index is None:
            return await embed_maker.command_error(ctx)

        if not index.isdigit():
            return await embed_maker.message(ctx, 'Invalid index', colour='red')

        daily_debate_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})

        index = int(index)
        if index > len(daily_debate_data['topics']):
            return await embed_maker.message(ctx, 'Index too big', colour='red')

        if index < 1:
            return await embed_maker.message(ctx, 'Index cant be smaller than 1', colour='red')

        topic_to_delete = daily_debate_data['topics'][index - 1]
        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$pull': {'topics': topic_to_delete}})

        return await embed_maker.message(
            ctx, f'`{topic_to_delete["topic"]}` has been removed from the list of daily debate topics'
                 f'\nThere are now **{len(daily_debate_data["topics"]) - 1}** topics on the list'
        )

    @_dailydebates.command(name='add', help='add a topic to the list topics along with optional options and topic author',
                           usage='dailydebates add [topic] -ta (topic author) -o (poll options)',
                           examples=['dailydebates add is ross mega cool? -ta hattyot -o yes | double yes | triple yes'],
                           clearance='Mod', cls=command.Command)
    async def _dailydebates_add(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = self.parse_dd_args(args)
        topic = args['t']
        topic_author_arg = args['ta']
        topic_options_arg = args['o']
        if topic_author_arg:
            member = await get_member(ctx, self.bot, topic_author_arg)
            if member is None:
                return await embed_maker.message(ctx, 'Invalid topic author', colour='red')
            elif isinstance(member, str):
                return await embed_maker.message(ctx, member, colour='red')
            topic_author_arg = member.id

        topic_obj = {
            'topic': topic,
            'topic_author_id': topic_author_arg,
            'topic_options': topic_options_arg
        }
        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$push': {'topics': topic_obj}})

        daily_debate_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})
        await embed_maker.message(
            ctx, f'`{topic}` has been added to the list of daily debate topics'
            f'\nThere are now **{len(daily_debate_data["topics"])}** topics on the list'
        )

        daily_debate_timer = db.timers.find_one({'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}})
        if not daily_debate_timer:
            return await self.start_daily_debate_timer(ctx.guild.id, daily_debate_data['time'])

    @_dailydebates.command(name='insert', help='insert a topic into the first place on the list of topics along with optional options and topic author',
                           usage='dailydebates insert [topic] -ta (topic author) -o (poll options)',
                           examples=['dailydebates insert is ross mega cool? -ta hattyot -o yes | double yes | triple yes'],
                           clearance='Mod', cls=command.Command)
    async def _dailydebates_insert(self, ctx, *, args=None):
        args = self.parse_dd_args(args)
        topic = args['t']
        topic_author_arg = args['ta']
        topic_options_arg = args['o']
        if topic_author_arg:
            member = await get_member(ctx, self.bot, topic_author_arg)
            if member is None:
                return await embed_maker.message(ctx, 'Invalid topic author', colour='red')
            elif isinstance(member, str):
                return await embed_maker.message(ctx, member, colour='red')
            topic_author_arg = member.id

        topic_obj = {
            'topic': topic,
            'topic_author_id': topic_author_arg,
            'topic_options': topic_options_arg
        }
        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$push': {'topics': {'$each': [topic_obj], '$position': 0}}})

        daily_debate_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})
        await embed_maker.message(
            ctx, f'`{topic}` has been inserted into first place in the list of daily debate topics'
                 f'\nThere are now **{len(daily_debate_data["topics"])}** topics on the list'
        )

        daily_debate_timer = db.timers.find_one({'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}})
        if not daily_debate_timer:
            return await self.start_daily_debate_timer(ctx.guild.id, daily_debate_data['time'])

    @staticmethod
    def parse_dd_args(args):
        result = {'t': '', 'ta': '', 'o': []}
        _args = list(filter(lambda a: bool(a), re.split(r' ?-(ta|o) ', args)))
        result['t'] = _args[0]
        del _args[0]

        for i in range(int(len(_args) / 2)):
            result[_args[i + (i * 1)]] = _args[i + (i + 1)]

        if result['o']:
            result['o'] = [o.strip() for o in result['o'].split('|')]

        return result

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
        timer_expires = round(time()) + time_diff_seconds - 3600  # one hour
        utils_cog = self.bot.get_cog('Utils')
        await utils_cog.create_timer(expires=timer_expires, guild_id=guild_id, event='daily_debate', extras={})

    @commands.Cog.listener()
    async def on_daily_debate_timer_over(self, timer):
        guild_id = timer['guild_id']
        guild = self.bot.get_guild(int(guild_id))

        now = round(time())
        dd_time = timer['expires'] + 3600
        tm = dd_time - now

        daily_debate_data = db.daily_debates.find_one({'guild_id': guild.id})
        # check if there are debate topics set up
        topics = daily_debate_data['topics']
        channel_id = daily_debate_data['channel_id']
        if not topics:
            # remind mods that a topic needs to be set up
            msg = f'Daily debate starts in {format_time.seconds(tm)} and no topics have been set up <@&{config.MOD_ROLE_ID}>'
            channel = guild.get_channel(channel_id)

            if channel is None:
                return

            return await channel.send(msg)
        else:
            # start final timer which sends daily debate topic
            timer_expires = dd_time
            utils_cog = self.bot.get_cog('Utils')
            await utils_cog.create_timer(expires=timer_expires, guild_id=guild.id, event='daily_debate_final', extras={})

    @commands.Cog.listener()
    async def on_daily_debate_final_timer_over(self, timer):
        guild_id = timer['guild_id']
        guild = self.bot.get_guild(int(guild_id))

        daily_debate_data = db.daily_debates.find_one({'guild_id': guild_id})
        topic_data = daily_debate_data['topics'][0]
        topic = topic_data['topic']
        topic_options = topic_data['topic_options']
        topic_author_id = topic_data['topic_author_id']
        topic_author = await self.bot.fetch_user(int(topic_author_id)) if topic_author_id else None

        dd_time = daily_debate_data['time']
        dd_channel_id = daily_debate_data['channel_id']
        dd_role_id = daily_debate_data['role_id']
        dd_poll_channel_id = daily_debate_data['poll_channel_id']

        dd_channel = discord.utils.find(lambda c: c.id == int(dd_channel_id), guild.channels) if dd_channel_id else None
        dd_role = discord.utils.find(lambda r: r.id == int(dd_role_id), guild.roles) if dd_role_id else None

        if not dd_channel:
            return

        message = f'Today\'s debate: **“{topic}”**'
        if topic_author:
            message += f' - Topic suggested by <@{topic_author_id}>'
        if dd_role:
            message += f'\n\n<@&{dd_role.id}>'

        msg = await dd_channel.send(message)

        # delete used topic
        db.daily_debates.update_one({'guild_id': guild.id}, {'$pull': {'topics': topic_data}})

        # change channel topic
        await dd_channel.edit(topic=f"{topic}")

        # unpin old topic message
        pins = [pin for pin in await dd_channel.pins() if pin.author.id == self.bot.user.id]
        if pins:
            last_pin = pins[0]
            await last_pin.unpin()

        # pin new topic message
        await msg.pin()

        if dd_poll_channel_id:
            dd_poll_channel = discord.utils.find(lambda c: c.id == int(dd_poll_channel_id), guild.channels)
            if dd_poll_channel:
                # send yes/no/abstain poll

                poll_emotes = ['👍', '👎', '😐']
                poll_options = ['Yes', 'No', 'Abstain']

                description = f'**"{topic}"**\n'
                colour = config.EMBED_COLOUR
                embed = discord.Embed(colour=colour, description=description, timestamp=datetime.datetime.now())
                embed.set_author(name='Daily Debate Poll')
                embed.set_footer(text='Started at', icon_url=guild.icon_url)

                description += '\n'.join(f'\n{e} | **{o}**' for e, o in zip(poll_emotes, poll_options))
                embed.description = description

                poll_msg = await dd_poll_channel.send(embed=embed)
                for e in poll_emotes:
                    await poll_msg.add_reaction(e)

                # start 20h to send results to users
                utils_cog = self.bot.get_cog('Utils')
                expires = round(time() + (3600 * 20))
                await utils_cog.create_timer(guild_id=guild_id, expires=expires, event='dd_results', extras={'poll_id': poll_msg.id, 'poll_channel_id':poll_msg.channel.id})

                # send poll with custom options if they are provided
                if topic_options:
                    all_num_emotes = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
                    poll_emotes = all_num_emotes[:len(topic_options)]
                    poll_options = topic_options

                    description = f'**"{topic}"**\n'
                    colour = config.EMBED_COLOUR
                    embed = discord.Embed(colour=colour, description=description, timestamp=datetime.datetime.now())
                    embed.set_author(name='Daily Debate - Which statement(s) do you agree with?')
                    embed.set_footer(text='Started at', icon_url=guild.icon_url)

                    description += '\n'.join(f'\n{e} | **{o}**' for e, o in zip(poll_emotes, poll_options))
                    embed.description = description

                    poll_msg = await dd_poll_channel.send(embed=embed)
                    for e in poll_emotes:
                        await poll_msg.add_reaction(e)

        # award topic author boost if there is one
        if topic_author:
            boost_dict = {
                'guild_id': guild_id,
                'user_id': topic_author.id,
                'expires': round(time()) + (3600 * 6),
                'multiplier': 0.15,
                'type': 'daily debate topic author'
            }
            db.boosts.insert_one(boost_dict)

        # start daily_debate timer over
        return await self.start_daily_debate_timer(guild.id, dd_time)

    @commands.Cog.listener()
    async def on_dd_results_timer_over(self, timer):
        poll_channel_id = timer['extras']['poll_channel_id']
        poll_id = timer['extras']['poll_id']

        channel = self.bot.get_channel(poll_channel_id)
        if channel is None:
            return

        poll_message = await channel.fetch_message(poll_id)
        if poll_message is None:
            return

        # get results
        results = {}
        reactions = poll_message.reactions
        for r in reactions:
            results[r.emoji] = r.count

        results_sum = sum(results.values())
        if results_sum == 0:
            return

        ayes = results["👍"]
        noes = results["👎"]
        abstain = results["😐"]

        who_has_it = 'noes' if noes > ayes else 'ayes'
        results_str = f'**ORDER! ORDER!**\n\nThe ayes to the right: **{ayes}**\nThe noes to the left: **{noes}**\nAbstentions: **{abstain}**\n\nThe **{who_has_it}** have it. The **{who_has_it}** have it. Unlock!'
        # send results string in dd poll channel
        return await channel.send(results_str)

    @commands.command(help='Open a ticket for discussion', usage='open_ticket [ticket]', clearance='Mod', cls=command.Command, examples=['open_ticket new mods'])
    async def open_ticket(self, ctx, *, ticket=None):
        if ticket is None:
            return await embed_maker.command_error(ctx)

        main_guild = self.bot.get_guild(config.MAIN_SERVER)
        embed_colour = config.EMBED_COLOUR
        ticket_embed = discord.Embed(colour=embed_colour, timestamp=datetime.datetime.now())
        ticket_embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
        ticket_embed.set_author(name='New Ticket', icon_url=main_guild.icon_url)
        ticket_embed.add_field(name='>Opened By', value=f'<@{ctx.author.id}>', inline=False)
        ticket_embed.add_field(name='>Ticket', value=ticket, inline=False)

        ticket_category = discord.utils.find(lambda c: c.name == 'Open Tickets', ctx.guild.categories)

        if ticket_category is None:
            # get all staff roles
            staff_roles = filter(lambda r: r.permissions.manage_messages, ctx.guild.roles)

            # staff roles can read channels in category, users cant
            overwrites = dict.fromkeys(staff_roles, discord.PermissionOverwrite(read_messages=True, send_messages=True, read_message_history=True))
            overwrites[ctx.guild.default_role] = discord.PermissionOverwrite(read_messages=False)

            ticket_category = await ctx.guild.create_category(name='Open Tickets', overwrites=overwrites)

        today = datetime.date.today()
        date_str = today.strftime('%Y-%m-%d')
        ticket_channel = await ctx.guild.create_text_channel(f'{date_str}-{ctx.author.name}', category=ticket_category)
        await ticket_channel.send(embed=ticket_embed)

    # @commands.command(help='Archive ticket and remove access to channel from users', usage='archive_ticket')

    @commands.command(help='Give user access to ticket', usage='get_user [user]', examples=['get_user hattyot'], clearance='Mod', cls=command.Command)
    async def get_user(self, ctx, member=None):
        if member is None:
            return await embed_maker.command_error(ctx)

        member = await get_member(ctx, self.bot, member)
        if member is None:
            return await embed_maker.command_error(ctx, '[member]')
        elif isinstance(member, str):
            return await embed_maker.message(ctx, member, colour='red')

        ticket_category = discord.utils.find(lambda c: c.name == 'Open Tickets', ctx.guild.categories)
        if ctx.channel.category != ticket_category:
            return await embed_maker.message(ctx, 'Invalid ticket channel')

        # check if user already has access to channel
        permissions = ctx.channel.permissions_for(member)
        if permissions.read_messages:
            return await embed_maker.message(ctx, 'User already has access to this channel')

        await ctx.channel.set_permissions(member, read_messages=True, send_messages=True, read_message_history=True)
        return await ctx.channel.send(f'<@{member.id}>')

    @commands.command(help='Grant users access to commands that aren\'t available to users or take away their access to a command',
                      usage='command_access [action/(member/role)] [command] [member/role]', clearance='Admin', cls=command.Command,
                      examples=['command_access give poll @Hattyot', 'command_access neutral anon_poll Mayor', 'command_access take rep Hattyot', 'command_access Hatty'])
    async def command_access(self, ctx, action=None, cmd=None, *, member=None):
        if action is None:
            return await embed_maker.command_error(ctx)

        async def member_or_role(src):
            if src is None:
                return '[member/role]', None

            mem = await get_member(ctx, self.bot, src)
            if mem:
                return 'user',  mem

            role = discord.utils.find(lambda r: r.name.lower() == src.lower(), ctx.guild.roles)
            if role:
                return 'role', role

            return '[member/role]', None

        # check if action is member or role
        if action not in ['give', 'neutral', 'take']:
            type, obj = await member_or_role(action)
            if type and obj:
                special_access = db.commands.find({'guild_id': ctx.guild.id, f'{type}_access.{obj.id}': {'$exists': True}})
                access_given = [a['command_name'] for a in special_access if a[f'{type}_access'][f'{obj.id}'] == 'give']
                access_taken = [a['command_name'] for a in special_access if a[f'{type}_access'][f'{obj.id}'] == 'take']

                access_given_str = ' |'.join([f' `{c}`' for c in access_given])
                access_taken_str = ' |'.join([f' `{c}`' for c in access_taken])
                if not access_given_str:
                    access_given_str = f'{type} has no special access to commands'
                if not access_taken_str:
                    access_taken_str = f'No commands have been taken away from this {type}'

                embed_colour = config.EMBED_COLOUR
                embed = discord.Embed(colour=embed_colour, timestamp=datetime.datetime.now(), description='Command Access')
                embed.add_field(name='>Access Given', value=access_given_str, inline=False)
                embed.add_field(name='>Access Taken', value=access_taken_str, inline=False)
                embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)

                return await ctx.send(embed=embed)

        type, obj = await member_or_role(member)
        if obj is None:
            if action not in ['give', 'neutral', 'take']:
                return await embed_maker.command_error(ctx, '[action/(member/role)]')
            if cmd is None:
                return await embed_maker.command_error(ctx, '[command]')
            return await embed_maker.command_error(ctx, type)

        cmd_obj = self.bot.get_command(cmd)
        if not cmd_obj:
            return await embed_maker.message(ctx, f'{cmd} is not a valid command', colour='red')
        command_data = db.commands.find_one({'guild_id': ctx.guild.id, 'command_name': cmd_obj.name})
        in_db = True
        if command_data is None:
            command_data = {
                'guild_id': ctx.guild.id,
                'command_name': cmd_obj.name,
                'disabled': 0,
                'user_access': {},
                'role_access': {}
            }
            in_db = False

        if action not in ['give', 'neutral', 'take']:
            return await embed_maker.message(ctx, 'invalid [action/(member/role)]', colour='red')

        if cmd_obj.clearance == 'Dev':
            return await embed_maker.message(ctx, 'You can not give people access to dev commands', colour='red')
        elif cmd_obj.clearance == 'Admin':
            return await embed_maker.message(ctx, 'You can not give people access to admin commands', colour='red')

        can_access_command = True

        if type == 'users':
            author_perms = ctx.author.guild_permissions
            member_perms = obj.guild_permissions
            if author_perms <= member_perms:
                return await embed_maker.message(ctx, 'You can not manage command access of people who have the same or more permissions as you')

            # can user run command
            member_clearance = get_user_clearance(obj)
            if cmd_obj.clearance not in member_clearance:
                can_access_command = False

        elif type == 'roles':
            top_author_role = ctx.author.roles[-1]
            top_author_role_perms = top_author_role.permissions
            role_perms = obj.permissions
            if top_author_role_perms <= role_perms:
                return await embed_maker.message(ctx, 'You can not manage command access of a role which has the same or more permissions as you')

        filter = {'guild_id': ctx.guild.id, 'command_name': cmd_obj.name}
        if action == 'give':
            if can_access_command and type == 'users':
                return await embed_maker.message(ctx, 'User already has access to that command', colour='red')

            type_access = command_data[f'{type}_access']
            if str(obj.id) in type_access and type_access[f'{obj.id}'] == 'give':
                return await embed_maker.message(ctx, f'{obj} already has been given access to that command', colour='red')

            if in_db:
                db.commands.update_one(filter, {'$set': {f'{type}_access.{obj.id}': 'give'}})
            else:
                command_data[f'{type}_access'][f'{obj.id}'] = 'give'
                db.commands.insert_one(command_data)

            return await embed_maker.message(ctx, f'{obj} has been granted access to: `{cmd}`')

        elif action == 'neutral':
            if str(obj.id) not in command_data[f'{type}_access']:
                return await embed_maker.message(ctx, f'{obj} is already neutral on that command', colour='red')

            db.commands.update_one(filter, {'$unset': {f'{type}_access.{obj.id}': ''}})
            await embed_maker.message(ctx, f'{obj} is now neutral on command `{cmd}`')

            # check if all data is default, if it is delete the data from db
            del command_data[f'{type}_access'][f'{obj.id}']
            if not command_data['disabled'] and not command_data['user_access'] and not command_data['role_access']:
                db.commands.delete_one(filter)

        elif action == 'take':
            if not can_access_command and type == 'users':
                return await embed_maker.message(ctx, 'User already doesn\'t have access to that command', colour='red')

            type_access = command_data[f'{type}_access']
            if str(obj.id) in type_access and type_access[f'{obj.id}'] == 'take':
                return await embed_maker.message(ctx, f'{obj} has had their access to that command already taken away', colour='red')

            if in_db:
                db.commands.update_one(filter, {'$set': {f'{type}_access.{obj.id}': 'take'}})
            else:
                command_data[f'{type}_access'][f'{obj.id}'] = 'take'
                db.commands.insert_one(command_data)

            return await embed_maker.message(ctx, f'{obj} will now not be able to use: `{cmd}`')

    @commands.command(help='see what roles are whitelisted for an emote', usage='emote_roles [emote]',
                      examples=['emote_roles :TldrNewsUK:'], clearance='Mod', cls=command.Command)
    async def emote_roles(self, ctx, emote=None):
        if emote is None:
            return await embed_maker.command_error(ctx)

        regex = re.compile(r'<:.*:(\d*)>')
        match = re.findall(regex, emote)
        if not match:
            return await embed_maker.command_error(ctx, '[emote]')
        else:
            emoji = discord.utils.find(lambda e: e.id == int(match[0]), ctx.guild.emojis)

        if emoji.roles:
            return await embed_maker.message(ctx, f'This emote is restricted to: {", ".join([f"<@&{r.id}>" for r in emoji.roles])}')
        else:
            return await embed_maker.message(ctx, 'This emote is available to everyone')

    @commands.command(help='restrict an emote to specific role(s)', usage='emote_role [role] [action] [emote 1], (emote 2)...',
                      examples=['emote_role Mayor add :TldrNewsUK:, ', 'emote_role Mayor remove :TldrNewsUK: :TldrNewsUS: :TldrNewsEU:'],
                      clearance='Mod', cls=command.Command)
    async def emote_role(self, ctx, role=None, action=None, *, emotes=None):
        if role is None:
            return await embed_maker.command_error(ctx)

        if action is None or action not in ['add', 'remove']:
            return await embed_maker.command_error(ctx, '[action]')

        if emotes is None:
            return await embed_maker.command_error(ctx, '[emotes]')

        regex = re.compile(r'<:.*:(\d*)>')
        emote_list = emotes.split(' ')
        msg = None
        on_list = []
        for emote in emote_list:
            match = re.findall(regex, emote)
            if not match:
                return await embed_maker.message(ctx, 'Invalid emote', colour='red')
            else:
                emoji = discord.utils.find(lambda e: e.id == int(match[0]), ctx.guild.emojis)

            if ctx.message.role_mentions:
                role = ctx.message.role_mentions[0]
            elif role.isdigit():
                role = discord.utils.find(lambda rl: rl.id == role, ctx.guild.roles)
            else:
                role = discord.utils.find(lambda rl: rl.name == role, ctx.guild.roles)

            if role is None:
                return await embed_maker.command_error(ctx, '[role]')

            emote_roles = emoji.roles
            if role in emote_roles:
                on_list.append(emote)
                continue

            if action == 'add':
                emote_roles.append(role)
                await emoji.edit(roles=emote_roles)
                await ctx.guild.fetch_emoji(emoji.id)
                msg = f'<@&{role.id}> has been added to whitelisted roles of emotes {emotes}'

            elif action == 'remove':
                for i, r in enumerate(emote_roles):
                    if r.id == role.id:
                        emote_roles.pop(i)
                        await emoji.edit(roles=emote_roles)
                        await ctx.guild.fetch_emoji(emoji.id)
                        msg = f'<@&{role.id}> has been removed from whitelisted roles of emotes {emotes}'
                else:
                    msg = f'<@&{role.id}> is not whitelisted for emote {emote}'
            else:
                return await embed_maker.command_error(ctx, '[action]')

        if msg:
            return await embed_maker.message(ctx, msg, colour='green')
        elif on_list:
            return await embed_maker.message(ctx, 'That role already has access to all those emotes', colour='red')


def setup(bot):
    bot.add_cog(Mod(bot))
