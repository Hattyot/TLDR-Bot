import discord
import copy

from modules import database
from discord import Webhook, AsyncWebhookAdapter
from typing import Optional

db = database.get_connection()


class Webhooks:
    def __init__(self, bot):
        self.bot = bot
        self.webhooks = {}
        self.bot.add_listener(self.on_ready, 'on_ready')

    async def on_ready(self):
        await self.initialize()

    async def initialize(self):
        """Cache all the existing webhooks."""
        webhooks = db.webhooks.find({})
        for webhook in webhooks:
            partial_webhook = Webhook.from_url(webhook['url'], adapter=AsyncWebhookAdapter(self.bot._connection.http._HTTPClient__session))
            self.webhooks[webhook['channel_id']] = partial_webhook

    async def create_webhook(self, channel: discord.TextChannel) -> discord.Webhook:
        """Create a webhook for a channel."""
        # first check if a webhook already exists
        channel_webhooks = await channel.webhooks()
        webhook = None
        if channel_webhooks:
            webhook = next(filter(lambda wh: wh.name == 'TLDR-Bot-webhook' and wh.url[:-4] != 'None', channel_webhooks), None)

        # if there truly is no webhook, create it
        if webhook is None:
            webhook = await channel.create_webhook(name='TLDR-Bot-webhook')

        self.webhooks[channel.id] = webhook
        db.webhooks.insert_one({'channel_id': channel.id, 'url': webhook.url})
        return webhook

    async def get_webhook(self, channel: discord.TextChannel) -> Optional[discord.Webhook]:
        """Get a webhook for a channel or create it, if it doesn't exist."""
        if channel.id in self.webhooks:
            webhook = self.webhooks[channel.id]
        else:
            webhook = await self.create_webhook(channel)

        return copy.copy(webhook)

    async def send(
            self,
            *,
            channel: discord.TextChannel,
            content: str = '',
            username: str = None,
            avatar_url: str = None,
            files: list[discord.File] = None,
            embeds: list[discord.Embed] = None,
            edit: int = None,
    ) -> Optional[discord.WebhookMessage]:
        """Send webhook message."""
        channel_webhook = await self.get_webhook(channel)

        kwargs = {'username': username, 'avatar_url': avatar_url, 'files': files, 'embeds': embeds, 'content': content}

        try:
            if edit:
                return await channel_webhook.edit_message(edit, **kwargs)

            return await channel_webhook.send(wait=True, **kwargs)
        except discord.NotFound:
            # try again
            del self.webhooks[channel.id]
            return await self.send(
                content=content,
                channel=channel,
                username=username,
                avatar_url=avatar_url,
                files=files,
                embeds=embeds,
                edit=edit
            )
        except Exception as e:
            await self.bot.on_event_error(e, 'webhook_send', **kwargs)
