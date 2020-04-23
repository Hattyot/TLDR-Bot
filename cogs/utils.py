from discord.ext import commands
from modules import cache
from config import DEV_IDS


class Utils(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @cache.cache()
    async def get_user_clearance(self, guild_id, member_id):
        guild = self.bot.get_guild(guild_id)
        member = guild.get_member(member_id)
        if member is None:
            member = await guild.fetch_member(member_id)

        permissions = member.guild_permissions
        clearance = []

        if member_id in DEV_IDS:
            clearance.append('Dev')
        if permissions.administrator:
            clearance.append('Admin')
        if permissions.manage_messages:
            clearance.append('Mod')
        clearance.append('User')

        return clearance


def setup(bot):
    bot.add_cog(Utils(bot))
