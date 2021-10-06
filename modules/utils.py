import discord
import re
import asyncio
import logging
import os
import sys
import requests

from io import BytesIO
from logging import handlers
from typing import Tuple, Union, Optional
from modules import embed_maker, database, commands
from discord.ext.commands import Context, Converter

db = database.get_connection()
log_session = None


class Command(Converter):
    """Special class for when used as a type on a command arg, :func:`convert` will be called on the argument."""
    async def convert(self, ctx: Context, argument: str = '') -> Optional[Union[commands.Command, commands.Group]]:
        """
        Converts provided argument to command

        Parameters
        ----------------
        ctx: :class:`discord.ext.commands.Context`
            Context, will be used to get member.
        argument: :class:`str`
            Argument passed that will be used as command name when getting command.

        Returns
        -------
        Optional[Union[:class:`modules.cls.Command`, :class:`modules.cls.Group`]]
            Returns command or group command or `None` if nothing is found.
        """
        return ctx.bot.get_command(argument, member=ctx.author)


class ParseArgs(Converter, dict):
    """Special class for when used as a type on a command arg, :func:`convert` will be called on the argument."""
    async def convert(self, ctx: Context, argument: str = '') -> dict:
        """
        Converts provided argument to dictionary of command args and their values.
        Command args are gotten from ctx.command.docs.command_args.

        This uses regex to parse args.

        Parameters
        ----------------
        ctx: :class:`discord.ext.commands.Context`
            Context, will be used to command.
        argument: :class:`str`
            Argument passed that will be parsed for args.

        Returns
        -------
        :class:`dict`
            Dictionary of command args and their values.
        """
        try:
            result = {}
            args = {}

            # replace short-form args with long-form args
            for arg, description in ctx.command.docs.command_args:
                long = arg[0]
                short = arg[1]
                data_type = arg[2]

                args[long[2:]] = data_type

                if type(short) == str:
                    matches = re.findall(rf'(\s|^)({short})(\s|$)', argument)
                    for match in matches:
                        argument = re.sub(''.join(match), match[0] + long + match[2], argument)

                result[long[2:]] = None

            # create regex to match command args
            regex = rf'(?:\s|^)--({"|".join(long for long in args.keys())})(?:\s|$)'
            # split argument with regex
            split_argument = re.split(regex, argument)
            # anything before the first arg is put into result['pre']
            result['pre'] = split_argument.pop(0)

            for arg, data in zip(split_argument[::2], split_argument[1::2]):
                data_type = args[arg]
                if not result[arg]:
                    try:
                        if data_type == list:
                            result[arg] = [data.strip()]
                        else:
                            result[arg] = data_type(data.strip())
                    except ValueError:
                        pass
                elif type(result[arg]) == list:
                    result[arg].append(data.strip())

            return result
        except Exception as e:
            logger = get_logger()
            logger.exception(f'Error in ParseArgs. Argument: {argument} | Error: {e}')


def id_match(identifier: str, extra: str) -> re.Match:
    """
    Matches identifier to discord ID regex and matches given extra regex to identifier

    Parameters
    ----------------
    identifier: :class:`str`
        The identifier that will be matched against discord ID regex and given extra regex
    extra: :class:`str`
        Extra regex to match identifier against

    Returns
    -------
    :class:`re.Match`
        Either discord ID match or extra regex match
    """
    id_regex = re.compile(r'([0-9]{15,21})$')
    additional_regex = re.compile(extra)
    return id_regex.match(identifier) or additional_regex.match(identifier)


def get_text_channel(ctx: Context, argument: str = '') -> Optional[discord.TextChannel]:
    match = id_match(argument, r'<#([0-9]+)>$')
    if match is None:
        # not a mention
        if ctx.guild:
            result = discord.utils.get(ctx.guild.text_channels, name=argument)
        else:
            def check(c):
                return isinstance(c, discord.TextChannel) and c.name == argument

            result = discord.utils.find(check, ctx.bot.get_all_channels())
    else:
        channel_id = int(match.group(1))
        if ctx.guild:
            result = ctx.guild.get_channel(channel_id)
        else:
            result = None

    if not isinstance(result, discord.TextChannel):
        result = None

    return result


def get_custom_emote(ctx: Context, emote: str) -> Optional[discord.Emoji]:
    """
    Look up custom emote by id or by name

    Parameters
    ----------------
    ctx: :class:`discord.ext.commands.Context`
        Context, used to get emojis.
    emote: :class:`str`
        Either emote name or id.

    Returns
    -------
    Optional[:class:`discord.Emoji`]
        Emoji if one is found, otherwise `None`.
    """
    match = id_match(emote, r'<a?:[a-zA-Z0-9\_]+:([0-9]+)>$')
    result = None

    if match is None:
        # Try to get the emoji by name. Try local guild first.
        if ctx.guild:
            result = discord.utils.get(ctx.guild.emojis, name=emote)

        if result is None:
            result = discord.utils.get(ctx.bot.emojis, name=emote)
    else:
        emoji_id = int(match.group(1))

        # Try to look up emoji by id.
        if ctx.guild:
            result = discord.utils.get(ctx.guild.emojis, id=int(emoji_id))

        if result is None:
            result = discord.utils.get(ctx.bot.emojis, id=int(emoji_id))

    return result


async def get_guild_role(guild: discord.Guild, role_identifier: str) -> Optional[discord.Role]:
    """
    Get guild's role by its name or id.

    Parameters
    ----------------
    guild: :class:`discord.Guild`
        Guild where to search the role from.
    role_identifier: :class:`str`
        Either role name or id.

    Returns
    -------
    Optional[:class:`discord.Role`]
        Role if one is found, otherwise `None`.
    """
    match = id_match(role_identifier, r'<@&([0-9]+)>$')
    if match:
        role = guild.get_role(int(match.group(1)))
    else:
        role = discord.utils.find(lambda rl: rl.name == role_identifier, guild.roles)

    return role


async def get_member_from_string(ctx: Optional[Context], string: str, *, guild: discord.Guild = None) -> Tuple[Optional[discord.Member], str]:
    """
    Get member from the first part of the string and return the remaining string.

    Parameters
    ----------------
    ctx: :class:`discord.ext.commands.Context`
        Context.
    string: :class:`str`
        String where the member will be searched from.
    guild: :class:`discord.Guild`,
        Optional guild paramater that can be used to use the simplified get_guild_member function

    Returns
    -------
    Tuple[Optional[:class:`discord.Member`], :class:`str`]
        Member and remaining string if member is found or `None` and string.
    """
    if ctx:
        # check if source is member mention
        if ctx.message.mentions:
            return ctx.message.mentions[0], ' '.join(string.split()[1:])

    member_name = ""
    previous_result = None

    if guild:
        ctx = guild
        member_func = get_guild_member
    else:
        member_func = get_member

    for part in string.split():
        member_match = await member_func(ctx, f'{member_name} {part}'.strip(), multi=False, return_message=False)
        if member_match is None:
            # if both member and previous result are None, nothing can be found from the string, return None and the string
            if previous_result is None:
                return None, string
            # if member is None, but previous result is a list, return Normal get_member call and allow user to choose member
            elif type(previous_result) == list:
                return await member_func(ctx, f'{member_name}'.strip()), string.replace(f'{member_name}'.strip(), '').strip()
            elif type(previous_result) == discord.Member:
                return previous_result, string.replace(f'{member_name}'.strip(), '').strip()
        else:
            # update variables
            previous_result = member_match
            member_name = f'{member_name} {part}'.strip()

    if len(string.split()) == 1 and type(previous_result) != discord.Member:
        if type(previous_result) == list:
            return await get_member(ctx, f'{member_name}'.strip()), string.replace(f'{member_name}'.strip(), '').strip()
        elif type(previous_result) == discord.Member:
            return previous_result, string.replace(f'{member_name}'.strip(), '').strip()

    return previous_result, string.replace(f'{member_name}'.strip(), '').strip()


async def get_member_by_id(guild: discord.Guild, member_id: int) -> Optional[discord.Member]:
    """
    Simple function to get or fetch member in guild by member's id.

    Parameters
    ----------------
    guild: :class:`discord.guild`
        Guild from which to get member.
    member_id: :class:`id`
        ID of the member.

    Returns
    -------
    Optional[:class:`discord.Member`]:
        Member if they are in the guild, `None` if not.
    """
    member = guild.get_member(member_id)
    if member is None:
        # Try to fetch member with an api request
        try:
            member = await guild.fetch_member(member_id)
        except Exception:
            pass

    return member


async def get_guild_member(guild: discord.Guild, source, **_) -> Optional[Union[discord.Member, discord.Message, list]]:
    """
    Clean version of get member which only needs guild. It was easier to do this rather than start upgrading get_member.

    Parameters
    ----------------
    guild: :class:`discord.Guild`
        Context.
    source: :class:`str`
        Identifier to which members are matched, can be id or name.

    Returns
    -------
    Optional[Union[:class:`discord.Member`, :class`discord.Message`, :class:`list`]]:
        discord.Member if member is found else None.
    """
    if type(source) == int:
        source = str(source)

    # Check if source is member id
    if source.isdigit() and len(source) > 9:
        member = guild.get_member(int(source))

        # if member isn't found by get, maybe they aren't in the cache, fetch them by making an api call
        if not member:
            try:
                # if member hasnt been cached yet, fetching them should work, if member is inaccessible, it will return None
                member = await guild.fetch_member(int(source))
                if member is None:
                    return
            except:
                return

        if member:
            return member

    # if source length is less than 3, don't bother searching, too many matches will come
    if len(source) < 3:
        return

    # checks first for a direct name match
    members = list(
        filter(
            lambda m: m.name.lower() == source.lower() or  # username match
                      m.display_name.lower() == source.lower() or  # nickname match (if user doesnt have a nickname, it'll match the name again)
                      str(m).lower() == source.lower(),  # name and discriminator match
            guild.members
        )
    )

    # if can't find direct name match, check for a match with regex
    if not members:
        # checks for regex match
        special_chars_map = {i: '\\' + chr(i) for i in b'()[]{}?*+-|^$\\.&~#'}
        safe_source = source.translate(special_chars_map)

        members = list(
            filter(
                lambda m: re.findall(fr'({safe_source.lower()})', str(m).lower()) or  # regex match name and discriminator
                          re.findall(fr'({safe_source.lower()})', m.display_name.lower()),  # regex match nickname
                guild.members
            )
        )

        if not members:
            return

    # only one match, return member
    if len(members) == 1:
        return members[0]


async def get_member(ctx: Context, source, *, multi: bool = True, return_message: bool = True) -> Optional[Union[discord.Member, discord.Message, list]]:
    """
    Get member from given source. Source could be id or name.
    Member could also be a mention, so ctx.message.mentions are checked.

    Parameters
    ----------------
    ctx: :class:`discord.ext.commands.Context`
        Context.
    source: :class:`str`
        Identifier to which members are matched, can be id or name.
    multi: :class:`bool`
        If true, when multiple matches are found, user will presented with the option and allowed to choose between the members,
        if False, list of matched members will be returned
    return_message :class:`bool`
        If true, when and error is encountered, a message about the error will be returned

    Returns
    -------
    Optional[Union[:class:`discord.Member`, :class`discord.Message`, :class:`list`]]:
        Member if member is found.
        Message if error is encountered and return_message is True.
        List if multiple members are found and multi is False.
    """
    # just in case source is empty
    if not source and return_message:
        return await embed_maker.error(ctx, 'Input is empty') if return_message else None

    if type(source) == int:
        source = str(source)

    # check if source is member mention
    if ctx.message.mentions:
        return ctx.message.mentions[0]

    # Check if source is member id
    if source.isdigit() and len(source) > 9:
        member = ctx.guild.get_member(int(source))

        # if member isn't found by get, maybe they aren't in the cache, fetch them by making an api call
        if not member:
            try:
                # if member hasnt been cached yet, fetching them should work, if member is inaccessible, it will return None
                member = await ctx.guild.fetch_member(int(source))
                if member is None:
                    return await embed_maker.error(ctx, f'Member not found by ID: `{source}`') if return_message else None
            except discord.Forbidden:
                return await embed_maker.error(ctx, 'Bot does not have access to the guild members') if return_message else None
            except discord.HTTPException:
                return await embed_maker.error(ctx, f'Member not found by id: `{source}`') if return_message else None

        if member:
            return member

    # if source length is less than 3, don't bother searching, too many matches will come
    if len(source) < 3:
        return await embed_maker.error(ctx, 'User name input needs to be at least 3 characters long') if return_message else None

    # checks first for a direct name match
    members = list(
        filter(
            lambda m: m.name.lower() == source.lower() or  # username match
                      m.display_name.lower() == source.lower() or  # nickname match (if user doesnt have a nickname, it'll match the name again)
                      str(m).lower() == source.lower(),  # name and discriminator match
            ctx.guild.members
        )
    )

    # if can't find direct name match, check for a match with regex
    if not members:
        # checks for regex match
        special_chars_map = {i: '\\' + chr(i) for i in b'()[]{}?*+-|^$\\.&~#'}
        safe_source = source.translate(special_chars_map)

        members = list(
            filter(
                lambda m: re.findall(fr'({safe_source.lower()})', str(m).lower()) or  # regex match name and discriminator
                          re.findall(fr'({safe_source.lower()})', m.display_name.lower()),  # regex match nickname
                ctx.guild.members
            )
        )

        if not members:
            return await embed_maker.error(ctx, f'No members found by the name `{source}`') if return_message else None

    # too many matches
    if len(members) > 10 and multi:
        return await embed_maker.error(ctx, 'Too many user matches') if return_message else None

    # only one match, return member
    if len(members) == 1:
        return members[0]
    elif not multi or not return_message:
        return members

    # send embed containing member matches and let member choose which one they meant
    description = 'Found multiple users, which one did you mean? `type index of member`\n\n'
    for i, member in enumerate(members):
        description += f'`#{i + 1}` | {member.display_name}#{member.discriminator}'

        # also display members nickname, if member has one
        if member.nick:
            description += f' - [{member.name}#{member.discriminator}]'

        description += '\n'

    # generate embed
    users_embed_message = await embed_maker.message(
        ctx,
        description=description,
        author={'name': 'Members'},
        footer={'text': str(ctx.author), 'icon_url': ctx.author.avatar_url},
        send=True
    )

    # function that validates member input
    def input_check(m):
        return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.isdigit()

    # wait for member input
    try:
        user_message = await ctx.bot.wait_for('message', check=input_check, timeout=20)
        await users_embed_message.delete(delay=5)
        index = user_message.content
        if index.isdigit() and len(members) >= int(index) - 1 >= 0:
            return members[int(index) - 1]
        elif not index.isdigit():
            return await embed_maker.error(ctx, 'Input is not a number') if return_message else None
        elif int(index) - 1 > len(members) or int(index) - 1 < 0:
            return await embed_maker.error(ctx, 'Input number out of range') if return_message else None

    except asyncio.TimeoutError:
        await users_embed_message.delete()
        return await embed_maker.error(ctx, 'Timeout') if return_message else None


def get_logger(name: str = 'TLDR-Bot-log'):
    """
    Get logging session, or create it if needed.

    Parameters
    -----------
    name: :class:`str`
        Name of the file where logs will be put.

    Returns
    -------
    :class:`logging.LoggerAdapter`
        The logging adapter.
    """
    global log_session

    logger = logging.getLogger('TLDR')
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        log_path = os.path.join('logs/', f'{name}.log')
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        formatter = logging.Formatter('{asctime} {levelname:<8} {message}', style='{')

        # sys
        sysh = logging.StreamHandler(sys.stdout)
        sysh.setLevel(logging.DEBUG)
        sysh.setFormatter(formatter)
        logger.addHandler(sysh)

        # Log file
        fh = logging.handlers.RotatingFileHandler(log_path, backupCount=2)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    adapter = logging.LoggerAdapter(logger, extra={'session': 2})
    return adapter


def replace_mentions(guild: discord.Guild, string) -> str:
    # replace mentions in values with actual names
    mentions = re.findall(r'(<(@|@&|@!|#)\d+>)', string)
    for mention in mentions:
        # get type, ie. @, @&, @! or #
        mention_type = mention[1]
        # get id from find
        mention_id = re.findall(r'(\d+)', mention[0])[0]

        # turn type into iterable
        iterable_switch = {
            '@': guild.members,
            '@!': guild.members,
            '@&': guild.roles,
            '#': guild.channels
        }
        iterable = iterable_switch.get(mention_type, None)
        if not iterable:
            continue

        # get object from id
        mention_object = discord.utils.find(lambda o: o.id == int(mention_id), iterable)
        # if object actually exists replace mention in string
        if mention_object:
            string = string.replace(f'{mention[0]}', f'{mention_type[0]}{mention_object.name}')

    return string


def embed_message_to_text(embed):
    # get either title or author
    title = ''
    if embed.title:
        title = embed.title.name if type(embed.title) != str else embed.title
    elif embed.author:
        title = embed.author.name if type(embed.author) != str else embed.author
    # format description
    description = ('\n' if title else '') + embed.description if embed.description else ''

    # convert fields to text
    fields = ""
    for field in embed.fields:
        if fields or description:
            fields += '\n'

        fields += f'{field.name}\n{field.value}'

    # convert values to a multi line message
    text = f"{title}" \
           f"{description}" \
           f"{fields}"

    return text


async def async_file_downloader(urls: list[str], headers: dict = None) -> list[BytesIO]:
    async def fetch_file(index: int, files: list, url: str):
        response = requests.get(url, headers=headers)
        file = BytesIO(response.content)
        file.seek(0)
        files[index] = file

    futures = []
    files = [None] * len(urls)
    for i, url in enumerate(urls):
        future = asyncio.create_task(fetch_file(i, files, url))
        futures.append(future)

    if futures:
        await asyncio.gather(*futures)

    return [file for file in files if file]
