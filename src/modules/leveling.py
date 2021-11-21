from __future__ import annotations

import math
import time
from datetime import datetime
from typing import List, Optional, Tuple, Union

import config
import discord
from pymongo.collection import Collection

from modules import database
from modules.utils import get_guild_role, get_member_by_id

db = database.get_connection()


class DatabaseList(list):
    """
    Special list which co-opts the append, remove and other methods, so the same values can be updated in the database.
    since append and remove don't set the value of the list, the __setattr__ method couldn't be used and this had to be created.

    To keep things simple, __delitem__ and insert methods automatically raise an exception.

    Attributes
    ---------------
    collection: :class:`pymongo.collection.Collection`
        The collection that the list is tied to.
    query_filter: :class:`dict`
        Filter used in database queries.
    key: :class:`str`
        Key used in database queries when setting value.
    *args:
        Initial values that will be set in the list.
    """

    def __init__(self, collection: Collection, query_filter: dict, key: str, *args):
        self.collection = collection
        self.query_filter = query_filter
        self.key = key

        super().__init__()
        self.extend(list(args))

    def __delitem__(self, index: int):
        """Hard to implement, so it will raise exception."""
        raise Exception("Del operation not allowed on DatabaseList")

    def __setitem__(self, index: int, value):
        """Set item by index."""
        self.collection.update_one(
            self.query_filter,
            {
                "$set": {
                    f"{self.key}.{index}": value
                    if type(value) != LevelingRole
                    else value.values()
                }
            },
        )
        super()[index] = value

    def insert(self, index: int, value):
        """Hard to implement, so it will raise exception."""
        raise Exception("Insert operation not allowed on DatabaseList")

    def append(self, item) -> None:
        """Method that pushes item to list and database list."""
        self.collection.update_one(
            self.query_filter,
            {
                "$push": {
                    self.key: item if type(item) != LevelingRole else item.values()
                }
            },
        )
        super().append(item)

    def remove(self, item) -> None:
        """Method that removes item from list and database list."""
        self.collection.update_one(
            self.query_filter,
            {
                "$pull": {
                    self.key: item if type(item) != LevelingRole else item.values()
                }
            },
        )
        super().remove(item)


class Boost:
    """
    Holds boost data and implements some functionality for the boost.

    A boost gives a user (multiplier * 100)% more parliamentary points.

    Attributes
    ---------------
    leveling_member: :class:`LevelingMember`
        The LevelingMember who has the boost.
    boost_type: :class:`str`
        Type of the boost, rep, daily_debate, etc etc.
    multiplier: :class:`int`
        Multiplier of the boost, a multiplier is a floating point number. Example: 0.15 -> 15% more parliamentary points.
    expires: :class:`int`
        Time when boost expires - unix epoch.
    """

    def __init__(self, leveling_member: LevelingMember, boost_type: str, boost: dict):
        self.leveling_member = leveling_member
        self.boost_type = boost_type
        self.multiplier = boost.get("multiplier", 0)
        self.expires = boost.get("expires", 0)

    def has_expired(self):
        """
        Check if boost has expired.

        Returns
        -------
        :class:`bool`
            True if boost has expires, False if it hasn't
        """
        return round(time.time()) > self.expires

    def remove(self):
        """Delete boost from the database."""
        db.leveling_users.update_one(
            {
                "guild_id": self.leveling_member.guild.id,
                "user_id": self.leveling_member.id,
            },
            {"$unset": {f"boosts.{self.boost_type}": 1}},
        )

    def values(self):
        """Returns info in the form of a dictionary."""
        return {"multiplier": self.multiplier, "expires": self.expires}

    def __setattr__(self, key, value):
        """For some variables, changing their value will also edit the entry in the database."""
        if (
            key in ["multiplier", "expires"]
            and key in self.__dict__
            and self.__dict__[key] != value
        ):
            db.leveling_users.update_one(
                {
                    "guild_id": self.leveling_member.guild.id,
                    "user_id": self.leveling_member.id,
                },
                {"$set": {f"boosts.{self.boost_type}.{key}": value}},
            )
        self.__dict__[key] = value


class LevelingUserBoosts:
    """
    Represents LevelingUser's boosts.

    Attributes
    ---------------
    leveling_member: :class:`LevelingMember`
        The LevelingMember to whom these boosts belong to.
    rep: :class:`Boost`
        The rep boost a user can have.
    daily_debate: :class:`Boost`
        The daily debate boost a user can have.
    """

    def __init__(self, leveling_member: LevelingMember, boosts: dict):
        self.leveling_member = leveling_member
        self.rep = Boost(leveling_member, "rep", boosts.get("rep", {}))
        self.daily_debate = Boost(
            leveling_member, "daily_debate", boosts.get("daily_debate", {})
        )

    def __iter__(self):
        """
        Iter over list of boosts, where boost is included if it has an actual expires time and multiplier.
        If a boost has an expires time of 0, it means it isn't set in the database
        """
        yield from [
            *filter(
                lambda boost: boost.expires > 0
                and boost.multiplier > 0
                and not boost.has_expired(),
                [self.rep, self.daily_debate],
            )
        ]

    def __bool__(self):
        """Returns True if there are any active boosts"""
        return bool(
            [*filter(lambda boost: boost.expires > 0, [self.rep, self.daily_debate])]
        )

    def get_multiplier(self) -> int:
        """
        Get the sum of all the boosts multipliers + 1

        Returns
        -------
        :class:`int`
            Multiplier sum of boosts.
        """
        multiplier = 1
        for boost in self:
            if boost.has_expired():
                boost.remove()

            multiplier += boost.multiplier

        return multiplier

    def __setattr__(self, key, value):
        """For some variables, changing their value will also edit the entry in the database."""
        if (
            key in ["rep", "daily_debate"]
            and key in self.__dict__
            and self.__dict__[key] != value
            and type(value) == Boost
        ):
            db_value = value.values()
            db.leveling_users.update_one(
                {
                    "guild_id": self.leveling_member.guild.id,
                    "user_id": self.leveling_member.id,
                },
                {"$set": {f"boosts.{key}": db_value}},
            )

        self.__dict__[key] = value


class LevelingUserSettings:
    """
    Represents LevelingUser's settings.

    Also implements some functionality for the settings.

    Attributes
    ---------------
    leveling_member: :class:`LevelingMember`
        The LevelingMember.
    at_me: :class:`bool`
        The @me setting, if True, member will be @'d when they level up.
    rep_at: :class:`bool`
        The rep@ setting, if True, after a user gives a rep to someone, a timer will be started to @ them when the timer is over.
    """

    def __init__(self, leveling_member: LevelingMember, settings: dict):
        self.leveling_member = leveling_member
        self.at_me = settings.get("@_me", False)
        self.rep_at = settings.get("rep@", False)

    def toggle_at_me(self):
        """Toggle @me setting."""
        self.at_me = not bool(self.at_me)
        db.leveling_users.update_one(
            {
                "guild_id": self.leveling_member.guild.id,
                "user_id": self.leveling_member.id,
            },
            {"$set": {"settings.@_me": self.at_me}},
        )

    def toggle_rep_at(self):
        """Toggle rep@ setting."""
        self.rep_at = not bool(self.rep_at)
        db.leveling_users.update_one(
            {
                "guild_id": self.leveling_member.guild.id,
                "user_id": self.leveling_member.id,
            },
            {"$set": {"settings.rep@": self.rep_at}},
        )


class LevelingUserBranch:
    """
    Represents the data a user has on a branch, points, level, role etc etc.

    Attributes
    ---------------
    leveling_member: :class:`LevelingMember`
        The LevelingMember.
    branch: :class:`LevelingRoute`
        The leveling route.
    points: :class:`int`
        The amount of points the user has on the branch.
    level: :class:`int`
        The level the user has on the branch.
    role: :class:`str`
        The role the user has on the branch.
    """

    def __init__(
        self,
        leveling_member: LevelingMember,
        branch: LevelingRoute,
        points: int,
        level: int,
        role: str,
    ):
        self.leveling_member = leveling_member
        self.branch = branch
        self.points = points
        self.level = level
        self.role = role

    def __setattr__(self, key, value):
        """For some variables, changing their value will also edit the entry in the database."""
        if (
            key in ["points", "level", "role"]
            and key in self.__dict__
            and self.__dict__[key] != value
        ):
            key_switch = {
                "points": f"{self.branch.name[0]}p",
                "level": f"{self.branch.name[0]}_level",
                "role": f"{self.branch.name[0]}_role",
            }
            db.leveling_users.update_one(
                {
                    "guild_id": self.leveling_member.guild.id,
                    "user_id": self.leveling_member.id,
                },
                {"$set": {key_switch.get(key): value}},
            )

        self.__dict__[key] = value


class LevelingUser:
    """
    Represents all the data in the database on a user.

    Attributes
    ---------------
    leveling_member: :class:`LevelingMember`
        The LevelingMember.
    parliamentary: :class:`LevelingUserBranch`
        The user branch with all the parliamentary data.
    honours: :class:`LevelingUserBranch`
        The user branch with all the honours data.
    settings: :class:`LevelingUserSettings`
        The user's settings.
    reputation: :class:`LevelingUserBranch`
        The user branch with reputation points, needed in some places.
    rp: :class:`int`
        The amount of reputation points the user has.
    last_rep: :class:`int`
        The ID of the user that LevelingUser gave a reputation point last.
    rep_timer: :class:`int`
        Time in seconds when the LevelingUser can give a reputation point again.
    boosts: :class:`LevelingUserBoosts`
        Represents all the boosts user can have.
    """

    def __init__(self, leveling_member: LevelingMember, leveling_user_data: dict):
        self.leveling_member = leveling_member

        self.parliamentary = LevelingUserBranch(
            leveling_member,
            self.leveling_member.guild.leveling_routes.parliamentary,
            leveling_user_data["pp"],
            leveling_user_data["p_level"],
            leveling_user_data["p_role"],
        )

        self.honours = LevelingUserBranch(
            leveling_member,
            self.leveling_member.guild.leveling_routes.honours,
            leveling_user_data["hp"],
            leveling_user_data["h_level"],
            leveling_user_data["h_role"],
        )

        self.settings = LevelingUserSettings(
            leveling_member, leveling_user_data.get("settings", {})
        )

        # this is needed in some places like the leaderboard command
        self.reputation = LevelingUserBranch(
            leveling_member,
            self.leveling_member.guild.leveling_routes.reputation,
            leveling_user_data.get("rp", 0),
            0,
            "",
        )

        self.rp = leveling_user_data.get("rp", 0)
        self.last_rep = leveling_user_data.get("last_rep", 0)
        self.rep_timer = leveling_user_data.get("rep_timer", 0)

        self.boosts = LevelingUserBoosts(
            leveling_member, leveling_user_data.get("boosts", {})
        )

    @property
    def rep_timer_expired(self) -> bool:
        """
        See if :attr:`rep_timer` has expired.

        Returns
        -------
        :class:`bool`
            True if timer has expired, False if it hasn't.
        """
        return round(time.time()) > self.rep_timer

    @property
    def rep_time_left(self) -> int:
        """
        See how many seconds left until timer expires.

        Returns
        -------
        :class:`int`
            Seconds left until timer expires.

        """
        return self.rep_timer - round(time.time())

    def __setattr__(self, key, value):
        """For some variables, changing their value will also edit the entry in the database."""
        if (
            key in ["rp", "rep_timer", "last_rep"]
            and key in self.__dict__
            and self.__dict__[key] != value
        ):
            db.leveling_users.update_one(
                {
                    "guild_id": self.leveling_member.guild.id,
                    "user_id": self.leveling_member.id,
                },
                {"$set": {key: value}},
            )

        self.__dict__[key] = value


class LevelingRole:
    """
    Represents a leveling role attached to a :class:`LevelingRoute`.

    Attributes
    ---------------
    guild: :class:`discord.Guild`
        The discord guild object.
    branch: :class:`LevelingRoute`
        The leveling route of the role.
    name: :class:`str`
        The name of the role.
    name: :class:`list`
        List of the perks the role has to offer.
    """

    def __init__(
        self, guild: discord.Guild, branch: LevelingRoute, leveling_role: dict
    ):
        self.guild = guild
        self.branch = branch
        self.name = leveling_role.get("name", "")
        self.perks = DatabaseList(
            db.leveling_data,
            {
                "guild_id": self.guild.id,
                f"leveling_routes.{self.branch}": {"$elemMatch": {"name": self.name}},
            },
            f"leveling_routes.{self.name}.$.perks",
            *leveling_role.get("perks", []),
        )

    def values(self):
        """Returns info in the form of a dictionary."""
        return {"name": self.name, "perks": self.perks}

    async def get_guild_role(self) -> discord.Role:
        """
        Get a the guild role object. If a role by the LevelingRoles name doesn't exist, it will be crated.

        Returns
        -------
        :class:`discord.Role`
            The discord role.
        """
        # TODO: maybe cache this value?
        role = await get_guild_role(self.guild, self.name)
        # if role doesnt exist, create it
        if role is None:
            role = await self.guild.create_role(name=self.name)

        return role

    def __setattr__(self, key, value):
        """For some variables, changing their value will also edit the entry in the database."""
        if (
            key in ["name", "perks"]
            and key in self.__dict__
            and self.__dict__[key] != value
        ):
            db.leveling_data.update_one(
                {
                    "guild_id": self.guild.id,
                    f"leveling_routes.{self.branch}": {
                        "$elemMatch": {"name": self.name}
                    },
                },
                {f"$set": {f"leveling_routes.{self.name}.$.{key}": value}},
            )

        # special case for perks
        if key == "perks" and "perks" in self.__dict__:
            self.__dict__[key].list = value
            return

        self.__dict__[key] = value


class LevelingRoute:
    """
    Represents a leveling route.

    Attributes
    ---------------
    guild: :class:`discord.Guild`
        The discord guild object.
    name: :class:`str`
        The name of the leveling route.
    roles: :class:`DatabaseList`
        List of roles in the route.
    """

    def __init__(self, guild: discord.Guild, name: str, roles: list):
        self.guild = guild
        self.name = name
        self.roles = DatabaseList(
            db.leveling_data,
            {"guild_id": self.guild.id},
            f"leveling_routes.{self.name}",
            *[LevelingRole(guild, self, role) for role in roles],
        )

    def find_role(self, role_name: str) -> Optional[LevelingRole]:
        """
        Get a role in the LevelingRoute.

        Parameters
        ----------------
        role_name: :class:`str`
            The name of the role that will be searched for.

        Returns
        -------
        Optional[:class:`LevelingRole`]
            The LevelingRole or `None` if it isn't found.
        """
        for role in self.roles:
            if role.name.lower() == role_name.lower():
                return role

    def __iter__(self):
        """Iterator magic method to loop over the LevelingRoute's roles."""
        yield from self.roles


class LevelingRoutes:
    """
    Represents all the leveling routes attached to :class:`LevelingGuild`.

    Attributes
    ---------------
    guild: :class:`discord.Guild`
        The discord guild object.
    parliamentary: :class:`LevelingRoute`
        The parliamentary route.
    honours: :class:`LevelingRoute`
        The honours route.
    reputation: :class:`LevelingRoute`
        The reputation route.
    """

    def __init__(self, guild: discord.Guild, leveling_routes: dict):
        self.guild = guild
        self.parliamentary = LevelingRoute(
            guild, "parliamentary", leveling_routes.get("parliamentary", [])
        )
        self.honours = LevelingRoute(
            guild, "honours", leveling_routes.get("honours", [])
        )
        self.reputation = LevelingRoute(guild, "reputation", [])  # need in some places

    def get_leveling_role(self, role_name: str) -> LevelingRole:
        """
        Get :class:`LevelingRole` by it's name.

        Parameters
        ----------------
        role_name: :class:`str`
            The name of the role that will be searched for.

        Returns
        -------
        :class:`LevelingRole`
            The LevelingRole or `None` if it isn't found.
        """
        for branch in self:
            role = branch.find_role(role_name)
            if role:
                return role

    def __iter__(self) -> List[LevelingRoute]:
        """Iter magic method so when an instance of this class is looped over, it'll loop over the list of available branches."""
        yield from [self.parliamentary, self.honours]


class LevelingData:
    """
    Represents all the data attached to :class:`LevelingGuild`.

    Attributes
    ---------------
    guild: :class:`discord.Guild`
        The discord guild object.
    level_up_channel: :class:`int`
        ID of the level up channel for the LevelingGuild, defaults to 0 if not set.
    leveling_routes: :class:`LevelingRoutes`
        The leveling routes of LevelingGuild.
    honours_channels :class:`DatabaseList`
        List of honours channels.
    automember :class:`bool`
        True if automember functionality is enabled, defaults to False if not set in the database.
    """

    def __init__(self, guild: discord.Guild, leveling_data: dict):
        self.guild = guild
        self.level_up_channel = leveling_data.get("level_up_channel", 0)
        self.invite_logger_channel = leveling_data.get("invite_logger_channel", 0)
        self.leveling_routes = LevelingRoutes(
            guild, leveling_data.get("leveling_routes", {})
        )
        self.honours_channels = DatabaseList(
            db.leveling_data,
            {"guild_id": guild.id},
            f"honours_channels",
            *leveling_data.get("honours_channels", []),
        )
        self.automember = leveling_data.get("automember", False)

    def toggle_automember(self):
        """Toggle :attr:`automember` and in the database."""
        self.automember = not bool(self.automember)
        db.leveling_data.update_one(
            {"guild_id": self.guild.id}, {"$set": {"automember": self.automember}}
        )

    def __setattr__(self, key, value):
        """For some variables, changing their value will also edit the entry in the database."""
        if (
            key in ["level_up_channel", "invite_logger_channel"]
            and key in self.__dict__
            and self.__dict__[key] != value
        ):
            db.leveling_data.update_one(
                {"guild_id": self.guild.id}, {"$set": {key: value}}
            )

        # special case for honours_channels
        if key == "honours_channels" and "honours_channels" in self.__dict__:
            self.__dict__[key].list = value
            return

        self.__dict__[key] = value


class LevelingGuild(LevelingData):
    """Represents a Leveling Guilds.

    This implements the functionality of :class:`LevelingData`.

    Attributes
    ---------------
    bot: :class:`TLDR`
        The bot instance.
    guild: :class:`discord.Guild`
        The discord guild object.
    id: :class:`int`
        The discord id of the guild.
    members :class:`List[:class:`LevelingMember`]`
        List of LevelingMembers that belong to this guild.
    """

    # TODO: remove user function
    def __init__(self, bot, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.id = guild.id

        self.members = []

        leveling_data = db.get_leveling_data(guild.id)
        super().__init__(guild, leveling_data)

    def get_leveling_role(self, role_name: str) -> LevelingRole:
        """
        Get :class:`LevelingRole` by it's name.

        Parameters
        ----------------
        role_name: :class:`str`
            The name of the role that will be searched for.

        Returns
        -------
        :class:`LevelingRole`
            The LevelingRole or `None` if it isn't found.
        """
        return self.leveling_routes.get_leveling_role(role_name)

    def get_leveling_route(self, name: str) -> LevelingRoute:
        """
        Get :class:`LevelingRoute` by it's name.

        Parameters
        ----------------
        name: :class:`str`
            The name of the route that will be searched for.

        Returns
        -------
        :class:`LevelingRole`
            The LevelingRoute or `None` if it isn't found.
        """
        for branch in self.leveling_routes:
            # since all the branches have unique names, search only by their first character
            if branch.name[0] == name[0]:
                return branch

    async def get_member(self, member_id: int) -> Optional[LevelingMember]:
        """
        Looks for member in :attr:`members`, if member isn't found, will look for member in guild and add it to :attr:`members`.

        Parameters
        ----------------
        member_id: :class:`int`
            Id of the member that will be searched for.

        Returns
        -------
        Optional[:class:`LevelingRole`]
            The LevelingMember or `None` if member isn't in the guild.
        """
        # try to get member from list of members
        member = None
        for _member in self.members:
            if _member.id == member_id:
                member = _member

        if member is None:
            # try to get member from cache
            member = await get_member_by_id(self.guild, member_id)
            if member:
                member = await self.add_member(member)

        return member

    async def add_member(
        self, member: discord.Member, *, leveling_user_data: dict = None
    ) -> LevelingMember:
        """
        Converts :class:`discord.Member` to :class:`LevelingMember` and adds it to :attr:`members`.

        Parameters
        ----------------
        member: :class:`discord.Member`
            The discord member.

        Returns
        -------
        :class:`LevelingMember`
            The LevelingMember.
        """
        leveling_member = LevelingMember(
            self.bot, self, member, leveling_user_data=leveling_user_data
        )
        self.members.append(leveling_member)
        return leveling_member

    def get_level_up_channel(self, message: discord.Message) -> discord.TextChannel:
        """
        Get level up channel for LevelingGuild.

        Parameters
        ----------------
        message: :class:`discord.Message`
            The discord message that will be used as a backup if LevelingGuild doesn't have a level_up_channel set.

        Returns
        -------
        :class:`discord.TextChannel`
            The discord channel.
        """
        # get channel where to send level up message
        channel = self.bot.get_channel(self.level_up_channel)
        # if channel is none default to message channel
        if channel is None:
            channel = message.channel

        return channel


class LevelingMember(LevelingUser):
    """Represents a Leveling Member to a :class:`LevelingGuild`.

    This implements the functionality of :class:`LevelingUser`.

    Attributes
    ---------------
    bot: :class:`TLDR`
        The bot instance.
    guild: :class:`LevelingGuild`
        The guild the LevelingMember belongs to.
    id: :class:`int`
        The discord id of the member.
    member :class:`discord.Member`
        The discord member object.
    """

    def __init__(
        self,
        bot,
        guild: LevelingGuild,
        member: discord.Member,
        *,
        leveling_user_data: dict = None,
    ):
        self.bot = bot
        self.guild = guild

        self.id = member.id
        self.member = member

        # add leveling user data to this class
        if not leveling_user_data:
            leveling_user_data = db.get_leveling_user(member.guild.id, member.id)

        super().__init__(self, leveling_user_data)

    async def add_points(self, branch: Union[LevelingRoute, str], amount: int) -> None:
        """
        Add points to a branch for LevelingMember.

        Parameters
        -----------
        branch: Union[:class:`str`, :class:`LevelingRoute`]
            The branch that the points will be added to. Can be either :class:`str` or :class:`LevelingRoute`.
            If :class:`str`, the branch will be converted to :class:`LevelingRoute`.
        amount: :class:`int`
            The amount of points to add.
        """
        patreon_role_id = 644182117051400220
        member_role_id = 662036345526419486
        if self.guild.automember and patreon_role_id not in [
            r.id for r in self.member.roles
        ]:
            member_role = discord.utils.find(
                lambda r: r.id == member_role_id, self.guild.guild.roles
            )
            await self.member.add_roles(member_role)

        if type(branch) == str:
            branch = self.guild.get_leveling_route(branch)

        user_branch = (
            self.parliamentary if branch.name == "parliamentary" else self.honours
        )
        # if user is receiving their first points give them the first role
        if user_branch.points == 0:
            user_branch.role = branch.roles[0].name

        # increase amount if user has boost
        boost_multiplier = self.boosts.get_multiplier()
        amount = round(amount * boost_multiplier)

        user_branch.points += amount

    async def add_role(self, role: LevelingRole) -> discord.Role:
        """
        Converts LevelingRole to guild role object and adds the role to the discord member.

        Parameters
        ----------------
        role: :class:`LevelingRole`
            The role that will be added to the member.

        Returns
        -------
        :class:`discord.Role`
            The guild role object.
        """
        # get discord.Role role
        guild_role = await role.get_guild_role()
        # give role to user
        await self.member.add_roles(guild_role)
        return guild_role

    async def level_up(self, branch: LevelingRoute) -> Tuple[LevelingRole, int, int]:
        """
        Levels up and ranks up LevelingMember.

        Parameters
        ---------------
        branch :class:`LevelingRoute`
            The branch the LevelingMember will be leveled up on.

        Returns
        -------
        Tuple[:class:`discord.Role`, :class:`int`, :class:`int`]
            The new or current discord role of the member, how many levels LevelingMember went up, how many roles/ranks LevelingMember went up.
        """
        user_branch = (
            self.parliamentary if branch.name == "parliamentary" else self.honours
        )
        levels_up = self.calculate_levels_up(user_branch)
        user_branch.level += levels_up

        # Checks if user has current role
        current_role = branch.find_role(user_branch.role)
        current_guild_role = await current_role.get_guild_role()
        if current_guild_role not in self.member.roles:
            await self.member.add_roles(current_guild_role)

        # get user role level
        role_level = self.user_role_level(user_branch)

        # user needs to go up a role
        if role_level < 0:
            role_index = branch.roles.index(current_role)
            new_role = (
                branch.roles[-1]
                if len(branch.roles) - 1 < role_index + abs(role_level)
                else branch.roles[role_index + abs(role_level)]
            )

            user_branch.role = new_role.name
            await self.add_role(new_role)

            await self.notify_perks(new_role)

            current_role = new_role

        return current_role, levels_up, abs(role_level)

    async def level_up_message(
        self,
        message: discord.Message,
        user_branch: LevelingUserBranch,
        current_role: discord.Role,
        roles_up: int,
    ):
        """
        Send LevelingMember message about their level up.

        Parameters
        ---------------
        message: :class:`discord.Message`
            The message which caused the level up, needed for :func:`get_level_up_channel`.
        user_branch: :class:`LevelingUserBranch`
            The branch which the user leveled up on.
        current_role: :class:`discord.Role`
            The current/new role of LevelingMember which will be used in the reward_text
        roles_up: :class:`int`
            The number of roles/ranks LevelingMember went up.
        """
        role_level = self.user_role_level(user_branch)
        if roles_up:
            reward_text = f"Congrats **{self.member.name}** you've advanced to a level **{role_level}** <@&{current_role.id}>"
        else:
            reward_text = f"Congrats **{self.member.name}** you've become a level **{role_level}** <@&{current_role.id}>"

        reward_text += (
            " due to your contributions!" if user_branch.branch == "honours" else ""
        )

        # send level up message
        embed = discord.Embed(colour=config.EMBED_COLOUR, timestamp=datetime.now())
        embed.description = reward_text
        embed.set_author(name="Level Up!", icon_url=self.guild.guild.icon_url)
        embed.set_footer(text=str(self.member), icon_url=self.member.avatar_url)

        # @ user if they have @me enabled
        content = f"<@{self.id}>" if self.settings.at_me else ""

        # get channel where to send level up message
        channel = self.guild.get_level_up_channel(message)
        await channel.send(embed=embed, content=content)

    @staticmethod
    def user_role_level(user_branch: LevelingUserBranch) -> int:
        """
        Get the role level of LevelingMembers current rank.

        Parameters
        -----------
        user_branch: :class:`LevelingUserBranch`
            The user branch that will be used.

        Returns
        -------
        :class:`int`
            Negative number if LevelingMember needs to go up a rank/role, otheriwise, positive number from 0-5 indicating
            LevelingMember's role level for user_branch
        """
        branch = user_branch.branch

        user_role = branch.find_role(user_branch.role)
        if not user_role:
            return 0  # return 0 if user's current role isn't listen in the branch

        all_roles = branch.roles
        role_index = all_roles.index(user_role)

        # + 1 includes current role
        up_to_current_role = all_roles[: role_index + 1]

        # how many levels to reach current user role
        current_level_total = 5 * len(up_to_current_role)

        # how many levels to reach previous user role
        previous_level_total = 5 * len(up_to_current_role[:-1])

        # if user is on last role user level - how many levels it took to reach previous role
        # or if current level total is bigger than user level
        if len(all_roles) == role_index + 1 or current_level_total > user_branch.level:
            return int(user_branch.level - previous_level_total)

        # if current level total equals user level return current roles max level
        if current_level_total == user_branch.level:
            return 5

        # if current level total is smaller than user level, user needs to rank up
        if current_level_total < user_branch.level:
            # calculates how many roles user goes up
            roles_up = 0
            # loop through roles above current user role
            for _ in all_roles[role_index + 1 :]:
                if current_level_total < user_branch.level:
                    roles_up += 1
                    current_level_total += 5

            return -roles_up

    @staticmethod
    def calculate_levels_up(user_branch: LevelingUserBranch) -> int:
        """
        Calculate how many levels user needs to go up from current standing for given user branhc.

        Parameters
        -----------
        user_branch: :class:`LevelingUserBranch`
            The user branch that will be used.

        Returns
        -------
        :class:`int`
            The number of levels LevelingMember needs to go up.
        """
        user_levels = user_branch.level
        user_points = user_branch.points

        total_points = 0
        total_levels_up = 0
        while total_points <= user_points:
            next_level = user_levels + total_levels_up + 1
            # total points needed to gain the next level
            total_points = round(
                5
                / 6
                * next_level
                * (2 * next_level * next_level + 27 * next_level + 91)
            )

            total_levels_up += 1

        return total_levels_up - 1

    async def notify_perks(self, role: LevelingRole):
        """
        Sends user info about role's perks if role has them.

        Parameters
        -----------
        role: :class:`LevelingRole`
            The role which's perks will be sent to user
        """
        if role.perks:
            perks_str = "\n • ".join(role.perks)
            perks_message = (
                f"**Congrats** again on advancing to **{role.name}**!"
                f"\nThis role also gives you new **perks:**"
                f"\n • {perks_str}"
                f"\n\nFor more info on these perks ask one of the TLDR server mods"
            )

            embed = discord.Embed(colour=config.EMBED_COLOUR, timestamp=datetime.now())
            embed.description = perks_message
            embed.set_author(name="New Perks!", icon_url=self.guild.guild.icon_url)
            embed.set_footer(text=str(self.member), icon_url=self.member.avatar_url)

            try:
                await self.member.send(embed=embed)
            # in case user doesnt allow dms from bot
            except Exception:
                # TODO: maybe send message to bot channel
                pass

    def rank(self, user_branch: LevelingUserBranch) -> int:
        """
        Get LevelingMember's rank in branch.

        Parameters
        -----------
        user_branch: :class:`LevelingUserBranch`
            The user branch that will be used.

        Returns
        -------
        :class:`int`
            The rank of LevelingMember in user branch.
        """
        key = f"{user_branch.branch.name[0]}p"
        sorted_users = [
            u
            for u in db.leveling_users.find(
                {
                    "guild_id": self.guild.id,
                    key: {
                        "$gt": user_branch.points - 0.1
                    },  # 0.1 is subtracted so member will be included
                }
            ).sort(key, -1)
        ]

        return len(sorted_users)

    @staticmethod
    def percent_till_next_level(user_branch: LevelingUserBranch) -> float:
        """
        Get the percent number of how close user is to leveling up.

        Parameters
        -----------
        user_branch: :class:`LevelingUserBranch`
            The user branch that will be used.

        Returns
        -------
        :class:`float`
            The percent number, with one decimal point of how close user is to leveling up
        """
        # points needed to gain next level from beginning of user level
        points_to_level_up = 5 * (user_branch.level ** 2) + 50 * user_branch.level + 100

        next_level = user_branch.level + 1
        # total points needed to gain next level
        total_points_to_next_level = round(
            5 / 6 * next_level * (2 * next_level * next_level + 27 * next_level + 91)
        )
        points_needed = total_points_to_next_level - int(user_branch.points)

        percent = (
            math.floor((100 - ((points_needed * 100) / points_to_level_up)) * 10) / 10
        )

        return percent


class LevelingSystem:
    """
    The handler of :class:`LevelingGuild`s.

    This is used to get LevelingGuilds and LevelingMembers if needed.

    Attributes
    ---------------
    bot: :class:`TLDR`
        The bot instance.
    guilds: :class:`List[:class:`LevelingGuild`]`
        List of the LevelingGuilds attached to the bot.
    """

    def __init__(self, bot):
        self.bot = bot
        # list of leveling guilds
        self.guilds = []
        self.bot.add_listener(self.on_message, "on_message")
        self.bot.add_listener(self.on_ready, "on_ready")
        self.bot.logger.info("LevelingSystem module has been initiated")

    async def on_ready(self):
        await self.initialise_guilds()
        await self.check_left_members()

    async def check_left_members(self):
        self.bot.logger.info(f"Checking Guilds for left members.")
        left_member_count = 0
        # check if any users have left while the bot was offline
        for guild in self.bot.guilds:
            initial_left_members = left_member_count
            guild_members = [
                m.id for m in await guild.fetch_members(limit=None).flatten()
            ]
            leveling_users = db.leveling_users.find({"guild_id": guild.id})

            self.bot.logger.debug(
                f"Checking {guild.name} [{guild.id}] for left members. Guild members: {len(guild_members)} Leveling Users: {leveling_users.count()}"
            )

            for user in leveling_users:
                # if true, user has left the server while the bot was offline
                if int(user["user_id"]) not in guild_members:
                    left_member_count += 1
                    self.transfer_leveling_data(user)

            self.bot.logger.debug(
                f"{left_member_count - initial_left_members} members left guild."
            )

        self.bot.left_check.set()
        self.bot.logger.info(
            f"Left members have been checked - Total {left_member_count} members left guilds."
        )

    def transfer_leveling_data(self, leveling_user: dict):
        db.leveling_users.delete_many(leveling_user)
        db.left_leveling_users.delete_many(leveling_user)
        db.left_leveling_users.insert_one(leveling_user)

        data_expires = round(time.time()) + 30 * 24 * 60 * 60  # 30 days

        self.bot.timers.create(
            guild_id=leveling_user["guild_id"],
            expires=data_expires,
            event="leveling_data_expires",
            extras={"user_id": leveling_user["user_id"]},
        )

    async def on_message(self, message: discord.Message):
        """Function called on every message to level up members."""
        if not self.bot._ready.is_set():
            return

        if message.guild is not None:
            if message.guild.id != config.MAIN_SERVER and config.MAIN_SERVER != 0:
                return

        if (
            message.author.bot
            or not message.guild
            or message.content.startswith(config.PREFIX)
        ):
            return

        leveling_cog = self.bot.get_cog("Leveling")
        await leveling_cog.process_message(message)

    async def initialise_guilds(self):
        """Function called in :func:`cogs.events.on_ready` to initialise all the guilds and cache them."""
        self.bot.logger.info(
            f"Initialising {len(self.bot.guilds)} guilds as LevelingGuilds."
        )
        for guild in self.bot.guilds:
            self.add_guild(guild)

    async def get_member(self, guild_id: int, member_id: int) -> LevelingMember:
        """
        Get :class:`LevelingMember` from :class:`LevelingGuild`.

        Parameters
        -----------
        guild_id: :class:`int`
            The ID of the guild where the LevelingMember will be gotten from.
        member_id: :class:`int`
            The ID of the member that will be returned.

        Returns
        -------
        :class:`LevelingMember`
            The LevelingMember with all the leveling data attached or `None` if member isn't found.
        """
        guild = self.get_guild(guild_id)
        if guild:
            return await guild.get_member(member_id)

    def get_guild(self, guild_id: int) -> LevelingGuild:
        """
        Get :class:`LevelingGuild`.

        Parameters
        -----------
        guild_id: :class:`int`
            The ID of the needed guild.

        Returns
        -------
        :class:`LevelingGuild`
            The LevelingGuild or `None` if the LevelingGuild isn't found.
        """
        for guild in self.guilds:
            if guild.id == guild_id:
                return guild

    def add_guild(self, guild: discord.Guild) -> LevelingGuild:
        """
        Converts :class:`discord.Guild` to :class:`LevelingGuild` and adds it to :attr:`guilds`.

        Parameters
        -----------
        guild: :class:`discord.Guild`
            The guild that will be added.

        Returns
        -------
        :class:`LevelingGuild`
            The converted guild.
        """
        self.bot.logger.debug(
            f"Adding guild {guild.name} [{guild.id}] to LevelingSystem."
        )
        leveling_guild = LevelingGuild(self.bot, guild)
        self.guilds.append(leveling_guild)
        return leveling_guild
