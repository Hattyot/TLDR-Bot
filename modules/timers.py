import asyncio
import time

from bson import ObjectId
from discord.ext.commands import Bot

from modules import database

db = database.get_connection()


class Loop:
    def __init__(self, coro, seconds, minutes, hours):
        self.coro = coro
        self._injected = None

        self.seconds = seconds
        self.minutes = minutes
        self.hours = hours
        self.time = seconds + (minutes * 60) + (hours * 60 * 60)

        self.started = asyncio.Event()
        self.loop = asyncio.get_event_loop()
        self.loop.create_task(self.run_loop())

    def start(self):
        self.started.set()

    def stop(self):
        self.started.clear()

    def is_running(self):
        return self.started.is_set()

    def __get__(self, obj, objtype):
        if obj is None:
            return self

        self._injected = obj
        return self

    async def run_loop(self):
        print(self.started.is_set())
        await self.started.wait()
        while True:
            await asyncio.sleep(self.time)

            # if loop is stopped return to waiting
            if not self.started.is_set() or not self.loop.is_running():
                return await self.run_loop()

            try:
                await self.coro(self._injected)
            except Exception as e:
                if hasattr(self._injected, "bot"):
                    await self._injected.bot.on_event_error(
                        e, self.coro.__name__, loop=True
                    )
                if isinstance(self._injected, Bot):
                    # checking if isinstace bot, cause can't import TLDR due to circular import
                    await self._injected.on_event_error(
                        e, self.coro.__name__, loop=True
                    )


def loop(*, seconds=0, minutes=0, hours=0):
    def decorator(func):
        kwargs = {
            "seconds": seconds,
            "minutes": minutes,
            "hours": hours,
        }
        return Loop(func, **kwargs)

    return decorator


class Timers:
    """
    Class for implementing functions with timed calls.
    Functions will be called by dispatching bot events by the name `on_{event}_timer_over`.

    Attributes
    ---------------
    bot: :class:`bot.TLDR`
        The discord bot.
    """

    def __init__(self, bot):
        self.bot = bot
        self.bot.add_listener(self.on_ready, "on_ready")
        self.bot.logger.info("Timers module has been initiated")

    async def on_ready(self):
        await self.run_old()

    async def run_loop(self, loop: Loop):
        await loop.started.wait()
        while True:
            # if loop is stopped return
            if not loop.started.is_set():
                return self.run_loop(loop)

            await asyncio.sleep(loop.time)
            await loop.coro()

    async def run_old(self) -> None:
        """Runs all the timers that were cut short, that are still in the database."""
        await self.bot.left_check.wait()

        timers = db.timers.find({})
        self.bot.logger.info(f"Running {timers.count()} old timers.")

        for timer in timers:
            asyncio.create_task(self.run(timer))

    async def run(self, timer) -> None:
        """
        Runs a timer, by sleeping until the timer expires.

        Parameters
        ----------------
        timer: :class:`dict`
            Timer dictionary from :func:`create`
        """
        now = round(time.time())

        if timer["expires"] > now:
            await asyncio.sleep(timer["expires"] - now)

        self.call_event(timer)

    def call_event(self, timer) -> None:
        """
        Call timer event.
        Event will be dispatched with the name `on_{event}_timer_over`.

        Parameters
        ----------------
        timer: :class:`dict`
            Timer dictionary from :func:`create`
        """
        timer = db.timers.find_one({"_id": ObjectId(timer["_id"])})
        if not timer:
            return

        db.timers.delete_one({"_id": ObjectId(timer["_id"])})
        self.bot.dispatch(f'{timer["event"]}_timer_over', timer)

    def create(self, *, guild_id: int, expires: int, event: str, extras: dict):
        """
        Create a new timer.

        Parameters
        ----------------
        guild_id: :class:`int`
            ID of the guild the timer will belong to.
        expires: :class:`int`
            Time when timer will expire and the event will be dispatched.
        event: :class:`str`
            The name of the event that will be dispatched with the name `on_{event}_timer_over`.
        extras: :class:`dict`
            Extra data that can be passed to the timer.
        """
        timer_dict = {
            "guild_id": guild_id,
            "expires": expires,
            "event": event,
            "extras": extras,
        }

        result = db.timers.insert_one(timer_dict)
        timer_dict["_id"] = str(result.inserted_id)
        asyncio.create_task(self.run(timer_dict))
