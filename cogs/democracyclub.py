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
import os
from until.spin import spin


# >>democracy_club
ENDPOINT_DEMOCRACY_CLUB = "https://candidates.democracyclub.org.uk/api/next/"
ENDPOINT_WHEREDOIVOTE = "https://wheredoivote.co.uk/api/beta/"
p = re.compile(r'([0-9]*)-([0-9]*)-([0-9]*)T([0-9]*):([0-9]*):([0-9]*)\+([0-9]*)', re.IGNORECASE)


def timeStop(thing, path_a, path_b):
    time = p.search(thing[path_a][path_b])
    then = datetime.datetime(int(time[1]), int(time[2]), int(time[3]), int(time[4]), int(time[5]), int(time[6]))
    now = datetime.datetime.now()
    then_duration = datetime.timedelta(**config.timediff)
    duration = now - then
    return not duration < then_duration


class DemocracyClub(Cog):
    def __init__(self, bot):
        self.bot = bot
        self.slug = []
        self.facebook_adverts_id = []
        #
        self.person_name= {}
        self.party = {}
        self.funding_entity = []
        self.region_distribution =[]

    @Cog.listener()
    async def on_ready(self):
        await self.facebook_ad_post(await self.facebook_ad_scan())
        self.democracy_club.start()
        self.facebook_ad.start()
    
    async def facebook_ad_scan(self,block_list = []):
        url = ENDPOINT_DEMOCRACY_CLUB + "facebook_adverts/"
        loop = True
        results_ = []
        while loop:
            spin("downloading for facebook_ads")
            r = requests.get(url)
            data = r.json()
            results_ = results_ + data["results"]
            for result in data["results"]:
                if timeStop(result, "ad_json", "ad_creation_time"):
                    loop = False
                    break
                if result["ad_id"] in block_list:
                    loop = False
                    break
            if data["next"] is None:
                break
            else:
                url = data["next"]
        for results in results_:
            spin("scaning results of facebook_ads")
            # for self.candidacie["party"]["ec_id"] not in  data_person["candidacies"]:
            #     if candidacie["party"]["ec_id"] in self.party.keys():
            #         self.party[self.candidacie["party"]["ec_id"]] = self.candidacie["party"]["name"]
            if results["person"]["id"] not in  self.person_name.keys(): 
                r = requests.get(results["person"]["url"])
                data_person = r.json()
                self.person_name[data_person["id"]] =  data_person["honorific_prefix"]+" "+ data_person["name"]
            if "funding_entity" in results["ad_json"].keys():
                if results["ad_json"]["funding_entity"] not in self.region_distribution:
                    self.funding_entity.append(results["ad_json"]["funding_entity"])
            if "region_distribution" in results["ad_json"].keys():
                if results["ad_json"]["region_distribution"] not in self.region_distribution:
                    self.region_distribution.append(results["ad_json"]["region_distribution"])
        return results_

    @command(
        help='Show someone you polling station based on their home address.',
        usage="polls",
        examples=["polls"],
        cls=commands.Command,
    )
    async def get_facebookads_by_most_recent_candidate_of_party(self,ctx:Context,regx):
        pass

    @command(
        help='Show someone you polling station based on their home address.',
        usage="polls",
        examples=["polls"],
        cls=commands.Command,
    )
    async def get_facebookads_by_page_name(self,ctx:Context,regx):
        pass

    @command(
        help='Show someone you polling station based on their home address.',
        usage="polls",
        examples=["polls"],
        cls=commands.Command,
    )
    async def get_facebookads_by_funding_entity(self,ctx:Context,regx):
        pass

    @command(
        help='Show someone you polling station based on their home address.',
        usage="polls",
        examples=["polls"],
        cls=commands.Command,
    )
    async def get_facebookads_by_person_name(self,ctx:Context,regx):
        pass

    @command(
        help='Show someone you polling station based on their home address.',
        usage="polls",
        examples=["polls"],
        cls=commands.Command,
    )
    async def list_partys(self,ctx:Context,regx):
        pass

    @command(
        help='Show someone you polling station based on their home address.',
        usage="polls",
        examples=["polls"],
        cls=commands.Command,
    )
    async def list_person(self,ctx:Context,regx):
        pass

    @command(
        help='Show someone you polling station based on their home address.',
        usage="polls",
        examples=["polls"],
        cls=commands.Command,
    )
    async def list_page_name(self,ctx:Context,regx):
        pass

    @command(
        help='Show someone you polling station based on their home address.',
        usage="polls",
        examples=["polls"],
        cls=commands.Command,
    )
    async def list_funding_entity(self,ctx:Context,regx):
        pass



    @command(
        help='Show someone you polling station based on their home address.',
        usage="polls",
        examples=["polls"],
        cls=commands.Command,
    )
    async def polling_station(self, ctx: Context, postcode):
        url = ENDPOINT_WHEREDOIVOTE + "postcode/{postcode}.json".format(postcode=postcode)
        r = requests.get(url)
        data = r.json()
        polling_station_known = data["polling_station_known"]
        electoral_services_contacts_phone_numbers = data["council"]["electoral_services_contacts"]["phone_numbers"]
        electoral_services_contacts_email = data["council"]["electoral_services_contacts"]["email"]
        electoral_services_contacts_address = data["council"]["electoral_services_contacts"]["address"]
        electoral_services_contacts_postcode = data["council"]["electoral_services_contacts"]["postcode"]
        electoral_services_contacts_website = data["council"]["electoral_services_contacts"]["website"]
        #electoral_services_contacts_identifiers = data ["council"]["electoral_services_contacts"]["identifiers"]
        #nation = data ["council"]["electoral_services_contacts"]["nation"]
        council_id = data["council"]["council_id"]
        embed = discord.Embed()
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
        given_name = "democracyclub"
        channel = discord.utils.get(self.bot.get_all_channels(), name=given_name)
        msgs = await channel.history(limit=len(results_feed.entries) * 2).flatten()
        for msg in msgs:
            if msg.embeds != []:
                if msg.embeds[0].footer.text not in self.slug:
                    self.slug.append(msg.embeds[0].footer.text)
        for entries_i in range(1, len(results_feed.entries) - 1):
            entries = results_feed.entries[entries_i]

            if entries["election_slug"] in self.slug:
                continue
            self.slug.append(entries["election_slug"])
            embed = discord.Embed(title=entries["title"], url=entries["information_source"])
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
        results_ = await self.facebook_ad_scan(self.facebook_adverts_id)
        await self.facebook_ad_post(results_)
    
    async def facebook_ad_post(self,results_):
        given_name = "facebook-adverts-poitcal"
        channel = discord.utils.get(self.bot.get_all_channels(), name=given_name)
        msgs = await channel.history(limit=200).flatten()
        for msg in msgs:
            if msg.embeds != []:
                if msg.embeds[0].footer.text not in self.facebook_adverts_id:
                    self.facebook_adverts_id.append(msg.embeds[0].footer.text)
        results_.reverse()
        for result in results_:
            if result["ad_id"] in self.facebook_adverts_id:
                break
            embed = discord.Embed(title=result["ad_json"]["page_name"], url=result["associated_url"])
            embed.set_thumbnail(url=result["image"])
            embed.add_field(name="page_name", value=result["ad_json"]["page_name"], inline=False)
            if "funding_entity" in result["ad_json"].keys():
                embed.add_field(name="funding_entity", value=result["ad_json"]["funding_entity"], inline=False)

            if "ad_creative_body" in result["ad_json"].keys():
                if len(result["ad_json"]["ad_creative_body"]) < 1024:
                    embed.add_field(name="ad_creative_body", value=result["ad_json"]["ad_creative_body"], inline=False)
                else:
                    embed.add_field(name="ad_creative_body", value=result["ad_json"]["ad_creative_body"][0:1000] + "...", inline=False)
            embed.add_field(name="ad_creation_time", value=result["ad_json"]["ad_creation_time"], inline=False)
            if "ad_delivery_stop_time" in result["ad_json"].keys():
                embed.add_field(name="ad_delivery_stop_time", value=result["ad_json"]["ad_delivery_stop_time"], inline=False)
            if "ad_delivery_start_time" in result["ad_json"].keys():
                embed.add_field(name="ad_delivery_start_time", value=result["ad_json"]["ad_delivery_start_time"], inline=False)
            embed.add_field(name="spend", value="between inclusively: " + str(result["ad_json"]["spend"]["lower_bound"]) + " and " + str(result["ad_json"]["spend"]["upper_bound"] + " " + result["ad_json"]["currency"]), inline=False)
            if "impressions" in result["ad_json"].keys():
                embed.add_field(name="impressions", value="between inclusively: " + str(result["ad_json"]["impressions"]["lower_bound"]) + " and " + str(result["ad_json"]["impressions"]["upper_bound"]), inline=False)
            embed.add_field(name="person", value=result["person"]["name"], inline=False)
            embed.set_footer(text=result["ad_id"])
            #embed.set_image(url="attachment://"+"grath_facebook_ad" + str(result["ad_id"]) + ".png")

            self.facebook_adverts_id.append(result["ad_id"])
            ageRageIndex = {
                "13-17": 0,
                "18-24": 1,
                "25-34": 2,
                "35-44": 3,
                "45-54": 4,
                "55-64": 5,
                "65+": 6,
            }
            men_means = [None,None, None, None, None, None, None]
            women_means = [None,None, None, None, None, None, None]
            unknown_means = [None,None, None, None, None, None, None]
            region_percentage = []
            region_lab = []
            for i in result["ad_json"]["demographic_distribution"]:
                if i["gender"] == "male":
                    men_means[ageRageIndex[i["age"]]] = float(i["percentage"])
                elif i["gender"] == "female":
                    women_means[ageRageIndex[i["age"]]] = float(i["percentage"])
                elif i["gender"] == "unknown":
                    unknown_means[ageRageIndex[i["age"]]] = float(i["percentage"])
            for i in result["ad_json"]["region_distribution"]:
                region_lab.append(i["region"])
                region_percentage.append(i["percentage"])
            width = 0.35
            labels = ["13-17",'18-24', '25-34', '35-44', '45-54', '55-64', '65+']
            fig, (ax1, ax2) = plt.subplots(2)
            ax1.set_title('demographic distribution')
            ax1.plot(labels, men_means,"o", label="men")
            ax1.plot(labels, women_means,"o", label="women")
            ax1.plot(labels, unknown_means,"o", label="unknown")
            ax1.legend()
            ax2.set_title('region')
            ax2.plot(region_lab, region_percentage,"bo", label="region")
            plt.legend()
            plt.savefig("grath_facebook_ad" + str(result["ad_id"]) + ".png")
            plt.close()
            image = discord.File("grath_facebook_ad" + str(result["ad_id"]) + ".png", filename="grath_facebook_ad" + str(result["ad_id"]) + ".png")
            await channel.send(embed=embed, file=image)
            os.remove("grath_facebook_ad" + str(result["ad_id"]) + ".png")


def setup(bot):
    bot.add_cog(DemocracyClub(bot))
