import pymongo
from config import MONGODB_URL, DEV_IDS
from modules import cache


class Connection:
    def __init__(self):
        self.mongo_client = pymongo.MongoClient(MONGODB_URL)
        self.db = self.mongo_client['TLDR']
        self.levels = self.db['levels']
        self.timers = self.db['timers']
        self.cases = self.db['cases']
        self.server_options = self.db['server_options']
        self.polls = self.db['polls']

    def _get_server_options(self, guild_id):
        doc = self.server_options.find_one({'guild_id': guild_id})
        if doc is None:
            doc = {
                'guild_id': guild_id,
                'mute_role': 0
            }
            self.server_options.insert_one(doc)
        return doc

    @cache.cache()
    def get_server_options(self, guild_id, value):
        doc = self._get_server_options(guild_id)
        return doc[value] if value in doc else None

    def _get_levels(self, guild_id):
        doc = self.levels.find_one({'guild_id': guild_id})
        if doc is None:
            doc = {
                'guild_id': guild_id,
                'users': {},
                'level_up_channel': 0,
                'leveling_routes': {
                    'parliamentary': [
                        ('Citizen', 5),
                        ('Party Member', 5),
                        ('Party Campaigner', 5),
                        ('Local Councillor', 5),
                        ('Council Chair', 5),
                        ('Mayor', 5),
                        ('Candidate', 5),
                        ('Opposition Backbencher', 5),
                        ('Shadow Minister', 5),
                        ('Opposition Whip', 5),
                        ('Shadow Cabinet Minister', 5),
                        ('Government Backbencher', 5)
                    ],
                    'honours': [
                        ('Public Servant', 5)
                    ]
                },
                'honours_channels': []
            }
            self.levels.insert_one(doc)
        return doc

    @cache.cache()
    def get_levels(self, value, guild_id, user_id=None):
        doc = self._get_levels(guild_id)
        if user_id is None:
            return doc[value]
        user_id = str(user_id)
        if user_id not in doc['users']:
            user = {
                'pp': 0,
                'p_level': 0,
                'hp': 0,
                'h_level': 0,
                'p_role': 'Citizen',
                'h_role': ''
            }
            self.levels.update_one({'guild_id': guild_id}, {'$set': {f'users.{user_id}': user}})
            doc['users'][user_id] = user

        return doc['users'][user_id][value]

    def _get_timers(self, guild_id):
        doc = self.timers.find_one({'guild_id': guild_id})
        if doc is None:
            doc = {
                'guild_id': guild_id,
                'timers': [
                    #     {_id: ''
                    #     'expires': 0,
                    #     'event': ''
                    #     'extras': {}},
                ]
            }
            self.timers.insert_one(doc)
        return doc

    @cache.cache()
    def get_timer(self, guild_id, timer_id):
        doc = self._get_timers(guild_id)
        timers = doc['timers']
        timer = [t for t in timers if t['id'] == timer_id]
        return timer[0] if timer else None

    @cache.cache()
    def get_user_timer(self, guild_id, user_id, event):
        self._get_timers(guild_id)
        match = self.timers.find_one({'guild_id': guild_id},
                                     {'timers': {'$elemMatch': {'extras.member_id': user_id, 'event': event}}})
        return match['timers'][0] if match and 'timers' in match else False

    def _get_cases(self, guild_id):
        doc = self.cases.find_one({'guild_id': guild_id})
        if doc is None:
            doc = {
                'guild_id': guild_id,
                'users': {
                    # 'user_id': {
                    #     'mute': [
                    #        { 'by': 0, | user id
                    #         'reason': '',
                    #         'length': 0 } | Seconds
                    #     ],
                    #     'kick': [
                    #        { 'by': 0,
                    #         'reason': '' }
                    #     ],
                    #     'temp_ban': [
                    #        { 'by': 0,
                    #         'reason': '',
                    #         'length': 0 }
                    #     ]
                    # }
                }
            }
            self.cases.insert_one(doc)
        return doc

    @cache.cache()
    def get_cases(self, value, guild_id, user_id=None):
        doc = self._get_cases(guild_id)
        if user_id is None:
            return doc[value]
        user_id = str(user_id)
        if user_id not in doc['users']:
            user = {
                'warn': [],
                'mute': [],
                'kick': [],
                'temp_ban': []
            }
            self.cases.update_one({'guild_id': guild_id}, {'$set': {f'users.{user_id}': user}})
            doc['users'][user_id] = user

        return doc['users'][user_id][value]

    def _get_polls(self, guild_id):
        doc = self.polls.find_one({'guild_id': guild_id})
        if doc is None:
            doc = {
                'guild_id': guild_id,
                'polls': {
                    # 'message id': {
                    #     'emote': 0,
                    # }
                }
            }
            self.polls.insert_one(doc)
        return doc

    @cache.cache()
    def get_polls(self, guild_id, message_id=None):
        doc = self._get_polls(guild_id)
        if message_id is None:
            return doc['polls']
        else:
            message_id = str(message_id)
            return doc['polls'][message_id] if message_id in doc['polls'] else None
