"""Tests for the Turkish/English interface translations."""

import ast
import glob
import os

import pytest
from PyQt6 import QtWidgets

from beeref import i18n
from beeref.i18n import tr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, 'beeref')


def iter_python_files():
    for path in glob.glob(os.path.join(PACKAGE, '**', '*.py'),
                          recursive=True):
        if '__pycache__' in path:
            continue
        yield path


def literal_tr_strings():
    """All string literals that are passed to ``tr()`` in the package."""

    found = {}
    for path in iter_python_files():
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, 'id', None) or getattr(func, 'attr', None)
            if name != 'tr' or not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.setdefault(arg.value, set()).add(
                    os.path.relpath(path, ROOT))
    return found


def collect_constant_attributes(classes, attribute):
    """Values of ``attribute`` on the given classes (may be None)."""

    values = []
    for cls in classes:
        value = getattr(cls, attribute, None)
        if isinstance(value, str):
            values.append(value)
    return values


def missing_translations():
    """Source strings that have no Turkish translation."""

    table = i18n.TRANSLATIONS['tr']
    missing = sorted(s for s in literal_tr_strings() if s not in table)

    # Texts that reach tr() indirectly must be translated as well
    from beeref.actions.actions import actions
    from beeref.actions.menu_structure import menu_structure
    from beeref import widgets
    from beeref.config.controls import KeyboardSettings

    indirect = set()
    for action in actions.values():
        if action.text and not action.text.startswith('File '):
            indirect.add(action.text)
    for menu in menu_structure:
        indirect.add(menu['menu'])
    for name in dir(widgets.settings):
        cls = getattr(widgets.settings, name)
        if not isinstance(cls, type):
            continue
        for attribute in ('TITLE', 'HELPTEXT', 'LABEL'):
            value = getattr(cls, attribute, None)
            if isinstance(value, str):
                indirect.add(value)
        options = getattr(cls, 'OPTIONS', None)
        if options:
            for _value, label, helptext in options:
                indirect.add(label)
                indirect.add(helptext)
    for action in KeyboardSettings.MOUSE_ACTIONS.values():
        indirect.add(action.text)
    for action in KeyboardSettings.MOUSEWHEEL_ACTIONS.values():
        indirect.add(action.text)
    from beeref.config.controls import MouseConfigBase
    for name in MouseConfigBase.MODIFIER_MAP:
        indirect.add(name)
    for name in MouseConfigBase.BUTTON_MAP:
        indirect.add(name)

    # Proper nouns / native language names stay as they are
    skip = {'English', 'Türkçe', 'Ctrl', 'Shift', 'Alt', 'Meta'}
    for text in indirect:
        if text in skip:
            continue
        if text not in table and text not in missing:
            missing.append(text)
    return sorted(missing)


def test_every_translatable_string_has_a_turkish_translation():
    missing = missing_translations()
    assert not missing, (
        'Missing Turkish translations:\n' + '\n'.join(
            f'  {text!r} (used in {sorted(literal_tr_strings().get(text, []))})'
            for text in missing))


def test_turkish_table_has_no_unknown_placeholders():
    """Placeholders must match between source and translation."""

    import string

    def fields(text):
        try:
            return {name for _literal, name, _spec, _conv
                    in string.Formatter().parse(text) if name}
        except ValueError:
            return None

    problems = []
    for source, target in i18n.TRANSLATIONS['tr'].items():
        source_fields = fields(source)
        target_fields = fields(target)
        if source_fields is None or target_fields is None:
            continue
        if source_fields != target_fields:
            problems.append((source, source_fields, target_fields))
    assert not problems, problems


def test_tr_returns_source_for_unknown_strings(qapp):
    i18n.set_language('tr')
    try:
        assert tr('This string does not exist') == 'This string does not exist'
        assert tr('') == ''
    finally:
        i18n.set_language('en')


def test_tr_formats_placeholders(qapp):
    i18n.set_language('tr')
    try:
        assert tr('Removed {count} link(s)', count=3) == (
            '3 bağlantı kaldırıldı')
    finally:
        i18n.set_language('en')


def test_language_selection_falls_back_to_english(qapp):
    assert i18n.set_language('fr') == 'en'
    assert i18n.current_language() == 'en'
    assert tr('&Open') == '&Open'
    i18n.set_language('TR')
    assert i18n.current_language() == 'tr'
    assert tr('&Open') == '&Aç'
    i18n.set_language('en')


def test_available_languages_lists_both(qapp):
    languages = i18n.available_languages()
    assert languages['en'] == 'English'
    assert languages['tr'] == 'Türkçe'


def test_language_change_updates_actions_and_window_title(
        view, qapp, monkeypatch):
    from beeref.actions.actions import actions

    overlay = getattr(view, 'welcome_overlay', None)
    assert overlay is not None
    # An unsaved scene shows the (translated) placeholder file name
    monkeypatch.setattr(view.undo_stack, 'isClean', lambda: False)
    i18n.set_language('en')
    view.update_window_title()
    english = actions['open'].qaction.text()
    english_title = view.parent.windowTitle()
    assert '[Untitled]*' in english_title
    try:
        i18n.set_language('tr')
        qapp.processEvents()
        assert actions['open'].qaction.text() == '&Aç'
        assert english != actions['open'].qaction.text()
        assert view.parent.windowTitle() != english_title
        assert 'Adsız' in view.parent.windowTitle()
        assert 'Untitled' not in view.parent.windowTitle()
        # The welcome overlay follows the language as well
        assert 'yapıştırın' in overlay.label.text()
    finally:
        i18n.set_language('en')
        qapp.processEvents()
        assert actions['open'].qaction.text() == english
        assert view.parent.windowTitle() == english_title


def test_menu_titles_are_translated(view, qapp):
    i18n.set_language('tr')
    try:
        titles = [menu.title() for menu in view.toplevel_menus]
        assert '&Dosya' in titles
        assert '&Birlikte Çalış' in titles
        assert '&File' not in titles
    finally:
        i18n.set_language('en')


def test_settings_dialog_has_a_language_selector(view, qapp):
    from beeref.widgets.settings import SettingsDialog
    dialog = SettingsDialog(view)
    try:
        from beeref.widgets.settings import LanguageWidget
        selectors = dialog.findChildren(LanguageWidget)
        assert len(selectors) == 1
        selector = selectors[0]
        assert set(selector.buttons) == {'en', 'tr'}
        assert selector.buttons[i18n.current_language()].isChecked()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_language_setting_is_remembered(qapp):
    from beeref.config import BeeSettings

    settings = BeeSettings()
    old = settings.value('General/language')
    try:
        i18n.set_language('tr')
        settings.setValue('General/language', 'tr')
        assert BeeSettings().valueOrDefault('General/language') == 'tr'
    finally:
        if old is None:
            settings.remove('General/language')
        else:
            settings.setValue('General/language', old)
        i18n.set_language('en')


def test_startup_applies_the_stored_language(qapp):
    from beeref.config import BeeSettings

    settings = BeeSettings()
    old = settings.value('General/language')
    try:
        settings.setValue('General/language', 'tr')
        i18n.set_language('en')
        BeeSettings().on_startup()
        assert i18n.current_language() == 'tr'
    finally:
        if old is None:
            settings.remove('General/language')
        else:
            settings.setValue('General/language', old)
        i18n.set_language('en')


def test_help_document_is_available_in_both_languages():
    from importlib.resources import files as rsc_files

    for name in ('controls.html', 'controls_tr.html'):
        path = rsc_files('beeref.documentation').joinpath(name)
        assert path.is_file(), name
    turkish = rsc_files('beeref.documentation').joinpath(
        'controls_tr.html').read_text(encoding='utf-8')
    assert 'Kaydır' in turkish
