import discord
import config

from datetime import datetime


class InviteLogger:
    def __init__(self, bot):
        self.bot = bot
        self.invites: dict[int, dict[str, discord.Invite]] = {}

        self.bot.add_listener(self._on_member_join, 'on_member_join')
        self.bot.add_listener(self._on_invite_create, 'on_invite_create')
        self.bot.add_listener(self._on_ready, 'on_ready')

        self.bot.logger.info('InviteLogger module has been initiated')

    async def _on_ready(self):
        await self.initialize_invites()

    async def initialize_invites(self):
        await self.bot.wait_until_ready()

        for guild in self.bot.guilds:
            self.invites[guild.id] = {}

            guild_invites = await guild.invites()
            for invite in guild_invites:
                self.invites[guild.id][invite.id] = invite

    async def invite_log_message(self, member: discord.Member, invite: discord.Invite):
        embed = discord.Embed(
            description=f"<@{member.id}> **joined** [**{invite.code}**]\nInvited By: <@{invite.inviter.id}> (**{invite.uses}** uses)",
            colour=config.EMBED_COLOUR,
            timestamp=datetime.now()
        )
        embed.set_footer(text=str(member), icon_url=member.avatar_url)

        leveling_guild = self.bot.leveling_system.get_guild(member.guild.id)

        if leveling_guild.invite_logger_channel:
            channel = self.bot.get_channel(leveling_guild.invite_logger_channel)
            return await channel.send(embed=embed)

    async def _on_member_join(self, member: discord.Member):
        guild_invites: list[discord.Invite] = await member.guild.invites()
        for new_invite in guild_invites:
            old_invite = self.invites[member.guild.id].get(new_invite.id, None)
            if not old_invite:
                break

            if new_invite.uses > old_invite.uses:
                await self.invite_log_message(member, new_invite)
                break
        else:
            invite_used = set(i.id for i in self.invites[member.guild.id].values()) - set([i.id for i in guild_invites])
            if invite_used:
                invite_used = self.invites[member.guild.id][invite_used.pop()]
                await self.invite_log_message(member, invite_used)

        for invite in guild_invites:
            self.invites[member.guild.id][invite.id] = invite

    async def _on_invite_create(self, invite: discord.Invite) -> None:
        if invite.guild.id in self.invites:
            self.invites[invite.guild.id][invite.id] = invite
