import enum
import typing

import discord

from model.schedule import ScheduleSlot


class Channel(enum.Enum):
    SCHEDULE_READONLY = enum.auto()
    SCHEDULE_ADMIN = enum.auto()
    SCHEDULE_DATA = enum.auto()
    SCHEDULE_REQUEST = enum.auto()


def timeslot_is_owned_by_author(_author: discord.Member,
                                _opponent: typing.Union[discord.Member, None],
                                _slot: ScheduleSlot) -> bool:
    if _opponent:
        return _slot.has_participant(str(_author.id)) and _slot.has_participant(str(_opponent.id))
    else:
        return _slot.has_participant(str(_author.id))


def timeslot_is_free(_slot: ScheduleSlot) -> bool:
    return _slot.is_free()


def timeslot_mark_as_free(_slot: ScheduleSlot) -> bool:
    _slot.free()
    return True


def timeslot_mark_as_owned(_author: discord.Member, _opponent: discord.Member, _slot: ScheduleSlot):
    _slot.set_participants(str(_author.id if _author else ''), str(_opponent.id if _opponent else ''))
    return True
