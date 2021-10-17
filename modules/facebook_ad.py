import threading
from warnings import filters
import requests
from pymongo import MongoClient, mongo_client
import time
import sys
client = MongoClient(port=27017)
democracyclub = client.democracyclub


def recoder_facebook(data_ad_in):
    data = {}
    data["_id"]=data_ad_in["ad_id"]
    if "spend" in data_ad_in["ad_json"].keys():
        data["spend"]=data_ad_in["ad_json"]["spend"]
    if "page_id" in data_ad_in["ad_json"].keys() and "page_name" in data_ad_in["ad_json"].keys():
        data["page"] ={
            "name":data_ad_in["ad_json"]["page_name"],
            "id":data_ad_in["ad_json"]["page_id"]
        }
    elif "page_name" in data_ad_in["ad_json"].keys():
        data["page"] ={
            "name":data_ad_in["ad_json"]["page_name"]
            }
    elif  "page_id" in data_ad_in["ad_json"].keys():
        data["page"] ={
            "id":data_ad_in["ad_json"]["page_id"]
            }
    if "currency" in data_ad_in["ad_json"].keys():
        data["currency"]=data_ad_in["ad_json"]["currency"]
    if "funding_entity" in data_ad_in["ad_json"].keys():
        data["fundingEntity"] = data_ad_in["ad_json"]["funding_entity"]
    if "impressions" in data_ad_in["ad_json"].keys():
        data["impressions"] = data_ad_in["ad_json"]["impressions"]
    if "regionDistribution" in data_ad_in["ad_json"].keys():
        data["region_distribution"] = data_ad_in["ad_json"]["region_distribution"]
    if "ad_creative_body" in data_ad_in["ad_json"].keys():
        data["adCreativeBody"] = data_ad_in["ad_json"]["ad_creative_body"]
    if "ad_delivery_start_time" in data_ad_in["ad_json"].keys():
        data["adDeliveryStartTime"] = data_ad_in["ad_json"]["ad_delivery_start_time"]
    if "ad creation time" in data_ad_in["ad_json"].keys():
        data["adCreationTime"] = data_ad_in["ad_json"]["ad_creation_time"]
    if "ad_delivery_stop_time" in data_ad_in["ad_json"].keys():
        data["adDeliveryStopTime"] = data_ad_in["ad_json"]["ad_delivery_stop_time"]
    if "associated url" in data_ad_in["ad_json"].keys():
        data["associated_url"] = data_ad_in["ad_json"]["associated_url"]
    if "image" in data_ad_in["ad_json"].keys():
        data["image"] = data_ad_in["ad_json"]["image"]
    if "demographic distribution" in data_ad_in["ad_json"].keys():
        data["demographicDistribution"] = data_ad_in["demographic_distribution"]["image"]
    # if "region_distribution" in data_ad_in["ad_json"].keys():
        # data["region distribution"] = data_ad_in["region_distribution"]["image"]
    data["person"]= {
        "id": data_ad_in["person"]["id"],
        "url": data_ad_in["person"]["url"],
        "name": data_ad_in["person"]["name"],
    }
    #"associated_url"=data_ad["ad_json"]["associated_url"],
    return data

def recoder_people(data_people_in):
    person ={
        "id":data_people_in["id"],
        "candidacies":data_people_in["candidacies"],
        "identifiers":data_people_in["identifiers"],
        "gender":data_people_in["gender"],
        "name":data_people_in["name"],
        "honorific_prefix":data_people_in["honorific_prefix"],
    }
    return person

class facebookAdPuller(threading.Thread):
    def __init__(self):
        super().__init__()
        self.ENDPOINT_DEMOCRACY_CLUB = "https://candidates.democracyclub.org.uk/api/next/"
        client = MongoClient(port=27017)
        self.democracyclub = client.democracyclub

    def run(self):
        super().run()
        while True:
            self.facebook_ad_db_download()
            time.sleep(2.4)

 

    def facebook_ad_db_download(self):
        url = self.ENDPOINT_DEMOCRACY_CLUB + "facebook_adverts/"
        downlading = True
        while downlading:
            r = requests.get(url)
            data = r.json()
            for result in data["results"]:
                ## Check is in DB
                number_of_entrys = self.democracyclub.facebook_ad_db.count_documents({"_id": result["ad_id"]})
                #print(number_of_entrys)
                if number_of_entrys != 0:
                    continue
                ## Copy data in to db
                document1 = recoder_facebook(result)
                #print(document1)
                output = self.democracyclub.facebook_ad_db.insert_one(document1)
            url = data["next"]
            if url is None:
                break


 

    def wikidata_db_download_politicians(self):
        from SPARQLWrapper import SPARQLWrapper, JSON
        sparql = SPARQLWrapper("https://query.wikidata.org/sparql")
        f = """
        SELECT ?human ?humanLabel ?member_of_political_partyLabel ?political_alignmentLabel ?political_ideologyLabel ?Democracy_Club_candidate_ID ?Companies_House_officer_ID ?PublicWhip_ID ?UK_Parliament_identifier ?UK_Parliament_thesaurus_ID WHERE {
        SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }
        ?human wdt:P31 wd:Q5;
        wdt:P106 wd:Q82955.
        MINUS { ?human wdt:P570 ?date_of_death. }
        ?human wdt:P27 wd:Q145.
        { ?human wdt:P102 ?member_of_political_party. }
        OPTIONAL { ?member_of_political_party wdt:P1387 ?political_alignment. }
        OPTIONAL { ?human wdt:P1142 ?political_ideology. }
        OPTIONAL { ?member_of_political_party wdt:P1387 ?political_alignment. }
        OPTIONAL { ?member_of_political_party wdt:P1142 ?political_ideology. }
        OPTIONAL { ?human wdt:P6465 ?Democracy_Club_candidate_ID. }
        OPTIONAL { ?human wdt:P5297 ?Companies_House_officer_ID. }
        OPTIONAL { ?human wdt:P2169 ?PublicWhip_ID. }
        OPTIONAL { ?human wdt:P6213 ?UK_Parliament_identifier. }
        OPTIONAL { ?human wdt:P4527 ?UK_Parliament_thesaurus_ID. }
        }
        """
        sparql.setQuery(f)
        sparql.setReturnFormat(JSON)
        results = sparql.query().convert()
        for result in results["results"]["bindings"]:
            f = {}
            print(result["member_of_political_partyLabel"])
            if "political_alignment" in result.keys():
              print(result["political_alignment"])
            if "political_ideology" in result.keys():
              print(result["political_ideology"])
            if "Companies_House_officer_ID" in result.keys():
              print(result["Companies_House_officer_ID"])
            if "PublicWhip_ID" in result.keys():
              print(result["PublicWhip_ID"])
            if "UK_Parliament_identifier" in result.keys():
              print(result["UK_Parliament_identifier"])
            if "UK_Parliament_thesaurus_ID" in result.keys():
              print(result["UK_Parliament_thesaurus_ID"])
def query(*q):
    def myFunc(e):
      return e["index"]
    alist = []
    qstring = " ".join(q)
    keywords = [
        "ad delivery stop time",
        "less then ad delivery stop time",
        "greater then ad delivery stop time",
        "greater equal then ad delivery stop time",
        "less equal then ad delivery stop time",
        #ad creation time
        "ad creation time",
        "less then ad creation time",
        "greater then ad creation time",
        "greater equal then ad creation time",
        "less equal then ad creation time",
        #ad delivery start time
        "ad delivery start time" ,
        "less then ad delivery start time" ,
        "greater then ad delivery start time" ,
        "greater equal then ad delivery start time" ,
        "less equal then ad delivery start time"
        #ad creative body
        "ad creative body" ,
        "regx ad creative body" ,
        "has ad creative body" ,
        "end ad creative body" ,
        "start ad creative body" ,
        "region distribution",
        #impressions
        "impressions",
        "less then impressions",
        "greater then impressions",
        "greater equal then impressions",
        "less equal then impressions",
        #currency
        "currency",
        "less then currency",
        "greater then currency",
        "greater equal then currency",
        "less equal then currency",
        #page name
        "page name",
        "regx page name",
        "start page name",
        "end page name",
        "has page name",
        # funding entity
        "funding entity",
        "regx funding entity",
        "start funding entity",
        "end funding entity",
        "has funding entity",
        #name

        ]
    for kayword in keywords:
        if kayword in qstring:
            index = qstring.index(kayword)
            alist.append({
                "type":kayword,
                "index":index,
                "len":len(kayword + " ")
            })
    alist.sort(key=myFunc)
    mongo_qurry = {    }
    for i in range(len(alist)):
        print(alist)
        start = alist[i]["len"] + alist[i]["index"]
        print(qstring[ alist[i]["index"]:start])
        if len(alist) != i+1:
            end = alist[i+1]["index"]
            print(qstring[start:end])
        else:
            end = len(qstring)
            print(qstring[start:end])
        alist[i] = {"type":alist[i]["type"],"value":qstring[start:end]}
    for i in range(len(alist)):
        if "ad delivery stop time" in alist[i]["type"]:
            mongo_qurry["adDeliveryStopTime"] = alist[i]["value"]
        elif "less then ad delivery stop time" in alist[i]["type"]:
            pass
        elif "greater then ad delivery stop time" in alist[i]["type"]:
            pass
        elif "greater equal then ad delivery stop time" in alist[i]["type"]:
            pass
        elif "less equal then ad delivery stop time" in alist[i]["type"]:
            pass
        # if #ad creation time in alist[i]["type"]:
        #     pass
        elif "ad creation time" in alist[i]["type"]:
            mongo_qurry["adCreationTime"] = alist[i]["value"]
        elif "less then ad creation time" in alist[i]["type"]:
            pass
        elif "greater then ad creation time" in alist[i]["type"]:
            pass
        elif "greater equal then ad creation time" in alist[i]["type"]:
            pass
        elif "less equal then ad creation time" in alist[i]["type"]:
            pass
        # if #ad delivery start time in alist[i]["type"]:
        #     pass
        elif "ad delivery start time"  in alist[i]["type"]:
            mongo_qurry["adDeliveryStartTime"] = alist[i]["value"]
        elif "less then ad delivery start time"  in alist[i]["type"]:
            pass
        elif "greater then ad delivery start time"  in alist[i]["type"]:
            pass
        elif "greater equal then ad delivery start time"  in alist[i]["type"]:
            pass
        elif "less equal then ad delivery start time" in alist[i]["type"]:
            pass
        # if #ad creative body in alist[i]["type"]:
        #     pass
        elif "ad creative body"  in alist[i]["type"]:
            mongo_qurry["adCreativeBody"] = alist[i]["value"]
        elif "regx ad creative body" in alist[i]["type"]:
            pass
        elif "has ad creative body" in alist[i]["type"]:
            pass
        elif "end ad creative body" in alist[i]["type"]:
            pass
        elif "start ad creative body" in alist[i]["type"]:
            pass
        elif "region distribution" in alist[i]["type"]:
            pass
        # if #impressions in alist[i]["type"]:
        #     pass
        elif "impressions" in alist[i]["type"]:
            mongo_qurry["impressions"] = alist[i]["value"]
        elif "less then impressions" in alist[i]["type"]:
            pass
        elif "greater then impressions" in alist[i]["type"]:
            pass
        elif "greater equal then impressions" in alist[i]["type"]:
            pass
        elif "less equal then impressions" in alist[i]["type"]:
            pass
        # if #currency in alist[i]["type"]:
        #     pass
        elif "currency" in alist[i]["type"]:
            mongo_qurry["currency"] = alist[i]["value"]
        elif "less then currency" in alist[i]["type"]:
            pass
        elif "greater then currency" in alist[i]["type"]:
            pass
        elif "greater equal then currency" in alist[i]["type"]:
            pass
        elif "less equal then currency" in alist[i]["type"]:
            pass
        # if #page name in alist[i]["type"]:
        #     pass
        elif "page name" in alist[i]["type"]:
            mongo_qurry["page.name"] = alist[i]["value"]
        elif "regx page name" in alist[i]["type"]:
            pass
        elif "start page name" in alist[i]["type"]:
            pass
        elif "end page name" in alist[i]["type"]:
            pass
        elif "has page name" in alist[i]["type"]:
            pass
        # if # funding entity in alist[i]["type"]:
        #     pass
        elif "funding entity" in alist[i]["type"]:
            mongo_qurry["fundingEntity"]  = alist[i]["value"]
        elif "regx funding entity" in alist[i]["type"]:
            pass
        elif "start funding entity" in alist[i]["type"]:
            pass
        elif "end funding entity" in alist[i]["type"]:
            pass
        elif "has funding entity" in alist[i]["type"]:
            pass
        # if #name in alist[i]["type"]:
        #     pass
        elif "regx name" in alist[i]["type"]:
            pass
        elif "star tname" in alist[i]["type"]:
            pass
        elif "end name" in alist[i]["type"]:
            pass
        elif "name" in alist[i]["type"]:
            mongo_qurry["name"] = alist[i]["value"]
        print("qurry:",mongo_qurry)
        rulsts = democracyclub.facebook_ad_db.find(mongo_qurry)
        for i in rulsts:
            print(i)
        return rulsts
code = facebookAdPuller()
code.start()

## TEST script form hear down
if __name__ == "__main__":
    def exit():
        sys.exit(0)
    # funding_entity
    def  list_funding_entity(pNp = 0):
        p = int(pNp) * 10
        print("page number: ",p)
        number_of_entrys = democracyclub.facebook_ad_db.distinct("funding_entity")
        print (number_of_entrys[p:min(p+5,len(number_of_entrys))])
    def  list_person_id_count():
        number_of_entrys = democracyclub.facebook_ad_db.distinct("funding_entity")
        print(len(number_of_entrys))
    # page_name
    def  list_page_name_entity(pNp = 0):
        p = int(pNp) * 10
        print("page number: ",p)
        number_of_entrys = democracyclub.facebook_ad_db.distinct("page_name")
        print (number_of_entrys[p:min(p+5,len(number_of_entrys))])
    def  page_name_count():
        number_of_entrys = democracyclub.facebook_ad_db.distinct("page_name")
        print(len(number_of_entrys))
    # impressions
    def  list_impressionsentity(pNp = 0):
        p = int(pNp) * 10
        print("page number: ",p)
        number_of_entrys = democracyclub.facebook_ad_db.distinct("impressions")
        print (number_of_entrys[p:min(p+5,len(number_of_entrys))])
    def impressions_count():
        number_of_entrys = democracyclub.facebook_ad_db.distinct("impressions")
        print(len(number_of_entrys))
    # region_distribution
    def  list_region_distribution(pNp = 0):
        p = int(pNp) * 10
        print("page number: ",p)
        number_of_entrys = democracyclub.facebook_ad_db.distinct("region_distribution")
        print (number_of_entrys[p:min(p+5,len(number_of_entrys))])
    def region_distribution_count():
        number_of_entrys = democracyclub.facebook_ad_db.distinct("region_distribution")
        print(len(number_of_entrys))
    # ad_creative_body
    def  list_ad_creative_body(pNp = 0):
        p = int(pNp) * 10
        print("page number: ",p)
        number_of_entrys = democracyclub.facebook_ad_db.distinct("ad_creative_body")
        print (number_of_entrys[p:min(p+5,len(number_of_entrys))])
    def ad_creative_body_count():
        number_of_entrys = democracyclub.facebook_ad_db.distinct("ad_creative_body")
        print(len(number_of_entrys))
    # ad_delivery_start_time
    def  list_ad_delivery_start_time(pNp = 0):
        p = int(pNp) * 10
        print("page number: ",p)
        number_of_entrys = democracyclub.facebook_ad_db.distinct("ad_delivery_start_time")
        print (number_of_entrys[p:min(p+5,len(number_of_entrys))])
    def ad_delivery_start_time_count():
        number_of_entrys = democracyclub.facebook_ad_db.distinct("ad_delivery_start_time")
        print(len(number_of_entrys))
    # ad_delivery_stop_time
    def  list_ad_delivery_stop_time(pNp = 0):
        p = int(pNp) * 10
        print("page number: ",p)
        number_of_entrys = democracyclub.facebook_ad_db.distinct("ad_delivery_stop_time")
        print (number_of_entrys[p:min(p+5,len(number_of_entrys))])
    def ad_delivery_stop_time_count():
        number_of_entrys = democracyclub.facebook_ad_db.distinct("ad_delivery_stop_time")
        print(len(number_of_entrys))
    # corrys
    def  list_ad_delivery_stop_time(pNp = 0):
        p = int(pNp) * 10
        print("page number: ",p)
        number_of_entrys = democracyclub.facebook_ad_db.distinct("ad_delivery_stop_time")
        print (number_of_entrys[p:min(p+5,len(number_of_entrys))])
    def ad_delivery_stop_time_count():
        number_of_entrys = democracyclub.facebook_ad_db.distinct("ad_delivery_stop_time")
        print(len(number_of_entrys))
    # person_id
    def list_person_id(pNp = 0):
        p = int(pNp) * 10
        print("page number: ",p)
        number_of_entrys = democracyclub.facebook_ad_db.distinct("person_id")
        print (number_of_entrys[p:min(p+5,len(number_of_entrys))])
    def aperson_id_count():
        number_of_entrys = democracyclub.facebook_ad_db.distinct("person_id")
        print(len(number_of_entrys))
    # currency
    def list_currency(pNp = 0):
        p = int(pNp) * 10
        print("page number: ",p)
        number_of_entrys = democracyclub.facebook_ad_db.distinct("currency")
        print (number_of_entrys[p:min(p+5,len(number_of_entrys))])
    def currency_count():
        number_of_entrys = democracyclub.facebook_ad_db.distinct("currency")
        print(len(number_of_entrys))
    
    def currency_count():
        number_of_entrys = democracyclub.facebook_ad_db.distinct("currency")
        print(len(number_of_entrys))
    # Query


    commands ={
        "query": query,
        "exit": exit,
        "list_funding_entity": list_funding_entity,
        "list_person_id_count": list_person_id_count,
        "list_page_name_entity": list_page_name_entity,
        "page_name_count": page_name_count,
        "list_impressionsentity": list_impressionsentity,
        "impressions_count": impressions_count,
        "list_region_distribution": list_region_distribution,
        "region_distribution_count": region_distribution_count,
        "list_ad_delivery_start_time": list_ad_delivery_start_time,
        "ad_delivery_start_time_count": ad_delivery_start_time_count,
        "list_ad_delivery_stop_time": list_ad_delivery_stop_time,
        "list_person_id": list_person_id,
        "aperson_id_count": aperson_id_count,
        "list_currency": list_currency,
        "currency_count": currency_count,
    }
    while True:
            iput = input(">>")
            c = iput.split(" ")
            print(c)
            commands[c[0]](*c[1:len(c)])

