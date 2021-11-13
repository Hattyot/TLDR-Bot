import random
import string
from datetime import datetime
from io import BytesIO
from typing import Union

import config
import discord
from cachetools.ttl import TTLCache
from discord import File
from discord.embeds import Embed
from discord.guild import Guild

from modules import database, timers
from modules.utils import SettingsHandler
from ukparliament.bills_tracker import (BillsStorage, Conditions, Feed,
                                        FeedUpdate, PublicationUpdate)
from ukparliament.divisions_tracker import DivisionStorage
from ukparliament.structures.bills import Bill, CommonsDivision, LordsDivision
from ukparliament.structures.members import ElectionResult, PartyMember
from ukparliament.ukparliament import UKParliament
from ukparliament.utils import BetterEnum


class UKParliamentConfig:
    def __init__(self, settings_handler: SettingsHandler, guild_id: int):
        """
        Utility/handler class to interface with the collection containing the channel ids for each tracker.
        Used soley to store the ids of channel assigned to each tracker.
        """
        self._settings_handler: SettingsHandler = settings_handler
        self.db = database.get_connection()
        settings = self._settings_handler.get_settings(guild_id)
        self.guild_id = guild_id

        if "ukparliament" not in settings["modules"].keys():
            settings["modules"]["ukparliament"] = {
                "royal_assent": 0,
                "lords_divisions": 0,
                "commons_divisions": 0,
                "publications": 0,
                "feed": 0,
            }
            self._settings_handler.save(settings)

    def set_channel(self, tracker_name: str, channel_id: int):
        """
        Set a channel to a tracker.

        Parameters
        ----------
        tracker_name: :class:`str`
            The id of the tracker.
        channel_id: :class:`int`
            The id of the text channel.
        """
        settings = self._settings_handler.get_settings(self.guild_id)
        if tracker_name not in settings["modules"]["ukparliament"].keys():
            raise Exception(
                f"Tracker name {tracker_name} is not a key for a channel id."
            )

        settings["modules"]["ukparliament"][tracker_name] = channel_id
        self._settings_handler.save(settings)

    def get_channel_id(self, tracker_id):
        """
        Retrieved the text channel id from the config by the tracker id is was
        assigned to previously.

        Parameters
        ----------
        tracker_id: :class:`str`
            The id of the tracker.

        Returns
        -------
        :class:`int`
            The id of the text channel or 0
        """

        settings = self._settings_handler.get_settings(self.guild_id)
        if tracker_id not in settings["modules"]["ukparliament"].keys():
            raise Exception(f"Tracker name {tracker_id} is not a key for a channel id.")

        return settings["modules"]["ukparliament"][tracker_id]

    def get_channel_ids(self):
        return self._settings_handler.get_settings(self.guild_id)["modules"][
            "ukparliament"
        ]


class PartyColour(BetterEnum):
    """
    An enumeration class used to assign party colours to colours selected from
    the TLDR Colour Palette.

    Enum Variables
    --------------
    id: :class:`int`
        The id of a party, used to relate a party object to an enum
    colour: :class:`str`
        The hex colour code
    """

    ALBA = {"id": 1034, "colour": "#73BFFA"}
    ALLIANCE = {"id": 1, "colour": "#D5D5D5"}
    CONSERVATIVE = {"id": 4, "colour": "#489FF8"}
    DUP = {"id": 7, "colour": "#3274B5"}
    GREEN = {"id": 44, "colour": "#82D552"}
    INDEPENDENT = {"id": 8, "colour": "#929292"}
    LABOUR = {"id": 15, "colour": "#DB3B26"}
    LIBERAL = {"id": 17, "colour": "#F19937"}
    PLAID_CYMRU = {"id": 22, "colour": "#54AE33"}
    SNP = {"id": 29, "colour": "#EFBD40"}
    SINN_FEIN = {"id": 30, "colour": "#986541"}
    SDLP = {"id": 31, "colour": "#ED6D57"}
    BISHOPS = {"id": 3, "colour": "#8648BA"}
    CONSERVATIVE_IND = {"id": 5, "colour": "#ED6D57"}
    CROSSBENCH = {"id": 6, "colour": "#A99166"}
    IND_SOCIAL_DEMOCRATS = {"id": 53, "colour": "#A62A16"}
    LABOUR_IND = {"id": 43, "colour": "#DE68A5"}
    ULSTER_UNIONIST = {"id": 38, "colour": "#8648BA"}
    NONAFFILIATED = {"id": 49, "colour": "#929292"}

    @classmethod
    def from_id(cls, value: int):
        """
        Get a enum
        """
        for p_enum in cls:
            if p_enum.value["id"] == value:
                return p_enum
        return cls.NONAFFILIATED


class BillsMongoStorage(BillsStorage):
    """
    The class used to store information pertinent to the bills tracker.

    This is only used to store information about a bill so that the bill is not
    reannounced when the tracker polls the various rss feeds and endpoints.
    """

    async def add_feed_update(self, bill_id: int, update: FeedUpdate):
        """
        Add a feed update.

        Parameters
        ----------
        bill_id: :class:`int`
            The id of the bill related to the feed update.
        update: :class:`FeedUpdate`
            The feed update.
        """
        database.get_connection().add_bill_feed_update(bill_id, update)

    async def has_update_stored(self, bill_id: int, update: FeedUpdate):
        """
        Check if an update has been stored.

        Parameters
        ----------
        bill_id: :class:`int`
            The id of the bill related to the feed update.
        update: :class:`FeedUpdate`
            The feed update.

        Returns
        -------
        :class:`bool`
            True if the update has been stored else False
        """
        return database.get_connection().is_bill_update_stored(bill_id, update)

    async def get_last_update(self, bill_id: int):
        """
        Gets the most recent update to be stored in relation to the bill_id.

        Parameters
        ---------
        bill_id: :class:`int`
            The id of the bill.

        Returns
        -------
        :class: `Union[object, None]`
            A dictionary object with three keys: bill_id, timestamp, and stage. Or nothing.
        """
        return database.get_connection().get_bill_last_update(bill_id)

    async def add_publication_update(self, bill_id: int, update: PublicationUpdate):
        pass

    async def has_publication_update(self, bill_id: int, update: PublicationUpdate):
        pass


class DivisionMongoStorage(DivisionStorage):
    """
    Used to store information relevant to divisions.

    Information stored via this class is used to prevent already announced
    divisions from being reannounced when the tracker polls the two commons and
    lords endpoints.
    """

    async def add_division(self, division: Union[LordsDivision, CommonsDivision]):
        """
        Add a division to the collection. A non-bill division is a division that is
        not related to a bill.

        Parameters
        ----------
        divsion: :class:`Union[LordsDivision, CommonsDivision]`
            A commons or lords division.
        """
        database.get_connection().add_division(division)

    async def add_bill_division(
        self, bill_id: int, division: Union[LordsDivision, CommonsDivision]
    ):
        """
        Add a bill division. Bill divisions are divisions relating to a bill.

        Parameters
        ----------
        bill_id: :class:`int`
            A bill id
        division: :class:`Union[LordsDivision, CommonsDivision]`
            A commons or lords division.
        """
        database.get_connection().add_bill_division(bill_id, division)

    async def division_stored(self, division: Union[LordsDivision, CommonsDivision]):
        """
        Check if a non-bill division has been stored.

        Parameters
        ----------
        division: :class:`Union[LordsDivision, CommonsDivision]`
            A commons or lords division.
        """
        return database.get_connection().is_division_stored(division)

    async def bill_division_stored(
        self, bill_id: int, division: Union[LordsDivision, CommonsDivision]
    ):
        """
        Check if a bill division is stored.

        Parameters
        ----------
        bill_id: :class:`int`
            The bill id
        division: :class:`Union[LordsDivision, CommonsDivision]`
            A commons or lords division
        """
        return database.get_connection().is_bill_division_stored(bill_id, division)

    async def get_bill_divisions(self, bill_id: int):
        """
        Fetch all bill divisions.

        Parameters
        ----------
        bill_id: :class:`int`
            The bill id

        Returns
        -------
        :class:`list`
            A list of dictionaries with the following keys:
            'bill_id': the id of the bill
            'division_id': the id of the division
            'timestamp': the timestamp of the division
        """
        return database.get_connection().get_bill_divisions(bill_id)


class ConfirmManager:
    def __init__(self):
        """
        A simple temporary code confirmation system. Used only for the 'dbclear'
        command.
        """
        self.cache = TTLCache(maxsize=30, ttl=90)

    def gen_code(self, member: discord.Member):
        """
        Generate a code and assign said code to a member. Lasts a maximum of 90 seconds.

        Parameters
        ---------
        member: :class:`discord.Member`
            A member of a guild.
        """
        code = "".join(random.choice(string.ascii_lowercase) for i in range(5))
        self.cache[member.id] = code
        return code

    def confirm_code(self, member: discord.Member, code: str):
        """
        Confirm a code.

        Parameters
        ---------
        member: :class:`discord.Member`
            A discord member.
        code: :class:`str`
            The 5 character code.

        Returns
        ------
        :class:`bool`
            True if the code was valid, else False.
        """
        c_code = self.cache.get(member.id)
        if c_code is None:
            return False
        confirmed = c_code == code
        if confirmed:
            self.cache.pop(member.id)
        return confirmed

    def has_code(self, member: discord.Member):
        """
        Check if a member has a code.

        Parameters
        ---------
        member: :class:`discord.Member`
            A discord member.

        Returns
        ------
        :class:`bool
            A discord member.

        Returns
        ------
        :class:`bool`
            True if the member does has a code cached, else false.
        """
        return self.cache.get(member.id) is not None


class UKParliamentModule:
    def __init__(self, bot):
        self._bot = bot
        self._divisions_storage = DivisionMongoStorage()
        self._bills_storage = BillsMongoStorage()
        self.confirm_manager = ConfirmManager()
        bot.add_listener(self.on_ready, "on_ready")

        """
        These are used to allow a check  of the trackers to be done in the guild.
        started refers to a listener has been registered to that tracker, confirmed
        refers that listener being fired.

        """
        self.tracker_status = {
            "loop": False,
            "lordsdivisions": {"started": False, "confirmed": False},
            "commonsdivisions": {"started": False, "confirmed": False},
            "royalassent": {"started": False, "confirmed": False},
            "feed": {"started": False, "confirmed": False},
            "publications": {"started": False, "confirmed": False},
        }

        self._guild: Union[Guild, None] = None
        bot.logger.info("UK Parliament module has been initiated.")

    async def on_ready(self):
        self.set_guild(self._bot.get_guild(config.MAIN_SERVER))
        await self.load()
        self._bot.get_cog("UK").load()
        self.load_trackers()
        self.tracker_event_loop.start()

    async def load_settings(self):
        pass

    async def load(self):
        """
        Given that the aiohttp session can't be retrieved before the bot has invoked the on_ready
        event this function is used to load what would have been loaded in the contructor if it
        wasn't for this impediment.

        """
        self.config = UKParliamentConfig(self._bot.settings_handler, self._guild.id)
        self.aiohttp_session = getattr(self._bot.http, "_HTTPClient__session")
        self.parliament = UKParliament(self.aiohttp_session)
        await self.parliament.load()
        self._bot.logger.info("UKParliament Legislative Module has been initiated.")

    def get_aiohttp_session(self):
        return self.aiohttp_session

    def load_trackers(self):
        """
        A function used to load the various trackers and listeners.
        """
        channels = self.config.get_channel_ids()

        if (
            channels["lords_divisions"] != 0
            or channels["commons_divisions"] != 0
            or channels["royal_assent"] != 0
            or channels["feed"] != 0
        ):
            self.parliament.start_bills_tracker(self._bills_storage)

            if channels["feed"] != 0:
                self.parliament.get_bills_tracker().register(
                    self.on_feed_update, [Conditions.ALL]
                )
                self.tracker_status["feed"]["started"] = True

            if channels["royal_assent"]:
                self.parliament.get_bills_tracker().register(
                    self.on_royal_assent_update, [Conditions.ROYAL_ASSENT]
                )
                self.tracker_status["royalassent"]["started"] = True

        if channels["lords_divisions"] != 0 or channels["commons_divisions"] != 0:
            self.parliament.start_divisions_tracker(self._divisions_storage)
            if channels["commons_divisions"] != 0:
                self.parliament.get_divisions_tracker().register(
                    self.on_commons_division
                )
                self.tracker_status["commonsdivisions"]["started"] = True

            if channels["lords_divisions"] != 0:
                self.parliament.get_divisions_tracker().register(
                    self.on_lords_division, False
                )
                self.tracker_status["lordsdivisions"]["started"] = True

        if (
            channels["publications"] != 0
            and self.parliament.get_bills_tracker() is not None
        ):
            b_tracker = self.parliament.get_bills_tracker()
            if b_tracker is None:
                return
            self.parliament.start_publications_tracker(b_tracker)
            self.tracker_status["publications"]["started"] = True

    def set_guild(self, guild):
        self._guild = guild

    def get_guild(self) -> Union[Guild, None]:
        return self._guild

    @timers.loop(seconds=60)
    async def tracker_event_loop(self):
        self._bot.logger.info("UKParliament Tracker Event Loop triggered.")
        division_listener = (
            self.tracker_status["lordsdivisions"]["started"]
            or self.tracker_status["commonsdivisions"]["started"]
        )
        self.tracker_status["loop"] = True
        feed_listener = self.tracker_status["feed"]["started"]
        royal_assent_listener = self.tracker_status["royalassent"]["started"]
        publications_listener = self.tracker_status["publications"]["started"]

        if (
            self.parliament.get_publications_tracker() is not None
            and publications_listener
        ):
            self._bot.logger.info("UKParliament  Tracker: Polling publications.")
            await self.parliament.get_publications_tracker().poll()

        if self.parliament.get_bills_tracker() is not None and (
            feed_listener or royal_assent_listener
        ):
            self._bot.logger.info(
                "UKParliament Tracker: Polling Bills/Royal Assent. test"
            )
            await self.parliament.get_bills_tracker().poll()

        self._bot.logger.info(
            f"UKParliament Tracker: Divisions Tracker: {'Online' if self.parliament.get_divisions_tracker() is not None else 'Null'}"
        )
        self._bot.logger.info(
            f"UKParliament Tracker: Division Listener: {'Online' if division_listener is not None else 'Null'}"
        )
        if self.parliament.get_divisions_tracker() is not None and division_listener:
            self._bot.logger.info(
                "UKParliament Tracker: Polling Commons and Lords Division."
            )
            await self.parliament.get_divisions_tracker().poll_commons()
            await self.parliament.get_divisions_tracker().poll_lords()

    async def on_feed_update(self, feed: Feed, update: FeedUpdate):
        channel = self._guild.get_channel(int(self.config.get_channel_id("feed")))
        if channel is None:
            return
        embed = Embed(colour=config.EMBED_COLOUR, timestamp=datetime.now())
        next_line = "\n"
        last_update = await self._bills_storage.get_last_update(update.get_bill_id())
        embed.description = (
            f"**Last Stage:**: {last_update['stage']}{next_line}"
            if last_update is not None
            else ""
            f"**Next Stage:** {update.get_stage()}{next_line} **Summary:** {update.get_description()}"
            f"{next_line}**Categories:**{', '.join(update.get_categories())}"
        )
        embed.title = update.get_title()
        if self._guild is not None:
            embed.set_author(name="TLDRBot", icon_url=self._guild.icon_url)

        self.tracker_status["feed"]["confirmed"] = True
        await channel.send(embed=embed)  # type: ignore

    async def on_royal_assent_update(self, feed: Feed, update: FeedUpdate):
        channel = self._guild.get_channel(
            int(self.config.get_channel_id("royal_assent"))
        )
        if channel is None:
            return
        next_line = "\n"
        embed = Embed(
            colour=discord.Colour.from_rgb(134, 72, 186), timestamp=datetime.now()
        )
        embed.title = f"**Royal Assent Given:** {update.get_title()}"
        embed.description = (
            f"**Signed At:** {update.get_update_date().strftime('%H:%M:%S on %Y:%m:%d')}{next_line}"
            f"**Summary:** {update.get_description()}"
        )
        self.tracker_status["royalassent"]["confirmed"] = True
        await channel.send(embed=embed)

    async def on_commons_division(self, division: CommonsDivision, bill: Bill):
        channel = self._guild.get_channel(
            int(self.config.get_channel_id("commons_divisions"))
        )
        if channel is None:
            return
        division_file = await self.generate_division_image(self.parliament, division)
        embed = Embed(
            color=discord.Colour.from_rgb(84, 174, 51), timestamp=datetime.now()
        )
        did_pass = division.get_aye_count() > division.get_no_count()
        embed.title = f"**{division.get_division_title()}**"
        next_line = "\n"
        description = (
            f"**Division Result:** {'Passed' if did_pass else 'Not passed'} by a division of"
            f" {division.get_aye_count() if did_pass else division.get_no_count()} {'Ayes' if did_pass else 'Noes'}"
            f" to {division.get_no_count() if did_pass else division.get_aye_count()} "
            f"{'Noes' if did_pass else 'Ayes'}{next_line}**Division Date:** "
            f"{division.get_division_date().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        if bill is not None:
            description += (
                f"{next_line}**Bill Summary [(Link)](https://bills.parliament.uk/"
                f"bills/{bill.get_bill_id()})**: {bill.get_long_title()}"
            )

        embed.description = description
        embed.set_image(url="attachment://divisionimage.png")
        self.tracker_status["commonsdivisions"]["confirmed"] = True
        await channel.send(
            file=division_file,
            embed=embed,
        )

    async def on_lords_division(self, division: LordsDivision, bill: Bill):
        channel = self._guild.get_channel(
            int(self.config.get_channel_id("lords_divisions"))
        )
        if channel is None:
            return
        division_file = await self.generate_division_image(self.parliament, division)
        embed = Embed(
            color=discord.Colour.from_rgb(166, 42, 22), timestamp=datetime.now()
        )
        did_pass = division.get_aye_count() > division.get_no_count()
        embed.title = f"**{division.get_division_title()}**"
        embed.set_image(url="attachment://divisionimage.png")
        next_line = "\n"
        description = (
            f"**ID:** {division.get_id()}{next_line}**Summary [(Link)](https://votes.parliament.uk/"
            f"Votes/Lords/Division/{division.get_id()}):** {division.get_amendment_motion_notes()[0:250]}...{next_line}"
            f"**Division Result:** {'Passed' if did_pass else 'Not passed'} by a division of "
            f"{division.get_aye_count() if did_pass else division.get_no_count()} "
            f"{'Ayes' if did_pass else 'Noes'} to {division.get_no_count() if did_pass else division.get_aye_count()}"
            f" {'Noes' if did_pass else 'Ayes'}{next_line}**Division Date:** "
            f"{division.get_division_date().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        if bill is not None:
            description += (
                f"{next_line}**Bill Summary [(Link)](https://bills.parliament.uk/bills/"
                f"{bill.get_bill_id()})**: {bill.get_long_title()}**"
            )
        embed.description = description
        self.tracker_status["lordsdivisions"]["confirmed"] = True
        embed.set_image(url="attachment://divisionimage.png")
        await channel.send(
            file=division_file,
            embed=embed,
        )

    async def get_mp_portrait(self, url: str):
        """
        Get a portrait of an MP.

        Parameters
        ---------
        url: :class:`str`
            The url of the portrait image.

        Returns
        -------
        :class:`File`
            A discord File.
        """
        async with self.aiohttp_session.get(url) as resp:
            if resp.status != 200:
                return None
            buffer = BytesIO(await resp.read())
            buffer.seek(0)
            return File(fp=buffer, filename="portrait.jpeg")

    async def generate_election_graphic(
        self,
        result: ElectionResult,
        include_nonvoters: bool = False,
        generate_table: bool = False,
    ):
        """
        Fetches a generated election graphic from the image_processor app.
        This election graphic is either in the form of a pie or a table.

        Parameters
        ----------
        result: :class:`ElectionResult`
            An election result object.
        include_nonvoters: :class:`bool`
            Whether or not to include people who didn't vote in the chart.
        generate_table:
            Whether or not to generate a table rather than a pie chart.

        Returns
        -------
        :class:`File`
            A discord File.
        """
        serialized_candidates = []

        for candidate in result.get_candidates():
            party = self.parliament.get_party_by_id(candidate["party_id"])
            party_name = party.get_abber() if party is not None else ""
            if party_name == "UK Independent Party":
                party_name = "UKIP"
            if party_name == "Scottish National Party":
                party_name = "SNP"

            serialized_candidates.append(
                {
                    "party_name": party_name,
                    "votes": candidate["votes"],
                    "vote_share": candidate["vote_share"],
                    "vote_share_change": candidate["vote_share_change"],
                    "name": candidate["name"],
                }
            )

        async with self.aiohttp_session.post(
            f"{config.WEB_API_URL}/electionimage",
            json={
                "candidates": serialized_candidates,
                "electorate_size": result.get_electorate_size(),
                "turnout": result.get_turnout(),
                "include_nonvoters": include_nonvoters,
                "generate_table": generate_table,
            },
        ) as resp:
            if resp.status != 200:
                raise Exception("Failed to get election image for election result.")
            buffer = BytesIO(await resp.read())
            buffer.seek(0)
            return File(fp=buffer, filename="electionimage.png")

    async def generate_division_image(
        self, parliament: UKParliament, division: Union[LordsDivision, CommonsDivision]
    ):
        """
        Gets a generated division image from the image_processor app.

        Parameters
        ---------
        parliament: :class:`UKParliament`
            The uk parliament instance.
        division: :class:`Union[LordsDivision, CommonsDivision]`
            A lords of commons division.

        Returns
        -------
        :class:`File`
            A discord File
        """

        # Takes only the colour from each member and puts it into a json compatible dictionary.
        def serialize_members(members: list[PartyMember]) -> dict[str, str]:
            serialized_members: dict[str, str] = {}

            for member in members:
                serialized_members[str(member.get_id())] = PartyColour.from_id(
                    member.get_party_id()
                ).value["colour"]

            return serialized_members

        # Sorts members into their respective parties then sitches the list back together.
        def sort_members(members: list[PartyMember]) -> list[PartyMember]:
            parties = {}

            for member in members:
                if member.get_party_id() not in parties:
                    parties[member.get_party_id()] = [member]
                else:
                    parties[member.get_party_id()].append(member)

            results = []

            for key in sorted(parties.keys(), key=lambda k: len(parties[k])):
                results.extend(parties[key])

            results.reverse()
            return results

        aye_serialized_members = serialize_members(
            sort_members(division.get_aye_members())
        )
        no_serialized_members = serialize_members(
            sort_members(division.get_no_members())
        )
        serialized_parties = {}

        members = division.get_aye_members()
        members.extend(division.get_no_members())

        for member in members:
            party_id = member.get_party_id()
            if party_id in serialized_parties:
                continue
            party = self.parliament.get_party_by_id(party_id)
            if party is None:
                continue
            party_name = party.get_abber()
            # Shortens the longest party names, for easy reading on the chart.
            if party_name == "UK Independent Party":
                party_name = "UKIP"
            if party_name == "Scottish National Party":
                party_name = "SNP"

            serialized_parties[str(party_id)] = {
                "name": party_name,
                "colour": PartyColour.from_id(party_id).value["colour"],
            }

        if config.WEB_API_URL == "":
            raise Exception("WEB_API_URL for image processor has not been set.")

        async with self.aiohttp_session.post(
            f"{config.WEB_API_URL}/divisionimage",
            json={
                "aye_members": aye_serialized_members,
                "no_members": no_serialized_members,
                "parties": serialized_parties,
            },
        ) as resp:
            if resp.status != 200:
                raise Exception(
                    f"Couldn't fetch division image. Status Code: {resp.status}"
                )
            buffer = BytesIO(await resp.read())
            buffer.seek(0)
            return File(fp=buffer, filename="divisionimage.png")
