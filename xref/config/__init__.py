# This file is part of XRef.
#
# XRef is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# XRef is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with XRef.  If not, see <https://www.gnu.org/licenses/>.

"""Handling of command line args and Qt settings."""

import logging
import logging.config
import os.path

from PyQt6 import QtCore

from xref import constants
from xref.config.controls import KeyboardSettings  # noqa F401
from xref.config.settings import (   # noqa F401
    XRefSettings,
    CommandlineArgs,
    settings_events,
)
from xref.logging import qt_message_handler


logger = logging.getLogger(__name__)


def logfile_name():
    return os.path.join(
        os.path.dirname(XRefSettings().fileName()), f'{constants.APPNAME}.log')


logging_conf = {
    'version': 1,
    'formatters': {
        'verbose': {
            'format': ('{asctime} {name} {process:d} {thread:d} {message}'),
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            'level': CommandlineArgs().loglevel,
        },
        'file': {
            'class': 'xref.logging.XRefRotatingFileHandler',
            'formatter': 'verbose',
            'filename': logfile_name(),
            'maxBytes': 1024 * 1000,  # 1MB
            'backupCount': 1,
            'level': 'DEBUG',
            'delay': True,
        }
    },
    'loggers': {
        'xref': {
            'handlers': ['console', 'file'],
            'level': 'TRACE',
            'propagate': False,
        },
        'Qt': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'DEBUG',
    },
}

logging.config.dictConfig(logging_conf)

# Redirect Qt logging to Python logger:
QtCore.qInstallMessageHandler(qt_message_handler)
