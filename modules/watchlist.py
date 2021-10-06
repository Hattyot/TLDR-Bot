import datetime
import discord

from typing import Optional
from modules import database

db = database.get_connection()


class Watchlist:
    def __init__(self, bot):
        self.bot = bot

        if not self.bot.webhooks:
            self.bot.watchlist = None
            raise Exception('Watchlist module depends on google drive module being enabled')

        self.members = {}
        self.watchlist_data = {}
        self.bot.add_listener(self.on_message, 'on_message')
        self.bot.add_listener(self.on_ready, 'on_ready')

    async def on_ready(self):
        self.bot.watchlist.initialize()

    def initialize(self):
        """Cache all the existing webhook users."""
        for guild in self.bot.guilds:
            self.watchlist_data[guild.id] = {}
            users = db.watchlist.find({"guild_id": guild.id})
            for user in users:
                self.watchlist_data[guild.id][user['user_id']] = user

    @staticmethod
    async def get_watchlist_category(guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        """Get the watchlist category or create it if it doesn't exist."""
        if guild is None:
            return

        category = discord.utils.get(guild.categories, name='Watchlist')
        if category is None:
            # get all staff roles
            staff_roles = filter(lambda r: r.permissions.manage_messages, guild.roles)
            # staff roles can read channels in category, users cant
            overwrites = dict.fromkeys(staff_roles, discord.PermissionOverwrite(read_messages=True, send_messages=True, read_message_history=True))
            overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False, read_messages=False)
            category = await guild.create_category(name='Watchlist', overwrites=overwrites)

        return category

    def get_member(self, member: discord.Member) -> Optional[dict]:
        """Get a watchlist member."""
        if not member.guild:
            return None

        guild_watchlist_data = self.watchlist_data[member.guild.id]
        return guild_watchlist_data[member.id] if member.id in guild_watchlist_data else None

    async def add_member(self, member: discord.Member, filters: list) -> dict:
        """Add a watchlist member, creating a channel for them."""
        category = await self.get_watchlist_category(member.guild)
        watchlist_channel = await member.guild.create_text_channel(f'{member.name}', category=category)
        watchlist_doc = {
            'guild_id': member.guild.id,
            'user_id': member.id,
            'filters': filters,
            'channel_id': watchlist_channel.id
        }
        db.watchlist.insert_one(watchlist_doc)
        self.watchlist_data[member.guild.id][member.id] = watchlist_doc
        return watchlist_doc

    async def remove_member(self, member: discord.Member):
        """Remove watchlist member and delete their channel."""
        watchlist_member = self.get_member(member)
        channel = self.bot.get_channel(int(watchlist_member['channel_id']))
        if channel:
            await channel.delete()

        db.watchlist.delete_one({'guild_id': member.guild.id, 'user_id': member.id})

    def add_filters(self, member: discord.Member, filters: list):
        """Add filters to a watchlist member."""
        watchlist_member = self.get_member(member)
        all_filters = watchlist_member['filters']
        if all_filters:
            filters += all_filters

        db.watchlist.update_one({'guild_id': member.guild.id, 'user_id': member.id}, {'$set': {f'filters': filters}})

    async def send_message(self, channel: discord.TextChannel, message: discord.Message):
        """Send watchlist message with a webhook."""
        embeds = [discord.Embed(description=f'{message.content}\n{message.channel.mention} [link]({message.jump_url})', timestamp=datetime.datetime.now())]
        files = [await attachment.to_file() for attachment in message.attachments]
        await self.bot.webhooks.send(
            channel=channel,
            content='',
            username=message.author.name,
            avatar_url=message.author.avatar_url,
            files=files,
            embeds=embeds
        )

    async def on_message(self, message: discord.Message):
        """Function run on every message to check if user is on watchlist and send their message."""
        if not self.bot._ready.is_set():
            return

        if not message.guild:
            return

        guild_watchlist_data = self.watchlist_data[message.guild.id]
        user_watchlist_data = guild_watchlist_data[message.author.id] if message.author.id in guild_watchlist_data else None
        watchlist_category = await self.get_watchlist_category(message.guild)
        if not user_watchlist_data or not watchlist_category:
            return

        channel_id = user_watchlist_data["channel_id"]
        channel = self.bot.get_channel(int(channel_id))
        if channel:
            await self.send_message(channel, message)
        else:
            # remove from watchlist, since watchlist channel doesnt exist
            db.watchlist.delete_one({"guild_id": message.guild.id, "user_id": message.author.id})
