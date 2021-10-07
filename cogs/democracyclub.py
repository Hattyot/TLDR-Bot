from discord import client
from discord.ext.commands.cog import Cog
import feedparser
import discord
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
from discord.ext import tasks





##>>democracy_club


class DemocracyClub(Cog):
    def __init__(self, bot):
        self.bot = bot
        self.slug =[]

    @Cog.listener()
    async def on_ready(self):
        self.democracy_club.start()





    @tasks.loop(seconds=10.0)
    async def democracy_club(self):
        given_name ="democracyclub"
        channel = discord.utils.get(self.bot.get_all_channels(), name=given_name)
        results_feed = feedparser.parse(r'https://candidates.democracyclub.org.uk/results/all.atom')
        msgs = await channel.history(limit=len(results_feed.entries)*2).flatten()
        for msg in msgs:
            if msg.embeds != []:
                if msg.embeds[0].footer.text not in self.slug:
                    self.slug.append(msg.embeds[0].footer.text)
        for entries_i in range(1,len(results_feed.entries)-1):
            entries = results_feed.entries[entries_i]
            if entries["election_slug"] in self.slug:
                continue
            self.slug.append(entries["election_slug"])
            embed= discord.Embed(title=entries["title"], url=entries["information_source"])
            if "image_url" in entries.keys():
                img_url = entries["image_url"]
                img_url = img_url.replace("https://candidates.democracyclub.org.uk/", "")
                embed.set_thumbnail(url=img_url)
            if "winner_party_name" in entries.keys():
                embed.add_field(name="winner party", value=entries["winner_party_name"], inline=False)
            embed.add_field(name="winner person", value=entries["winner_person_name"], inline=False)
            embed.add_field(name="post name", value=entries["post_name"], inline=False)
            embed.add_field(name="election name", value=entries["election_name"], inline=False)
            embed.set_footer(text=entries["election_slug"]) 
            self.slug.append(entries["election_slug"])
            await channel.send(embed=embed)


def setup(bot):
    bot.add_cog(DemocracyClub(bot))
