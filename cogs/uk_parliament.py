import functools
import math
from datetime import datetime
from io import BytesIO
from typing import Union

import modules.commands as cls
from bot import TLDR
from discord import embeds
from discord.ext import commands
from discord.ext.commands import Context
from discord.ext.commands.converter import TextChannelConverter
from discord.file import File
from modules import database, embed_maker
from modules.custom_commands import Guild
from modules.reaction_menus import BookMenu
from modules.utils import ParseArgs
from ukparliament.bills import SearchBillsBuilder, SearchBillsSortOrder
from ukparliament.structures.bills import Bill, CommonsDivision, LordsDivision
from ukparliament.utils import URL_BILLS


class UK(commands.Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot
        self.loaded = False

    def load(self):
        self.ukparl_module = self.bot.ukparl_module
        self.parliament = self.ukparl_module.parliament
        self.loaded = True

    @staticmethod
    async def construct_bills_search_embed(
        ctx: Context,
        bills: list[Bill],
        max_page_num: int,
        page_limit: int,
        *,
        page: int,
    ):
        if len(bills) == 0:
            return await embed_maker.message(ctx, description="No bills found.")

        bits = []
        next_line = "\n"
        for i, bill in enumerate(bills[page_limit * (page - 1) : page_limit * page]):
            bill_title = bill.get_title()
            description = None
            if bill.get_long_title() is not None:
                description = bill.get_long_title()[0:160] + "..."

            bill_id = bill.get_bill_id()
            bill_url = f"https://bills.parliament.uk/bills/{bill.get_bill_id()}"
            entry = f"**{(i + 1) + (page_limit * (page - 1))}. [{bill_title}]({bill_url}) | ID: {bill_id}**{next_line}"
            if description is not None:
                entry = entry + f"**Description:** {description}"
            bits.append(entry)

        embed = await embed_maker.message(
            ctx,
            description=next_line.join(bits),
            author={"name": "UKParliament Bills"},
            footer={"text": f"Page {page}/{max_page_num}"},
        )
        return embed

    @staticmethod
    async def construct_bill_info_embed(
        ctx: Context,
        bill: Bill,
        c_divisions: list[CommonsDivision],
        l_divisions: list[LordsDivision],
        page_limit: int,
        *,
        page: int,
    ):
        formatted_bill_information = [
            f"**Title:** {bill.get_title()}",
            f"**Description:** {bill.get_long_title()}",
            # f"**Introduced:** {bill.get_date_introduced().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Last Update:** {bill.get_last_update().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Act of Parliament:** {'Yes' if bill.is_act() else 'No'}",
        ]

        if bill.has_royal_assent():
            formatted_bill_information.append(
                "**Current Stage:** Received Royal Assent"
            )
        else:
            formatted_bill_information.extend(
                [
                    f"**Current Stage:** {bill.get_current_stage().get_name()}",
                    f"**Current House:** {bill.get_current_house()}",
                ]
            )

        total_length = (
            len(l_divisions) + len(c_divisions) + len(formatted_bill_information)
        )
        max_pages = math.ceil(total_length / page_limit)
        pages: list[embeds.Embed] = []

        async def template(description: str, title: str) -> embeds.Embed:
            return await embed_maker.message(
                ctx,
                title=title,
                description=description,
                author={"name": "UKParliament Bill"},
                footer={"text": f"Page: {page}/{max_pages}"},
            )  # type: ignore

        next_line = "\n"
        if len(l_divisions) > 0:
            bits = []
            for i, division in enumerate(l_divisions):
                did_pass = division.get_aye_count() > division.get_no_count()
                bits.append(
                    f"**{i + 1}. [{division.get_division_title()}](https://votes.parliament.uk/Votes/"
                    f"Lords/Division/{division.get_id()})**{next_line}"
                    f"**ID:** {division.get_id()}{next_line}"
                    f"**Summary:** "
                    f"{division.get_amendment_motion_notes()[0:150].replace('<p>', '').replace('</p>', '')}..."
                    if division.get_amendment_motion_notes() is not None
                    and division.get_amendment_motion_notes() != ""
                    else ""
                    f"{next_line}**Division Result:** {'Passed' if did_pass else 'Not passed'} by a division"
                    f"of {division.get_aye_count() if did_pass else division.get_no_count()}"
                    f"{'Ayes' if did_pass else 'Noes'} to "
                    f"{division.get_aye_count() if did_pass is False else division.get_no_count()}"
                    f" {'Noes' if did_pass else 'Ayes'}"
                    f"{next_line}**Division Date:** {division.get_division_date().strftime('%Y-%m-%d %H:%M:%S')}"
                )

                if i == (page_limit - 1) or i == (len(l_divisions) - 1):
                    pages.append(
                        await template(
                            title="Lords Divisions", description="\n".join(bits)
                        )
                    )
                    bits.clear()

        if len(c_divisions) > 0:
            bits = []
            for i, division in enumerate(c_divisions):
                did_pass = division.get_aye_count() > division.get_no_count()
                bits.append(
                    f"**{i + 1}. [{division.get_division_title()}](https://votes.parliament.uk/"
                    f"Votes/Lords/Division/{division.get_id()})**{next_line}"
                    f"**ID:** {division.get_id()}{next_line}**Division Result:**"
                    f"{'Passed' if did_pass else 'Not passed'} by a division of"
                    f" {division.get_aye_count() if did_pass else division.get_no_count()}"
                    f"{'Ayes' if did_pass else 'Noes'} to "
                    f"{division.get_aye_count() if did_pass is False else division.get_no_count()}"
                    f"{'Noes' if did_pass else 'Ayes'}{next_line}**Division Date:**"
                    f"{division.get_division_date().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                if i == (page_limit - 1) or i == (len(l_divisions) - 1):
                    pages.append(
                        await template(
                            title="Commons Divisions", description="\n".join(bits)
                        )
                    )
                    bits.clear()

        first_page: embeds.Embed = await embed_maker.message(
            ctx,
            description="\n".join(formatted_bill_information),
            author={"name": "UKParliament Bill"},
            footer={"text": f"Page: {page}/{max_pages}"},
        )  # type: ignore
        pages.insert(0, first_page)
        return (pages[(page - 1)], len(pages))

    @staticmethod
    async def construct_divisions_lords_embed(
        ctx: commands.Context,
        divisions: list[LordsDivision],
        page_limit: int,
        *,
        page: int,
    ):
        max_pages = math.ceil(len(divisions) / page_limit)

        bits = []
        next_line = "\n"
        for i, division in enumerate(
            divisions[page_limit * (page - 1) : page_limit * page]
        ):
            did_pass = division.get_aye_count() > division.get_no_count()
            bits.append(
                f"**{(page_limit * (page -1)) + i + 1}. [{division.get_division_title()}]"
                f"(https://votes.parliament.uk/Votes/Lords/Division/{division.get_id()})**{next_line}"
                f"**ID:** {division.get_id()}{next_line}**Summary:** {division.get_amendment_motion_notes()[0:150]}..."
                f"{next_line}**Division Result:** {'Passed' if did_pass else 'Not passed'} by a division of "
                f"{division.get_aye_count() if did_pass else division.get_no_count()} {'Ayes' if did_pass else 'Notes'}"
                f" to {division.get_no_count() if did_pass else division.get_aye_count()} "
                f"{'Noes' if did_pass else 'Ayes'}{next_line}**Division Date:** "
                f"{division.get_division_date().strftime('%Y-%m-%d %H:%M:%S')}"
            )

        embed = await embed_maker.message(
            ctx,
            description=next_line.join(bits),
            author={"name": "UKParliament Division"},
            footer={"text": f"Page  {page}/{max_pages}"},
        )
        return (embed, max_pages)

    @staticmethod
    async def construct_divisions_commons_embed(
        ctx: commands.Context,
        divisions: list[CommonsDivision],
        page_limit: int,
        *,
        page: int,
    ):
        max_pages = math.ceil(len(divisions) / page_limit)
        next_line = "\n"
        bits = []
        for i, division in enumerate(
            divisions[page_limit * (page - 1) : page_limit * page]
        ):
            did_pass = division.get_aye_count() > division.get_no_count()
            bits.append(
                f"**{(page_limit * (page -1)) + i + 1}. [{division.get_division_title()[0:100]}]"
                f"(https://votes.parliament.uk/Votes/Commons/Division/{division.get_id()})**{next_line}"
                f"**ID:** {division.get_id()}{next_line}**Division Result:** {'Passed' if did_pass else 'Not passed'}"
                f" by a division of {division.get_aye_count() if did_pass else division.get_no_count()} "
                f"{'Ayes' if did_pass else 'Notes'} to "
                f"{division.get_no_count() if did_pass else division.get_aye_count()} {'Noes' if did_pass else 'Ayes'}"
                f"{next_line}**Division Date:** {division.get_division_date().strftime('%Y-%m-%d %H:%M:%S')}"
            )

        embed: embeds.Embed = await embed_maker.message(
            ctx,
            description=next_line.join(bits),
            author={"name": "UKParliament Division"},
            footer={"text": f"Page {page}/{max_pages}"},
        )  # type: ignore
        return embed, max_pages

    @commands.group(
        help="To access the commands interfacing the UK Parliament Site.",
        invoke_without_command=True,
        usage="uk [sub command]",
        examples=["uk divisions linfo 1234", "uk mpelection Boris Johnson"],
        Mod=cls.Help(
            help="To access the commands inferfacing with the UK Parliament Site. And to access commands relevant to"
            " the configuration of this feature",
            usage="uk [sub command]",
            examples=["uk mod tracker channels"],
            sub_commands=["bills", "divisions", "minfo", "mpelection", "mod"],
        ),
        cls=cls.Group,
        module_dependency=["ukparl_module"],
    )
    async def uk(self, ctx: commands.Context):
        return await embed_maker.command_error(ctx)

    @uk.group(
        help="For commands relating to bills",
        invoke_without_command=True,
        usage="uk bills [sub command]",
        examples=["uk bills search European Withdrawal"],
        cls=cls.Group,
        module_dependency=["ukparl_module"],
    )
    async def bills(self, ctx: commands.Context):
        return await embed_maker.command_error(ctx)

    @uk.group(
        name="divisions",
        help="For commands relating to divisions",
        invoke_without_command=True,
        usage="uk divisions [sub command]",
        examples=["uk divisions lsearch [args]"],
        cls=cls.Group,
        module_dependency=["ukparl_module"],
    )
    async def divisions(self, ctx: commands.Context):
        return await embed_maker.command_error(ctx)

    @uk.group(
        name="mod",
        invoke_without_command=True,
        help="Moderator level commands for this feature",
        usage="uk mod [sub command]",
        examples=["uk mod tracker [args]"],
        cls=cls.Group,
        module_dependency=["ukparl_module"],
    )
    async def mod_commands(self, ctx: commands.Context):
        return await embed_maker.command_error(ctx)

    @mod_commands.group(
        name="tracker",
        invoke_without_command=True,
        help="Commands related to the trackering section of this feature",
        usage="uk mod tracker [sub command]",
        examples=["uk mod tracker channels"],
        cls=cls.Group,
        module_dependency=["ukparl_module"],
    )
    async def mod_cmd_tracker(self, ctx: commands.Context):
        return await embed_maker.command_error(ctx)

    @mod_commands.command(
        name="ping",
        help="Pings an endpoint on the REST api and returns the latency between the bot and a REST request.",
        usage="uk mod ping",
        examples=["uk mod ping"],
        cls=cls.Command,
        module_dependency=["ukparl_module"],
    )
    async def mod_cmd_ping(self, ctx: commands.Context):
        if self.loaded is False:
            return

        start = datetime.now()

        async with self.ukparl_module.get_aiohttp_session().get(
            f"{URL_BILLS}/BillTypes"
        ) as resp:
            if resp.status != 200:
                return await embed_maker.message(
                    ctx=ctx,
                    description=f"Couldn't get ping, status: {resp.status}",
                    send=True,
                )
            end = datetime.now()
            difference = end - start
            await embed_maker.message(
                ctx=ctx, description=f"{difference.microseconds / 1000} ms", send=True
            )

    @mod_cmd_tracker.command(
        name="dbclear",
        help=(
            "Clear all recorded entries from the two MongoDB collectioned used by the tracker."
            "Doing this will produce from the bot duplicate tracker announcement from the last few days."
        ),
        usage="uk mod tracker dbclear",
        examples=["uk mod tracker dbclear", "uk mod tracker dbclear [auth code]"],
        cls=cls.Command,
        module_dependency=["ukparl_module"],
    )
    async def mod_cmd_tracker_db_clear(self, ctx: commands.Context, code: str = ""):
        if self.loaded is False:
            return

        confirm_manager = self.ukparl_module.confirm_manager

        if confirm_manager.has_code(ctx.author):
            if code == "":
                return await embed_maker.message(
                    ctx,
                    description="Confirm code required to execute this command successfully.",
                    send=True,
                )
            if confirm_manager.confirm_code(ctx.author, code):
                database.get_connection().clear_bills_tracker_collection()
                database.get_connection().clear_divisions_tracker_collection()
                return await embed_maker.message(
                    ctx,
                    description="Cleared bills_tracker and division_tracker collections.",
                    send=True,
                )
            else:
                return await embed_maker.message(
                    ctx, description="Confirm code incorrect.", send=True
                )
        code = confirm_manager.gen_code(ctx.author)
        await embed_maker.message(
            ctx,
            description="Sending confirmation to delete contents of 'bills_tracker' and 'divisions_tracker'.",
            send=True,
        )
        await ctx.author.send(f"Code to confirm clear Mongo Collections: {code}")

    @mod_cmd_tracker.command(
        name="dbstats",
        help="At the moment this only displays the amount of documents in both bills_tracker and divisions_tracker collections",
        usage="uk mod tracker dbstats",
        clearence="dev",
        cls=cls.Command,
        module_dependency=["ukparl_module"],
    )
    async def mod_cmd_tracker_db_stats(self, ctx: commands.Context):
        if self.loaded is False:
            return
        next_line = "\n"
        await embed_maker.message(
            ctx,
            description=(
                f"**Collection Count**{next_line}- bills_tracker:"
                f" {database.get_connection().get_bills_tracker_count()}{next_line}- divisions_tracker:"
                f" {database.get_connection().get_divisions_tracker_count()}"
            ),
            send=True,
        )

    @mod_cmd_tracker.command(
        name="statuses",
        help="Show the status of each tracker",
        usage="uk mod tracker statuses",
        examples=["uk mod tracker statuses"],
        cls=cls.Command,
        module_dependency=["ukparl_module"],
    )
    async def mod_cmd_tracker_statuses(self, ctx: commands.Context):
        if self.loaded is False:
            return  # type: ignore
        next_line = "\n"
        statuses = self.bot.ukparl_module.tracker_status
        bits = []

        for key in statuses.keys():
            entry = statuses[key]
            if key == "loop":
                bits.append(
                    f"**Loop Status**: {'Enabled' if entry is True else 'Disabled'}"
                )
                continue

            bits.append(
                f"{next_line}**{key}**:{next_line}  - **Started:** {'Yes' if entry['started'] else 'No'}{next_line}  - "
                f"**Confirmed:** {'Yes' if entry['confirmed'] else 'No'}"
            )

        return await embed_maker.message(
            ctx,
            description=f"**Status for each Tracker**{next_line}{next_line.join(bits)}",
            send=True,
        )

    @mod_cmd_tracker.group(
        name="channels",
        invoke_without_command=True,
        usage="uk mod tracker channels [args]",
        examples=["uk mod tracker channels", "uk mod tracker channels set [args]"],
        cls=cls.Group,
        module_dependency=["ukparl_module"],
    )
    async def mod_cmd_tracker_channels(self, ctx: commands.Context):
        if self.loaded is False:
            return  # type: ignore
        bits = []

        channels = self.ukparl_module.config.get_channel_ids()

        for key in channels.keys():
            channel_id = channels[key]
            guild = self.ukparl_module.get_guild()
            if guild is not None:
                channel = guild.get_channel(int(channel_id))
                bits.append(
                    f"- {key}:" f" Couldn't find channel ({channel_id})"
                    if channel is None
                    else f"- {key}: {channel.name}"
                )
            else:
                bits.append("Couldn't fetch guild.")

        next_line = "\n"
        await embed_maker.message(
            ctx, description=f"**Channels**{next_line}{next_line.join(bits)}", send=True
        )

    @mod_cmd_tracker.group(
        name="loop",
        invoke_without_command=True,
        help="Commands to start and stop the event loop checking the various rss feeds",
        usage="uk mod tracker loop",
        examples=["uk mod tracker loop start", "uk mod tracker loop stop"],
        cls=cls.Group,
        module_dependency=["ukparl_module"],
    )
    async def mod_cmd_tracker_eventloop(self, ctx: commands.Context):
        if self.loaded is False:
            return
        return await embed_maker.message(
            ctx,
            description=(
                "The event loop is currently "
                f"{'running' if self.bot.ukparl_module.tracker_event_loop.is_running() else 'not running'}."
            ),
            send=True,
        )

    @mod_cmd_tracker_eventloop.command(
        name="start",
        help="Start the event loop.",
        usage="uk mod tracker loop start",
        examples=["uk mod tracker loop start"],
        cls=cls.Command,
        module_dependency=["ukparl_module"],
    )
    async def mod_cmd_tracker_eventloop_start(self, ctx: commands.Context):
        if self.loaded is False:
            return  # type: ignore
        tracker_statuses = self.bot.ukparl_module.tracker_status
        config = self.bot.ukparl_module.config

        if (
            config.get_channel_id("feed") == 0
            and tracker_statuses["feed"]["started"] is True
        ):
            return await embed_maker.message(
                ctx,
                description="A listener registered to the 'feed' tracker doesn't have a channel to output to.",
                send=True,
            )

        if self.bot.ukparl_module.tracker_event_loop.is_running() is False:
            self.bot.ukparl_module.tracker_event_loop.start()
            self.bot.ukparl_module.tracker_status["loop"] = True
            await embed_maker.message(ctx, description="Started event loop.", send=True)
        else:
            await embed_maker.message(
                ctx, description="Event loop is already running.", send=True
            )

    @mod_cmd_tracker_eventloop.command(
        name="stop",
        help="Stop the event loop",
        usage="uk mod tracker loop stop",
        examples=["uk mod tracker loop stop"],
        cls=cls.Command,
        module_dependency=["ukparl_module"],
    )
    async def mod_cmd_tracker_eventloop_stop(self, ctx: commands.Context):
        if self.loaded is False:
            return  # type: ignore
        if self.bot.ukparl_module.tracker_event_loop.is_running() is True:
            self.bot.ukparl_module.tracker_event_loop.stop()
            await embed_maker.message(ctx, description="Stopped event loop.", send=True)
            self.ukparl_module.tracker_status["loop"] = False
        else:
            await embed_maker.message(
                ctx, description="Event loop is already not running.", send=True
            )

    @mod_cmd_tracker_channels.command(
        name="set",
        help="Set a channel to one of the four trackers",
        usage="uk mod tracker channels set [tracker_id] [channel_id or mention]",
        examples=["uk mod tracker channelts set royalassent #royal-assent"],
        cls=cls.Command,
        module_dependency=["ukparl_module"],
    )
    async def mod_cmd_tracker_channels_set(
        self,
        ctx: commands.Context,
        tracker_id: str = "",
        channel: TextChannelConverter = None,
    ):
        if self.loaded is False:
            return  # type: ignore

        if tracker_id == "":
            return await embed_maker.command_error(ctx, "tracker_id")

        if channel == "":
            return await embed_maker.command_error(ctx, "channel_id/mention")

        config = self.bot.ukparl_module.config
        channels = config.get_channel_ids()

        if tracker_id.lower() not in channels.keys():
            next_line = "\n"
            return await embed_maker.message(
                ctx,
                description=f"**Valid tracker ids:**{next_line} - {(next_line + ' - ').join(channels.keys)}",
                send=True,
            )

        config.set_channel(tracker_id, channel.id)
        await embed_maker.message(
            ctx, description=f"Set {tracker_id} to channel {channel.name}", send=True
        )

    @uk.command(
        name="mpelection",
        help="View latest election results of an MP by name or constituency name",
        clearence="User",
        usage="uk mpelection [mp name] or uk mpelection <argument identifier> [borough name]",
        examples=[
            "uk mpelection Boris Johnson",
            "uk mpelection --borough Belfast South --nonvoters",
        ],
        cls=cls.Command,
        command_args=[
            (("--borough", "-bo", str), "Name of a borough"),
            (("--nonvoters", "-nv", bool), "Include non-voters in the charts"),
            (
                ("--table", "-t", bool),
                "Whether or not the chart should be a pie or a table",
            ),
            (
                ("--name", "-n", str),
                "The name of the MP (used only if you're using the other arguments",
            ),
            (("--historical", "-h", str), "Get list of recorded election results"),
        ],
        module_dependency=["ukparl_module"],
    )
    async def mp_elections(
        self, ctx: commands.Context, *, args: Union[ParseArgs, str] = ""
    ):
        if self.loaded is False:
            return
        member = None
        if args == "":
            return await embed_maker.command_error(ctx)
        name_arg = args["pre"] if args["pre"] != "" else args["name"]
        if name_arg != "" and name_arg is not None:
            for m in self.parliament.get_commons_members():
                name = m.get_titled_name()
                if name is None:
                    name = m.get_addressed_name()
                if name is None:
                    name = m.get_display_name()

                if name_arg.lower() in name.lower():
                    member = m
                    break

        elif args["borough"] != "" and args["borough"] is not None:
            for m in self.parliament.get_commons_members():
                if args["borough"].lower() in m.get_membership_from().lower():
                    member = m
                    break

        if member is None:
            return await embed_maker.message(
                ctx,
                description=f"Couldn't find latest elections results for"
                f" {'Borough' if args['borough'] != '' and args['borough'] is not None else 'MP'}"
                f" {args['borough'] if args['borough'] != '' and args['borough'] is not None else (args['pre'] if args['pre'] != '' else args['name'])}",
                send=True,
            )

        next_line = "\n"
        results = await self.parliament.get_election_results(member)
        result = results[0]
        if args["historical"] is not None:
            found_result = False

            if args["historical"] != "":
                for h_result in results:
                    if (
                        h_result.get_election_date().strftime("%Y")
                        == args["historical"]
                    ):
                        result = h_result
                        found_result = True

            if found_result is False:
                historical_bits = [
                    f"- {er.get_election_date().strftime('%Y')}" for er in results
                ]

                return await embed_maker.message(
                    ctx,
                    title=f"Recorded Election Results of the Borough {member.get_membership_from()}",
                    description=f"**Elections:** {next_line}{next_line.join(historical_bits)}",
                    send=True,
                )

        others_formatted = []
        the_rest_formatted = []

        for candidate in result.get_candidates():
            if candidate["votes"] > 1000:
                the_rest_formatted.append(
                    f"- {candidate['name']}: {candidate['party_name']}"
                )
            else:
                others_formatted.append(
                    f"- {candidate['name']}: {candidate['party_name']}"
                )

        embed = embeds.Embed = await embed_maker.message(
            ctx,
            title=f'{result.get_election_date().strftime("%Y")} Election Results of {member.get_membership_from()}',
            description=f"**Electorate Size:** {result.get_electorate_size():,}{next_line}"
            f"**Turnout:** {result.get_turnout():,}{next_line}**Main Candidates:**{next_line}"
            f"{next_line.join(the_rest_formatted)}{next_line}**Other Candidates (Under 1k):"
            f"**{next_line}{next_line.join(others_formatted)}"
            if len(others_formatted) > 0
            else "",
        )
        if result is not None:
            image_file = await self.ukparl_module.generate_election_graphic(
                result, args["nonvoters"] is not None, args["table"] is not None
            )
            embed.set_image(url="attachment://electionimage.png")  # type: ignore
            await ctx.send(
                file=image_file,
                embed=embed,
            )
        else:
            await ctx.send(embed=embed)

    @uk.command(
        name="minfo",
        help="Get information on a currently serving MP or Lord",
        usage="uk minfo [mp name / lord name]",
        examples=[
            "uk minfo Boris Johnson",
            "uk minfo Duke of Norfolk",
            "uk minfo -n Lord Sugar -p",
        ],
        command_args=[
            (("--borough", "-b", str), "Get mp info by borough name"),
            (("--portrait", "-p", bool), "Fetch the portrait of the member"),
            (
                ("--name", "-n", str),
                "The name of the mp (used only if you're using the other args",
            ),
        ],
        cls=cls.Command,
        module_dependency=["ukparl_module"],
    )
    async def member_info(
        self, ctx: commands.Context, *, args: Union[ParseArgs, str] = ""
    ):
        if self.loaded is False:
            return  # type: ignore
        if args == "":
            return await embed_maker.command_error(ctx)

        member = None
        members = self.parliament.get_commons_members()
        members.extend(self.parliament.get_lords_members())

        arg_name = args["pre"] if args["pre"] != "" else args["name"]
        if arg_name is not None:
            for m in members:
                name = m.get_titled_name()
                if name is None:
                    name = m.get_addressed_name()
                if name is None:
                    name = m.get_display_name()
                if arg_name.lower() in name.lower():
                    member = m
        else:
            if args["borough"] is not None:
                members = list(
                    filter(
                        lambda m: m.get_membership_from().lower()
                        == args["borough"].lower(),
                        self.parliament.get_commons_members(),
                    )
                )
                if len(members) != 0:
                    member = members[0]

        if member is None:
            await embed_maker.message(
                ctx,
                description="Couldn't find " + arg_name
                if args["pre"] is not None or args["name"] is not None
                else "of borough" + args["borough"] + ".",
                send=True,
            )
            return

        biography = await self.parliament.get_biography(member)
        next_line = "\n"

        representing_bits = []

        for rep in biography.get_representations():
            representing_bits.append(
                (
                    f"- MP for {rep['constituency_name']} from {rep['started'].strftime('%Y-%m-%d')}"
                    f"{' to ' if rep['ended'] is not None else ''}"
                    f"{rep['ended'].strftime('%Y-%m-%d') if rep['ended'] is not None else ''}"
                )
            )

        gov_posts_bits = []

        for post in biography.get_government_posts():
            gov_posts_bits.append(
                (
                    f"- {post['office']} from {post['started'].strftime('%Y-%m-%d')}"
                    f"{' to ' if post['ended'] is not None else ''}"
                    f"{post['ended'].strftime('%Y-%m-%d') if post['ended'] is not None else ''}"
                )
            )

        opp_posts_bits = []

        for post in biography.get_oppositions_posts():
            opp_posts_bits.append(
                (
                    f" - {post['office']} from {post['started'].strftime('%Y-%m-%d')}"
                    f"{' to ' if post['ended'] is not None else ''}"
                    f"{post['ended'].strftime('%Y-%m-%d') if post['ended'] is not None else ''}"
                )
            )

        other_posts_bits = []

        for post in biography.get_other_posts():
            other_posts_bits.append(
                (
                    f" - {post['office']} from {post['started'].strftime('%Y-%m-%d')}"
                    f"{' to ' if post['ended'] is not None else ''}"
                    f"{post['ended'].strftime('%Y-%m-%d') if post['ended'] is not None else ''}"
                )
            )

        cmte_bits = []

        for membership in biography.get_committee_memberships():
            cmte_bits.append(
                (
                    f"- Member of {membership['committee']} from {membership['started'].strftime('%Y-%m-%d')}"
                    f"{' to ' if membership['ended'] is not None else ''}"
                    f"{membership['ended'].strftime('%Y-%m-%d') if membership['ended'] is not None else ''}"
                )
            )

        d = (
            f"**Name:** {member.get_display_name()}{next_line}**"
            f"{'Representing:' if member.get_house() == 1 else 'Peer Type'}** {member.get_membership_from()}"
            f"{next_line}**Gender:** {'Male' if member.get_gender() == 'M' else 'Female'}"
            + (
                f"{next_line}**Represented/Representing:**{next_line}{next_line.join(representing_bits)}"
                if len(representing_bits) > 0
                else ""
            )
            + (
                f"{next_line}**Government Posts**{next_line}{next_line.join(gov_posts_bits)}"
                if len(gov_posts_bits) > 0
                else ""
            )
            + (
                f"{next_line}**Opposition Posts:**{next_line}{next_line.join(opp_posts_bits)}"
                if len(opp_posts_bits) > 0
                else ""
            )
            + (
                f"{next_line}**Other Posts:**{next_line}{next_line.join(other_posts_bits)}"
                if len(other_posts_bits) > 0
                else ""
            )
            + (
                f"{next_line}**Committee Posts:**{next_line}{next_line.join(cmte_bits)}"
                if len(cmte_bits) > 0
                else ""
            )
        )

        embed: embeds.Embed = await embed_maker.message(ctx, description=d)  # type: ignore

        if args["portrait"] is not None:
            url = (
                member.get_thumbnail_url().replace("Thumbnail", "Portrait")
                + "?cropType=FullSize&webVersion=false"
            )
            portrait_image = await self.ukparl_module.get_mp_portrait(url)
            if portrait_image is not None:
                embed.set_image(url=f"attachment://portrait.jpeg")
                await ctx.send(file=portrait_image, embed=embed)
        else:
            await ctx.send(embed=embed)

    @divisions.command(
        name="linfo",
        help="Get House of Lords Division information",
        usage="uk divisions linfo [division id]",
        examples=["uk divisions linfo 1234"],
        cls=cls.Command,
        module_dependency=["ukparl_module"],
    )
    async def division_lord_info(self, ctx: commands.Context, division_id: int = -1):
        if self.loaded is False:
            return  # type: ignore

        if division_id == -1:
            await embed_maker.command_error(ctx, "division_id")
            return

        division = await self.parliament.get_lords_division(division_id)
        if division is None:
            await embed_maker.message(
                ctx,
                description=f"Couldn't find division under id {division_id}",
                send=True,
            )

        division_image = await self.ukparl_module.generate_division_image(
            self.parliament, division
        )
        next_line = "\n"
        did_pass = division.get_aye_count() > division.get_no_count()
        embed: embeds.Embed = await embed_maker.message(
            ctx,
            description=f"**Title:** {division.get_division_title()}{next_line}"
            f"**Division Outcome:** {'Passed' if did_pass else 'Not passed'} by a division of "
            f"{division.get_aye_count() if did_pass else division.get_no_count()} {'Ayes' if did_pass else 'Noes'}"
            f" to {division.get_no_count() if did_pass else division.get_aye_count()} {'Noes' if did_pass else 'Ayes'}"
            f"{next_line}**Division Date:** {division.get_division_date().strftime('%Y-%m-%d %H:%M:%S')}{next_line}"
            f"**Summary:** {division.get_amendment_motion_notes()[0:250]}",
        )  # type: ignore
        embed.set_image(url="attachment://divisionimage.png")
        await ctx.send(file=division_image, embed=embed)

    @divisions.command(
        name="cinfo",
        help="Get House of Commons Division information",
        usage="uk divisions cinfo [division id]",
        examples=["uk divisions cinfo 1234"],
        cls=cls.Command,
        module_dependency=["ukparl_module"],
    )
    async def division_common_info(self, ctx: commands.Context, division_id: int):
        if self.loaded is False:
            return  # type: ignore
        division = await self.parliament.get_commons_division(division_id)
        if division is None:
            await embed_maker.message(
                ctx,
                description=f"Couldn't find division under id {division_id}",
                send=True,
            )

        image_file = await self.ukparl_module.generate_division_image(
            self.parliament, division
        )
        next_line = "\n"
        did_pass = division.get_aye_count() > division.get_no_count()
        embed: embeds.Embed = await embed_maker.message(
            ctx,
            description=f"**Title:** {division.get_division_title()}{next_line}**Division Outcome:**"
            f" {'Passed' if did_pass else 'Not passed'} by a division of "
            f"{division.get_aye_count() if did_pass else division.get_no_count()} {'Ayes' if did_pass else 'Noes'} "
            f"to {division.get_no_count() if did_pass else division.get_aye_count()} {'Noes' if did_pass else 'Ayes'}"
            f"{next_line}**Division Date:** {division.get_division_date().strftime('%Y-%m-%d %H:%M:%S')}",
        )  # type: ignore

        embed.set_image(url=f"attachment://{image_file.filename}")
        await ctx.send(file=image_file, embed=embed)

    @divisions.command(
        name="csearch",
        help="Search for commons divisions",
        usage="uk divisions csearch [search term]",
        examples=["uk divisions csearch European"],
        cls=cls.Command,
        module_dependency=["reaction_menus"],
    )
    async def division_commons_search(self, ctx: commands.Context, *, search_term=""):
        if self.loaded is False:
            return  # type: ignore
        divisions = await self.parliament.search_for_commons_divisions(
            search_term, result_limit=30
        )
        if len(divisions) == 0:
            await embed_maker.message(
                ctx,
                description=f"Couldn't find any Commons divisions under search term '{search_term}'.",
                send=True,
            )

        page_constructor = functools.partial(
            self.construct_divisions_commons_embed,
            ctx=ctx,
            divisions=divisions,
            page_limit=5,
        )
        pair = await page_constructor(page=1)
        message = await ctx.send(embed=pair[0])

        async def temp_page_constructor(page: int):
            pair = await page_constructor(page=page)
            return pair[0]

        menu = BookMenu(
            message=message,
            author=ctx.author,  # type: ignore
            max_page_num=pair[1],
            page_constructor=temp_page_constructor,
            page=1,
        )
        self.bot.reaction_menus.add(menu)

    @divisions.command(
        name="lsearch",
        help="Search for lords divisions",
        usage="uk divisions lsearch [search term]",
        examples=["uk divisions lsearch European"],
        cls=cls.Command,
        module_dependency=["ukparl_module"],
    )
    async def division_lords_search(self, ctx: commands.Context, *, search_term=""):
        if self.loaded is False:
            return  # type: ignore
        divisions = await self.parliament.search_for_lords_divisions(
            search_term, result_limit=30
        )

        if len(divisions) == 0:
            await embed_maker.message(
                ctx,
                description=f"Couldn't find any Lords divisions under the search term '{search_term}'.",
                send=True,
            )
            return

        page_constructor = functools.partial(
            self.construct_divisions_lords_embed,
            ctx=ctx,
            divisions=divisions,
            page_limit=5,
        )
        pair = await page_constructor(page=1)
        embed = pair[0]
        max_pages = pair[1]

        async def temp_page_constructor(page: int):
            pair = await page_constructor(page=page)
            return pair[0]

        message = await ctx.send(embed=embed)
        menu = BookMenu(
            message=message,
            author=ctx.author,  # type: ignore
            max_page_num=max_pages,
            page_constructor=temp_page_constructor,
            page=1,
        )
        self.bot.reaction_menus.add(menu)

    @bills.command(
        name="info",
        help="To display in more detail information about a bill.",
        usage="uk bills info [bill id]",
        examples=["uk bills info 1234"],
        cls=cls.Command,
        module_dependency=["reaction_menus", "ukparl_module"],
    )
    async def bill_info(self, ctx: commands.Context, bill_id: int):
        if self.loaded is False:
            return  # type: ignore
        try:
            bill = await self.parliament.get_bill(bill_id)
            c_divisions = await self.parliament.search_for_commons_divisions(
                bill.get_title()
            )
            l_divisions = await self.parliament.search_for_lords_divisions(
                bill.get_title()
            )
            page_constructor = functools.partial(
                self.construct_bill_info_embed,
                ctx=ctx,
                bill=bill,
                l_divisions=l_divisions,
                c_divisions=c_divisions,
                page_limit=10,
            )
            pair: tuple[embeds.Embed, int] = await page_constructor(page=1)
            message = await ctx.send(embed=pair[0])

            async def temp_page_constructor(
                page: int,
            ):  # Due to the unique nature of ther result, this is needed ot return only the embed.
                pair = await page_constructor(page=page)
                return pair[0]

            menu = BookMenu(
                message,
                author=ctx.author,  # type: ignore
                page=1,
                max_page_num=pair[1],
                page_constructor=temp_page_constructor,
            )
            self.bot.reaction_menus.add(menu)

        except Exception as ignore:
            await embed_maker.message(
                ctx, description=f"Couldn't fetch bill {bill_id}.", send=True
            )
            raise ignore

    @bills.command(
        help="Seach for bills using certain values and search terms",
        usage="uk bills search [search terms]",
        examples=[
            "uk bills search European Withdrawal",
            "uk bills search --query Finance Bill --currenthouse Lords",
            "uk bills search --sponsor Rishu Sunak",
        ],
        name="search",
        command_args=[
            (("--query", "-q", str), "Search Term to search for"),
            (("--sponsor", "-s", str), "The name of the bill sponsor"),
            (("--types", None, "-t"), "The types of bill to search for"),
            (("--order", None, "-o"), "The order to display the searches in"),
            (("--currenthouse", "-ch", str), "The house the bill is currently in"),
            (("--originatinghouse", "-oh", str), "The house the bill originated in"),
        ],
        cls=cls.Command,
        module_dependency=["reaction_menus", "ukparl_module"],
    )
    async def bills_search(
        self, ctx: commands.Context, *, args: Union[ParseArgs, str] = ""
    ):
        if self.loaded is False:
            return  # type: ignore

        if args == "":
            return await embed_maker.command_error(ctx)
        builder = SearchBillsBuilder.builder()

        if args is None:
            return

        if args["pre"] is not None:
            builder.set_search_term(args["pre"])
        else:
            if args["query"] is not None:
                builder.set_search_term(args["query"])
            if args["sponsor"] is not None:
                member = self.parliament.get_member_by_name(args["sponsor"])
                if member is None:
                    await embed_maker.message(
                        ctx,
                        description=f"Couldn't find member {args['sponsor']}",
                        send=True,
                    )
                builder.set_member_id(member.get_id())
            if args["types"] is not None:
                split_types = args["types"].split(" ")
                types = self.parliament.get_bill_types()
                arg_types = []
                for t_type in split_types:
                    for b_type in types:
                        if b_type.get_name().lower() == t_type.lower():
                            arg_types.append(b_type)
                builder.set_bill_type(arg_types)
            if args["order"] is not None:
                formatted_acceptable_args = list(
                    map(lambda order: order.name.lower(), SearchBillsSortOrder)
                )
                next_line = "\n"
                await embed_maker.message(
                    ctx,
                    description=f"Couldn't find order type {args['order']}. Acceptable arguments: {next_line}"
                    f"{next_line.join(formatted_acceptable_args)}",
                    send=True,
                )
            if args["currenthouse"] is not None:
                if args["currenthouse"].lower() not in [
                    "all",
                    "commons",
                    "lords",
                    "unassigned",
                ]:
                    await embed_maker.message(
                        ctx,
                        description="Incorrect house value. "
                        "Accepted arguments: 'all', 'commons', 'lords', 'unassigned'",
                        send=True,
                    )
                    return
                builder.set_current_house(args["currenthouse"])
            if args["originatinghouse"] is not None:
                if args["originatinghouse"] not in [
                    "all",
                    "commons",
                    "lords",
                    "unassigned",
                ]:
                    await embed_maker.message(
                        ctx,
                        description="Incorrect house value. "
                        "Accepted arguments: 'all', 'commons', 'lords', 'unassigned'",
                        send=True,
                    )
                    return
                builder.set_originating_house(args["originatinghouse"])

        bills = await self.parliament.search_bills(
            builder.set_sort_order(SearchBillsSortOrder.DATE_UPDATED_DESENDING).build()
        )
        next_line = "\n"

        max_page_size = 4
        max_page_num = math.ceil(len(bills) / max_page_size)
        if max_page_num == 0:
            max_page_num = 1
        page_constructor = functools.partial(
            self.construct_bills_search_embed,
            ctx=ctx,
            bills=bills,
            max_page_num=max_page_num,
            page_limit=max_page_size,
        )

        embed = await page_constructor(page=1)
        message = await ctx.send(embed=embed)
        menu = BookMenu(
            message,
            author=ctx.author,  # type: ignore
            page=1,
            max_page_num=max_page_num,
            page_constructor=page_constructor,
        )
        self.bot.reaction_menus.add(menu)


def setup(bot: TLDR):
    bot.add_cog(UK(bot))
