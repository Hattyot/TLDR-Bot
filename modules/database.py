import pymongo
import config

from ukparliament.bills_tracker import FeedUpdate
from ukparliament.divisions_tracker import LordsDivision, CommonsDivision
from typing import Union
from bson import ObjectId

active_connection = None


class Connection:
    """
    Database handler. Creates connection to the database.

    Attributes
    ---------------
    mongo_client: :class:`pymongo.MongoClient`
        The pymongo client.

    db: :class:`pymongo.database.Database`
        The TLDR database.

    leveling_users: :class:`pymongo.collection.Collection`
        The leveling_users collection.
            {
                "guild_id" : :class:`int`,
                "user_id" : :class:`int`,
                "pp" : :class:`int`,
                "p_level" : :class:`int`,
                "hp" : :class:`int`,
                "h_level" : :class:`int`,
                "p_role" : :class:`str`,
                "h_role" : :class:`str`,
                "settings" : {
                    "@_me" : bool
                },
                "rep_timer" : :class:`int`,
                "last_rep" : :class:`int`,
                "rep" : :class:`int`,
                "boosts" : {
                    :class:`str`: {
                        "expires": :class:`int`,
                        "multiplier": float
                    }
                },
                "rp" : :class:`int`
            }

    leveling_data: :class:`pymongo.collection.Collection`
        The leveling_data collection.
            {
                "guild_id" : :class:`int`,
                "level_up_channel" : :class:`int`,
                "leveling_routes" : {
                    "parliamentary" : [
                        {
                            "name" : :class:`str`,
                            "perks" : List[:class:`str`]
                        }
                    ],
                    "honours" : [
                        {
                            "name" : :class:`str`,
                            "perks" : List[:class:`str`]
                        }
                    ]
                },
                "honours_channels" : List[:class:`int`],
                "automember" : bool
            }

    left_leveling_users: :class:`pymongo.collection.Collection`
        The left_leveling_users collection for holding members who have left their guild.
        Same as leveling_users.

    timers: :class:`pymongo.collection.Collection`
        The timers collection
            {
                "guild_id" : :class:`int`,
                "expires" : :class:`int`,
                "event" : :class:`str`,
                "extras" : :class:`dict`
            }

    commands: :class:`pymongo.collection.Collection`
        The commands collection
            {
                "guild_id" : :class:`int`,
                "command_name" : :class:`str`,
                "disabled" : :class:`int`,
                "user_access" : {
                    "user id" : "take" or "give"
                },
                "role_access" : {
                    "role id" : "take" or "give"
                }
            }

    daily_debates: :class:`pymongo.collection.Collection`
        The daily_debates collection
            {
                "guild_id" : :class:`int`,
                "channel_id" : :class:`int`,
                "poll_channel_id" : :class:`int`,
                "role_id" : :class:`int`,
                "time" : :class:`str`,
                "topics" : [
                    {
                        "topic" : :class:`str`
                        "topic_author_id" : :class:`int`,
                        "topic_options" : :class:`str`
                    },
                ]
            }

    tickets: :class:`pymongo.collection.Collection`
        The tickets collection
            {
                "guild_id" : :class:`int`,
                "ticket_channel_id" : :class:`int`,
                "ticket_author_id" : :class:`int`
            }

    custom_commands: :class:`pymongo.collection.Collection`
        The custom_commands collection
            {
                "name" : :class:`str`,
                "response" : :class:`str`,
                "clearance-groups" : :class:`list`,
                "clearance-roles" : :class:`list`,
                "clearance-users" : :class:`list`,
                "response-channel" : :class:`int`,
                "command-channels" : List[:class:`int`],
                "reactions" : List[:class:`str`],
                "python" : :class:`str`,
                "pre" : :class:`str`,
                "guild_id" : :class:`int`
            }

    watchlist: :class:`pymongo.collection.Collection`
        The watchlist collection
            {
                "guild_id" : :class:`int`,
                "user_id" : :class:`int`,
                "filters" : List[:class:`str`],
                "channel_id" : :class:`int`
            }

    cases: :class:`pymongo.collection.Collection`
        The cases collection
            {
                'guild_id': :class:`int`,
                'user_id': :class:`int`,
                'type': :class:`str`,
                'reason': :class:`str`,
                'created_at': :class:`int`,
                'moderator': :class:`int`,
                'case_number': :class:`int`
            }
    guild_settings :class:`pymongo.collection.Collection`
        The guild settings collection
            {
                'guild_id': :class:`int`,
                'mute_role_id': :class:`int`,
                'slack_bridges': {
                   'slack_channel_id': 'discord_channel_id'
                }
            }
    bills_tracker: :class:`pymongo.collection.Collection`
        The bills tracker collection:
            {
                'bill_id': :class:`int`,
                'stage': :class:`str`,
                'timestamp': :class:`str`
            }
    divisions_tarcker: :class:`pymongo.collection.Collection`
        The divisions tracker collection:
            {
                'bill_id': :class:`int`
                'division_id': :class:`int`
            }
    webhooks: :class:`pymongo.collection.Collection`
        The webhooks collection
            {
                "channel_id": :class:`int`,
                'url': :class:`str`
            }
    slack_bridge :class:`pymongo.collection.Collection`
        The collection for the slack bridge system
            {
                'aliases': [
                    {
                        "slack_id": :class:`str`
                        "discord_id": :class:`int`
                    }
                ]
                'bridges': [
                    {
                        "slack_channel_id": :class:`str`
                        "discord_channel_id": :class:`int`
                    }
                ]
            }
    slack_messages :class:`pymongo.collection.Collection`
        The collection for keeping track of which slack message corresponds to which discord message and vice-versa.
            {
                'slack_message_id': :class:`str`
                'discord_message_id': :class:`int`
                'slack_channel_id': :class:`str`
                'discord_channel_id': :class:`str`
                'origin': :class:`str`
                'files': :class:`list`
                'text': :class:`str`
                'user_id': :class`str`
                'timestamp': :class:`int`
            }
    tasks :class:`pymongo.collection.Collection`
        The collection for linking the api and the main bot through running tasks.
            {
                'function': :class:`str`  # name of the function in tasks that will be called
                'kwargs': :class:`dict`
            }
    """
    def __init__(self):
        self.mongo_client = pymongo.MongoClient(config.MONGODB_URL)
        self.db = self.mongo_client["TLDR"]
        self.leveling_users = self.db["leveling_users"]
        self.leveling_data = self.db["leveling_data"]
        self.left_leveling_users = self.db["left_leveling_users"]
        self.timers = self.db["timers"]
        self.commands = self.db["commands"]
        self.daily_debates = self.db["daily_debates"]
        self.tickets = self.db["tickets"]
        self.custom_commands = self.db["custom_commands"]
        self.watchlist = self.db["watchlist"]
        self.cases = self.db["cases"]
        self.bills_tracker = self.db["bills_tracker"]
        self.divisions_tracker = self.db["divisions_tracker"]
        self.guild_settings = self.db["guild_settings"]
        self.webhooks = self.db['webhooks']
        self.slack_bridge = self.db['slack_bridge']
        self.slack_messages = self.db['slack_messages']
        self.tasks = self.db['tasks']

    def clear_bills_tracker_collection(self):
        self.bills_tracker.delete_many({})

    def clear_divisions_tracker_collection(self):
        self.divisions_tracker.delete_many({})

    def get_bills_tracker_count(self):
        return self.bills_tracker.count_documents({})

    def get_divisions_tracker_count(self):
        return self.divisions_tracker.count_documents({})

    def is_bill_update_stored(self, bill_id: int, update: FeedUpdate):
        """
        Check if a bill update from a feed is stored.
        """
        feed_update = self.bills_tracker.find_one(
            {
                "bill_id": bill_id,
                "timestamp": update.get_update_date().isoformat(),
                "stage": update.get_stage(),
            }
        )

        return feed_update is not None

    def add_bill_feed_update(self, bill_id: int, update: FeedUpdate):
        """
        Adds a feed update to the collection under the bill's id.
        """
        if self.is_bill_update_stored(bill_id, update):
            return
        self.bills_tracker.insert_one(
            {
                "bill_id": bill_id,
                "timestamp": update.get_update_date().isoformat(),
                "stage": update.get_stage(),
            }
        )

    def get_bill_last_update(self, bill_id):
        """
        Fetches the most recent update in a feed stored in the relevant
        collection.
        """
        entries = self.bills_tracker.find({"bill_id": bill_id}).sort(
            [("timestamp", pymongo.DESCENDING)]
        )
        return entries[0] if entries.count() > 0 else None

    def is_division_stored(self, division: Union[LordsDivision, CommonsDivision]):
        """
        Checks if a division that is not related to a bill has already been stored in the relevant collection
        """
        entry = self.divisions_tracker.find_one({"division_id": division.get_id()})
        return entry is not None

    def add_division(self, division: Union[LordsDivision, CommonsDivision]):
        """
        Stores a division that is not related to a bill.
        """
        if self.is_division_stored(division):
            return
        self.divisions_tracker.insert_one(
            {"bill_id": 0, "division_id": division.get_id()}
        )

    def is_bill_division_stored(
        self, bill_id: int, division: Union[LordsDivision, CommonsDivision]
    ):
        """
        Check if a division that is also related has already been stored in the relevant collection.
        """
        entry = self.divisions_tracker.find_one(
            {"bill_id": bill_id, "division_id": division.get_id()}
        )
        return entry is not None

    def add_bill_division(
        self, bill_id: int, division: Union[LordsDivision, CommonsDivision]
    ):
        """
        Store a divisin that is related to a bill.
        """
        if self.is_bill_division_stored(bill_id, division):
            return
        self.divisions_tracker.insert_one(
            {"bill_id": bill_id, "division_id": division.get_id()}
        )

    def get_bill_divisions(self, bill_id: int):
        """
        Fetch the division ids asscoatied with the provided bill id.
        """
        divisions = self.divisions_tracker.find({"bill_id": bill_id}).distinct(
            "division_id"
        )
        return divisions

    def get_guild_settings(self, guild_id: int) -> dict:
        """
        Get Settings attached to guild that dont fit in other collections.

        Parameters
        ----------------
        guild_id: :class:`int`
            ID of the guild.

        Returns
        -------
        :class:`dict`
            Guild's settings.
        """
        guild_settings = self.guild_settings.find_one({"guild_id": guild_id})
        if guild_settings is None:
            guild_settings = {"guild_id": guild_id, "mute_role_id": None}
            self.guild_settings.insert_one(guild_settings)

        return guild_settings

    def get_leveling_user(self, guild_id: int, member_id: int) -> dict:
        """
        Get member's leveling data from the database, if user isn't in the database, they will be added.

        Parameters
        ----------------
        guild_id: :class:`int`
            ID of the member's guild.
        member_id: :class:`int`
            ID of the member.

        Returns
        -------
        :class:`dict`
            Leveling data on the member.
        """
        leveling_user = self.leveling_users.find_one(
            {"guild_id": guild_id, "user_id": member_id}
        )

        if leveling_user is None:
            # add user to leveling_user collection
            leveling_user = schemas["leveling_user"]
            leveling_user["guild_id"] = guild_id
            leveling_user["user_id"] = member_id
            self.leveling_users.insert_one(leveling_user.copy())

        return leveling_user

    def get_leveling_data(self, guild_id: int, fields: dict = None) -> dict:
        """
        Get guild's leveling data from the database, if guild isn't in the database, it will be added.

        Parameters
        ----------------
        guild_id: :class:`int`
            ID of the guild.
        fields: Optional[:class:`dict`]
            what fields to return when querying the database, if not set, all the data will be returned.

        Returns
        -------
        :class:`dict`
            Leveling data of the guild.
        """
        if fields is None:
            fields = {}

        if fields:
            leveling_data = self.leveling_data.find_one({"guild_id": guild_id}, fields)
        else:
            leveling_data = self.leveling_data.find_one({"guild_id": guild_id})

        if not leveling_data:
            leveling_data = schemas["leveling_data"]
            leveling_data["guild_id"] = guild_id
            self.leveling_data.insert_one(leveling_data.copy())

        return leveling_data

    def get_command_data(self, command_name: str, *, insert: bool = False) -> dict:
        """
        Get data on a command from the database.

        Parameters
        ----------------
        command_name: :class:`int`
            Name of the command
        insert: Optional[:class:`bool`]
            If True, command data will be inserted into the database.

        Returns
        -------
        :class:`dict`
            The command data.
        """
        command_data = self.commands.find_one({"command_name": command_name})
        if command_data is None:
            command_data = {
                "command_name": command_name,
                "disabled": 0,
            }
            if insert:
                self.commands.insert_one(command_data)

        return command_data

    def get_daily_debates(self, guild_id: int) -> dict:
        """
        Get daily debates data of a guild.

        Parameters
        ----------------
        guild_id: :class:`int`
            ID of the guild.

        Returns
        -------
        :class:`dict`
            The daily debate data.
        """
        daily_debates = self.daily_debates.find_one({"guild_id": guild_id})
        if not daily_debates:
            daily_debates = schemas["daily_debates"]
            daily_debates["guild_id"] = guild_id
            self.daily_debates.insert_one(daily_debates)

        return daily_debates

    def get_automember(self, guild_id: int) -> bool:
        """
        Get automember setting of guild.

        Parameters
        ----------------
        guild_id: :class:`int`
            ID of the guild.

        Returns
        -------
        :class:`bool`
            True if automember is enabled, False if not.
        """
        leveling_data = self.get_leveling_data(guild_id, {"automember": 1})
        if not leveling_data or "automember" not in leveling_data:
            self.leveling_data.update_one(
                {"guild_id": guild_id}, {"$set": {"automember": False}}
            )
            automember = False
        else:
            automember = leveling_data["automember"]

        return automember

    def get_cases(self, guild_id: int, **kwargs) -> list:
        """
        Get cases based on given kwargs.

        Parameters
        ----------------
        guild_id: :class:`int`
           ID of the guild.
        kwargs: :class:`dict`
           Different values to search for cases by.

        Returns
        -------
        :class:`list`
           All the found cases.
        """
        query = {"guild_id": guild_id, **kwargs}
        return [c for c in self.cases.find(query).sort({"created_at": 1})]

    def add_case_logs(self, case_id: ObjectId, logs_url: str):
        """
        Set the logs url for a case.

        Parameters
        ___________
        case_id: :class:`ObjectId`
           ID of the case.
        logs_url: :class:`str`
           url of the logs.
        """
        self.cases.update_one({"_id": case_id}, {"$set": {"logs_url": logs_url}})


def get_connection():
    """
    Set the global connection variable active_connection to an active connection to the database.
    If it's already set, it returns active_connection.
    """

    global active_connection
    if active_connection is None:
        active_connection = Connection()

    return active_connection


schemas = {
    "leveling_user": {
        "pp": 0,  # Participation points or parliamentary points
        "p_level": 0,  # parliamentary level
        "hp": 0,  # honours points
        "h_level": 0,  # honours level
        "p_role": "",  # parliamentary role
        "h_role": None,  # honours role
        "settings": {
            "@_me": False  # setting to check if user wants to be @'d when they level up
        },
        "rp": 0,
        "rep_timer": 0,
        "last_rep": 0,
        "boosts": {
            # 'rep': {
            #     'expires': 0,
            #     'multiplier': 0
            # }
        },
    },
    "leveling_data": {
        "guild_id": 0,
        "level_up_channel": 0,
        "leveling_routes": {"parliamentary": [], "honours": []},
        "honours_channels": [],
    },
    "daily_debates": {
        "guild_id": 0,
        "channel_id": 0,
        "poll_channel_id": 0,
        "role_id": 0,
        "time": 0,
        "topics": [],
    },
}
