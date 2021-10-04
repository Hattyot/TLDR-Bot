import discord
import config
import copy
import config
from discord.ext.commands.core import hooked_wrapped_callback
from modules import database, embed_maker
from typing import Callable, Union

db = database.get_connection()


class Clearance_fake:
    def __init__(self, bot):
        self.bot = bot

        # raw data from the excel spreadsheet
        self.groups = {}
        self.roles = {}
        self.command_access = {}

    @staticmethod
    def split_comma(value: str, *, value_type: Callable = str):
        """Split string of comma separated values into a list."""
        return [
            value_type(v.strip())
            for v in value.split(",")
            if v and v.strip() and value_type(v.strip())
        ]

    def member_clearance(self, member: discord.Member):
        """
        Returns dict with info about what group user belongs to and what roles they have.

        Parameters
        ----------------
        member: :class:`discord.Member`
            The member.

        Returns
        -------
        :class:`dict`
            Clearance info about the user.
        """
        clearance = {
            "groups": ["Staff"],
            "roles": ["User","Staff"],
            "user_id": member.id
            }
        return clearance
    @staticmethod
    def highest_member_clearance(member_clearance: dict):
        """Function that returns the highest group or role user has."""
        highest_group = "User"
        if member_clearance["groups"]:
            if member_clearance["groups"][0] != "Staff":
                highest_group = member_clearance["groups"][0]
            elif member_clearance["roles"]:
                highest_group = member_clearance["roles"][0]

        return highest_group

    def command_clearance(self, command: Union["Group", "Command"]):
        """
        Return dict with info about what groups, roles and users have access to command.

        Parameters
        ----------------
        command: :class:`Command`
            The Command.

        Returns
        -------
        :class:`dict`
            Clearance info about the command.
        """
        return {}

    @staticmethod
    def member_has_clearance(member_clearance: dict, command_clearance: dict):
        """Function for checking id member clearance and command clearance match"""
        return True

    async def refresh_data(self):
        """Refreshes data from the spreadsheet"""
        pass


