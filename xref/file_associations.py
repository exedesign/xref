"""Windows file associations for XRef board files."""

import logging
import os
import sys

from xref import constants

logger = logging.getLogger(__name__)

PROG_ID = 'XRef.Board'
CAPABILITIES_KEY = r'Software\XRef\Capabilities'
REGISTERED_APPLICATIONS_KEY = r'Software\RegisteredApplications'
BOARD_EXTENSIONS = ('.xref', '.bee')


def _set_registry_value(winreg, key_path, name, value, value_type):
    key = winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
    try:
        winreg.SetValueEx(key, name, 0, value_type, value)
    finally:
        winreg.CloseKey(key)


def _register_with_winreg(winreg, executable):
    command = f'"{executable}" "%1"'
    icon = f'"{executable}",0'

    _set_registry_value(
        winreg, rf'Software\Classes\{PROG_ID}', '', constants.APPNAME_FULL,
        winreg.REG_SZ)
    _set_registry_value(
        winreg, rf'Software\Classes\{PROG_ID}\DefaultIcon', '', icon,
        winreg.REG_SZ)
    _set_registry_value(
        winreg, rf'Software\Classes\{PROG_ID}\shell\open\command', '',
        command, winreg.REG_SZ)

    for extension in BOARD_EXTENSIONS:
        _set_registry_value(
            winreg, rf'Software\Classes\{extension}', '', PROG_ID,
            winreg.REG_SZ)
        _set_registry_value(
            winreg,
            rf'Software\Classes\{extension}\OpenWithProgids',
            PROG_ID, b'', winreg.REG_NONE)
        _set_registry_value(
            winreg, rf'{CAPABILITIES_KEY}\FileAssociations', extension,
            PROG_ID, winreg.REG_SZ)

    _set_registry_value(
        winreg, REGISTERED_APPLICATIONS_KEY, constants.APPNAME,
        CAPABILITIES_KEY, winreg.REG_SZ)
    _set_registry_value(
        winreg, CAPABILITIES_KEY, 'ApplicationName', constants.APPNAME_FULL,
        winreg.REG_SZ)
    _set_registry_value(
        winreg, CAPABILITIES_KEY, 'ApplicationDescription',
        constants.APPNAME_FULL, winreg.REG_SZ)


def register_windows_file_associations():
    """Register .xref and .bee for the frozen Windows application.

    Windows 10 and later may require the user to confirm XRef in Default
    Apps before changing an existing default handler.
    """

    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        return

    import winreg

    executable = os.path.abspath(sys.executable)
    try:
        _register_with_winreg(winreg, executable)
    except OSError:
        logger.exception('Could not register XRef board file associations')
        return
    logger.info('Registered .xref and .bee board file associations')
