from discord.ext import commands
from modules import database
from config import DEV_IDS

db = database.Connection()


class Context(commands.Context):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bot = kwargs['bot']
        self.message = kwargs['message']
        if not self.message.author.bot:
            self.author_xp = self.xp
            self.author_level = self.level
            self.author_clearance = self.clearance
            self.author_cp = self.cp
            self.author_c_level = self.c_level
            self.author_role = self.role
            self.author_c_role = self.c_role

    @property
    def session(self):
        return self.bot.session

    @property
    def role(self):
        return db.get_levels(self.message.guild.id, self.message.author.id, 'role')

    @property
    def c_role(self):
        return db.get_levels(self.message.guild.id, self.message.author.id, 'c_role')

    @property
    def cp(self):
        return db.get_levels(self.message.guild.id, self.message.author.id, 'cp')

    @property
    def c_level(self):
        return db.get_levels(self.message.guild.id, self.message.author.id, 'c_level')

    @property
    def xp(self):
        return db.get_levels(self.message.guild.id, self.message.author.id, 'xp')

    @property
    def level(self):
        return db.get_levels(self.message.guild.id, self.message.author.id, 'level')

    @property
    def clearance(self):
        user_permissions = self.channel.permissions_for(self.message.author)
        clearance = []

        if self.message.author.id in DEV_IDS:
            clearance.append('Dev')
        if user_permissions.administrator:
            clearance.append('Admin')
        if user_permissions.manage_messages:
            clearance.append('Mod')
        clearance.append('User')

        return clearance
