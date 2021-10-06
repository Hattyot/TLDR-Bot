import config

from modules import database
from slack_bolt.app.async_app import AsyncWebClient
from sanic import Sanic, HTTPResponse
from sanic.views import HTTPMethodView
from sanic.response import redirect

db = database.get_connection()
app = Sanic("TLDR-Bot-api")


class SlackOauth(HTTPMethodView):
    async def get(self, request):
        code = request.args.get('code')
        if not code:
            return HTTPResponse("Invalid Code")

        client = AsyncWebClient()
        try:
            response = await client.oauth_v2_access(
                client_id=config.SLACK_CLIENT_ID,
                client_secret=config.SLACK_CLIENT_SECRET,
                code=code
            )
        except:
            return HTTPResponse("Authentication Failed.")

        team_id = response['team']['id']
        access_token = response['access_token']
        bot_id = response['bot_user_id']

        # update slack team in the database
        data = db.slack_bridge.find_one({'team_id': team_id})
        if data and data.get('token', '') != access_token:
            db.slack_bridge.update_one(
                {'team_id': team_id},
                {'$set': {'token': access_token}}
            )
        if not data:
            db.slack_bridge.insert_one({
                'team_id': team_id,
                'token': access_token,
                'bot_id': bot_id,
                'aliases': [],
                'bridges': []
            })

        # create task
        db.tasks.insert_one({
            'function': 'update_slack_team',
            'kwargs': {
                'team_id': team_id
            }
        })

        return redirect(f'https://app.slack.com/client/{team_id}')


app.add_route(SlackOauth.as_view(), '/slack/oauth')
app.run(
  host='0.0.0.0',
  port=443,
  ssl=dict(
    cert=f"/etc/letsencrypt/live/{config.SLACK_REDIRECT_DOMAIN}/fullchain.pem",
    key=f"/etc/letsencrypt/live/{config.SLACK_REDIRECT_DOMAIN}/privkey.pem",
  )
)

