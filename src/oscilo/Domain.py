from enum import IntEnum

from . import oscilo_engine


class Domain(IntEnum):
    LOCAL = oscilo_engine.LOCAL
    GLOBAL = oscilo_engine.GLOBAL
    ENCLOSING = oscilo_engine.ENCLOSING
    BUILTIN = oscilo_engine.BUILTIN
    NOT_FOUND = oscilo_engine.NOT_FOUND


# These are for backwards compatibility with the old oscilo_engine module.
LOCAL = Domain.LOCAL
GLOBAL = Domain.GLOBAL
ENCLOSING = Domain.ENCLOSING
BUILTIN = Domain.BUILTIN
NOT_FOUND = Domain.NOT_FOUND