import matplotlib.pyplot as plt
import requests
from modules.utils import get_member
from modules import commands, embed_maker
from discord.ext.commands import Cog, command, Context
from datetime import date
import statsmodels.api as sm
import numpy as np
import time
import discord
import config
class poll_election(Cog):
    def __init__(self, bot):
        self.bot = bot

    @command(
        help="get the poll parties from opinionbee ",
        usage="polls",
        examples=["polls"],
        cls=commands.Command,
    )
    async def parties(self, ctx: Context, code: str = None, start_date: str = None, end_date: str = None, company: str = None):
        print("response")
        params = ["key="+config.OPINIONBEE_KEY]
        if code is not None:
            params.append("code="+code)
        if start_date is not None:
            params.append("start_date="+start_date)
        if end_date is not None:
            params.append("end_date="+end_date)
        if company is not None:
            params.append("company="+company)
        url = "https://opinionbee.uk/json/v1.0/parties?"+ ",".join(params)
        response = requests.get(url, headers={"Accept": "text/plain"})
        print(response)

    @command(
        help="get the poll companies from opinionbee ",
        usage="polls",
        examples=["polls"],
        cls=commands.Command,
    )
    async def companies(self, ctx: Context, code: str = None, start_date: str = None, end_date: str = None, company: str = None):
        params = ["key="+config.OPINIONBEE_KEY]
        if code is not None:
            params.append("code="+code)
        if start_date is not None:
            params.append("start_date="+start_date)
        if end_date is not None:
            params.append("end_date="+end_date)
        if company is not None:
            params.append("company="+company)
        url = "https://opinionbee.uk/json/v1.0/companies?"+ ",".join(params)
        response = requests.get(url, headers={"Accept": "text/plain"})


    @command(
        help="get the poll types from opinionbee ",
        usage="polls",
        examples=["polls"],
        cls=commands.Command,
    )
    async def types(self, ctx: Context, code: str = None, start_date: str = None, end_date: str = None, company: str = None):
        params = ["key="+config.OPINIONBEE_KEY]
        if code is not None:
            params.append("code="+code)
        if start_date is not None:
            params.append("start_date="+start_date)
        if end_date is not None:
            params.append("end_date="+end_date)
        if company is not None:
            params.append("company="+company)
        url = "https://opinionbee.uk/json/v1.0/types?"+ ",".join(params)
        response = requests.get(url, headers={"Accept": "text/plain"})  
        types = response.json()
        embed = discord.Embed(title="Types of polls", description="Your desc here") 
        for p in types.keys():
            embed.add_field(name= str(p) , value=str(types[p]["name"]))
        await ctx.send(embed=embed)

            

    @command(
        help="get the polls from opinionbee ",
        usage="polls",
        examples=["polls"],
        cls=commands.Command,
    )
    async def polls(self, ctx: Context, code: str = None, start_date: str = None, end_date: str = None, company: str = None):
        params = ["key="+config.OPINIONBEE_KEY]
        if code is not None:
            params.append("code="+code)
        else:
            params.append("code=WESTVI")
        if start_date is not None:
            params.append("start_date="+start_date)
        if end_date is not None:
            params.append("end_date="+end_date)
        if company is not None:
            params.append("company="+company)
        url = "https://opinionbee.uk/json/v1.0/polls?"+ "&".join(params)
        response = requests.get(url, headers={"Accept": "text/plain"})
        polls = {}
        for p in response.json():
           date_ = date.fromisoformat(p["date"])
           times = time.mktime(date_.timetuple())
           for i in p["headline"].keys():
               if i not in polls.keys():
                   polls[i] = {
                       "pct":[],
                       "time":[],
                       "colour":"#"+p["headline"][i]["party"]["colour"],
                       "name":p["headline"][i]["party"]["name"]
                   }
               polls[i]["pct"] .append(p["headline"][i]["pct"])
               polls[i]["time"].append(date_)
        for i in polls.keys():
            plt.plot(polls[i]["time"],polls[i]["pct"], 'o', color=polls[i]["colour"],label=polls[i]["name"])
        plt.legend()
        plt.savefig("test.png")
        plt.close()
        image = discord.File("test.png")
        await ctx.send(file=image)






def setup(bot):
    bot.add_cog(poll_election(bot))
