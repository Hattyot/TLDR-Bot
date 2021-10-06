import datetime
import hashlib
import time
import traceback

import config
import discord
from bot import TLDR
from bson import ObjectId
from discord.ext.commands import Cog, Context
from modules import database, embed_maker, format_time

db = database.get_connection()


class Events(Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot

    @Cog.listener()
    async def on_ready(self):
        bot_game = discord.Game(f">help")
        await self.bot.change_presence(activity=bot_game)

        await self.check_left_members()
        await self.bot.timers.run_old()
        await self.bot.invite_logger.initialize_invites()
        await self.bot.clearance.parse_clearance_spreadsheet()
        self.bot.leveling_system.initialise_guilds()
        self.bot.ukparl_module.set_guild(self.bot.get_guild(config.MAIN_SERVER))
        await self.bot.ukparl_module.load()
        self.bot.get_cog("UK").load()
        self.bot.logger.info(f"{self.bot.user} is ready")
        self.bot.ukparl_module.load_trackers()
        self.bot.webhooks.initialize()
        self.bot.watchlist.initialize()

        self.bot.ukparl_module.tracker_event_loop.start()

        self.bot.first_ready = True

    async def check_left_members(self):
        self.bot.logger.info(f"Checking Guilds for left members.")
        left_member_count = 0
        # check if any users have left while the bot was offline
        for guild in self.bot.guilds:
            initial_left_members = left_member_count
            guild_members = [
                m.id for m in await guild.fetch_members(limit=None).flatten()
            ]
            leveling_users = db.leveling_users.find({"guild_id": guild.id})
        if not self.bot.leveling_system:
            self.bot.left_check.set()

        self.bot.logger.info(f"{self.bot.user} is ready")

    @Cog.listener()
    async def on_command_error(self, ctx: Context, exception: Exception):
        trace = exception.__traceback__
        verbosity = 4
        lines = traceback.format_exception(type(exception), exception, trace, verbosity)
        traceback_text = "".join(lines)

        # send error to channel where eval was called
        if ctx.command and ctx.command.name == "eval":
            print(exception, traceback_text)
            return await ctx.send(f"```py\n{exception}\n{traceback_text}```")

        print(traceback_text)
        print(exception)

        # send error message to certain channel in a guild if error happens during bot runtime
        guild = self.bot.get_guild(config.ERROR_SERVER)
        if guild is None:
            return print("Invalid error server id")

        channel = self.bot.get_channel(config.ERROR_CHANNEL)
        if channel is None:
            return print("Invalid error channel id")

        embed = await embed_maker.message(
            ctx,
            author={
                "name": f"{ctx.command.name if ctx.command else 'Unknown'} - Command Error"
            },
            description=f"```{exception}\n{traceback_text}```",
        )

        embed.add_field(name="Message", value=ctx.message.content)
        embed.add_field(name="User", value=ctx.message.author)
        embed.add_field(name="Channel", value=f"{ctx.message.channel.name}")

        return await channel.send(embed=embed)

    @Cog.listener()
    async def on_daily_debate_timer_over(self, timer):
        guild_id = timer["guild_id"]
        guild = self.bot.get_guild(int(guild_id))

        now = round(time.time())
        dd_time = timer["expires"] + 3600
        tm = dd_time - now

        daily_debate_data = db.daily_debates.find_one({"guild_id": guild.id})
        # check if there are debate topics set up
        topics = daily_debate_data["topics"]
        channel_id = daily_debate_data["channel_id"]
        if not topics:
            # remind mods that a topic needs to be set up
            msg = f"Daily debate starts in {format_time.seconds(tm)} and no topics have been set up <@&810787506022121533>"
            channel = guild.get_channel(channel_id)

            if channel is None:
                return

            return await channel.send(msg)
        else:
            # start final timer which sends daily debate topic
            self.bot.timers.create(
                expires=dd_time,
                guild_id=guild.id,
                event="daily_debate_final",
                extras={},
            )

    @Cog.listener()
    async def on_daily_debate_final_timer_over(self, timer):
        guild_id = timer["guild_id"]
        guild = self.bot.get_guild(int(guild_id))

        daily_debate_data = db.daily_debates.find_one({"guild_id": guild_id})
        topic_data = daily_debate_data["topics"][0]
        topic = topic_data["topic"]
        topic_options = topic_data["topic_options"]
        topic_author_id = topic_data["topic_author_id"]
        topic_author = (
            await self.bot.fetch_user(int(topic_author_id)) if topic_author_id else None
        )

        dd_time = daily_debate_data["time"]
        dd_channel_id = daily_debate_data["channel_id"]
        dd_role_id = daily_debate_data["role_id"]
        dd_poll_channel_id = daily_debate_data["poll_channel_id"]

        dd_channel = (
            discord.utils.find(lambda c: c.id == int(dd_channel_id), guild.channels)
            if dd_channel_id
            else None
        )
        dd_role = (
            discord.utils.find(lambda r: r.id == int(dd_role_id), guild.roles)
            if dd_role_id
            else None
        )

        if not dd_channel:
            return

        message = f"Today's debate: **“{topic}”**"
        if topic_author:
            message += f" - Topic suggested by <@{topic_author_id}>"
        if dd_role:
            message += f"\n\n<@&{dd_role.id}>"

        msg = await dd_channel.send(message)

        # delete used topic
        db.daily_debates.update_one(
            {"guild_id": guild.id}, {"$pull": {"topics": topic_data}}
        )

        # change channel topic
        await dd_channel.edit(topic=f"{topic}")

        # unpin old topic message
        pins = [
            pin for pin in await dd_channel.pins() if pin.author.id == self.bot.user.id
        ]
        if pins:
            last_pin = pins[0]
            await last_pin.unpin()

        # pin new topic message
        await msg.pin()

        if dd_poll_channel_id:
            dd_poll_channel = discord.utils.find(
                lambda c: c.id == int(dd_poll_channel_id), guild.channels
            )
            if dd_poll_channel:
                # send yes/no/abstain poll

                poll_emotes = ["👍", "👎", "😐"]
                poll_options = ["Yes", "No", "Abstain"]

                description = f'**"{topic}"**\n'
                colour = config.EMBED_COLOUR
                embed = discord.Embed(
                    colour=colour,
                    description=description,
                    timestamp=datetime.datetime.now(),
                )
                embed.set_author(name="Daily Debate Poll")
                embed.set_footer(text="Started at", icon_url=guild.icon_url)

                description += "\n".join(
                    f"\n{e} | **{o}**" for e, o in zip(poll_emotes, poll_options)
                )
                embed.description = description

                poll_msg = await dd_poll_channel.send(embed=embed)
                for e in poll_emotes:
                    await poll_msg.add_reaction(e)

                # start 20h to send results to users
                expires = round(time.time() + (3600 * 20))
                self.bot.timers.create(
                    guild_id=guild_id,
                    expires=expires,
                    event="dd_results",
                    extras={
                        "poll_id": poll_msg.id,
                        "poll_channel_id": poll_msg.channel.id,
                    },
                )

                # send poll with custom options if they are provided
                if topic_options:
                    description = f'**"{topic}"**\n'
                    colour = config.EMBED_COLOUR
                    embed = discord.Embed(
                        colour=colour,
                        description=description,
                        timestamp=datetime.datetime.now(),
                    )
                    embed.set_author(
                        name="Daily Debate - Which statement(s) do you agree with?"
                    )
                    embed.set_footer(text="Started at", icon_url=guild.icon_url)

                    description += "\n".join(
                        f"\n{e} | **{o}**" for e, o in topic_options.items()
                    )
                    embed.description = description

                    poll_msg = await dd_poll_channel.send(embed=embed)
                    for e in poll_emotes:
                        await poll_msg.add_reaction(e)

        # give topic author boost if there is a topic author
        if topic_author and self.bot.leveling_system:
            leveling_member = await self.bot.leveling_system.get_member(
                int(guild_id), topic_author_id
            )
            leveling_member.boosts.daily_debate.expires = round(time.time()) + (
                3600 * 6
            )
            leveling_member.boosts.daily_debate.multiplier = 0.15

        # start daily_debate timer over
        mod_cog = self.bot.get_cog("Mod")
        return await mod_cog.start_daily_debate_timer(guild.id, dd_time)

    @Cog.listener()
    async def on_dd_results_timer_over(self, timer):
        poll_channel_id = timer["extras"]["poll_channel_id"]
        poll_id = timer["extras"]["poll_id"]

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

        if ayes != noes:
            who_has_it = "noes" if noes > ayes else "ayes"
            results_str = (
                f"**ORDER! ORDER!**\n\n"
                f"The ayes to the right: **{ayes}**\n"
                f"The noes to the left: **{noes}**\n"
                f"Abstentions: **{abstain}**\n\n"
                f"The **{who_has_it}** have it. The **{who_has_it}** have it. Unlock!"
            )
        else:
            results_str = "The vote is a tie."
        # send results string in dd poll channel
        return await channel.send(results_str)

    @Cog.listener()
    async def on_message_edit(self, before, after):
        if not self.bot._ready.is_set():
            return

        # re run command if command was edited
        if before.content != after.content and after.content.startswith(config.PREFIX):
            return await self.bot.process_command(after)

    @Cog.listener()
    async def on_raw_reaction_add(self, payload):
        guild_id = payload.guild_id

        channel_id = payload.channel_id
        message_id = payload.message_id
        user_id = payload.user_id

        # check if message is reaction_menu
        anon_poll = db.timers.find_one({"extras.message_id": message_id})
        if not anon_poll:
            return

        anon_poll_data = anon_poll["extras"]

        emote = payload.emoji.name
        if payload.emoji.is_custom_emoji():
            emote = f"<:{payload.emoji.name}:{payload.emoji.id}>"

        user = self.bot.get_user(user_id)
        if user.bot or not user:
            return

        # poll is message sent to user in dms
        if "main_poll_id" in anon_poll["extras"]:
            main_poll = db.timers.find_one(
                {"extras.message_id": anon_poll["extras"]["main_poll_id"]}
            )
            if emote not in main_poll["extras"]["options"]:
                return

            main_poll_data = main_poll["extras"]

            # check if user has voted for this option already
            user_pick = emote
            user_pick_hash = hashlib.md5(
                b"%a" % config.BOT_TOKEN + b"%a" % user.id + b"%a" % user_pick
            ).hexdigest()

            if (
                f"{user.id}" in main_poll_data["voted"]
                and user_pick_hash in main_poll_data["voted"][f"{user.id}"]
            ):
                embed = discord.Embed(
                    colour=config.EMBED_COLOUR,
                    description=f"You have already voted for {user_pick}",
                    timestamp=datetime.datetime.now(),
                )
                return await user.send(embed=embed, delete_after=10)

            # inform user of what they picked
            description = f"Your vote has been counted towards {user_pick}"
            # inform user if they have more options to pick
            pick_count = int(main_poll_data["pick_count"])
            options_picked_count = (
                len(main_poll_data["voted"][f"{user.id}"]) + 1
                if f"{user.id}" in main_poll_data["voted"]
                else 1
            )
            if options_picked_count < pick_count:
                description += f"\nYou can pick **{pick_count - options_picked_count}** more options"
            else:
                # delete poll message
                await self.bot.http.delete_message(
                    channel_id, anon_poll_data["message_id"]
                )
                # delete temporary poll from database
                db.timers.delete_one(anon_poll)

            embed = discord.Embed(
                colour=config.EMBED_COLOUR,
                description=description,
                timestamp=datetime.datetime.now(),
            )
            inform_message = await user.send(embed=embed, delete_after=10)
            await inform_message.delete(delay=5)

            # count user vote
            db.timers.update_one(
                {"extras.message_id": main_poll_data["message_id"]},
                {
                    "$inc": {f"extras.results.{emote}": 1},
                    "$push": {f"extras.voted.{user.id}": user_pick_hash},
                },
                upsert=True,
            )

        if not guild_id:
            return

        guild = self.bot.get_guild(int(guild_id))

        if not guild:
            return

        # to see user roles we need to get member
        member = guild.get_member(user_id)
        if member is None:
            member = await guild.fetch_member(user_id)

        if emote == "🇻":
            question = anon_poll_data["question"]

            # check if poll is restricted to role
            restrict_role_id = anon_poll_data["restrict_role"]
            if restrict_role_id:
                restrict_role = discord.utils.find(
                    lambda r: r.id == int(restrict_role_id), guild.roles
                )
                # user doesnt have required role
                if restrict_role and restrict_role not in member.roles:
                    return

            # send user poll
            embed_colour = config.EMBED_COLOUR
            embed = discord.Embed(
                colour=embed_colour, timestamp=datetime.datetime.now()
            )
            embed.set_footer(text=f"{guild.name}", icon_url=guild.icon_url)

            pick_count = int(anon_poll_data["pick_count"])
            options_picked_count = (
                len(anon_poll_data["voted"][f"{member.id}"])
                if f"{member.id}" in anon_poll_data["voted"]
                else 0
            )
            if options_picked_count >= pick_count:
                return

            embed = discord.Embed(
                title="Anonymous Poll",
                colour=config.EMBED_COLOUR,
                timestamp=datetime.datetime.now(),
            )
            embed.set_footer(
                text=f"You can pick {pick_count} option(s)", icon_url=guild.icon_url
            )

            emote_options = anon_poll_data["options"]

            description = f'**"{question}"**\n\n' + "\n\n".join(
                f"{e} | **{o}**" for e, o in emote_options.items()
            )
            embed.description = description

            msg = await member.send(embed=embed)
            for e in emote_options.keys():
                await msg.add_reaction(e)

            # check if there is already an active temporary timer
            temp_timer_data = db.timers.find_one({"extras.main_poll_id": message_id})
            if temp_timer_data:
                db.timers.delete_one({"extras.main_poll_id": message_id})
                await self.bot.http.delete_message(
                    temp_timer_data["extras"]["channel_id"],
                    temp_timer_data["extras"]["message_id"],
                )

            expires = int(time.time()) + (60 * 10)  # 10 minutes
            self.bot.timers.create(
                guild_id=0,
                expires=expires,
                event="delete_temp_poll",
                extras={
                    "main_poll_id": anon_poll["extras"]["message_id"],
                    "channel_id": msg.channel.id,
                    "message_id": msg.id,
                    "user_id": member.id,
                },
            )

    @Cog.listener()
    async def on_delete_temp_poll_timer_over(self, timer):
        channel_id = timer["extras"]["channel_id"]
        message_id = timer["extras"]["message_id"]

        try:
            return await self.bot.http.delete_message(channel_id, message_id)
        except:
            return

    @Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        # if name has changed, edit database entry
        if before.name != after.name and self.bot.leveling_system:
            leveling_guild = self.bot.leveling_system.get_guild(before.guild.id)

            for branch in leveling_guild.leveling_routes:
                for role in branch:
                    if role.name == before.name:
                        role.name = after.name

                        db.leveling_users.update_many(
                            {
                                "guild_id": after.guild.id,
                                f"{branch.name[0]}_role": before.name,
                            },
                            {"$set": {f"{branch.name[0]}_role": after.name}},
                        )

    @Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild_id = member.guild.id
        user_id = member.id

        # see if user is in left_leveling_users, if they are, move the data back to leveling_users
        left_user = db.left_leveling_users.find_one(
            {"guild_id": guild_id, "user_id": user_id}
        )
        if left_user:

            # transfer back data
            db.left_leveling_users.delete_many(
                {"guild_id": guild_id, "user_id": user_id}
            )
            del left_user["_id"]
            db.leveling_users.insert_one(left_user)

            # delete timer
            db.timers.delete_one(
                {
                    "guild_id": guild_id,
                    "extras.user_id": user_id,
                    "event": "leveling_data_expires",
                }
            )

            if self.bot.leveling_system:
                leveling_member = await self.bot.leveling_system.get_member(
                    member.guild.id, member.id
                )

                for branch in leveling_member.guild.leveling_routes:
                    user_role = next(
                        (
                            role
                            for role in branch.roles
                            if role.name == left_user[f"{branch.name[0]}_role"]
                        ),
                        None,
                    )
                    if user_role:
                        user_role_index = branch.roles.index(user_role)
                        up_to_role = branch.roles[: user_role_index + 1]
                        for role in up_to_role:
                            await leveling_member.add_role(role)

    @Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        leveling_user = db.leveling_users.find_one(
            {"guild_id": member.guild.id, "user_id": member.id}
        )

        if not leveling_user:
            return

        self.bot.leveling_system.transfer_leveling_data(leveling_user)

    @Cog.listener()
    async def on_leveling_data_expires_timer_over(self, timer: dict):
        # delete user from left_leveling_users
        db.left_leveling_users.delete_one(
            {"guild_id": timer["guild_id"], "user_id": timer["extras"]["user_id"]}
        )

    @Cog.listener()
    async def on_guild_channel_delete(self, channel):
        ticket = db.tickets.find_one(
            {"guild_id": channel.guild.id, "channel_id": channel.id}
        )
        if ticket:
            db.tickets.delete_one({"_id": ObjectId(ticket["_id"])})

    @Cog.listener()
    async def on_rep_at_timer_over(self, timer: dict):
        guild: discord.Guild = self.bot.get_guild(timer["guild_id"])
        if not guild:
            return

        member: discord.Member = guild.get_member(timer["extras"]["member_id"])
        if member is None:
            try:
                member: discord.Member = await guild.fetch_member(
                    timer["extras"]["member_id"]
                )
            except Exception:
                return

        description = (
            "Your rep timer has expired, you can give someone a reputation point again."
        )

        embed = discord.Embed(
            colour=config.EMBED_COLOUR,
            description=description,
            timestamp=datetime.datetime.now(),
        )
        embed.set_author(name="Rep timer", icon_url=guild.icon_url)
        try:
            await member.send(embed=embed)
        except Exception:
            # wasnt able to send dm to user, so will send the message in the bot channel
            channel: discord.TextChannel = self.bot.get_channel(config.BOT_CHANNEL_ID)
            await channel.send(
                embed=embed, content=f"<@{member.id}>, I wasn't able to dm you"
            )

    @Cog.listener()
    async def on_ban(self, member: discord.Member):
        # delete user from leveling_users
        db.leveling_users.delete_one(
            {"guild_id": member.guild.id, "user_id": member.id}
        )


def setup(bot):
    bot.add_cog(Events(bot))
