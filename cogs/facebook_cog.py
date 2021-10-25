import discord
from bot import TLDR
from modules import commands, embed_maker
from modules.facebook_ad import query, keywords
from modules.utils import ParseArgs
from typing import Union
from discord.ext.commands import Cog, command, Context
import numpy as np
import matplotlib.pyplot as plt

class facebook_ad(Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot
        print("loaded")
    # when giving an arg a type, discord.py will attempt to convert that arg to the given type
    # rest_of_the_args will attempt to convert to ParseArgs, if it fails, it'll convert to str

    @command(
        help='Show someone you polling station based on their home address.',
        usage="facebookAd_keywords",
        examples=["polls"],
        cls=commands.Command,
    )
    async def facebookAdKeywords(self, ctx: Context):
        embed = discord.Embed(title="keywords", description="Desc", color=0x00ff00)
        for keyword in keywords.keys():
            embed.add_field(name=keyword, value=keywords[keyword]["text"], inline=False)
        await ctx.send(embed=embed)



    @command(
        help='Show someone you polling station based on their home address.',
        usage="facebookAd_query",
        examples=["polls"],
        cls=commands.Command,
    )
    async def facebookAdQuery(self, ctx: Context, *, args: str):
        rets = query(args)
        adDeliveryStartTime = []
        adDeliveryStopTime = []
        spend_lower_bounds = []
        spend_upper_bounds = []
        impressions_upper_bounds = []
        impressions_lower_bounds = []
        fundingEntity = []
        page_name = []
        fundingEntity_count = []
        page_name_count = []
        currency = []
        adCreationTime = []
        for ret in rets:

            if "impressions" in ret.keys():
                impressions_upper_bounds.append(int(ret["impressions"]["upper_bound"]))
                impressions_lower_bounds.append(int(ret["impressions"]["lower_bound"]))
            else:
                currency.append(None)

            if "spend" in ret.keys():
                spend_upper_bounds.append(int(ret["spend"]["upper_bound"]))
                spend_lower_bounds.append(int(ret["spend"]["lower_bound"]))
            else:
                currency.append(None)

            if "fundingEntity" in ret.keys():
                if  ret["fundingEntity"] not  in fundingEntity:
                    fundingEntity.append(ret["fundingEntity"])
                    fundingEntity_count.append(0)
                    count  = fundingEntity.index(ret["fundingEntity"])  - 1
                fundingEntity_count[count] = fundingEntity_count[count] + 1
            else:
                fundingEntity.append(None)

            if "currency" in ret.keys():
                currency.append(ret["currency"])
            else:
                currency.append(None)

            if "page" in ret.keys():
                if  ret["page"]["name"] not in page_name:
                    page_name.append(ret["page"]["name"])
                    page_name_count.append(0)
                count  = page_name.index(ret["page"]["name"]) - 1
                page_name_count[count] = page_name_count[count] + 1
            else:
                page_name_count.append(0)
                page_name.append(None)

            if "adDeliveryStartTime" in ret.keys():
                adDeliveryStartTime.append(ret["adDeliveryStartTime"])
            else:
                adDeliveryStartTime.append(None)

            if "adDeliveryStopTime" in ret.keys():
                adDeliveryStopTime.append(ret["adDeliveryStopTime"])
            else:
                adDeliveryStopTime.append(None)

            if "adCreationTime" in ret.keys():
                adCreationTime.append(ret["adCreationTime"])
            else:
                adCreationTime.append(None)
            #page_name.append()
            #currency.append()
        fig = plt.figure()
        plt.title("impressions")
        plt.ylabel("impressions range")
        plt.xlabel("date/time")
        plt.bar(adDeliveryStartTime, impressions_upper_bounds, bottom=impressions_upper_bounds)
        #plt.bar(adDeliveryStopTime, impressions_upper_bounds, bottom=impressions_upper_bounds)
        plt.savefig('impressions.png')
        plt.clf()
        plt.title("spend")
        plt.bar(adDeliveryStartTime,spend_upper_bounds , bottom=spend_lower_bounds)
        #plt.bar(adDeliveryStopTime,spend_upper_bounds , bottom=spend_lower_bounds)
        plt.ylabel("spend range")
        plt.xlabel("date/time")
        plt.savefig('spend.png')
        plt.clf()
        plt.title("page name")
        plt.bar(page_name,page_name_count)
        plt.ylabel("numer")
        plt.xlabel("page name")
        plt.title("page name")
        plt.savefig('page_name.png')
        plt.clf()
        plt.bar(fundingEntity,fundingEntity_count)
        plt.title("funding Entity")
        plt.ylabel("numer")
        plt.xlabel("funding Entity")
        plt.savefig('fundingEntity.png')
        plt.clf()
        file = discord.File("./impressions.png", filename="image.png")
        await ctx.send(file=file)
        file = discord.File("./page_name.png", filename="image.png")
        await ctx.send(file=file)
        file = discord.File("./spend.png", filename="image.png")
        await ctx.send(file=file)
        file = discord.File("./fundingEntity.png", filename="image.png")
        await ctx.send(file=file)


def setup(bot: TLDR):
    bot.add_cog(facebook_ad(bot))
