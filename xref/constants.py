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

APPNAME = 'XRef'
APPNAME_FULL = f'{APPNAME} Reference Board'
VERSION = '0.4.0-dev'
WEBSITE = 'https://github.com/exedesign/xref'
# The original BeeRef copyright stays, as required by the GPL
COPYRIGHT = ('Based on BeeRef, Copyright (C) 2021-2024 Rebecca Breu; '\
             'XRef, Copyright (C) 2025-2026 XRef contributors')

#: Extension used when saving boards
FILE_EXTENSION = 'xref'
#: Boards saved by older versions (and by BeeRef)
LEGACY_FILE_EXTENSIONS = ('bee',)

CHANGED_SYMBOL = '✎'

COLORS = {
    # Qt:
    'Active:Base': (60, 60, 60),
    'Active:AlternateBase': (70, 70, 70),
    'Active:Window': (40, 40, 40),
    'Active:Button': (40, 40, 40),
    'Active:Text': (200, 200, 200),
    'Active:HighlightedText': (255, 255, 255),
    'Active:WindowText': (200, 200, 200),
    'Active:ButtonText': (200, 200, 200),
    'Active:Highlight': (83, 167, 165),
    'Active:Link': (90, 181, 179),

    'Disabled:Base': (40, 40, 40),
    'Disabled:Window': (40, 40, 40, 50),
    'Disabled:WindowText': (120, 120, 120),
    'Disabled:Light': (0, 0, 0, 0),
    'Disabled:Text': (140, 140, 140),

    # XRef specific:
    'Scene:Selection': (116, 234, 231),
    'Scene:Canvas': (0, 0, 0),
    'Scene:Text': (200, 200, 200),
}
