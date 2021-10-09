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
import re
import datetime 
import config 
import matplotlib.pyplot as plt

##>>democracy_club
ENDPOINT_DEMOCRACY_CLUB = "https://candidates.democracyclub.org.uk/api/next/"
ENDPOINT_WHEREDOIVOTE= "https://wheredoivote.co.uk/api/beta/"
p = re.compile(r'([0-9]*)-([0-9]*)-([0-9]*)T([0-9]*):([0-9]*):([0-9]*)\+([0-9]*)', re.IGNORECASE)

def TimeStop(thing,path_a,path_b):
        time = p.search(thing[path_a][path_b])
        then = datetime.datetime(int(time[1]),int(time[2]),int(time[3]),int(time[4]),int(time[5]),int(time[6]))
        now  = datetime.datetime.now()
        then_duration = datetime.timedelta(**config.timediff)
        duration = now - then
        return not duration<then_duration



class DemocracyClub(Cog):
    def __init__(self, bot):
        self.bot = bot
        self.slug =[]
        self.facebook_adverts_id =[]

    @Cog.listener()
    async def on_ready(self):
        await self.facebook_ad()
        self.democracy_club.start()
        self.facebook_ad.start()
    
    @command(
        help='Show someone you polling station based on their home address.',
        usage="polls",
        examples=["polls"],
        cls=commands.Command,
    )
    async def polling_station(self, ctx: Context,postcode):
        url = ENDPOINT_WHEREDOIVOTE + "postcode/{postcode}.json".format(postcode=postcode)
        r = requests.get(url)
        data = r.json()
        polling_station_known = data ["polling_station_known"]
        electoral_services_contacts_phone_numbers = data ["council"]["electoral_services_contacts"]["phone_numbers"]
        electoral_services_contacts_email = data ["council"]["electoral_services_contacts"]["email"]
        electoral_services_contacts_address = data ["council"]["electoral_services_contacts"]["address"]
        electoral_services_contacts_postcode = data ["council"]["electoral_services_contacts"]["postcode"]
        electoral_services_contacts_website = data ["council"]["electoral_services_contacts"]["website"]
        #electoral_services_contacts_identifiers = data ["council"]["electoral_services_contacts"]["identifiers"]
        #nation = data ["council"]["electoral_services_contacts"]["nation"]
        council_id = data ["council"]["council_id"]
        embed=discord.Embed()
        embed.add_field(name="polling_station_known", value=polling_station_known, inline=False)
        embed.add_field(name="electoral services contacts phone_numbers", value=electoral_services_contacts_phone_numbers, inline=False)
        embed.add_field(name="electoral services contacts email", value=electoral_services_contacts_email, inline=False)
        embed.add_field(name="electoral services contacts address", value=electoral_services_contacts_address, inline=False)
        embed.add_field(name="electoral services contacts postcode", value=electoral_services_contacts_postcode, inline=False)
        embed.add_field(name="electoral services contacts website", value=electoral_services_contacts_website, inline=False)
        #embed.add_field(name="electoral services contacts identifiers", value=electoral_services_contacts_identifiers, inline=False)
        #embed.add_field(name="electoral services contacts nation", value=nation, inline=False)
        embed.add_field(name="council id", value=council_id, inline=False)
        await ctx.send(embed=embed)


    @tasks.loop(seconds=10.0)
    async def democracy_club(self):
        # pull data from democracyclub
        results_feed = feedparser.parse(r'https://candidates.democracyclub.org.uk/results/all.atom')
        # Check the Channel just i case i dont know what as been sent before
        given_name ="democracyclub"
        channel = discord.utils.get(self.bot.get_all_channels(), name=given_name)
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
            embed.add_field(name="election date", value=entries["election_date"], inline=False)
            embed.set_footer(text=entries["election_slug"]) 
            self.slug.append(entries["election_slug"])
            await channel.send(embed=embed)


    @tasks.loop(seconds=10.0)
    async def facebook_ad(self):
        given_name ="facebook-adverts-poitcal"
        channel = discord.utils.get(self.bot.get_all_channels(), name=given_name)
        url = ENDPOINT_DEMOCRACY_CLUB + "facebook_adverts/"
        msgs = await channel.history(limit=200).flatten()

        for msg in msgs:
            if msg.embeds != []:
                if msg.embeds[0].footer.text not in self.slug:
                    self.facebook_adverts_id.append(msg.embeds[0].footer.text)

        results_ = []
        print(self.facebook_adverts_id)
        loop = True
        while loop:
                
            r = requests.get(url)
            data = r.json()
            results_ = results_ + data["results"]
            print(url)
            for result in data["results"]:
                if TimeStop(result,"ad_json","ad_creation_time"):
                   loop = False
                   break
                if result["ad_id"] in self.facebook_adverts_id:
                    loop = False
                    break
            if data["next"] is None:
                break
            else:
                url = data["next"]
        results_.reverse()
        for result in results_:
            if result["ad_id"] in self.facebook_adverts_id:
                continue
            embed= discord.Embed(title=result["ad_json"]["page_name"], url=result["associated_url"])
            embed.set_thumbnail(url=result["image"])
            embed.add_field(name="page_name", value=result["ad_json"]["page_name"], inline=False)
            if "funding_entity" in result["ad_json"].keys():
                embed.add_field(name="funding_entity", value=result["ad_json"]["funding_entity"], inline=False)
            
            if "ad_creative_body" in result["ad_json"].keys():
                if len(result["ad_json"]["ad_creative_body"]) < 1024:
                    embed.add_field(name="ad_creative_body", value=result["ad_json"]["ad_creative_body"], inline=False)
                else:
                    embed.add_field(name="ad_creative_body", value=result["ad_json"]["ad_creative_body"][0:1000] +"...", inline=False)
            embed.add_field(name="ad_creation_time", value=result["ad_json"]["ad_creation_time"], inline=False)
            embed.add_field(name="currency", value=result["ad_json"]["currency"], inline=False)
            embed.add_field(name="spend", value=str(result["ad_json"]["spend"]["lower_bound"])+">"+str(result["ad_json"]["spend"]["upper_bound"]), inline=False)
            embed.add_field(name="person", value=result["person"]["name"], inline=False)
            embed.set_footer(text=result["ad_id"]) 
            self.facebook_adverts_id.append(result["ad_id"])
            ff = {
                "18-24":0,
                "25-34":1,
                "35-44":2,
                "45-54":3,
                "55-64":4,
                "65+":5,
            }
            men_means = [0, 0, 0, 0, 0, 0]
            women_means = [0, 0, 0, 0, 0, 0]
            unknown_means = [0, 0, 0, 0, 0, 0]
            for i in result["ad_json"]["demographic_distribution"]:
                if i["gender"] == "male":
                    men_means[ff[i["age"]]] = float(i["percentage"])
                elif i["gender"] == "female":
                    women_means[ff[i["age"]]] = float(i["percentage"])
                elif i["gender"] == "unknown":
                    unknown_means[ff[i["age"]]] = float(i["percentage"])
            width = 0.35
            labels = ['18-24','25-34','35-44','45-54','55-64','65+']
            x = np.arange(len(labels))
            plt.plot(labels, men_means, label ="men")
            plt.plot(labels, women_means, label ="women")
            plt.plot(labels, unknown_means, label ="unknown")
            plt.show()
            await channel.send(embed=embed)

def setup(bot):
    bot.add_cog(DemocracyClub(bot))
