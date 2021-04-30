
import os

import simplebot
from deltachat import Message
from simplebot import DeltaBot
from simplebot.bot import Replies

from .db import DBManager

__version__ = '1.0.0'
db: DBManager


@simplebot.hookimpl
def deltabot_init(bot: DeltaBot) -> None:
    global db
    db = _get_db(bot)

    _getdefault(bot, 'score_badge', '🎖️')


@simplebot.filter(name=__name__)
def filter_messages(bot: DeltaBot, message: Message, replies: Replies) -> None:
    """Detect messages like +1 or -1 to increase/decrease score.
    """
    if message.quote:
        receiver = message.quote.get_sender_contact().addr
        score = _parse(message.text)
    else:
        args = message.text.split(maxsplit=2)
        if len(args) == 2 and '@' in args[0]:
            receiver = args[0]
            score = _parse(args[1])
        else:
            score = 0
    if not score:
        return
    sender = message.get_sender_contact().addr
    is_admin = bot.is_admin(sender)
    if score < 0 and not is_admin:
        return
    if not is_admin and db.get_score(sender) - score < 0:
        replies.add(text="❌ You can't give what you don't have...",
                    quote=message)
        return
    if sender == receiver:
        return

    sender_score = _add_score(sender, -score)
    receiver_score = _add_score(receiver, score)
    if is_admin:
        text = '{0}: {1}{4}'
    else:
        text = '{0}: {1}{4}\n{2}: {3}{4}'
    text = text.format(
        bot.get_contact(receiver).name,
        receiver_score,
        bot.get_contact(sender).name,
        sender_score,
        _getdefault(bot, 'score_badge'))
    replies.add(text=text, quote=message)


@simplebot.command(admin=True)
def scoreSet(bot: DeltaBot, args: list, message: Message, replies: Replies) -> None:
    """Set score for given address.

    Example: `/score foo@example.com +100`
    """
    score = _parse(args[1])
    if not score:
        replies.add(
            text='❌ Invalid number, use + or -', quote=message)
    else:
        score = _add_score(args[0], score)
        name = bot.get_contact(args[0]).name
        text = '{}: {}{}'.format(name, score, _getdefault(bot, 'score_badge'))
        replies.add(text=text, quote=message)


@simplebot.command
def score(bot: DeltaBot, payload: str, message: Message, replies: Replies) -> None:
    """Get score from given address or your current score if no address is given.

    Example: `/score`
    """
    if payload:
        addr = payload
    else:
        addr = message.get_sender_contact().addr
    name = bot.get_contact(addr).name
    badge = _getdefault(bot, 'score_badge')
    replies.add(text='{0}: {1}/{2}{3}'.format(
        name, db.get_score(addr), db.get_score(), badge))


def _get_db(bot: DeltaBot) -> DBManager:
    path = os.path.join(os.path.dirname(bot.account.db_path), __name__)
    if not os.path.exists(path):
        os.makedirs(path)
    return DBManager(os.path.join(path, 'sqlite.db'))


def _getdefault(bot: DeltaBot, key: str, value: str = None) -> str:
    val = bot.get(key, scope=__name__)
    if val is None and value is not None:
        bot.set(key, value, scope=__name__)
        val = value
    return val


def _parse(score: str) -> int:
    if not score.startswith(('-', '+')):
        return 0
    try:
        return int(score)
    except ValueError:
        return 0


def _add_score(addr: str, score: int) -> int:
    score = db.get_score(addr) + score
    if score == 0:
        db.delete_score(addr)
    else:
        db.set_score(addr, score)
    return score
