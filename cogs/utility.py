import datetime
import discord
import time
import config
import os
import inspect
import pytz
import bs4

from iso639 import languages
from googletrans import Translator
from emoji.unicode_codes.en import EMOJI_UNICODE_ENGLISH, EMOJI_ALIAS_UNICODE_ENGLISH
from timezonefinder import TimezoneFinder
from typing import Union
from bson import ObjectId
from modules import commands, database, embed_maker, format_time
from modules.utils import get_member, ParseArgs, get_custom_emote
from discord.ext.commands import Cog, command, Context
from bot import TLDR

db = database.get_connection()


class Utility(Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot

    @command(
        help="Translate text to english",
        usage="translate [text]",
        examples=["translate tere"],
        cls=commands.Command,
    )
    async def translate(self, ctx: Context, *, text: str = None):
        if text is None:
            return await embed_maker.command_error(ctx)

        translator = Translator()
        translated = translator.translate(text, dest="en")
        source_language = languages.get(alpha2=translated.src).name

        return await embed_maker.message(
            ctx,
            author={"name": "Translator"},
            description=f"**{source_language}:** {text}\n"
            f"**English:** {translated.text}",
            send=True,
        )

    def cg_to_string(
        self, tags: bs4.element.Tag, asked_for: list[str], parent: str = ""
    ):
        spacer = f'|{"-" * 4}'
        string = ""
        parent_count = len(parent.split(".")) if parent else 0
        asked_for_cg_number = (
            asked_for[parent_count] if len(asked_for) > parent_count else None
        )

        for i, cg in enumerate(filter(lambda cg: type(cg) == bs4.element.Tag, tags)):
            contents = cg.contents

            cg_number = str(i + 1)
            if asked_for_cg_number is None or asked_for_cg_number == cg_number:
                new_parent = f'{parent + ("." if parent else "")}{cg_number}'
                if len(contents) > 1:
                    sub_cg = self.cg_to_string(contents[1], asked_for, new_parent)
                    string += f"{spacer * parent_count}`{new_parent}.`: {contents[0]}"
                    string += f"{sub_cg}"
                else:
                    string += (
                        f"{spacer * parent_count}`{new_parent}.`: {cg.contents[0]}\n"
                    )

        return string

    async def get_cg(self, asked_for: list[str]):
        # This session needs to be gotten in this weird way cause it's a double underscore variable
        aiohttp_session = getattr(self.bot.http, "_HTTPClient__session")
        async with aiohttp_session.get(
            "https://tldrnews.co.uk/discord-community-guidelines/"
        ) as resp:
            content = await resp.text()

            soup = bs4.BeautifulSoup(content, "html.parser")
            entry = soup.find("div", {"class": "entry-content"})
            cg_list = [*entry.children][15]

            return self.cg_to_string(cg_list, asked_for)

    @command(
        help="command to get any community guideline",
        usage="cg [cg]",
        examples=["cg 1", "cg 1.5.1"],
        cls=commands.Command,
    )
    async def cg(self, ctx: Context, guideline: str = None):
        cg_link = "https://tldrnews.co.uk/discord-community-guidelines/"
        if guideline is None:
            return await embed_maker.message(
                ctx,
                description=f"You can find the full list of the community guidelines here: [{cg_link}]({cg_link})",
                send=True,
            )

        cg_text = await self.get_cg(guideline.split("."))

        if not cg_text:
            return await embed_maker.error(
                ctx, f"{guideline} is not a valid community guideline."
            )

        return await embed_maker.message(
            ctx, description=cg_text, author={"name": "Community Guidelines"}, send=True
        )

    @command(
        name="time",
        help="See time in any location in the world",
        usage="time [location]",
        examples=["time london"],
        cls=commands.Command,
    )
    async def time_in(self, ctx: Context, *, location_str: str = None):
        if location_str is None:
            return await embed_maker.command_error(ctx)

        if not config.GEONAMES_USERNAME:
            return await embed_maker.error(
                ctx, "GEONAMES_USERNAME has not been set in the config file."
            )

        aiohttp_session = getattr(self.bot.http, "_HTTPClient__session")
        async with aiohttp_session.get(
            f"http://api.geonames.org/searchJSON?q={location_str}&maxRows=1&username={config.GEONAMES_USERNAME}"
        ) as resp:
            location_json = await resp.json()
            if "geonames" not in location_json:
                return await embed_maker.error(
                    ctx, f'Geonames error: {location_json["status"]["message"]}'
                )

            location = location_json["geonames"][0]

            timezone_finder = TimezoneFinder()
            location_timezone_str = timezone_finder.timezone_at(
                lng=float(location["lng"]), lat=float(location["lat"])
            )
            location_timezone = pytz.timezone(location_timezone_str)

            time_at = datetime.datetime.now(location_timezone)
            time_at_str = time_at.strftime("%H:%M:%S")

            google_maps_link = f'https://www.google.com/maps/search/?api=1&query={location["lat"]},{location["lng"]}'
            return await embed_maker.message(
                ctx,
                description=f'Time at [{location["name"]}, {location["countryName"]}]({google_maps_link}) is: `{time_at_str}`',
                send=True,
            )

    @command(
        help="Create an anonymous poll similar to regular poll. after x amount of time (default 5 minutes), results are displayed\n"
        "Poll can be restricted to a specific role. An update interval can be set, every x amount of time results are updated",
        usage="anon_poll [args]",
        examples=[
            "anon_poll -q best food? -o pizza | burger | fish and chips | salad",
            "anon_poll -q Do you guys like pizza? -t 2m",
            "anon_poll -q Where are you from? -o [🇩🇪: Germany], [🇬🇧: UK] -t 1d -u 1m -p 2 -r Mayor",
        ],
        command_args=[
            (("--question", "-q", str), "The question for the poll"),
            (("--option", "-o", list), "Option for the poll"),
            (
                ("--time", "-t", format_time.parse),
                "[Optional] How long the poll will stay active for e.g. 5d 5h 5m",
            ),
            (
                ("--update_interval", "-u", str),
                "[Optional] If set, the bot will update the poll with data in given interval of time",
            ),
            (
                ("--pick_count", "-p", str),
                "[Optional] How many options users can pick, defaults to 1",
            ),
            (
                ("--role", "-r", str),
                "[Optional] The role the poll will be restricted to",
            ),
        ],
        cls=commands.Command,
        module_dependency=['timers']
    )
    async def anon_poll(self, ctx: Context, *, args: Union[ParseArgs, dict] = None):
        if not args:
            return await embed_maker.command_error(ctx)

        question = args["question"]
        options = args["option"]

        # return error if required variables are not given
        if not question:
            return await embed_maker.error(ctx, "Missing question arg")

        if not options:
            return await embed_maker.error(ctx, "Missing option args")

        # get all optional variables
        poll_time = args["time"]
        if not poll_time:
            poll_time = 300  # 5 minutes

        update_interval = args["update_interval"]
        pick_count = args["pick_count"] if args["pick_count"] else "1"
        restrict_role_identifier = args["role"]

        emote_options = await self.parse_poll_options(ctx, options)
        if type(emote_options) == discord.Message:
            return

        # validate all the variables
        err = ""

        restrict_role = ""
        if restrict_role_identifier:
            restrict_role = discord.utils.find(
                lambda r: r.name.lower() == restrict_role_identifier.lower()
                or str(r.id) == restrict_role_identifier,
                ctx.guild.roles,
            )
            if restrict_role is None:
                err = "Invalid role"

        if pick_count and not pick_count.isdigit():
            err = "pick count arg is not a number"

        if poll_time is None:
            err = "Invalid time arg"

        if update_interval and format_time.parse(update_interval) is None:
            err = "Invalid update interval time"
        else:
            update_interval = format_time.parse(update_interval)
            if update_interval and update_interval < 30:
                err = "Update interval can't be smaller than 30 seconds"

        if err:
            return await embed_maker.error(ctx, err)

        description = f'**"{question}"**\n'
        description += "\n".join(
            f"\n{emote} | **{option}**" for emote, option in emote_options.items()
        )

        description += f"\n\nReact with 🇻 to vote!\n"

        if restrict_role:
            description += f"Role needed to vote: <@&{restrict_role.id}>\n"

        poll_msg = await embed_maker.message(
            ctx,
            description=description,
            author={"name": "Anonymous Poll"},
            footer={"text": "Started at"},
            send=True,
        )

        await poll_msg.add_reaction("🇻")

        expires = 0 if update_interval else round(time.time()) + round(poll_time)

        # start timer
        # we shall also use the timer to keep track of votes and who voted
        self.bot.timers.create(
            guild_id=ctx.guild.id,
            expires=expires,
            event="anon_poll",
            extras={
                "message_id": poll_msg.id,
                "channel_id": poll_msg.channel.id,
                "question": question,
                "options": emote_options,
                "pick_count": pick_count,
                "voted": {},
                "results": dict.fromkeys(emote_options.keys(), 0),
                "update_interval": update_interval,
                "true_expire": 0
                if not update_interval
                else round(time.time()) + poll_time,
                "restrict_role": None if not restrict_role else restrict_role.id,
            },
        )

    @Cog.listener()
    async def on_anon_poll_timer_over(self, timer):
        message_id = timer["extras"]["message_id"]
        channel_id = timer["extras"]["channel_id"]
        guild_id = timer["guild_id"]
        update_interval = timer["extras"]["update_interval"]
        true_expire = timer["extras"]["true_expire"]

        question = timer["extras"]["question"]
        options = timer["extras"]["options"]
        results = timer["extras"]["results"]

        channel = self.bot.get_channel(channel_id)

        message = await channel.fetch_message(message_id)
        if not message:
            return

        total_votes = sum([v for v in results.values() if isinstance(v, int)])

        description = f'**"{question}"**\n\n'

        # just in case nobody participated
        if total_votes == 0:
            description += "\n\n".join(
                f"{emote} - {options[emote]} - **{emote_count}** | **0%**"
                for emote, emote_count in results.items()
                if emote in options
            )
        else:
            description += "\n\n".join(
                f"{emote} - {options[emote]} - **{emote_count}** | **{round((emote_count * 100) / total_votes)}%**"
                for emote, emote_count in results.items()
                if emote in options
            )

        description += f"\n\n**Total Votes:** {total_votes}"

        # later used to check if embed has changed
        old_embed = message.embeds[0].to_dict()

        embed = message.embeds[0]
        embed.timestamp = datetime.datetime.fromtimestamp(true_expire)

        if update_interval:
            embed.set_footer(
                text=f"Results updated every {format_time.seconds(update_interval)} | Ends at"
            )
        else:
            embed.set_footer(text="Ended at")

        expired = round(time.time()) > true_expire
        if not expired:
            description += "\n\nReact with :regional_indicator_v: to vote"
            if timer["extras"]["restrict_role"]:
                restrict_role_id = timer["extras"]["restrict_role"]
                description += f"\nRole needed to vote: <@&{restrict_role_id}>"
        else:
            embed.set_footer(text="Ended at")

        embed.description = description

        # if old and new are identical, dont bother the discord api
        if old_embed != embed.to_dict():
            await message.edit(embed=embed)

        # check if poll passed true expire
        if expired:
            # delete poll from db
            await message.clear_reactions()

            # delete any remaining temp polls in dms
            temp_polls = [
                d for d in db.timers.find({"extras.main_poll_id": message.id})
            ]
            if temp_polls:
                db.timers.delete_many({"main_poll_id": message.id})
                for poll in temp_polls:
                    await self.bot.http.delete_message(
                        poll["extras"]["channel_id"], poll["extras"]["message_id"]
                    )

            # send message about poll being completed
            return await channel.send(
                f"Anonymous poll finished: https://discordapp.com/channels/{guild_id}/{channel_id}/{message.id}"
            )

        # run poll timer again if needed
        elif update_interval:
            expires = round(time.time()) + round(update_interval)
            return self.bot.timers.create(
                guild_id=timer["guild_id"],
                expires=expires,
                event="anon_poll",
                extras=timer["extras"],
            )

    @staticmethod
    def remove_last_char(msg: str):
        pos = len(msg) - 1
        while pos > -1 and ord(msg[pos]) & 0xC0 == 0x80:
            # character at pos is a continuation byte (bit 7 set, bit 6 not)
            pos -= 1
        return msg[:pos]

    async def parse_poll_options(self, ctx, options):
        emote_options = {}
        is_valid_emote = (
            lambda e: e in EMOJI_UNICODE_ENGLISH.values()
            or e in EMOJI_ALIAS_UNICODE_ENGLISH.values()
        )
        encoded = options[0].split(":")[0].strip().encode()
        # check if user wants to have custom emotes
        first_emote = options[0].split(":")[0].strip()
        if (
            is_valid_emote(first_emote)
            or is_valid_emote(self.remove_last_char(first_emote))
            or get_custom_emote(ctx, ":".join(options[0].split(":")[:3]))
        ):
            for option in options:
                option = option.strip()
                option_split = option.split(":")
                emote = option_split[0].replace(" ", "")
                custom_emote = get_custom_emote(ctx, ":".join(option_split[:3]))

                if custom_emote:
                    emote = str(custom_emote)
                    option = ":".join(option_split[3:])
                else:
                    option = ":".join(option_split[1:])

                if len(option_split) > 1:
                    emote_options[emote] = option
                # in case user wanted to use options with emotes, but one of them didn't match
                else:
                    return await embed_maker.error(
                        ctx, f"Invalid emote provided for option: {emote}"
                    )
        else:
            if len(options) > 9:
                return await embed_maker.error(
                    ctx, "Too many options given, max without custom emotes is 9"
                )

            all_num_emotes = [
                "1️⃣",
                "2️⃣",
                "3️⃣",
                "4️⃣",
                "5️⃣",
                "6️⃣",
                "7️⃣",
                "8️⃣",
                "9️⃣",
            ]
            emote_options = {
                e: options[i] for i, e in enumerate(all_num_emotes[: len(options)])
            }

        return emote_options

    @command(
        help="Create a poll, without custom emotes, adds numbers as reactions",
        usage="poll [args]",
        examples=[
            "poll -q best food? -o pizza -o burger -o fish and chips -o salad",
            "poll -q Where are you from? -o 🇩🇪: Germany -o 🇬🇧: UK",
        ],
        command_args=[
            (("--question", "-q", str), "The question for the poll"),
            (("--option", "-o", list), "Option for the poll"),
        ],
        cls=commands.Command,
    )
    async def poll(self, ctx: Context, *, args: Union[ParseArgs, dict] = None):
        if not args:
            return await embed_maker.command_error(ctx)

        question = args["question"]
        options = args["option"]

        if not question:
            return await embed_maker.error(ctx, "Missing question arg")

        if not options:
            return await embed_maker.error(ctx, "Missing option arg(s)")

        emote_options = await self.parse_poll_options(ctx, options)
        # return if error message was sent
        if type(emote_options) == discord.Message:
            return

        description = f'**"{question}"**\n' + "\n".join(
            f"\n{emote} | **{option}**" for emote, option in emote_options.items()
        )
        poll_msg = await embed_maker.message(
            ctx,
            description=description,
            author={"name": "Poll"},
            footer={"text": "Started at"},
            send=True,
        )

        for e in emote_options.keys():
            await poll_msg.add_reaction(e)

    @command(
        help="See the list of your current reminders or remove some reminders",
        usage="reminders (action) (reminder index)",
        examples=["reminders", "reminders remove 1"],
        cls=commands.Command,
    )
    async def reminders(self, ctx: Context, action: str = None, *, index: str = None):
        user_reminders = sorted(
            [
                r for r in db.timers.find(
                    {
                        "guild_id": ctx.guild.id,
                        "event": "reminder",
                        "extras.member_id": ctx.author.id,
                    }
                )
            ],
            key=lambda r: r["expires"],
        )
        if action is None:
            if not user_reminders:
                msg = "You currently have no reminders"
            else:
                msg = ""
                for i, r in enumerate(user_reminders):
                    expires = r["expires"] - round(time.time())
                    msg += f'`#{i + 1}` - {r["extras"]["reminder"]} in **{format_time.seconds(expires)}**\n'

            return await embed_maker.message(ctx, description=msg, send=True)

        elif action not in ["remove"]:
            return await embed_maker.command_error(ctx, "(action)")
        elif index is None or int(index) <= 0 or int(index) > len(user_reminders):
            return await embed_maker.command_error(ctx, "(reminder index)")
        else:
            timer = user_reminders[int(index) - 1]
            db.timers.delete_one({"_id": ObjectId(timer["_id"])})
            return await embed_maker.message(
                ctx,
                description=f'`{timer["extras"]["reminder"]}` has been removed from your list of reminders',
                colour="green",
                send=True,
            )

    @command(
        help="Create a reminder",
        usage="remindme [time] [reminder]",
        examples=[
            "remindme 24h rep hattyot",
            "remindme 30m slay demons",
            "remindme 10h 30m 10s stay alive",
        ],
        cls=commands.Command,
        module_dependency=['timers']
    )
    async def remindme(self, ctx: Context, *, reminder: str = None):
        if reminder is None:
            return await embed_maker.command_error(ctx)

        remind_time, reminder = format_time.parse(reminder, return_string=True)

        if not reminder:
            return await embed_maker.error(ctx, "You cannot have an empty reminder")

        expires = round(time.time()) + remind_time
        self.bot.timers.create(
            expires=expires,
            guild_id=ctx.guild.id,
            event="reminder",
            extras={"reminder": reminder, "member_id": ctx.author.id},
        )

        return await embed_maker.message(
            ctx,
            description=f"Alright, in {format_time.seconds(remind_time, accuracy=10)} I will remind you: `{reminder}`",
            send=True,
        )

    @Cog.listener()
    async def on_reminder_timer_over(self, timer):
        guild_id = timer["guild_id"]
        guild = self.bot.get_guild(int(guild_id))

        member_id = timer["extras"]["member_id"]
        member = guild.get_member(int(member_id))
        if member is None:
            member = await guild.fetch_member(int(member_id))
            if member is None:
                return

        reminder = timer["extras"]["reminder"]
        embed_colour = config.EMBED_COLOUR
        embed = discord.Embed(
            colour=embed_colour,
            description=f"Reminder: `{reminder}`",
            timestamp=datetime.datetime.now(),
        )
        embed.set_footer(text=f"{member}", icon_url=member.avatar_url)

        try:
            return await member.send(embed=embed)
        except Exception as e:
            self.bot.logger.exception(e)
            bot_channel = self.bot.get_channel(config.BOT_CHANNEL_ID)
            return await bot_channel.send(
                f"I wasn't able to dm you, so here's the reminder <@{member.id}>",
                embed=embed,
            )

    @command(
        help="Get bot's latency", usage="ping", examples=["ping"], cls=commands.Command
    )
    async def ping(self, ctx: Context):
        message_created_at = ctx.message.created_at
        message = await ctx.send("Pong")
        ping = (datetime.datetime.utcnow() - message_created_at) * 1000
        await message.edit(
            content=f"\U0001f3d3 Pong   |   {int(ping.total_seconds())}ms"
        )

    @command(
        help="See someones profile picture",
        usage="pfp (user)",
        examples=["pfp", "pfp @Hattyot", "pfp hattyot"],
        cls=commands.Command,
    )
    async def pfp(self, ctx: Context, *, member: str = None):
        if not member:
            member = ctx.author
        else:
            member = await get_member(ctx, member)
            if type(member) == discord.Message:
                return

        embed = discord.Embed(description=f"**Profile Picture of {member}**")
        embed.set_image(
            url=str(member.avatar_url).replace(".webp?size=1024", ".png?size=2048")
        )

        return await ctx.send(embed=embed)

    @command(
        help="See info about a user",
        usage="userinfo (user)",
        examples=["userinfo", "userinfo Hattyot"],
        cls=commands.Command,
    )
    async def userinfo(self, ctx: Context, *, user: str = None):
        if user is None:
            member = ctx.author
        else:
            member = await get_member(ctx, user)
            if type(member) == discord.Message:
                return

        name = str(member)
        if member.display_name:
            name += f" [{member.display_name}]"

        embed = await embed_maker.message(ctx, author={"name": name})

        embed.add_field(name="ID", value=member.id, inline=False)

        created_at = datetime.datetime.now() - member.created_at
        created_at_seconds = int(created_at.total_seconds())
        embed.add_field(
            name="Account Created",
            value=f'{member.created_at.strftime("%b %d %Y %H:%M")}\n{format_time.seconds(created_at_seconds, accuracy=10)} Ago',
            inline=False,
        )

        joined_at = datetime.datetime.now() - member.joined_at
        joined_at_seconds = int(joined_at.total_seconds())
        embed.add_field(
            name="Joined Server",
            value=f'{member.joined_at.strftime("%b %d %Y %H:%M")}\n{format_time.seconds(joined_at_seconds, accuracy=10)} Ago',
            inline=False,
        )

        embed.add_field(name="Status", value=str(member.status), inline=False)
        embed.set_thumbnail(url=member.avatar_url)

        return await ctx.send(embed=embed)

    @command(
        help="Get help smh",
        usage="help (command)",
        examples=["help", "help ping"],
        cls=commands.Command,
    )
    async def help(self, ctx: Context, *, command_name: str = None):
        # compile help_object to include all the categories as keys and commands as values
        help_object = {}
        for command in self.bot.commands:
            if not command.can_use(ctx.author):
                continue

            cog_name = (
                "Special Access"
                if command.access_given(ctx.author)
                else command.cog_name
            )

            if cog_name == "PrivateMessages":
                cog_name = "Private Messages"

            if cog_name not in help_object:
                help_object[cog_name] = [command]
            else:
                help_object[cog_name].append(command)

        member_clearance = self.bot.clearance.member_clearance(ctx.author)
        # if user didnt ask for a specific command, display all the available categories and commands to the user
        if command_name is None:
            highest_member_clearance = self.bot.clearance.highest_member_clearance(
                member_clearance
            )

            embed = await embed_maker.message(
                ctx,
                description=f"**Prefix** : `{ctx.prefix}`\nFor additional info on a command, type `{ctx.prefix}help [command]`",
                author={"name": f"Help - {highest_member_clearance}"},
            )

            sorted_cog_names = [
                "Leveling",
                "Utility",
                "Private Messages",
                "Fun",
                "Mod",
                "Settings",
                "Admin",
                "Dev",
                "Special Access",
            ]
            for cog_name in sorted_cog_names:
                if cog_name not in help_object:
                    continue

                cog = help_object[cog_name]
                embed.add_field(
                    name=f">{cog_name}",
                    value=r" \| ".join(sorted([f"`{cmd}`" for cmd in cog])),
                    inline=False,
                )

            return await ctx.send(embed=embed)
        elif command_name:
            command = self.bot.get_command(command_name)
            if command is None:
                return await embed_maker.error(
                    ctx, f"Couldn't find a command by the name: `{command_name}`"
                )

            if not command.can_use(ctx.author):
                return

            command_help = command.get_help(ctx.author)

            if command.cog_name not in help_object:
                return

            command_list = help_object[command.cog_name]
            if "Special Access" in help_object:
                command_list += help_object["Special Access"]

            if not command and command not in command_list:
                return

            examples = f"\n".join(command_help.examples)
            cmd_help = (
                f"**Description:** {command_help.help}\n"
                f"**Usage:** {command_help.usage}\n"
                f"**Examples:**\n{examples}"
            )

            if type(command) == commands.Group and command.all_commands:
                sub_commands = command.sub_commands(member=ctx.author)
                if sub_commands:
                    sub_commands_str = '**\nSub Commands:** ' + ' | '.join(sc.name for sc in sub_commands)
                    sub_commands_str += f'\nTo view more info about sub commands, type `{ctx.prefix}help {command.name} [sub command]`'
                    cmd_help += sub_commands_str

            if command_help.command_args:
                command_args_str = (
                    "**\nCommand Args:**\n```"
                    + "\n\n".join(
                        f'{f"{arg[0]}" + (f", {arg[1]}" if type(arg[1]) == str else "")} - {description}'
                        for arg, description in command_help.command_args
                    )
                    + "```"
                )
                cmd_help += command_args_str

            author_name = f"Help: {command}"
            if command.special_help_group:
                author_name += f" - {command_help.clearance}"

            return await embed_maker.message(
                ctx, description=cmd_help, author={"name": author_name}, send=True
            )
        else:
            return await embed_maker.message(
                ctx, description="{command} is not a valid command", send=True
            )

    @command(
        help="View source code of any command",
        usage="source (command)",
        examples=["source", "source pfp"],
        cls=commands.Command,
    )
    async def source(self, ctx, *, command=None):
        u = "\u200b"
        if not command:
            return await embed_maker.message(
                ctx,
                description=f"Check out the full sourcecode on GitHub\nhttps://github.com/Hattyot/TLDR-Bot",
                send=True,
            )

        # pull source code
        command = self.bot.get_command(command)
        if not command:
            return await embed_maker.error(ctx, "Invalid command")

        src = f"```py\n{str(inspect.getsource(command.callback)).replace('```', f'{u}')}```"

        # pull back indentation
        new_src = ""
        for line in src.splitlines():
            new_src += f"{line.replace('    ', '', 1)}\n"

        src = new_src

        if len(src) > 2000:
            file = command.callback.__code__.co_filename
            location = os.path.relpath(file)
            total, fl = inspect.getsourcelines(command.callback)
            ll = fl + (len(total) - 1)
            return await embed_maker.message(
                ctx,
                description=f"This code was too long for Discord, you can see it instead [on GitHub](https://github.com/Hattyot/TLDR-Bot/blob/master/{location}#L{fl}-L{ll})",
                send=True,
            )
        else:
            await ctx.send(src)


def setup(bot):
    bot.add_cog(Utility(bot))
