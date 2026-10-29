from unittest.mock import patch, MagicMock

from PyQt6 import QtCore

from xref.__main__ import XRefMainWindow, main
from xref.assets import XRefAssets
from xref.view import XRefGraphicsView


@patch('PyQt6.QtWidgets.QWidget.show')
def test_xref_mainwindow_init(show_mock, qapp):
    window = XRefMainWindow(qapp)
    assert window.windowTitle() == 'XRef'
    assert XRefAssets().logo == XRefAssets().logo
    assert window.windowIcon()
    assert window.contentsMargins() == QtCore.QMargins(0, 0, 0, 0)
    assert isinstance(window.view, XRefGraphicsView)
    show_mock.assert_called()


@patch('xref.view.XRefGraphicsView.open_from_file')
def test_xrefapplication_fileopenevent(open_mock, qapp, main_window):
    event = MagicMock()
    event.type.return_value = QtCore.QEvent.Type.FileOpen
    event.file.return_value = 'test.bee'
    assert qapp.event(event) is True
    open_mock.assert_called_once_with('test.bee')


@patch('xref.__main__.XRefApplication')
@patch('xref.__main__.CommandlineArgs')
@patch('xref.config.XRefSettings.on_startup')
def test_main(startup_mock, args_mock, app_mock, qapp):
    app_mock.return_value = qapp
    args_mock.return_value.filename = None
    args_mock.return_value.loglevel = 'WARN'
    args_mock.return_value.debug_raise_error = ''

    with patch.object(qapp, 'exec') as exec_mock:
        main()
        exec_mock.assert_called_once_with()

    args_mock.assert_called_once_with(with_check=True)
    startup_mock.assert_called()
