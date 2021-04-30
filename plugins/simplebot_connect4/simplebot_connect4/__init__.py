
import os

import simplebot
from deltachat import Chat, Contact, Message
from simplebot import DeltaBot
from simplebot.bot import Replies

from .connect4 import BLACK, WHITE, Board
from .db import DBManager

__version__ = '1.0.0'
db: DBManager


@simplebot.hookimpl
def deltabot_init(bot: DeltaBot) -> None:
    global db
    db = _get_db(bot)


@simplebot.hookimpl
def deltabot_member_removed(bot: DeltaBot, chat: Chat, contact: Contact) -> None:
    game = db.get_game_by_gid(chat.id)
    if game:
        me = bot.self_contact
        p1, p2 = game['p1'], game['p2']
        if contact.addr in (me.addr, p1, p2):
            db.delete_game(p1, p2)
            if contact != me:
                chat.remove_contact(me)


@simplebot.filter(name=__name__)
def filter_messages(message: Message, replies: Replies) -> None:
    """Process move coordinates in Connect4 game groups
    """
    if message.text not in '1234567':
        return
    game = db.get_game_by_gid(message.chat.id)
    if game is None or game['board'] is None:
        return

    b = Board(game['board'])
    player = message.get_sender_contact().addr
    player = BLACK if game['black'] == player else WHITE
    if b.turn == player:
        if b.move(int(message.text)):
            db.set_board(game['p1'], game['p2'], b.export())
            replies.add(text=_run_turn(message.chat.id))
        else:
            replies.add(text='❌ Invalid move!')


@simplebot.command
def c4_play(bot: DeltaBot, payload: str, message: Message, replies: Replies) -> None:
    """Invite a friend to play Connect4.

    Example: `/c4_play friend@example.com`
    """
    if not payload:
        replies.add(text="Missing address")
        return

    if payload == bot.self_contact.addr:
        replies.add(text="Sorry, I don't want to play")
        return

    p1 = message.get_sender_contact().addr
    p2 = payload
    if p1 == p2:
        replies.add(text="You can't play with yourself")
        return

    g = db.get_game_by_players(p1, p2)

    if g is None:  # first time playing with p2
        chat = bot.create_group(
            '4️⃣ {} 🆚 {} [c4]'.format(p1, p2), [p1, p2])
        b = Board()
        db.add_game(p1, p2, chat.id, b.export(), p1)
        text = 'Hello {1},\nYou have been invited by {0} to play Connect4'
        text += '\n\n{2}: {0}\n{3}: {1}\n\n'
        text = text.format(
            p1, p2, b.get_disc(BLACK), b.get_disc(WHITE))
        replies.add(text=text + _run_turn(chat.id), chat=chat)
    else:
        text = 'You already have a game group with {}'.format(p2)
        replies.add(text=text, chat=bot.get_chat(g['gid']))


@simplebot.command
def c4_surrender(message: Message, replies: Replies) -> None:
    """End the Connect4 game in the group it is sent.
    """
    game = db.get_game_by_gid(message.chat.id)
    loser = message.get_sender_contact().addr
    # this is not your game group
    if game is None or loser not in (game['p1'], game['p2']):
        replies.add(text='This is not your game group')
    elif game['board'] is None:
        replies.add(text='There is no game running')
    else:
        db.set_board(game['p1'], game['p2'], None)
        text = '🏳️ Game Over.\n{} surrenders.\n\n▶️ Play again? /c4_new'
        replies.add(text=text.format(loser))

@simplebot.command
def c4_score(message: Message, replies: Replies) -> None:
    """Get Connect4 cumulative wins
    """
    game = db.get_game_by_gid(message.chat.id)
    # this is not your game group
    if game is None:
        replies.add(text='This is not your game group')
    else:
        text = '📊 Score:\n{1} {0}\n{3} {2}'
        replies.add(text=text.format(game['p1'], game['p1_wins'], game['p2'], game['p2_wins']))

@simplebot.command
def c4_new(message: Message, replies: Replies) -> None:
    """Start a new Connect4 game in the current game group.
    """
    sender = message.get_sender_contact().addr
    game = db.get_game_by_gid(message.chat.id)
    # this is not your game group
    if game is None or sender not in (game['p1'], game['p2']):
        replies.add(text='This is not your game group')
    elif game['board'] is None:
        b = Board()
        db.set_game(game['p1'], game['p2'], b.export(), sender)
        p2 = game['p2'] if sender == game['p1'] else game['p1']
        text = 'Game started!\n{}: {}\n{}: {}\n\n'.format(
            b.get_disc(BLACK), sender, b.get_disc(WHITE), p2)
        replies.add(text=text + _run_turn(message.chat.id))
    else:
        replies.add(text='There is a game running already')


@simplebot.command
def c4_repeat(message: Message, replies: Replies) -> None:
    """Send game board again.
    """
    replies.add(text=_run_turn(message.chat.id))


def _run_turn(gid: int) -> str:
    g = db.get_game_by_gid(gid)
    if not g:
        return 'This is not your game group'
    if not g['board']:
        return 'There is no game running'
    b = Board(g['board'])
    result = b.result()
    if result is None:
        if b.turn == BLACK:
            disc = b.get_disc(BLACK)
            turn = '{} {}'.format(disc, g['black'])
        else:
            disc = b.get_disc(WHITE)
            p2 = g['p2'] if g['black'] == g['p1'] else g['p1']
            turn = '{} {}'.format(disc, p2)
        text = "{} it's your turn...\n\n{}".format(turn, b)
    else:
        db.set_board(g['p1'], g['p2'], None)
        if result == '-':
            text = '🤝 Game over.\nIt is a draw!'
        else:
            if result == BLACK:
                winner_str = 'p1' if g['black'] == g['p1'] else 'p2'
                winner = '{} {}'.format(b.get_disc(BLACK), g['black'])
            else:
                winner_str = 'p2' if g['black'] == g['p1'] else 'p1'
                p2 = g['p2'] if g['black'] == g['p1'] else g['p1']
                winner = '{} {}'.format(b.get_disc(WHITE), p2)
            db.set_wins(g['p1'], g['p2'], winner_str)
            g = db.get_game_by_gid(gid) # to get current wins after this turn
            text = '🏆 Game over.\n{0} wins!\n\n📊 Score:\n{2} {1}\n{4} {3}'\
                .format(winner, g['p1'], g['p1_wins'], g['p2'], g['p2_wins'])
        text += '\n\n{}\n\n▶️ Play again? /c4_new'.format(b)
    return text


def _get_db(bot: DeltaBot) -> DBManager:
    path = os.path.join(os.path.dirname(bot.account.db_path), __name__)
    if not os.path.exists(path):
        os.makedirs(path)
    return DBManager(os.path.join(path, 'sqlite.db'))
