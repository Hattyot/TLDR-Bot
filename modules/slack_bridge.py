import asyncio
import re
import time
import discord
import discord.utils
import config

from cachetools import TTLCache
from html import unescape
from typing import Optional
from modules import database
from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from modules.utils import replace_mentions, embed_message_to_text, async_file_downloader, get_member_from_string

db = database.get_connection()
image_extensions = ['jpg', 'png', 'gif', 'webp', 'tiff', 'bmp', 'jpeg']


class SlackMessage:
    def __init__(self, data: dict, slack: 'Slack'):
        self.data = data
        self.slack = slack

        event_data = data['event']
        # ignore bot messages
        if 'subtype' in event_data and event_data['subtype'] == 'bot_message':
            return

        self.team_id = data['team_id']
        self.team = self.slack.get_team(self.team_id)
        self.user_id = event_data['user']
        self.channel_id = event_data['channel']
        self.text = event_data['text']
        self.ts = event_data['ts']
        self.thread_ts = event_data['thread_ts'] if 'thread_ts' in event_data else None
        self.files = [
            {'url': file['url_private_download'], 'name': file['name']}
            for file in event_data['files']
        ] if 'files' in event_data else []

        self.member = self.slack.get_user(self.user_id)
        self.channel = self.slack.get_channel(self.channel_id)

        if self.channel is None:
            self.channel = SlackChannel(self.team, self.channel_id, self.slack)
            self.team.channels.append(self.channel)

        self.discord_message_id = event_data['discord_message_id'] if 'discord_message_id' in event_data else None
        self.reactions = {}
        self.team.slack_messages[self.ts] = self
        slack.bot.loop.create_task(self.initialise_data())

    async def initialise_data(self):
        data = db.slack_messages.find_one({'slack_message_id': self.ts})
        if not data:
            db.slack_messages.insert_one({
                'team_id': self.team.team_id,
                'slack_message_id': self.ts,
                'discord_message_id': self.discord_message_id,
                'origin': 'slack',
                'timestamp': round(time.time())
            })

    def __setattr__(self, key, value):
        if (
            key in ["discord_message_id"]
            and key in self.__dict__
            and self.__dict__[key] != value
        ):
            db.slack_messages.update_one(
                {"slack_message_id": self.ts},
                {"$set": {f"{key}": value}},
            )
        self.__dict__[key] = value

    async def delete(self):
        if self.discord_message_id and self.channel.discord_channel:
            await self.slack.bot.http.delete_message(self.channel.discord_channel.id, self.discord_message_id)

            if self.ts in self.team.slack_messages:
                del self.team.slack_messages[self.ts]

            db.slack_messages.delete_one({'slack_message_id': self.ts})

    async def replace_custom_mentions(self, string: str) -> str:
        if not self.channel.discord_channel:
            return string

        mentions = re.findall(r'(?:^|\s|)@(.+)$', string)
        for mention in mentions:
            member, extra_string = await get_member_from_string(None, mention, guild=self.channel.discord_channel.guild)
            if member:
                string = string.replace(f'@{mention}', f'{member.mention} {extra_string}'.strip())

        return string

    def replace_valid_mentions(self, string: str) -> str:
        # replace mentions in values with actual names
        mentions = re.findall(r'(<([@#])([^|>]+)(?:\|(\w+))?>)', string)
        for mention in mentions:
            mention_type = mention[1]
            mention_id = mention[2]

            if mention_type == '#':
                string = string.replace(mention[0], f'#{mention[3]}')
            elif mention_type == '@':
                slack_member = self.slack.get_user(mention_id)
                if slack_member:
                    string = string.replace(mention[0], f'@{slack_member.name}')

        return string

    async def send_to_discord(self, *, edit: bool = False):
        """Function for sending messages from slack to discord via a webhook."""
        if not self.channel.discord_channel:
            return

        if edit and not self.discord_message_id:
            return

        if self.member is None:
            self.member = await self.team.add_user(self.user_id)

        file_urls = [file['url'] for file in self.files]
        download_files = [
            discord.File(file, filename=self.files[i]['name']) for i, file in
            enumerate(
                await async_file_downloader(file_urls, headers={'Authorization': f'Bearer {self.team.token}'})
            )
        ]

        text = unescape(self.text)
        text = await self.replace_custom_mentions(text)
        text = self.replace_valid_mentions(text)

        discord_message = await self.slack.bot.webhooks.send(
            content=text,
            channel=self.channel.discord_channel,
            username=self.member.name,
            avatar_url=str(self.member.avatar_url),
            files=download_files,
            embeds=[],
            edit=self.discord_message_id
        )

        if not edit:
            self.discord_message_id = discord_message.id


class DiscordMessage:
    def __init__(self, message: discord.Message, slack: 'Slack'):
        self.slack = slack

        self.id = message.id
        self.text = message.content
        self.embed = message.embeds[0] if message.embeds else None
        self.guild_id = message.guild.id
        self.guild: discord.Guild = slack.bot.get_guild(self.guild_id)
        self.channel_id = message.channel.id
        self.author_is_bot: bool = message.author.bot
        self.author_name = message.author.name
        self.author_avatar = str(message.author.avatar_url).replace('.webp', '.png')
        self.attachment_urls = [{'url': attachment.url, 'filename': attachment.filename} for attachment in message.attachments]
        # self.reply_id = message.reference.message_id if message.reference else None
        # self.reply_is_bot = message.reference.resolved.author.bot if message.reference and type(message.reference.resolved) == discord.Message else None

        self.slack_message_id = None
        self.initialise_data()

    def initialise_data(self):
        data = db.slack_messages.find_one({'discord_message_id': self.id})
        if not data:
            slack_channel = self.slack.get_channel(discord_id=self.channel_id)
            if not slack_channel:
                return

            db.slack_messages.insert_one({
                'team_id': slack_channel.team.team_id,
                'slack_message_id': self.slack_message_id,
                'discord_message_id': self.id,
                'origin': 'discord',
                'timestamp': round(time.time())
            })

    def __setattr__(self, key, value):
        if (
            key in ["slack_message_id"]
            and key in self.__dict__
            and self.__dict__[key] != value
        ):
            db.slack_messages.update_one(
                {"discord_message_id": self.id},
                {"$set": {f"{key}": value}},
            )
        self.__dict__[key] = value

    async def delete(self):
        if self.slack_message_id:
            slack_channel = self.slack.get_channel(discord_id=self.channel_id)
            team = slack_channel.team
            await team.app.client.chat_delete(channel=slack_channel.id, ts=self.slack_message_id)
            if self.id in team.discord_messages:
                del team.discord_messages[self.id]

            db.slack_messages.delete_one({'team_id': team.team_id, 'discord_message_id': self.id})

    def replace_custom_mentions(self, text: str) -> str:
        """
        This whole function is a mess.
        Replaces things like @hatty in a discord message with slack member mentions [<@U0271HF3ZQV>] before sending it off to slack.
        """
        slack_channel = self.slack.get_channel(discord_id=self.channel_id)
        if not slack_channel:
            return text

        team = slack_channel.team

        special_chars_map = {i: '\\' + chr(i) for i in b'()[]{}?*+-|^$\\.&~#'}
        mentions = re.findall(r'(?:^|\s)(@.+)', text)

        def match_member(string: str):
            safe_text = string.translate(special_chars_map)
            members = list(
                filter(
                    lambda m: re.findall(fr'({safe_text.lower()})', m.name.lower()),
                    team.members
                )
            )
            if len(members) == 1:
                return members[0]

            return members

        for mention in mentions:
            previous_match = None
            member_name = ""
            for part in mention[1:].split():
                member_match = match_member(f'{member_name} {part}'.strip())
                if not member_match:
                    if previous_match is None:
                        break
                    if type(previous_match) == SlackMember:
                        text = text.replace(f'@{member_name}', f'<@{previous_match.id}>')
                        break
                else:
                    # update variables
                    previous_match = member_match
                    member_name = f'{member_name} {part}'.strip()

            if len(mention[1:].split()) == 1 and type(previous_match) == SlackMember:
                text = text.replace(f'@{member_name}', f'<@{previous_match.id}>')

        return text

    @staticmethod
    def hyperlink_converter(text):
        """Converts discord hyperlink format to slack format."""
        special_chars_map = {i: '\\' + chr(i) for i in b'()[]{}?*+-|^$\\.&~#'}
        matches = re.findall(r'(\[(.*)]\((.*)\))', text)
        for match in matches:
            url_text = match[1]
            url = match[2]
            text = re.sub(match[0].translate(special_chars_map), f'<{url}|{url_text}>', text)

        return text

    def normalize_text(self, text):
        """Function for normalising discord text to slack standards."""
        text = self.replace_custom_mentions(text)
        text = replace_mentions(self.guild, text)
        text = self.hyperlink_converter(text)
        text = self.text_to_slack_formatting(text)
        return text

    def embed_to_blocks(self) -> tuple[list, str]:
        """Converts discord embeds into slack blocks."""
        text = embed_message_to_text(self.embed)
        text = '>' + text.replace('\n', '\n>')
        text = self.normalize_text(text)

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text
                }
            }
        ]
        return blocks, text

    @staticmethod
    def text_to_slack_formatting(text):
        """Converts discord's bold and italic formatting to slack standards."""
        special_chars_map = {i: '\\' + chr(i) for i in b'()[]{}?*+-|^$\\.&~#'}
        italic = re.findall(r'((?:[^*]|^)\*((?:[^*\s][^*]+[^*\s]?)|(?:[^*\s]?[^*]+[^*\s]))\*(?:[^*]|$))', text)
        for match in italic:
            match_text = match[1]
            text = re.sub(match[0].strip().translate(special_chars_map), f'_{match_text}_', text)

        bold = re.findall(r'(\*\*((?:[^*\s][^*]*[^*\s]?)|(?:[^*\s]?[^*]*[^*\s]))\*\*)', text)
        for match in bold:
            match_text = match[1]
            text = re.sub(match[0].translate(special_chars_map), f'*{match_text}*', text)

        return text

    # disabled, waiting for threads, maybe will be enabled in the future
    # async def reply_blocks(self):
    #     if self.reply_is_bot is None:
    #         return
    #
    #     slack_channel = self.slack.get_channel(discord_id=self.channel_id)
    #     if self.reply_is_bot:
    #         slack_message = next(filter(lambda sm: sm.discord_message_id == self.reply_id, self.slack.slack_messages.values()), None)
    #         if slack_message is None:
    #             slack_message_link = next(filter(lambda ml: ml[1] == self.reply_id, self.slack.message_links.items()), None)
    #             if slack_message_link is None:
    #                 return
    #             slack_message = await self.slack.get_slack_message(slack_channel.id, slack_message_link[0], self.reply_id)
    #     else:
    #         discord_message = self.slack.discord_messages.get(self.reply_id, None)
    #         if not discord_message:
    #             discord_message_link = self.slack.message_links.get(self.reply_id, None)
    #             discord_message = await self.slack.get_discord_message(self.channel_id, self.reply_id, discord_message_link)
    #             if not discord_message:
    #                 return
    #         slack_message = await self.slack.get_slack_message(slack_channel.id, discord_message.slack_message_id)
    #
    #     slack_message_link = await self.slack.app.client.chat_getPermalink(channel=slack_message.channel_id, message_ts=slack_message.ts)
    #     if slack_message_link['ok']:
    #         return [
    #             {
    #                 "type": "context",
    #                 "elements": [
    #                     {
    #                         "type": "mrkdwn",
    #                         "text": f"┌Reply to: <{slack_message_link['permalink']}|{slack_message.text[:15]}...>"
    #                     }
    #                 ]
    #             }
    #         ]

    async def to_slack_blocks(self):
        """Main entrypoint for converting discord message to appropriate slack format."""
        kwargs = {'text': '', 'blocks': []}

        # if self.reply_id:
        #     reply_blocks = await self.reply_blocks()
        #     if reply_blocks:
        #         kwargs['blocks'] += reply_blocks

        if self.author_is_bot and self.embed:
            blocks, text = self.embed_to_blocks()
            kwargs['blocks'] = blocks
            kwargs['text'] = text
        elif self.text:
            text = replace_mentions(self.guild, self.text)
            text = self.normalize_text(text)
            kwargs['text'] = text
            kwargs['blocks'].append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text,
                }
            })

        image_urls = [a for a in self.attachment_urls if a['url'].split('.')[-1] in image_extensions]
        for attachment in image_urls:
            kwargs['blocks'].append(
                {
                    "type": "image",
                    "image_url": attachment['url'],
                    "alt_text": f"Uploaded by {self.author_name} - {attachment['filename']}"
                }
            )
        if not kwargs['text'] and image_urls:
            kwargs['text'] = f'Image{"s" if len(image_urls) > 1 else ""} uploaded by {self.author_name}'

        return kwargs

    async def send_to_slack(self, edit: bool = False):
        if edit and not self.slack_message_id:
            return

        slack_channel = self.slack.get_channel(discord_id=self.channel_id)
        if not slack_channel:
            return

        kwargs = await self.to_slack_blocks()
        team = slack_channel.team

        if kwargs['blocks'] and kwargs['text']:
            kwargs.update({'channel': slack_channel.id})
            if edit:
                kwargs['ts'] = self.slack_message_id
                func = team.app.client.chat_update
            else:
                kwargs.update({'icon_url': str(self.author_avatar), 'username': self.author_name})
                func = team.app.client.chat_postMessage

            kwargs['token'] = team.token

            # if self.reply_id:
            #     kwargs['unfurl_links'] = False

            slack_message = await func(**kwargs)
            if not edit:
                slack_channel.team.discord_messages[self.id] = self
                self.slack_message_id = slack_message['message']['ts']

        if self.attachment_urls:
            file_urls = [a for a in self.attachment_urls if a['url'].split('.')[-1] not in image_extensions]
            files = await async_file_downloader([a['url'] for a in file_urls])
            for i, file in enumerate(files):
                await team.app.client.files_upload(
                    file=file,
                    filename=file_urls[i]['filename'],
                    channels=slack_channel.id,
                    initial_comment=f'Uploaded by: {self.author_name}'
                )


class SlackMember:
    def __init__(self, data, slack: 'Slack'):
        self.slack = slack

        self.team_id = data['team_id']
        self.team = slack.get_team(self.team_id)

        self.id = data['id']
        # this value should only be used for the slack member info command
        self.slack_name = data['real_name'] if 'real_name' in data else data['profile']['real_name']
        # bool used to check if member has a name set
        self.discord_name = False
        self.name = self.id

        self.discord_member = None
        self.avatar_url = ''

        self.initialize_data()

    def initialize_data(self):
        """Initialise slack user in the database if needed."""
        data = db.slack_bridge.find_one(
            {'team_id': self.team.team_id,
             'aliases': {
                 '$elemMatch': {'slack_id': self.id}
             }},
            {"aliases.$": 1}
        )
        if not data or not data.get('aliases', None):
            member_data = {
                'slack_id': self.id,
                'discord_id': None
            }
            db.slack_bridge.update_one(
                {'team_id': self.team.team_id},
                {'$push': {'aliases': member_data}}
            )

    async def get_discord_member(self):
        """Gets slack user alias and sets the alias variables if alias has been set."""
        data = db.slack_bridge.find_one({
            'team_id': self.team.team_id,
            'aliases': {
                '$elemMatch': {'slack_id': self.id}
            }},
            {"aliases.$": 1}
        )
        discord_id = data['aliases'][0].get('discord_id', None) if len(data.get('aliases', [])) > 0 else None
        discord_name = data['aliases'][0].get('discord_name', None) if len(data.get('aliases', [])) > 0 else None

        if discord_id:
            await self.slack.bot.wait_until_ready()
            main_guild = self.slack.bot.get_guild(config.MAIN_SERVER)
            self.discord_member = discord.utils.get(main_guild.members, id=int(discord_id))
            if self.discord_member:
                self.avatar_url = self.discord_member.avatar_url
                self.name = self.discord_member.name
        elif discord_name:
            user_info = await self.get_user_info()
            self.avatar_url = user_info['user']['profile']['image_192']
            self.name = discord_name
            self.discord_name = True

    def set_discord_name(self, name: str):
        """Set the discord name of slack user"""
        self.name = name
        self.discord_name = True

        db.slack_bridge.update_one(
            {'team_id': self.team.team_id, 'aliases': {'$elemMatch': {'slack_id': self.id}}},
            {'$set': {'aliases.$.discord_name': name}}
        )

    def unset_discord_member(self):
        """Unsets all the alias variables and  updates the database."""
        self.discord_member = None
        self.discord_name = False
        self.name = self.id

        db.slack_bridge.update_one(
            {'team_id': self.team.team_id, 'aliases': {'$elemMatch': {'slack_id': self.id}}},
            {'$set': {'aliases.$.discord_id': None, 'aliases.$.discord_name': None}}
        )

    def set_discord_member(self, discord_member: discord.Member):
        """Set the needed alias variables and update the database.."""
        self.discord_member = discord_member
        self.name = discord_member.name

        db.slack_bridge.update_one(
            {'team_id': self.team.team_id, 'aliases': {'$elemMatch': {'slack_id': self.id}}},
            {'$set': {'aliases.$.discord_id': discord_member.id}}
        )

    async def get_user_info(self):
        """Returns slack user info of user."""
        return await self.team.app.client.users_info(user=self.id)


class SlackChannel:
    def __init__(self, team: 'SlackTeam', channel_id: str, slack: 'Slack'):
        self.slack = slack

        self.team = team
        self.id = channel_id
        self.slack_name = self.id
        self.name = self.id

        self.discord_channel = None
        self.initialize_data()
        self.slack.bot.loop.create_task(self.get_discord_channel())
        self.slack.bot.loop.create_task(self.set_slack_name())

    def initialize_data(self):
        """Initialise data of the channel in the database if needed."""
        data = db.slack_bridge.find_one(
            {'team_id': self.team.team_id,
             'bridges': {
                 '$elemMatch': {'slack_channel_id': self.id}}
             },
            {"bridges.$": 1})
        if not data or not data.get('bridges', None):
            channel_data = {
                'slack_channel_id': self.id,
                'discord_channel_id': None
            }
            db.slack_bridge.update_one(
                {'team_id': self.team.team_id},
                {'$push': {'bridges': channel_data}}
            )

    async def set_slack_name(self):
        """Set the slack name of the channel."""
        data = await self.team.app.client.conversations_info(channel=self.id)
        self.slack_name = data['channel']['name']

    async def get_discord_channel(self):
        """Get discord channel if slack channel is bridged with a discord channel."""
        data = db.slack_bridge.find_one(
            {'team_id': self.team.team_id, 'bridges': {'$elemMatch': {'slack_channel_id': self.id}}},
            {"bridges.$": 1})
        discord_channel_id = data['bridges'][0]['discord_channel_id'] if len(data['bridges']) > 0 else None

        await self.slack.bot.wait_until_ready()
        main_guild = self.slack.bot.get_guild(config.MAIN_SERVER)
        self.discord_channel = discord.utils.get(main_guild.channels, id=discord_channel_id)
        if self.discord_channel:
            self.name = self.discord_channel.name

    def unset_discord_channel(self):
        """Unsets all the alias variables and updates the database."""
        self.discord_channel = None
        self.name = self.id

        db.slack_bridge.update_one(
            {'team_id': self.team.team_id, 'bridges': {'$elemMatch': {'slack_channel_id': self.id}}},
            {'$set': {'bridges.$.discord_channel_id': None}}
        )

    def set_discord_channel(self, discord_channel: discord.TextChannel):
        """Set the discord_channel and name variable and update the database."""
        self.discord_channel = discord_channel
        self.name = discord_channel.name

        db.slack_bridge.update_one(
            {'team_id': self.team.team_id, 'bridges': {'$elemMatch': {'slack_channel_id': self.id}}},
            {'$set': {'bridges.$.discord_channel_id': discord_channel.id}}
        )


class SlackTeam:
    def __init__(self, data: dict, slack: 'Slack'):
        self.slack = slack
        self.bot = self.slack.bot

        self.team_id = data['team_id']
        self.token = data['token']
        self.bot_id = data['bot_id']
        self.name = self.team_id

        self.app = AsyncApp(token=self.token)

        self.app.view("socket_modal_submission")(self.submission)
        self.app.event("message")(self.slack_message)
        self.app.event("member_joined_channel")(self.slack_member_joined)
        self.app.event("channel_left")(self.slack_channel_left)

        self.handler = AsyncSocketModeHandler(self.app, config.SLACK_APP_TOKEN)
        self.bot.loop.create_task(self.handler.start_async())

        self.bot.add_listener(self.on_message, 'on_message')
        self.bot.add_listener(self.on_raw_message_edit, 'on_raw_message_edit')
        self.bot.add_listener(self.on_raw_message_delete, 'on_raw_message_delete')

        self.channels: list[SlackChannel] = []
        self.members: list[SlackMember] = []

        self.slack.bot.loop.create_task(self.get_team_info())

        self.discord_messages: TTLCache[int, DiscordMessage] = TTLCache(ttl=600.0, maxsize=500)
        self.slack_messages: TTLCache[str, SlackMessage] = TTLCache(ttl=600.0, maxsize=500)
        self.message_links = TTLCache(ttl=86400.0, maxsize=1000)

        self.initialize_data()
        self.messages_cached = asyncio.Event()
        self.members_cached = asyncio.Event()
        self.channels_cached = asyncio.Event()
        self.slack.bot.loop.create_task(self.cache_members())
        self.slack.bot.loop.create_task(self.cache_channels())
        self.slack.bot.loop.create_task(self.cache_messages())

    def initialize_data(self):
        """Initilises the data in the database if needed."""
        data = db.slack_bridge.find_one({'team_id': self.team_id})
        if not data:
            data = {
                'team_id': self.team_id,
                'aliases': [],
                'bridges': [],
                'tokens': {}
            }
            db.slack_bridge.insert_one(data)

    async def get_team_info(self):
        team_data = await self.app.client.team_info()
        self.name = team_data['team']['name']

    async def get_channels(self) -> list[dict]:
        """Function for getting channels, makes call to slack api and filters out channels bot isnt member of."""
        channels_data = await self.app.client.conversations_list(team_id=self.team_id)
        return [channel for channel in channels_data['channels'] if channel['is_member']]

    async def get_members(self) -> list[dict]:
        """Function for getting members, makes call to slack api and filters out bot accounts and slack bot account."""
        members_data = await self.app.client.users_list(team_id=self.team_id)
        return [
            member for member in members_data['members']
            if not member['is_bot'] and not member['id'] == 'USLACKBOT'
        ]

    async def add_user(self, user_id: str):
        user_data = await self.app.client.users_info(user=user_id)
        slack_member = SlackMember(user_data['user'], self.slack)
        await slack_member.get_discord_member()
        self.members[slack_member.team_id].append(slack_member)
        return slack_member

    def get_user(self, slack_id: str = None, *, discord_id: int = None) -> Optional[SlackMember]:
        """Get SlackMember via slack id or discord id."""
        for member in self.members:
            if (slack_id is not None and member.id == slack_id) or \
               (discord_id is not None and member.discord_member and member.discord_member.id == discord_id):
                return member

    def get_channel(self, slack_id: str = None, *, discord_id: int = None) -> Optional[SlackChannel]:
        """Get SlackChannel via slack id or discord id."""
        for channel in self.channels:
            if (slack_id is not None and channel.id == slack_id) or \
               (discord_id is not None and channel.discord_channel and channel.discord_channel.id == discord_id):
                return channel

    async def cache_messages(self):
        """Cache messages in the database."""
        await self.members_cached.wait()
        await self.channels_cached.wait()

        messages = db.slack_messages.find({'team_id': self.team_id}).sort('timestamp', 1)
        for message in messages:
            twenty_four_hours = 24 * 60 * 60
            if time.time() - message['timestamp'] > twenty_four_hours:
                db.slack_messages.delete_one(message)
                continue

            if message['origin'] == 'discord':
                self.message_links[message['discord_message_id']] = message['slack_message_id']
            elif message['origin'] == 'slack':
                self.message_links[message['slack_message_id']] = message['discord_message_id']

        self.messages_cached.set()
        self.slack.bot.logger.debug(f'{len(self.message_links)} Slack and Discord messages cached for team [{self.team_id}]')

    async def cache_channels(self):
        """Caches channels."""
        channels = await self.get_channels()
        for channel_data in channels:
            if self.get_channel(channel_data['id']):
                continue

            channel = SlackChannel(
                team=self,
                channel_id=channel_data['id'],
                slack=self.slack,
            )
            self.channels.append(channel)

        self.channels_cached.set()
        self.slack.bot.logger.debug(f'{len(channels)} Slack channels cached for team [{self.team_id}]')

    async def cache_members(self):
        """Caches members."""
        members = await self.get_members()
        for member_data in members:
            if self.get_user(member_data['id']):
                continue

            member = SlackMember(
                data=member_data,
                slack=self.slack,
            )
            self.slack.bot.loop.create_task(member.get_discord_member())
            self.members.append(member)

        self.members_cached.set()
        self.slack.bot.logger.debug(f'{len(members)} Slack member cached for team [{self.team_id}]')

    async def delete_discord_message(self, channel_id: int, message_id: int, *, ts: str = None):
        await self.slack.bot.http.delete_message(channel_id, message_id)

        if ts in self.slack_messages:
            del self.slack_messages[ts]

        db.slack_messages.delete_one({'slack_message_id': ts})

    async def delete_slack_message(self, message_id: str, discord_channel_id: int, *, discord_message_id: int = None):
        slack_channel = self.get_channel(discord_id=discord_channel_id)

        await self.app.client.chat_delete(channel=slack_channel.id, ts=message_id)
        if discord_message_id in self.discord_messages:
            del self.discord_messages[discord_message_id]

        db.slack_messages.delete_one({'discord_message_id': discord_message_id})

    async def get_slack_message(self, channel_id: str, message_id: str, discord_message_id: int = None) -> Optional[SlackMessage]:
        if message_id is None:
            return

        result = await self.app.client.conversations_history(
            channel=channel_id,
            inclusive=True,
            oldest=message_id,
            limit=1
        )
        if not result or not result['messages']:
            return

        message = result['messages'][0]
        data = {
            'event': {
                'team_id': message['team_id'],
                'user': message['user'] if 'user' in message else message['username'],
                'discord_message_id': discord_message_id,
                'channel': channel_id,
                'text': message['text'],
                'ts': message_id,
                'files': [],
                'subtype': ''
            }
        }
        return SlackMessage(data, self.slack)

    async def get_discord_message(self, channel_id: int, message_id: int, slack_message_id: str = None) -> Optional[DiscordMessage]:
        channel = self.slack.bot.get_channel(channel_id)

        try:
            message = await channel.fetch_message(message_id)
        except:
            # most-likely errors when message has been deleted
            db.slack_messages.delete_one({'discord_message_id': message_id})
            return

        if message:
            discord_message = DiscordMessage(message, self.slack)
            discord_message.slack_message_id = slack_message_id
            return discord_message
        else:
            db.slack_messages.delete_one({'discord_message_id': message_id})

    async def submission(self, ack):
        """Function that acknowledges events."""
        await ack()

    async def slack_channel_left(self, body: dict):
        """Function called when bot leaves a channel"""
        event = body['event']
        channel_id = event['channel']
        channel = self.get_channel(channel_id)
        if channel:
            db.slack_bridge.update_one(
                {'team_id': self.team_id},
                {'$pull': {'bridges': {'slack_channel_id': channel_id}}}
            )
            self.channels.remove(channel)

    async def slack_member_joined(self, body: dict):
        event = body['event']
        channel_id = event['channel']
        user_id = event['user']
        if user_id == self.bot_id:
            channel = SlackChannel(self, channel_id, self.slack)
            self.channels.append(channel)
        else:
            user_data = await self.app.client.users_info(user=user_id)
            member = SlackMember(user_data['user'], self.slack)
            self.members.append(member)

    async def handle_delete_message(self, body: dict):
        event = body['event']

        ts = event['deleted_ts']
        channel_id = event['channel']

        slack_message = self.slack_messages.get(ts, None)
        slack_message_link = self.message_links.get(ts, None)

        if not slack_message:
            slack_channel = self.get_channel(slack_id=channel_id)
            if not slack_channel.discord_channel or not slack_message_link:
                return
            return await self.delete_discord_message(slack_channel.discord_channel.id, slack_message_link, ts=ts)

        return await slack_message.delete()

    async def handle_edit_message(self, body: dict):
        event = body['event']

        ts = event['message']['ts']
        channel_id = event['channel']

        # check if message was edited by the bot
        edit_message = next(filter(lambda dm: dm.slack_message_id == ts, self.discord_messages.values()), None)
        if edit_message:
            return

        slack_message = self.slack_messages.get(ts, None)
        if not slack_message:
            slack_message_link = self.message_links[ts] if ts in self.message_links else None
            slack_message = await self.get_slack_message(channel_id, ts, slack_message_link)

        if slack_message:
            slack_message.text = event['message']['text']
            asyncio.create_task(
                slack_message.send_to_discord(edit=True)
            )

    async def slack_message(self, body):
        """Function called on message even from slack."""
        await self.messages_cached.wait()

        event = body['event']
        is_delete = 'subtype' in body['event'] and body['event']['subtype'] == 'message_deleted'
        is_edit = 'subtype' in body['event'] and body['event']['subtype'] == 'message_changed'
        is_bot_message = 'subtype' in body['event'] and body['event']['subtype'] == 'bot_message'

        if is_edit:
            return await self.handle_edit_message(event)
        if is_delete:
            return await self.handle_delete_message(event)

        if is_bot_message:
            return

        message = SlackMessage(body, self.slack)
        asyncio.create_task(
            message.send_to_discord()
        )

    # Discord events

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        channel_id = payload.channel_id

        slack_channel = self.get_channel(discord_id=channel_id)
        if not slack_channel:
            return

        team = slack_channel.team
        await team.messages_cached.wait()

        message_id = payload.message_id
        discord_message = team.discord_messages.get(message_id, None)
        if not discord_message:
            discord_message_link = team.message_links[message_id]
            return await team.delete_slack_message(discord_message_link, channel_id, discord_message_id=message_id)

        await discord_message.delete()

    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        """
        Function called on on_edit_message event, used for dealing with message edit events on the discord side
        and doing the same on the slack end.
        """
        if 'content' not in payload.data:
            return

        channel_id = payload.channel_id

        slack_channel = self.get_channel(discord_id=channel_id)
        if not slack_channel:
            return

        team = slack_channel.team
        await team.messages_cached.wait()

        message_id = payload.message_id
        content = payload.data['content']
        cached_message = team.discord_messages.get(message_id, None)
        if not cached_message:
            cached_message_link = team.message_links.get(message_id, None)
            cached_message = await team.get_discord_message(channel_id, message_id, cached_message_link)
            if cached_message is None:
                return

        cached_message.text = content
        await cached_message.send_to_slack(edit=True)

    async def on_message(self, message: discord.Message):
        """Function call on on_message event, used for identifying discord bridge channel and forwarding the messages to slack."""
        # ignore webhook messages and pms
        if not message.guild or message.webhook_id:
            return

        slack_channel = self.get_channel(discord_id=message.channel.id)
        if not slack_channel:
            return

        await self.messages_cached.wait()

        discord_message = DiscordMessage(message, self.slack)
        await discord_message.send_to_slack()


class Slack:
    def __init__(self, bot):
        self.bot = bot
        self.logger = self.bot.logger

        self.teams: list[SlackTeam] = []
        self.cache_teams()

    def get_team(self, team_id: str) -> Optional[SlackTeam]:
        return next(filter(lambda team: team.team_id == team_id, self.teams), None)

    def cache_teams(self):
        teams = db.slack_bridge.find({})
        for team_data in teams:
            team = SlackTeam(team_data, self)
            self.teams.append(team)

    def get_user(self, slack_id: str = None, *, discord_id: int = None) -> Optional[SlackMember]:
        """Get SlackMember via slack id or discord id."""
        for team in self.teams:
            member = team.get_user(slack_id, discord_id=discord_id)
            if member:
                return member

    def get_channel(self, slack_id: str = None, *, discord_id: int = None) -> Optional[SlackChannel]:
        """Get SlackChannel via slack id or discord id."""
        for team in self.teams:
            channel = team.get_channel(slack_id, discord_id=discord_id)
            if channel:
                return channel
