import asyncio
from modules import database, slack_bridge

db = database.get_connection()


class Tasks:
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_listener(self.on_ready, 'on_ready')
        self.bot.logger.info('Task module has been initiated')

    async def on_ready(self):
        self.bot.loop.create_task(self.listen())

    async def listen(self):
        self.bot.logger.info('Task module has started listening to tasks.')
        while True:
            await asyncio.sleep(1.0)
            tasks = db.tasks.find({})
            if not tasks:
                continue

            for task in tasks:
                function_name = task['function']
                kwargs = task['kwargs']
                function = getattr(self, function_name, None)
                if function is None:
                    self.bot.logger.error(f'Invalid task function [{function_name}]')

                try:
                    await function(**kwargs)
                except Exception as e:
                    self.bot.logger.error(f'Error with task function [{function_name}] {e}')

                db.tasks.delete_one(task)

    async def update_slack_team(self, *, team_id: str):
        slack = self.bot.slack_bridge
        team_data = db.slack_bridge.find_one({'team_id': team_id})
        team = slack.get_team(team_id)
        if not team:
            team = slack_bridge.SlackTeam(team_data, slack)
            slack.teams.append(team)
        else:
            team.token = team_data['token']
            team.bot_id = team_data['bot_id']
