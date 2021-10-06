import discord
import config

from bot import TLDR
from discord.ext.commands import Cog, command, Context
from modules import database, commands, embed_maker, utils
from datetime import datetime

db = database.get_connection()


class Settings(Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot

    @command(
        help="Set the mute role",
        usage="setmuterole [role]",
        examples=[
            "setmuterole 672052748358778890",
            "setmuterole Muted",
            "setmuterole @Muted",
        ],
        cls=commands.Command,
    )
    async def setmuterole(self, ctx: Context, *, role_identifier: str = None):
        guild_settings = db.get_guild_settings(ctx.guild.id)
        current_mute_role_id = guild_settings["mute_role_id"]

        if role_identifier is None:
            embed_colour = config.EMBED_COLOUR
            embed = discord.Embed(
                colour=embed_colour,
                timestamp=datetime.now(),
                description="Set the mute role.",
            )
            embed.add_field(
                name=">Current Settings", value=current_mute_role_id, inline=False
            )
            embed.add_field(name=">Update", value="`setmuterole [role]`", inline=False)
            embed.add_field(
                name=">Valid Input", value="**Role:** Any valid role", inline=False
            )
            embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
            embed.set_author(name="Mute Role", icon_url=ctx.guild.icon_url)
            return await ctx.send(embed=embed)

        if role_identifier:
            role = await utils.get_guild_role(ctx.guild, role_identifier)

            if role is None:
                return await embed_maker.error(
                    ctx, f"Couldn't find a role by `{role_identifier}`"
                )

            if role.id == current_mute_role_id:
                return await embed_maker.error(
                    ctx, f"Mute role is already set to <@&{role.id}>"
                )

            db.guild_settings.update_one(
                {"guild_id": ctx.guild.id}, {"$set": {"mute_role_id": role.id}}
            )
            await embed_maker.message(
                ctx,
                description=f"Mute role has been set to <@&{role.id}>",
                colour="green",
                send=True,
            )

            # exchange mute roles for users who are muted
            if current_mute_role_id is not None:
                mute_timers = db.timers.find(
                    {"guild_id": ctx.guild.id, "event": "automatic_unmute"}
                )
                for timer in mute_timers:
                    member = await utils.get_member(ctx, timer["extras"]["member_id"])
                    old_mute_role = await utils.get_guild_role(
                        ctx.guild, current_mute_role_id
                    )

                    await member.add_roles(role)
                    await member.remove_roles(old_mute_role)

    @command(
        help="Change the channel where invite logger messages are sent",
        usage="invite_logger_channel [#channel]",
        examples=["invite_logger_channel #bots"],
        cls=commands.Command,
        module_dependency=['leveling_system', 'invite_logger'],
    )
    async def invite_logger_channel(
        self, ctx: Context, channel: discord.TextChannel = None
    ):
        leveling_guild = self.bot.leveling_system.get_guild(ctx.guild.id)
        current_channel_id = leveling_guild.invite_logger_channel

        if not current_channel_id:
            current_channel_string = (
                "Not set, messages about what invites people used wont be sent"
            )
        else:
            current_channel_string = f"<#{current_channel_id}>"

        if channel is None:
            embed_colour = config.EMBED_COLOUR
            embed = discord.Embed(
                colour=embed_colour,
                timestamp=datetime.now(),
                description="Change the channel where invite logs are sent.",
            )
            embed.add_field(
                name=">Current Settings", value=current_channel_string, inline=False
            )
            embed.add_field(
                name=">Update", value="`invite_logger_channel [#channel]`", inline=False
            )
            embed.add_field(
                name=">Valid Input",
                value="**Channel:** Any text channel | mention only",
                inline=False,
            )
            embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
            embed.set_author(name="Invite Logger Channel", icon_url=ctx.guild.icon_url)
            return await ctx.send(embed=embed)

        if channel:
            if channel.id == current_channel_id:
                return await embed_maker.error(
                    ctx, f"Invite logger channel is already set to <#{channel.id}>"
                )

            leveling_guild.invite_logger_channel = channel.id
            return await embed_maker.message(
                ctx,
                description=f"Invite logger channel has been set to <#{channel.id}>",
                colour="green",
                send=True,
            )
        else:
            return await embed_maker.command_error(ctx, "[#channel]")

    @command(
        help="Change the channel where level up messages are sent",
        usage="level_up_channel [#channel]",
        examples=["level_up_channel #bots"],
        cls=commands.Command,
        module_dependency=['leveling_system']
    )
    async def level_up_channel(self, ctx: Context, channel: discord.TextChannel = None):
        leveling_guild = self.bot.leveling_system.get_guild(ctx.guild.id)
        current_channel_id = leveling_guild.level_up_channel

        if not current_channel_id:
            current_channel_string = "Not set, defaults to message channel"
        else:
            current_channel_string = f"<#{current_channel_id}>"

        if channel is None:
            embed_colour = config.EMBED_COLOUR
            embed = discord.Embed(
                colour=embed_colour,
                timestamp=datetime.now(),
                description="Change the channel where level up announcements are sent.",
            )
            embed.add_field(
                name=">Current Settings", value=current_channel_string, inline=False
            )
            embed.add_field(
                name=">Update", value="`level_up_channel [#channel]`", inline=False
            )
            embed.add_field(
                name=">Valid Input",
                value="**Channel:** Any text channel | mention only",
                inline=False,
            )
            embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
            embed.set_author(name="Level Up Channel", icon_url=ctx.guild.icon_url)
            return await ctx.send(embed=embed)

        if channel:
            if channel.id == current_channel_id:
                return await embed_maker.error(
                    ctx, f"Level up channel is already set to <#{channel.id}>"
                )

            leveling_guild.level_up_channel = channel.id
            return await embed_maker.message(
                ctx,
                description=f"Level up channel has been set to <#{channel.id}>",
                colour="green",
                send=True,
            )
        else:
            return await embed_maker.command_error(ctx, "[#channel]")


def setup(bot):
    bot.add_cog(Settings(bot))
