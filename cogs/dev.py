import discord
import ast
import logging
from discord.ext import commands
from config import DEV_IDS
from modules import database, command

db = database.Connection()
logger = logging.getLogger(__name__)


def is_dev(ctx):
    return ctx.author.id in DEV_IDS


def insert_returns(body):
    if isinstance(body[-1], ast.Expr):
        body[-1] = ast.Return(body[-1].value)
        ast.fix_missing_locations(body[-1])

    if isinstance(body[-1], ast.If):
        insert_returns(body[-1].body)
        insert_returns(body[-1].orelse)

    if isinstance(body[-1], ast.With):
        insert_returns(body[-1].body)


class Dev(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(hidden=True, help='Evaluate code', usage='eval [code]', examples=['eval ctx.author.id'], clearance='Dev', cls=command.Command)
    @commands.check(is_dev)
    async def eval(self, ctx, *, cmd):
        fn_name = "_eval_expr"
        cmd = cmd.strip("` ")

        cmd = "\n".join(f"    {i}" for i in cmd.splitlines())

        body = f"async def {fn_name}():\n{cmd}"

        parsed = ast.parse(body)
        body = parsed.body[0].body

        insert_returns(body)

        env = {
            'bot': ctx.bot,
            'discord': discord,
            'commands': commands,
            'ctx': ctx,
            '__import__': __import__,
            'db': db
        }
        exec(compile(parsed, filename="<ast>", mode="exec"), env)

        result = (await eval(f"{fn_name}()", env))
        await ctx.send(result)

    @commands.command(hidden=True, help='Kill the bot', usage='kill_bot', examples=['kill_bot'], clearance='Dev', cls=command.Command)
    @commands.check(is_dev)
    async def kill_bot(self):
        await self.bot.close()


def setup(bot):
    bot.add_cog(Dev(bot))
