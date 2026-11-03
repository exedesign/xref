from unittest.mock import patch

from PyQt6 import QtGui

from xref.actions.actions import Action, actions


def test_action_str():
    action = Action(id='foo', text='Foo', shortcuts=['Ctrl+R'])
    assert str(action) == 'foo'


def test_action_equals_true():
    action1 = Action(id='foo', text='Foo', shortcuts=['Ctrl+R'])
    action2 = Action(id='foo', text='Bar', shortcuts=['Ctrl+F'])
    assert action1 == action2


def test_action_equals_false():
    action1 = Action(id='foo', text='Foo', shortcuts=['Ctrl+R'])
    action2 = Action(id='bar', text='Bar', shortcuts=['Ctrl+R'])
    assert not action1 == action2


def test_action_on_restore_defaults(kbsettings, view):
    action = Action(id='foo', text='Foo', shortcuts=['Ctrl+R'])
    action.qaction = QtGui.QAction('foo', view)
    action.on_restore_defaults()
    assert action.qaction.shortcuts() == ['Ctrl+R']


def test_action_on_restore_defaults_when_no_defaults(kbsettings, view):
    action = Action(id='foo', text='Foo')
    action.qaction = QtGui.QAction('foo', view)
    action.qaction.setShortcuts(['Ctrl+R'])
    action.on_restore_defaults()
    assert action.qaction.shortcuts() == []


def test_action_get_overwritten_shortcuts(kbsettings):
    kbsettings.set_list('Actions', 'foo', ['Alt+O'])
    action = Action(id='foo', text='Foo', shortcuts=['Ctrl+F'])
    assert action.get_shortcuts() == ['Alt+O']


def test_action_get_shortcuts_gets_default(kbsettings):
    action = Action(id='foo', text='Foo', shortcuts=['Ctrl+F'])
    assert action.get_shortcuts() == ['Ctrl+F']


def test_action_set_shortcuts_when_no_qaction(kbsettings):
    action = Action(id='foo', text='Foo')
    action.qaction = None
    action.set_shortcuts(['Ctrl+F'])
    assert kbsettings.get_list('Actions', 'foo') == ['Ctrl+F']


def test_action_set_shortcuts_when_qaction(kbsettings, view):
    action = Action(id='foo', text='Foo')
    action.qaction = QtGui.QAction('foo', view)
    action.set_shortcuts(['Ctrl+F'])
    assert kbsettings.get_list('Actions', 'foo') == ['Ctrl+F']
    assert action.qaction.shortcuts() == ['Ctrl+F']


def test_action_get_qkeysequence_first(kbsettings):
    action = Action(id='foo', text='Foo', shortcuts=['Ctrl+F'])
    assert action.get_qkeysequence(0) == QtGui.QKeySequence('Ctrl+F')


def test_action_get_qkeysequence_second(kbsettings):
    action = Action(id='foo', text='Foo', shortcuts=['Ctrl+F', 'Ctrl+B'])
    assert action.get_qkeysequence(1) == QtGui.QKeySequence('Ctrl+B')


def test_action_get_qkeysequence_first_when_not_set(kbsettings):
    action = Action(id='foo', text='Foo')
    assert action.get_qkeysequence(0) == QtGui.QKeySequence()


def test_action_get_qkeysequence_second_when_not_set(kbsettings):
    action = Action(id='foo', text='Foo', shortcuts=['Ctrl+F'])
    assert action.get_qkeysequence(1) == QtGui.QKeySequence()


def test_action_shortcuts_changed_when_not_changed(kbsettings):
    action = Action(id='foo', text='Foo', shortcuts=['Ctrl+F'])
    assert action.shortcuts_changed() is False


def test_action_shortcuts_changed_when_changed(kbsettings):
    action = Action(id='foo', text='Foo', shortcuts=['Ctrl+F'])
    kbsettings.set_list('Actions', 'foo', ['Ctrl+B'])
    assert action.shortcuts_changed() is True


def test_action_shortcuts_changed_when_empty(kbsettings):
    action = Action(id='foo', text='Foo')
    assert action.shortcuts_changed() is False


def test_action_get_default_shortcut_first():
    action = Action(id='foo', text='Foo', shortcuts=['Ctrl+F'])
    assert action.get_default_shortcut(0) == 'Ctrl+F'


def test_action_get_default_shortcut_second():
    action = Action(id='foo', text='Foo', shortcuts=['Ctrl+F', 'Ctrl+B'])
    assert action.get_default_shortcut(1) == 'Ctrl+B'


def test_action_get_default_shortcut_first_when_none_set():
    action = Action(id='foo', text='Foo')
    assert action.get_default_shortcut(0) is None


def test_action_get_default_shortcut_second_when_none_set():
    action = Action(id='foo', text='Foo', shortcuts=['Ctrl+F'])
    assert action.get_default_shortcut(1) is None


def test_pureref_matching_default_shortcuts():
    expected = {
        'open': ['Ctrl+L'],
        'save': ['Ctrl+S'],
        'save_as': ['Ctrl+Shift+S'],
        'export_scene': ['Ctrl+E'],
        'export_images': ['Ctrl+Alt+I'],
        'quit': ['Ctrl+Q'],
        'insert_images': ['Ctrl+I'],
        'insert_text': ['Ctrl+N'],
        'undo': ['Ctrl+Z'],
        'redo': ['Ctrl+Shift+Z'],
        'copy': ['Ctrl+C'],
        'cut': ['Ctrl+X'],
        'paste': ['Ctrl+V'],
        'delete': ['Del'],
        'raise_to_top': ['Up'],
        'lower_to_bottom': ['Down'],
        'normalize_height': ['Ctrl+Alt+Left'],
        'normalize_width': ['Ctrl+Alt+Right'],
        'normalize_size': ['Ctrl+Alt+Up'],
        'arrange_optimal': ['Ctrl+P'],
        'arrange_randomly': ['Ctrl+Alt+R'],
        'duplicate': ['Ctrl+D'],
        'grayscale': ['Alt+G'],
        'crop': ['Ctrl+Alt+Shift+C'],
        'flip_horizontally': ['Alt+Shift+H'],
        'flip_vertically': ['Alt+Shift+V'],
        'new_scene': ['Ctrl+K'],
        'reset_crop': ['Ctrl+Shift+C'],
        'reset_transforms': ['Ctrl+Shift+T'],
        'select_all': ['Ctrl+A'],
        'help': ['F1'],
        'maximize': ['Ctrl+F'],
        'minimize': ['Ctrl+M'],
        'always_on_top': ['Ctrl+Shift+A'],
        'settings': ['Ctrl+U'],
    }

    for action_id, shortcut in expected.items():
        assert actions[action_id].shortcuts == shortcut


def test_default_action_shortcuts_are_unique():
    shortcuts = [
        shortcut
        for action in actions.values()
        for shortcut in action.shortcuts
    ]
    assert len(shortcuts) == len(set(shortcuts))


@patch('xref.actions.actions.menu_structure',
       [{'menu': 'Foo', 'items': ['bar', 'baz']}])
def test_action_menu_path():
    action = Action(id='baz', text='Foo')
    assert action.menu_path == ['Foo']


@patch('xref.actions.actions.menu_structure',
       [{'menu': 'Foo', 'items': [{'menu': 'Bar', 'items': ['baz']}]}])
def test_action_menu_path_with_submenus():
    action = Action(id='baz', text='Foo')
    assert action.menu_path == ['Foo', 'Bar']


@patch('xref.actions.actions.menu_structure',
       [{'menu': 'Foo', 'items': '_build_recent_files'}])
def test_action_menu_path_recent_files():
    action = Action(id='baz', text='Foo', menu_id='_build_recent_files')
    assert action.menu_path == ['Foo']


@patch('xref.actions.actions.menu_structure',
       [{'menu': 'Foo', 'items': [
           {'menu': 'Bar', 'items': '_build_recent_files'}]}])
def test_action_menu_path_recent_files_in_submenu():
    action = Action(id='baz', text='Foo', menu_id='_build_recent_files')
    assert action.menu_path == ['Foo', 'Bar']
