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

from functools import partial
import logging

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from xref import constants, i18n
from xref.config import XRefSettings, settings_events
from xref.i18n import tr


logger = logging.getLogger(__name__)


class GroupBase(QtWidgets.QGroupBox):
    TITLE = None
    HELPTEXT = None
    KEY = None

    def __init__(self):
        super().__init__()
        self.settings = XRefSettings()
        self.update_title()
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        settings_events.restore_defaults.connect(self.on_restore_defaults)

        if self.HELPTEXT:
            helptxt = QtWidgets.QLabel(tr(self.HELPTEXT))
            helptxt.setWordWrap(True)
            self.layout.addWidget(helptxt)

    def update_title(self):
        title = [tr(self.TITLE)]
        if self.settings.value_changed(self.KEY):
            title.append(constants.CHANGED_SYMBOL)
        self.setTitle(' '.join(title))

    def on_value_changed(self, value):
        if self.ignore_value_changed:
            return

        value = self.convert_value_from_qt(value)
        if value != self.settings.valueOrDefault(self.KEY):
            logger.debug(f'Setting {self.KEY} changed to: {value}')
            self.settings.setValue(self.KEY, value)
            self.update_title()

    def convert_value_from_qt(self, value):
        return value

    def on_restore_defaults(self):
        new_value = self.settings.valueOrDefault(self.KEY)
        self.ignore_value_changed = True
        self.set_value(new_value)
        self.ignore_value_changed = False
        self.update_title()


class RadioGroup(GroupBase):
    OPTIONS = None

    def __init__(self):
        super().__init__()

        self.ignore_value_changed = True
        self.buttons = {}
        for (value, label, helptext) in self.OPTIONS:
            btn = QtWidgets.QRadioButton(tr(label))
            self.buttons[value] = btn
            btn.setToolTip(tr(helptext))
            btn.toggled.connect(partial(self.on_value_changed, value=value))
            if value == self.settings.valueOrDefault(self.KEY):
                btn.setChecked(True)
            self.layout.addWidget(btn)

        self.ignore_value_changed = False
        self.layout.addStretch(100)

    def set_value(self, value):
        for old_value, btn in self.buttons.items():
            btn.setChecked(old_value == value)


class IntegerGroup(GroupBase):
    MIN = None
    MAX = None

    def __init__(self):
        super().__init__()
        self.input = QtWidgets.QSpinBox()
        self.input.setRange(self.MIN, self.MAX)
        self.set_value(self.settings.valueOrDefault(self.KEY))
        self.input.valueChanged.connect(self.on_value_changed)
        self.layout.addWidget(self.input)
        self.layout.addStretch(100)
        self.ignore_value_changed = False

    def set_value(self, value):
        self.input.setValue(value)


class SingleCheckboxGroup(GroupBase):
    LABEL = None

    def __init__(self):
        super().__init__()
        self.input = QtWidgets.QCheckBox(self.LABEL)
        self.set_value(self.settings.valueOrDefault(self.KEY))
        self.input.checkStateChanged.connect(self.on_value_changed)
        self.layout.addWidget(self.input)
        self.layout.addStretch(100)
        self.ignore_value_changed = False

    def set_value(self, value):
        self.input.setChecked(value)

    def convert_value_from_qt(self, value):
        return value == Qt.CheckState.Checked


class ColorGroup(GroupBase):
    """A colour picker used as a setting."""

    def __init__(self):
        super().__init__()
        self.button = QtWidgets.QPushButton()
        self.button.clicked.connect(self.on_button_clicked)
        self.layout.addWidget(self.button)
        self.layout.addStretch(100)
        self.ignore_value_changed = False
        self.set_value(self.settings.valueOrDefault(self.KEY))

    def set_value(self, value):
        self.color = QtGui.QColor(value)
        if not self.color.isValid():
            self.color = QtGui.QColor(0, 0, 0)
        self.button.setText(self.color.name())
        pixmap = QtGui.QPixmap(16, 16)
        pixmap.fill(self.color)
        self.button.setIcon(QtGui.QIcon(pixmap))

    def on_button_clicked(self):
        dialog = QtWidgets.QColorDialog(
            self.color, self.window())
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.set_value(dialog.selectedColor().name())
            self.on_value_changed(self.color.name())


class ArrangeDefaultWidget(RadioGroup):
    TITLE = 'Default Arrange Method:'
    HELPTEXT = ('How images are arranged when inserted in batch')
    KEY = 'Items/arrange_default'
    OPTIONS = (
        ('optimal', 'Optimal', 'Arrange Optimal'),
        ('horizontal', 'Horizontal (by filename)',
         'Arrange Horizontal (by filename)'),
        ('vertical', 'Vertical (by filename)',
         'Arrange Vertical (by filename)'),
        ('square', 'Square (by filename)', 'Arrannge Square (by filename)'))


class ImageStorageFormatWidget(RadioGroup):
    TITLE = 'Image Storage Format:'
    HELPTEXT = ('How images are stored inside bee files.'
                ' Changes will only take effect on newly saved images.')
    KEY = 'Items/image_storage_format'
    OPTIONS = (
        ('best', 'Best Guess',
         ('Small images and images with alpha channel are stored as png,'
          ' everything else as jpg')),
        ('png', 'Always PNG', 'Lossless, but large bee file'),
        ('jpg', 'Always JPG',
         'Small bee file, but lossy and no transparency support'),
        ('webp', 'Always WebP',
         'Lossless or lossy, supports transparency, modern format'))


class ArrangeGapWidget(IntegerGroup):
    TITLE = 'Arrange Gap:'
    HELPTEXT = ('The gap between images when using arrange actions.')
    KEY = 'Items/arrange_gap'
    MIN = 0
    MAX = 200


class AllocationLimitWidget(IntegerGroup):
    TITLE = 'Maximum Image Size:'
    HELPTEXT = ('The maximum image size that can be loaded (in megabytes). '
                'Set to 0 for no limitation.')
    KEY = 'Items/image_allocation_limit'
    MIN = 0
    MAX = 10000


class ConfirmCloseUnsavedWidget(SingleCheckboxGroup):
    TITLE = 'Confirm when closing an unsaved file:'
    HELPTEXT = (
        'When about to close an unsaved file, should XRef ask for '
        'confirmation?')
    LABEL = 'Confirm when closing'
    KEY = 'Save/confirm_close_unsaved'


class AutosaveWidget(SingleCheckboxGroup):
    TITLE = 'Autosave:'
    HELPTEXT = ('Automatically save the board while you work. Only boards '
                'that already have a file are saved.')
    LABEL = 'Save automatically'
    KEY = 'Save/autosave'


class AutosaveIntervalWidget(IntegerGroup):
    TITLE = 'Autosave Interval:'
    HELPTEXT = 'How often the board is saved automatically (in minutes).'
    KEY = 'Save/autosave_interval'
    MIN = 1
    MAX = 120


class LanguageWidget(RadioGroup):
    TITLE = 'Language:'
    HELPTEXT = 'The language of the user interface.'
    KEY = 'General/language'
    OPTIONS = tuple(
        (code, name, name) for code, name in i18n.LANGUAGES.items())


class CanvasColorWidget(ColorGroup):
    TITLE = 'Canvas Background Color:'
    HELPTEXT = ('The background colour of the working area. Black is a good '
                'default for looking at reference images.')
    KEY = 'View/canvas_color'


class WindowButtonsDelayWidget(IntegerGroup):
    TITLE = 'Window Buttons Delay:'
    HELPTEXT = ('How long the pointer has to rest in the top right corner '
                '(in seconds) before the minimize, full screen and close '
                'buttons appear. Set to 0 to show them immediately.')
    KEY = 'View/window_buttons_delay'
    MIN = 0
    MAX = 30


class WindowMoveMarginWidget(IntegerGroup):
    TITLE = 'Window Edge Move Area:'
    HELPTEXT = ('The frameless window has no title bar. Drag this many pixels '
                'inside the window edge to move it; the outermost pixels '
                'resize the window. Set to 0 to disable the move area.')
    KEY = 'View/window_move_margin'
    MIN = 0
    MAX = 60


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        self.build()
        i18n.language_events.changed.connect(self.on_language_changed)
        self.show()

    def build(self):
        """(Re)builds the dialog, so it can follow language changes."""

        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.setWindowTitle(tr('{app} Settings', app=constants.APPNAME))

        tabs = QtWidgets.QTabWidget()

        # Miscellaneous
        misc = QtWidgets.QWidget()
        misc_layout = QtWidgets.QGridLayout()
        misc.setLayout(misc_layout)
        misc_layout.addWidget(LanguageWidget(), 0, 0)
        misc_layout.addWidget(ConfirmCloseUnsavedWidget(), 1, 0)
        misc_layout.addWidget(AutosaveWidget(), 2, 0)
        misc_layout.addWidget(AutosaveIntervalWidget(), 2, 1)
        misc_layout.addWidget(WindowMoveMarginWidget(), 3, 0)
        misc_layout.addWidget(WindowButtonsDelayWidget(), 3, 1)
        misc_layout.addWidget(CanvasColorWidget(), 4, 0)
        tabs.addTab(misc, tr('&Miscellaneous'))

        # Images & Items
        items = QtWidgets.QWidget()
        items_layout = QtWidgets.QGridLayout()
        items.setLayout(items_layout)
        items_layout.addWidget(ImageStorageFormatWidget(), 0, 0)
        items_layout.addWidget(AllocationLimitWidget(), 0, 1)
        items_layout.addWidget(ArrangeGapWidget(), 1, 0)
        items_layout.addWidget(ArrangeDefaultWidget(), 1, 1)
        tabs.addTab(items, tr('&Images && Items'))

        self.layout.addWidget(tabs)

        # Bottom row of buttons
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        reset_btn = QtWidgets.QPushButton(tr('&Restore Defaults'))
        reset_btn.setAutoDefault(False)
        reset_btn.clicked.connect(self.on_restore_defaults)
        buttons.addButton(reset_btn,
                          QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)

        self.layout.addWidget(buttons)

    def on_language_changed(self, code):
        # Deferred, so the widget that triggered the change is not deleted
        # while its signal is still being handled
        QtCore.QTimer.singleShot(0, self.build)

    def on_restore_defaults(self, *args, **kwargs):
        reply = QtWidgets.QMessageBox.question(
            self,
            tr('Restore defaults?'),
            tr('Do you want to restore all settings to their default '
               'values?'))

        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            XRefSettings().restore_defaults()
