import functools
import math
import re
from datetime import datetime, timedelta
from typing import Union

import modules.commands as commands
from bot import TLDR
from bson import json_util
from discord import Invite, Member, NotFound
from discord.embeds import Embed
from discord.ext.commands import Cog, Context, group
from discord.file import File
from discord.guild import Guild
from modules import embed_maker
from modules.captcha_verification import GatewayGuild
from modules.commands import Command, Group
from modules.reaction_menus import BookMenu
from modules.utils import ParseArgs, get_member_from_string


class Captcha(Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot

    async def construct_blacklist_embed(
        self,
        ctx: Context,
        blacklist: list,
        max_page_num: int,
        page_limit: int,
        *,
        page: int,
    ):
        if len(blacklist) == 0:
            return await embed_maker.message(
                ctx, description="No blacklist entries found."
            )

        bits = []

        for i, entry in enumerate(
            blacklist[page_limit * (page - 1) : page_limit * page]
        ):
            mid = entry["mid"]
            member_cache_entry = (
                self.bot.captcha.get_data_manager().get_blacklisted_member(mid)
            )
            blacklist_entry = (
                self.bot.captcha.get_data_manager().get_blacklisted_member_info(mid)
            )
            if member_cache_entry is None:
                self.bot.logger.info(f"Failed to find associated name for {mid}.")

            member_name = (
                member_cache_entry["name"] if member_cache_entry is not None else mid
            )
            started = entry["started"]
            ends = entry["ends"]
            formatted_started = datetime.fromtimestamp(started).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            formatted_ends = datetime.fromtimestamp(ends).strftime("%Y-%m-%d %H:%M:%S")
            diff = ends - started

            bits.append(
                "\n".join(
                    [
                        f"- **{member_name}/{mid}**"
                        if member_cache_entry is not None
                        else f"-  **{member_name}**",
                        f"  **Started:** {formatted_started}",
                        f"  **Ends:** {formatted_ends} ({timedelta(seconds=diff)})",
                        f"  **Reason:** {blacklist_entry['reason'] if blacklist_entry is not None else 'No Reason'}",
                    ]
                )
            )

        return await embed_maker.message(
            ctx,
            description="\n".join(bits),
            author={"name": "Captcha Gateway"},
            footer={"text": f"Page {page}/{max_page_num}"},
        )

    @group(
        help="Captcha Gateway System. A method of stopping the bot attacks.",
        name="captcha",
        usage="captcha [sub command]",
        examples=["captcha servers"],
        cls=Group,
        module_dependency=["captcha"],
        invoke_without_command=True,
    )
    async def captcha_cmd(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @captcha_cmd.group(
        help="For commands relating to creating, deleting, or listing servers.",
        name="servers",
        usage="captcha servers [sub command]",
        examples=["captcha servers list"],
        cls=Group,
        invoke_without_command=True,
    )
    async def captcha_servers_cmd(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @captcha_servers_cmd.command(
        help="Lists active gateway servers",
        name="list",
        usage="captcha servers list",
        examples=["captcha servers list"],
        cls=Command,
    )
    async def list_servers_cmd(self, ctx: Context):
        bits = []

        for g_guild in self.bot.captcha.get_gateway_guilds():
            invite = await g_guild.get_permantent_invite()
            g_bits = [
                f"- **{g_guild.get_name()}**",
                f"**ID:** {g_guild.get_id()}",
                f"**Link:** {invite.url}",
            ]
            bits.append("\n".join(g_bits))

        await embed_maker.message(
            ctx=ctx,
            title="Active Gateway Guilds",
            description="\n".join(bits) if len(bits) > 0 else "No Active Guilds.",
            send=True,
        )

    @captcha_cmd.command(
        help="A set of commands used to manage invitations that should not be tracked by the Tracker Manager. A Manager written to detect potential bot attacks from unregistered invitations and delete said invitations.",
        name="invite",
        examples=["captcha invite register"],
        usage="captcha invite [sub command]",
        cls=Group,
        invoke_without_command=True,
    )
    async def invite_cmd(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    async def construct_invite_list_embed(
        self,
        ctx: Context,
        r_invites: list,
        max_page_num: int,
        page_limit: int,
        *,
        page: int,
    ):
        if len(r_invites) == 0:
            return await embed_maker.message(
                ctx, description="No user registered invites."
            )

        bits = []
        for i, entry in enumerate(
            r_invites[page_limit * (page - 1) : page_limit * page]
        ):
            bits.append(f"{i + 1}. https://discord.gg/{entry}")

        return await embed_maker.message(
            ctx,
            description="\n".join(bits),
            author={"name": "Captcha Gateway"},
            footer={"text": f"Page {page}/{max_page_num}"},
        )

    @invite_cmd.command(
        help="Lists all user registered invitations",
        name="list",
        exmaples=["captcha invite list"],
        usage="captcha invite list",
        cls=Command,
    )
    async def list_invite_cmd(self, ctx: Context):
        max_page_size = 10
        r_invites = list(
            map(
                lambda e: e["code"],
                self.bot.captcha.get_data_manager().get_all_registered_invites(2),
            )
        )

        max_page_num = math.ceil(len(r_invites) / max_page_size)
        page_constructor = functools.partial(
            self.construct_invite_list_embed,
            ctx=ctx,
            r_invites=r_invites,
            max_page_num=max_page_num,
            page_limit=max_page_size,
        )

        embed = await page_constructor(page=1)
        message = await ctx.send(embed=embed)
        menu = BookMenu(
            message,
            page=1,
            max_page_num=max_page_num,
            page_constructor=page_constructor,
            author=ctx.author,
        )
        self.bot.reaction_menus.add(menu)

    @invite_cmd.command(
        help="Registers invitations with the Captcha Gateway Feature. Any invitations registered would not be tracked by the Tracker Manager. This manager tracks all unregistered invitations for potential bot attacks then deletes said invite after detecting an attack.",
        name="register",
        examples=["captcha invite register [invite url]"],
        usage="captcha invite register [invite url]",
        cls=Command,
    )
    async def register_invite_cmd(self, ctx: Context, invite_url: str = ""):
        if invite_url == "":
            return await embed_maker.command_error(ctx)

        data_manager = self.bot.captcha.get_data_manager()

        try:
            invite: Union[Invite, None] = await self.bot.fetch_invite(invite_url)
            if data_manager.is_registered_invitation(invite.id):
                return await embed_maker.message(
                    ctx,
                    description=f"Already registered invitation supplied.",
                    title="Already Registered.",
                    send=True,
                )
            else:
                data_manager.add_registered_invitation(invite.id, 2)
                return await embed_maker.message(
                    ctx,
                    description=f"Added invitation to the registered invitations collection.",
                    title="Registered invite.",
                    send=True,
                )
        except NotFound:
            return await embed_maker.message(
                ctx,
                description=f"Couldn't check the validity of invite {invite_url}. The invite has either expired or is invalid.",
                title="Invalid invite link.",
                send=True,
            )

    @captcha_cmd.command(
        help="Get a report on how many successful and unsuccessful captchas happened. The data set is determined by what the interval value is set as.",
        name="report",
        usage="captcha report",
        examples=["captcha report"],
        cls=Command,
    )
    async def report_mod_cmd(self, ctx: Context):
        return await ctx.send(embed=self.bot.captcha.construct_scheduled_report_embed())

    @captcha_cmd.group(
        help="A set of commands used to configure the configurable elements of this feature.",
        name="config",
        usage="captcha config [sub command]",
        examples=["captcha config set landing_channel.name welcome"],
        cls=Group,
        invoke_without_command=True,
    )
    async def config_mod_cmd(self, ctx: Context):
        config_copy = self.bot.captcha.get_settings().copy()
        # config_copy["modules"]["captcha"].pop("operators")
        return await embed_maker.message(
            ctx,
            description=f"```{json_util.dumps(config_copy['modules']['captcha'], indent=4)}```",
            title="Captcha Gateway Settings",
            send=True,
        )

    @config_mod_cmd.group(
        help="Set a value of a configuration variable.",
        name="set",
        usage="captcha config set [variable name] [value]",
        examples=["captcha config set landing_channel.name welcome-tldr"],
        cls=Command,
        command_args=[
            (
                ("--path", "-p", str),
                "The path of the setting, with fullspots substituting spaces.",
            ),
            (("--value", "-v", str), "Value to set the setting to."),
        ],
    )
    async def set_config_mod_cmd(
        self, ctx: Context, *, args: Union[ParseArgs, str] = ""
    ):
        if args["pre"] != "":
            split_pre = args["pre"].split(" ")
            args["path"] = split_pre[0]
            args["value"] = " ".join(split_pre[1:])
        else:
            if args["path"] is None:
                return await embed_maker.command_error(ctx, "path")

            if args["value"] is None:
                return await embed_maker.command_error(ctx, "value")

        await self.bot.captcha.set_setting(
            args["path"],
            args["value"] if args["value"].isnumeric() is False else int(args["value"]),
        )

        await embed_maker.message(
            ctx,
            description=f"Set value {args['value']} on setting {args['path']}",
            title="Changed Setting",
            send=True,
        )

    @captcha_cmd.group(
        help="Blacklist - for users who couldn't pass the first set of Captcha tests. These commands allow the viewing, adding, and removing of users on the Blacklist.",
        name="blacklist",
        usage="captcha blacklist [sub-command]",
        examples=[
            "captcha blacklist",
            "captcha blacklist add TheMasteredPanda 24h",
        ],
        cls=Group,
        invoke_without_command=True,
    )
    async def blacklist_mod_cmd(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @blacklist_mod_cmd.command(
        help="List all blacklisted users. Learn their reasons and for how long their blacklist lasts for.",
        name="list",
        usage="captcha blacklist list",
        examples=["captcha blacklist list"],
        cls=Command,
    )
    async def blacklist_list_mod_cmd(self, ctx: Context):
        blacklist = self.bot.captcha.get_data_manager().get_blacklist()
        max_page_size = 6
        max_page_num = math.ceil(len(blacklist) / max_page_size)
        page_constructor = functools.partial(
            self.construct_blacklist_embed,
            ctx=ctx,
            blacklist=blacklist,
            max_page_num=max_page_num,
            page_limit=max_page_size,
        )

        embed = await page_constructor(page=1)
        message = await ctx.send(embed=embed)
        menu = BookMenu(
            message,
            page=1,
            max_page_num=max_page_num,
            page_constructor=page_constructor,
            author=ctx.author,
        )
        self.bot.reaction_menus.add(menu)

    @blacklist_mod_cmd.command(
        help="Reset blacklist counter of member.",
        name="reset",
        usage="reset [Member Name or Member ID]",
        examples=["reset TheMasteredPanda"],
        cls=Command,
    )
    async def blacklist_counter_reset(self, ctx: Context, argument: str = ""):
        if argument == "":
            return await embed_maker.command_error(ctx)

        member = None

    @blacklist_mod_cmd.command(
        help="Add a member to the blacklist.",
        name="add",
        usage="add",
        examples=[
            "captcha blacklist add [name of member] [time (40h20m4s)]",
            "captcha blacklist add TheMasteredPanda 24h",
        ],
        command_args=[
            (("--name", "-n", str), "Name of the user you want to blacklist."),
            (
                ("--duration", "-d", str),
                "The amount of time you want to blacklist this user for ([integer][time unit]. Time Units: s (seconds), m (minutes), h(hours)",
            ),
        ],
        cls=Command,
    )
    async def blacklist_add_cmd(
        self, ctx: Context, *, args: Union[ParseArgs, str] = ""
    ):
        data_manager = self.bot.captcha.get_data_manager()
        split_pre = args["pre"].split(" ")

        if len(split_pre) == 0:
            return await embed_maker.command_error(ctx)

        name_string = args["name"] if args["name"] is not None else split_pre[0]

        blacklisted_members = data_manager.get_blacklisted_members(username=name_string)

        if len(blacklisted_members) > 0:
            return await embed_maker.message(
                ctx,
                description=f"Member {blacklisted_members[0]['name']} is already blacklisted.",
                title="Member already blacklisted.",
                send=True,
            )

        member, rest = get_member_from_string(ctx, args["pre"])
        amount_string = args["duration"]
        if amount_string is None:
            if rest is not None:
                amount_string = rest
            else:
                amount_string = split_pre[1]

        amount_string_bits = re.split("(\\d{1,2}\\w{1})", amount_string)

        duration_in_seconds = 0
        for bit in amount_string_bits:
            if bit.endswith("h"):
                duration_in_seconds = duration_in_seconds + (3600 * int(bit.strip("h")))
            if bit.endswith("m"):
                duration_in_seconds = duration_in_seconds + (60 * int(bit.strip("m")))
            if bit.endswith("s"):
                duration_in_seconds = duration_in_seconds + int(bit.strip("s"))

        data_manager.add_blacklisted_member(member)
        data_manager.add_member_to_blacklist(member.id, duration_in_seconds)
        await embed_maker.message(
            ctx,
            description=f"Blacklisted member {member.display_name} for {' '.join(amount_string_bits)}.",
            title="Blacklisted member.",
            send=True,
        )

    @blacklist_mod_cmd.command(
        help="Remove a member from the blacklist. This will also reset the relog counter of the user.",
        name="remove",
        usage="captcha blacklist remove",
        examples=["captcha blacklist remove [name of member / member id]"],
        cls=Command,
    )
    async def blacklist_rm_cmd(self, ctx: Context, *, argument: str = ""):
        if argument == "":
            return await embed_maker.command_error(ctx)

        data_manager = self.bot.captcha.get_data_manager()
        blacklisted_members = list(
            data_manager.get_blacklisted_members(username=argument)
            if argument.isnumeric() is False
            else data_manager.get_blacklisted_members(member_id=int(argument))
        )

        is_blacklisted = (
            data_manager.is_blacklisted(member_id=int(argument))
            if argument.isnumeric()
            else True
        )

        if len(blacklisted_members) == 0 and is_blacklisted is False:
            return await embed_maker.message(
                ctx,
                description=f"Couldn't find blacklisted member starting with name or id {argument}",
                title="Couldn't find blacklisted member.",
                send=True,
            )

        if len(blacklisted_members) > 1:
            bits = []

            for member in blacklisted_members:
                bits.append(f"- **{member['name']}/{member['mid']}**")

            return await embed_maker.message(
                ctx,
                description=f"Found multiple members starting with name or id {argument}. Please be more specific. Members found: "
                + "\n"
                + "\n".join(bits),
                title="Multiple members found.",
                send=True,
            )

        member_entry = blacklisted_members[0] if len(blacklisted_members) > 0 else None

        member_id = (
            member_entry["mid"] if len(blacklisted_members) > 0 else int(argument)
        )
        await self.bot.captcha.unban(member_id=member_id)
        data_manager.reset_captcha_counter(member_id=member_id)
        data_manager.remove_blacklisted_member(member_id)
        data_manager.remove_member_from_blacklist(member_id)

        await embed_maker.message(
            ctx,
            description=f"Removed {member_entry['name'] if len(blacklisted_members) > 0 else argument} from the blacklist.",
            title="Removed member from blacklist",
            send=True,
        )

    async def construct_dev_blacklist_member_embed(
        self,
        ctx: Context,
        blacklist_list: list,
        max_page_num: int,
        page_limit: int,
        *,
        page: int,
    ):
        if len(blacklist_list) == 0:
            return await embed_maker.message(
                ctx, description="No blacklist entries found."
            )

        bits = []

        for i, entry in enumerate(
            blacklist_list[page_limit * (page - 1) : page_limit * page]
        ):
            bits.append(
                "\n".join(
                    [f"{i + 1}. **{entry['name']}**", f"-- **ID:** {entry['mid']}"]
                )
            )

        return await embed_maker.message(
            ctx,
            description="\n".join(bits),
            author={"name": "Captcha Gatway"},
            footer={"text": f"Page {page}/{max_page_num}"},
        )

    @captcha_cmd.group(
        help="A set of dev commands used when testing this feature.",
        name="dev",
        usage="captcha dev [sub command]",
        examples=["captcha dev create guild"],
        cls=Group,
        invoke_without_command=True,
    )
    async def dev_cmds(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @dev_cmds.group(
        help="A set of dev commands associated to the blacklist cache.",
        name="bc",
        usage="captcha dev blacklist [sub command]",
        examples=["captcha dev blacklist add", "captcha dev blacklist remove"],
        cls=Group,
        invoke_without_command=True,
    )
    async def dev_blacklist_cmd(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @dev_blacklist_cmd.command(
        help="Search for or list all members within the blacklist.",
        name="list",
        usage="captcha dev blacklist list [Username or ID]",
        cls=Command,
        examples=["captcha dev blacklist list TheMa"],
    )
    async def dev_blacklist_list_cmd(self, ctx: Context, argument: str = ""):
        data_manager = self.bot.captcha.get_data_manager()

        blacklisted_members = list(
            (
                (
                    data_manager.get_blacklisted_members(username=argument)
                    if argument.isnumeric() is False
                    else data_manager.get_blacklisted_members(member_id=int(argument))
                )
                if argument != ""
                else data_manager.get_blacklisted_members()
            )
        )

        max_page_size = 5
        max_page_num = math.ceil(len(blacklisted_members) / max_page_size)
        page_constructor = functools.partial(
            self.construct_dev_blacklist_member_embed,
            ctx=ctx,
            blacklist_list=blacklisted_members,
            max_page_num=max_page_num,
            page_limit=max_page_size,
        )
        embed = await page_constructor(page=1)
        message = await ctx.send(embed=embed)
        menu = BookMenu(
            message,
            page=1,
            max_page_num=max_page_num,
            page_constructor=page_constructor,
            author=ctx.author,
        )
        self.bot.reaction_menus.add(menu)

    @dev_blacklist_cmd.command(
        help="Add a member to the blacklist cache",
        name="add",
        usage="captcha dev bc add [Member mention / Username]",
        example=["captcha dev bc add TheMasteredPanda"],
        cls=Command,
    )
    async def dev_blacklist_add_cmd(
        self, ctx: Context, argument: Union[Member, str] = ""
    ):
        if argument == "":
            return await embed_maker.command_error(ctx)

        member: Union[Member, None] = None

        if type(argument) is str:
            result = await get_member_from_string(ctx, argument)
            member = result[0]
        else:
            member = argument

        if member is None:
            return await embed_maker.message(
                ctx,
                description=f"Failed to find member {argument}.",
                title="Failed to find member.",
                send=True,
            )

        data_manager = self.bot.captcha.get_data_manager()
        blacklisted_members = list(
            data_manager.get_blacklisted_members(member_id=member.id)
        )

        if len(blacklisted_members) > 0:
            return await embed_maker.message(
                ctx,
                description=f"Member {member.display_name}/{member.id} is already in the Blacklist Cache.",
                send=True,
                title="Member already in Blacklist.",
            )

        data_manager.add_blacklisted_member(member)
        await embed_maker.message(
            ctx,
            description=f"Added member {member.display_name}/{member.id} to blacklist cache. The member will be removed manually or automatically if the member has a temporary ban that has elasped.",
            send=True,
        )

    @dev_blacklist_cmd.command(
        help="Remove a member from the blacklist cache.",
        name="remove",
        usage="captcha dev bc remove [Username / ID]",
        examples=["captcha dev bc remove TheMastered"],
        cls=Command,
    )
    async def dev_blacklist_remove_cmd(self, ctx: Context, argument: str = ""):
        if argument == "":
            return await embed_maker.command_error(ctx)

        data_manager = self.bot.captcha.get_data_manager()
        print(f"Is {argument} numeric: {argument.isnumeric()}")
        blacklisted_members = list(
            data_manager.get_blacklisted_members(username=argument)
            if argument.isnumeric() is False
            else data_manager.get_blacklisted_members(member_id=int(argument))
        )

        is_blacklisted = data_manager.is_blacklisted(int(argument))

        if len(blacklisted_members) == 0 and is_blacklisted is False:
            return await embed_maker.message(
                ctx,
                description=f"Member starting with name or id {argument} is not blacklisted.",
                title="Member is not blacklisted",
                send=True,
            )

        if len(blacklisted_members) > 1:
            return await embed_maker.message(
                ctx,
                description=f"{len(blacklisted_members)} blacklisted member starts with the characters/integers {argument}. Please be more specific. ",
                title="Returned more than one member.",
                send=True,
            )

        data_manager.reset_captcha_counter(
            member_id=blacklisted_members[0]["mid"]
            if len(blacklisted_members) > 0
            else int(argument)
        )
        data_manager.remove_blacklisted_member(
            member_id=blacklisted_members[0]["mid"]
            if len(blacklisted_members)
            else int(argument)
        )
        return await embed_maker.message(
            ctx,
            description=f"Removed member {blacklisted_members[0]['name'] if len(blacklisted_members) > 0 else argument} from blacklist and reset relog counter.",
            send=True,
            title="Removed member from blacklist.",
        )

    @dev_cmds.group(
        help="Create either a new guild or a captcha channel on any guild the bot is connected to.",
        name="create",
        usage="captcha dev create [sub command]",
        examples=["captcha dev create guild", "captcha dev create channel"],
        cls=Group,
        invoke_without_command=True,
    )
    async def dev_create_cmd(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @dev_create_cmd.command(
        help="Create a gateway guild.",
        name="guild",
        usage="captcha dev create guild",
        examples=["captcha dev create guild"],
        cls=Command,
        invoke_without_command=True,
    )
    async def dev_create_server(self, ctx: Context):
        guild_count = len(self.bot.guilds)
        if guild_count >= 10:
            return await embed_maker.message(
                ctx,
                description="Can't create new guild, bot cannot create new guilds if it is joined to more than 10 guilds.",
                title="Can't create guild.",
                send=True,
            )

        number = len(self.bot.captcha.get_gateway_guilds()) + 1
        g_guild = await self.bot.captcha.create_guild()
        await embed_maker.message(
            ctx, description=f"Created Gateway Guild No. {number}", send=True
        )

    @dev_cmds.command(
        help="List all the guilds the bot is in, not just the Gateway Guilds.",
        name="list",
        usage="captcha dev list",
        examples=["captcha dev list"],
        cls=Command,
    )
    async def dev_guild_list(self, ctx: Context):
        guilds = self.bot.guilds
        bits = []

        for guild in guilds:
            bits.append(
                "\n".join(
                    [
                        f"- **{guild.name}**",
                        f"  **ID**: {guild.id}",
                        f"  **User Count:** {len(guild.members)}",
                        f"  **Owner:** {guild.owner.name}/{guild.owner.id}",
                        f"  **Gateway Guild:** {'Yes' if self.bot.captcha.is_gateway_guild(guild.id) else 'No'}",
                    ]
                )
            )

        return await embed_maker.message(
            ctx, description="\n".join(bits), title="Guilds", send=True
        )

    @dev_cmds.command(
        help="Delete a guilds owned by the Bot.",
        name="delete",
        usage="captcha dev delete",
        examples=["captcha dev delete"],
        command_args=[
            (("--name", "-n", str), "Guild name"),
            (
                ("--gateway-guild", "-gg", str),
                "If this is true it will check the Gateway Guilds list, if not it will check the guilds the bot is joined to. Used in cases where a guild owned by the bot is not in the gateway guild list.",
            ),
        ],
        cls=Command,
    )
    async def dev_guild_delete(self, ctx: Context, *, args: Union[ParseArgs, str] = ""):
        if args == "":
            return await embed_maker.command_error(ctx)

        guilds: list[Guild] = self.bot.guilds
        name = args["pre"] if args["pre"] != "" else args["name"]

        for guild in guilds:
            if name.lower() == guild.name.lower():
                if args["gateway-guild"] == "no":
                    deleted = await self.bot.captcha.get_gateway_guild(
                        guild.id
                    ).delete()
                    if deleted is False:
                        return await embed_maker.message(
                            ctx,
                            description=f"Failed to delete guild {guild.name}.",
                            title="Couldn't delete gateway guild.",
                            send=True,
                        )
                elif args["gateway-guild"] is None:
                    guilds = self.bot.guilds

                    for guild in guilds:
                        if guild.name.lower() == name.lower():
                            await guild.delete()

                            return await embed_maker.message(
                                ctx,
                                description=f"Deleted guild {guild.name}.",
                                title="Deleted Gateway Guild.",
                                send=True,
                            )
        return await embed_maker.message(
            ctx,
            description=f"Couldn't find guild under name {name}.",
            title="Couldn't findguild.",
            send=True,
        )

    @dev_create_cmd.command(
        help="Create an invitation link for a gateway guild.",
        name="invite",
        usage="captcha dev create invite [minimum uses] [time to live (in seconds)] [temporary (yes/no)] [name]",
        examples=["captcha dev create invite 1 120 no [guild name]"],
        cls=Command,
        command_args=[
            (
                ("--max-uses", "-mu", int),
                "The amount of times this invite can be used (0 sets this to infinite)",
            ),
            (
                ("--max-age", "-ma", int),
                "The time-to-live value of this invite, in seconds (0 sets this to immortal)",
            ),
            (
                ("--temporary", "-t", bool),
                "If set to temporary, will kick the user off the guild if Discord reloads.",
            ),
            (("--name", "-n", list), "The name of the guild to create the invite on."),
        ],
    )
    async def dev_create_invite(
        self,
        ctx: Context,
        *,
        args: Union[ParseArgs, str] = "",
    ):
        if args == "":
            return await embed_maker.command_error(ctx)

        if args["pre"] != "":
            split_pre = args["pre"].split(" ")
            if len(split_pre) < 4:
                return await embed_maker.command_error(ctx)

            if split_pre[0].isnumeric() is False:
                return await embed_maker.command_error(
                    ctx, "1st Positional Argument (min-uses)"
                )
            args["max-uses"] = int(split_pre[0])
            if split_pre[1].isnumeric() is False:
                return await embed_maker.command_error(
                    ctx, "2nd Positional Argument (min-age)"
                )
            args["max-age"] = int(split_pre[1])
            args["temporary"] = False if split_pre[2].lower() == "no" else True
            args["name"] = split_pre[3:]

        max_uses: int = 0 if args["max-uses"] is None else args["max-uses"]
        max_age: int = 0 if args["max-age"] is None else args["max-age"]
        temporary: bool = False if args["temporary"] is None else args["temporary"]
        name = " ".join(args["name"])

        g_guilds: list[GatewayGuild] = self.bot.captcha.get_gateway_guilds()

        for g_guild in g_guilds:
            if g_guild.get_name().lower() == name.lower():
                if g_guild.get_landing_channel() is None:
                    return await embed_maker.message(
                        ctx,
                        description="Guild does not have landing channel set.",
                        title="Couldn't create invite.",
                        send=True,
                    )
                invite = await g_guild.get_landing_channel().create_invite(
                    max_age=max_age,
                    max_uses=max_uses,
                    temporary=True if temporary == "yes" else False,
                )
                return await embed_maker.message(
                    ctx, description=invite.url, title="Created invite.", send=True
                )
        return await embed_maker.message(
            ctx,
            description=f"Couldn't find guild {name}",
            title="Couldn't create invite.",
            send=True,
        )

    @dev_create_cmd.command(
        help="Create a captcha channel, for testing.",
        name="channel",
        usage="captcha dev create channel TheMasteredPanda Gateway Guild 1",
        examples=["captcha dev create channel"],
        command_args=[
            (
                ("--guild", "-g", str),
                "Name of guild to create the Gateway in. If not supplied it will assume the first Gateway Guild.",
            ),
            (("--member", "-m", str), "The name of the user who the channel is for."),
        ],
        cls=Command,
    )
    async def dev_create_captcha_channel(
        self, ctx: Context, *, args: Union[ParseArgs, str] = ""
    ):
        if args == "":
            return await embed_maker.command_error(ctx)

        if args["pre"] != "":
            split_pre = args["pre"].split(" ")
            args["member"] = split_pre[0]
            args["guild"] = " ".join(split_pre[1:])

        guild_name = args["guild"]
        member_name = args["member"]
        gateway_guilds = self.bot.captcha.get_gateway_guilds()
        member, ignore_string = await get_member_from_string(ctx, member_name)

        if member is None:
            return await embed_maker.message(
                ctx,
                description=f"Couldn't find member {member_name}.",
                title="Couldn't find member.",
                send=True,
            )

        for g_guild in gateway_guilds:
            if g_guild.get_name().lower().startswith(guild_name.lower()):
                captcha_channel = g_guild.create_captcha_channel(member)
                await captcha_channel.start()
                return await embed_maker.message(
                    ctx,
                    description=f"Created Captcha Channel named {captcha_channel.get_name()} for {member.display_name} on guild {g_guild.get_name()}.",
                    title="Create Captcha Channel.",
                    send=True,
                )

        return await embed_maker.message(
            ctx,
            description=f"Couldn't find guild {guild_name}.",
            title="Couldn't find guild.",
            send=True,
        )

    @dev_create_cmd.command(
        help="Create a captch image, for testing",
        name="image",
        usage="captcha dev create image",
        examples=["captcha dev create image"],
        cls=Command,
    )
    async def dev_create_captcha_image(self, ctx: Context):
        captcha_image, captcha_text = self.bot.captcha.create_captcha_image()
        embed: Embed = await embed_maker.message(
            ctx, title="Captcha Image.", description=f"Text: {captcha_text}"
        )
        embed.set_image(url="attachment://captcha.png")
        return await ctx.channel.send(
            file=File(fp=captcha_image, filename="captcha.png"), embed=embed
        )

    @captcha_cmd.command(
        help="Add or remove an operator to an operator list. This will allow member on the op list to become operators when they join Gateway Guilds. Affording them admin access on the guild.",
        name="op",
        usage="captcha op TheMasteredPanda",
        examples=["captcha op TheMasteredPanda"],
        cls=Command,
    )
    async def mod_operator(self, ctx: Context, member_string: str = None):
        if member_string is None:
            return await embed_maker.command_error(ctx)

        member, ignore = await get_member_from_string(ctx, member_string)
        if member is None:
            return await embed_maker.message(
                ctx,
                description=f"Couldn't find member {member_string}",
                title="Couldn't find Member",
                send=True,
            )

        was_op = member.id in self.bot.captcha.get_operators()
        self.bot.captcha.set_operator(member.id)

        if was_op is False:
            await embed_maker.message(
                ctx,
                description=f"Added {member.name} to the Operators list.",
                title="Added Operator.",
                send=True,
            )
        else:
            await embed_maker.message(
                ctx,
                description=f"Removed {member.name} from the Operators list",
                title="Removed Operator.",
                send=True,
            )

    @dev_cmds.group(
        help="A set of commands used to interface directly with the ban lists of active Gateway Guilds.",
        name="bans",
        usage="captcha dev bans [sub command]",
        examples=["captcha dev bans list", "captcha dev bans reset Gateway Guild 1"],
        cls=Group,
        invoke_without_command=True,
    )
    async def dev_bans(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    async def construct_dev_bans_embed(
        self, ctx: Context, bans: list, max_page_num: int, page_limit: int, *, page: int
    ):
        if len(bans) == 0:
            return await embed_maker.message(
                ctx, description="No bans found.", title="No bans found"
            )

        bits = []

        for i, entry in enumerate(bans[page_limit * (page - 1) : page_limit * page]):
            bits.append(
                "\n".join(
                    [
                        f"**{i + 1}.** {entry.user.name}#{entry.user.discriminator}",
                        f"  {entry.reason}",
                    ]
                )
            )

        return await embed_maker.message(
            ctx,
            description="\n".join(bits),
            author={"name": "Captcha Gateway"},
            footer={"text": f"Page {page}/{max_page_num}"},
        )

    @dev_bans.command(
        help="Reset bans on a Gateway Guild or all Gateway Guilds.",
        name="reset",
        usage="captcha dev bans reset [Gateway Guild ID] ['no' for this guild only, 'yes' for all guilds. Default is yes]",
        examples=["catpcha dev bans reset 1 yes", "captcha dev bans reset 1"],
        cls=Command,
    )
    async def dev_bans_reset(
        self, ctx: Context, g_guild_id: int = 0, all_guilds: str = "yes"
    ):
        captcha_module = self.bot.captcha
        gateway_guilds: list[GatewayGuild] = captcha_module.get_gateway_guilds()

        if g_guild_id <= 0 or g_guild_id > len(gateway_guilds):
            bits = []

            for i, g_guild in enumerate(gateway_guilds):
                bits.append(f"**{i + 1}**. {g_guild.get_name()}")

            return await embed_maker.message(
                ctx,
                description="Gateway Guilds. Guild IDs are highlighted: \n"
                + "\n".join(bits),
                title="Gateway Guilds",
                send=True,
            )
        else:
            g_guild = gateway_guilds[g_guild_id - 1]
            bans = await g_guild.get_guild().bans()
            removed_bans = 0
            for entry in bans:
                if all_guilds == "no":
                    await g_guild.get_guild().unban(entry.user)
                    removed_bans += 1
                else:
                    await captcha_module.unban(entry.user.id)
                    removed_bans += 1

            return await embed_maker.message(
                ctx,
                description=f"Removed {removed_bans} bans.",
                title="Removed bans",
                send=True,
            )


def setup(bot: TLDR):
    bot.add_cog(Captcha(bot))
