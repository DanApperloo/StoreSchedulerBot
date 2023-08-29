from collections.abc import Sequence


def is_sequence_but_not_str(val):
    return isinstance(val, Sequence) and not isinstance(val, (str, bytes, bytearray))


def is_not_numerical(val):
    return not (isinstance(val, int) or isinstance(val, float))
