from bot import TLDR
from modules import commands, embed_maker
from modules.facebook_ad import query
from modules.utils import ParseArgs
from typing import Union
from discord.ext.commands import Cog, command, Context


class facebook_ad(Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot
        print("loaded")
    # when giving an arg a type, discord.py will attempt to convert that arg to the given type
    # rest_of_the_args will attempt to convert to ParseArgs, if it fails, it'll convert to str

    @command(
        help='Show someone you polling station based on their home address.',
        usage="polls",
        examples=["polls"],
        cls=commands.Command,
    )
    async def facebook_ad_query(self, ctx: Context, *, args: str):
        ret = query(args)
        print(ret)


def setup(bot: TLDR):
    bot.add_cog(facebook_ad(bot))
