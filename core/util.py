import typing

import discord

from model.schedule import ScheduleSlot
from util.type import is_sequence_but_not_str


def timeslot_is_owned_by_author(
        _author: discord.Member,
        _opponent: typing.Union[list[discord.Member], discord.Member, None],
        _slot: ScheduleSlot) -> bool:

    checks = [_author]

    if _opponent:
        if is_sequence_but_not_str(_opponent):
            checks.extend(_opponent)
        else:
            checks.extend([_opponent])

    is_owned = True
    for check in checks:
        is_owned = is_owned and _slot.has_participant(str(check.id))
        if not is_owned:
            break

    return is_owned


def timeslot_is_free(_slot: ScheduleSlot) -> bool:
    return _slot.is_free()


def timeslot_mark_as_free(_slot: ScheduleSlot) -> bool:
    _slot.free()
    return True


def timeslot_mark_as_owned(
        _author: discord.Member,
        _opponent: typing.Union[list[discord.Member], discord.Member, None],
        _info: typing.Union[str, None],
        _slot: ScheduleSlot):

    if is_sequence_but_not_str(_opponent):
        secondaries = [str(x.id) for x in _opponent]
    else:
        secondaries = _opponent.id if _opponent else None

    _slot.set_participants(
        primary=(_author.id if _author else ''),
        secondaries=secondaries
    )
    _slot.info = _info
    return True
