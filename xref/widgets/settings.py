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

from xref import constants, i18n, model3d
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
    HELPTEXT = ('How newly generated images are encoded in scene files. '
                'Imported source images are embedded unchanged.')
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


class ImagePreviewMaxDimensionWidget(IntegerGroup):
    TITLE = 'Maximum Image Preview Dimension:'
    HELPTEXT = (
        'Images larger than this are decoded as smaller on-screen previews. '
        'The original image is preserved in the scene file.')
    KEY = 'Items/image_preview_max_dimension'
    MIN = 256
    MAX = 16384


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


class RememberSceneLayoutsWidget(SingleCheckboxGroup):
    TITLE = 'Remember Scene Layouts:'
    HELPTEXT = ('Save the window position and size for each scene in a '
                'small file next to it. Reopening a scene restores its '
                'window; new windows keep using the last closed layout.')
    LABEL = 'Remember layouts per scene'
    KEY = 'View/remember_scene_layouts'


class ModelMaxTrianglesWidget(IntegerGroup):
    TITLE = 'Model Quality (Triangles):'
    HELPTEXT = ('Maximum number of triangles rendered per 3D model. Higher '
                'values look more detailed but rotate slower; lower values '
                'are faster. Models above the limit keep their silhouette.')
    KEY = 'Items/model_max_triangles'
    MIN = 1000
    MAX = 500000


class ModelPreviewIntervalWidget(IntegerGroup):
    TITLE = 'Model Preview Interval (ms):'
    HELPTEXT = ('While rotating a heavy model, the preview is refreshed at '
                'most this often. 0 disables the throttle (smoothest, but '
                'big models can lag).')
    KEY = 'Items/model_preview_interval'
    MIN = 0
    MAX = 1000


class ShowMediaTitlesWidget(SingleCheckboxGroup):
    TITLE = 'Show Media Titles:'
    HELPTEXT = ('Show the file name of each image, video and PDF on the '
                'canvas, so references are easier to identify.')
    LABEL = 'Show media titles'
    KEY = 'Items/show_media_titles'


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


class WindowCornerRadiusWidget(IntegerGroup):
    TITLE = 'Window Corner Radius (px):'
    HELPTEXT = ('Rounds the corners of the frameless window. The default '
                'matches the rounded look of the window control buttons; '
                'set to 0 for sharp corners.')
    KEY = 'View/window_corner_radius'
    MIN = 0
    MAX = 32


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        self.resize(900, 560)
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

        content = QtWidgets.QHBoxLayout()
        sidebar = QtWidgets.QWidget()
        sidebar.setFixedWidth(220)
        sidebar_layout = QtWidgets.QVBoxLayout(sidebar)
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText(tr('Search settings'))
        self.search_input.textChanged.connect(self.filter_settings)
        sidebar_layout.addWidget(self.search_input)
        self.categories = QtWidgets.QListWidget()
        self.categories.currentRowChanged.connect(
            self.on_category_changed)
        sidebar_layout.addWidget(self.categories)
        content.addWidget(sidebar)

        self.pages = QtWidgets.QStackedWidget()
        content.addWidget(self.pages, 1)
        self.layout.addLayout(content, 1)

        performance_widgets = [
            ImagePreviewMaxDimensionWidget, ModelPreviewIntervalWidget]
        if not model3d.F3D_ENABLED:
            performance_widgets.insert(1, ModelMaxTrianglesWidget)
        category_specs = [
            ('Performance', QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon,
             performance_widgets),
            ('Appearance', QtWidgets.QStyle.StandardPixmap.SP_DesktopIcon,
             [CanvasColorWidget, ShowMediaTitlesWidget]),
            ('Saving and loading',
             QtWidgets.QStyle.StandardPixmap.SP_DialogSaveButton,
             [ImageStorageFormatWidget, AutosaveWidget,
              AutosaveIntervalWidget, ConfirmCloseUnsavedWidget,
              RememberSceneLayoutsWidget]),
            ('Window', QtWidgets.QStyle.StandardPixmap.SP_TitleBarMenuButton,
             [WindowButtonsDelayWidget, WindowCornerRadiusWidget]),
            ('Images',
             QtWidgets.QStyle.StandardPixmap.SP_FileDialogContentsView,
             [ArrangeDefaultWidget, ArrangeGapWidget]),
            ('Keyboard shortcuts',
             QtWidgets.QStyle.StandardPixmap.SP_DialogApplyButton, []),
            ('System', QtWidgets.QStyle.StandardPixmap.SP_BrowserReload,
             [LanguageWidget]),
        ]
        self.category_pages = []
        for title, icon, widget_classes in category_specs:
            page = QtWidgets.QWidget()
            page_layout = QtWidgets.QVBoxLayout(page)
            heading = QtWidgets.QLabel(tr(title))
            heading.setObjectName('settingsCategoryHeading')
            heading_font = heading.font()
            heading_font.setPointSize(16)
            heading_font.setBold(True)
            heading.setFont(heading_font)
            page_layout.addWidget(heading)

            if widget_classes:
                grid = QtWidgets.QGridLayout()
                widgets = []
                for index, widget_class in enumerate(widget_classes):
                    setting_widget = widget_class()
                    widgets.append(setting_widget)
                    grid.addWidget(setting_widget, index // 2, index % 2)
                grid.setRowStretch((len(widgets) + 1) // 2, 1)
                grid.setColumnStretch(0, 1)
                grid.setColumnStretch(1, 1)
                page_layout.addLayout(grid, 1)
            else:
                widgets = []
                description = QtWidgets.QLabel(
                    tr('Configure keyboard and mouse shortcuts.'))
                description.setWordWrap(True)
                page_layout.addWidget(description)
                open_controls = QtWidgets.QPushButton(
                    tr('Open Keyboard & Mouse Controls'))
                open_controls.clicked.connect(self.open_controls_dialog)
                page_layout.addWidget(open_controls, 0, Qt.AlignmentFlag.AlignLeft)
                page_layout.addStretch(1)

            page.searchable_widgets = widgets
            page.category_title = title
            self.pages.addWidget(page)
            item = QtWidgets.QListWidgetItem(
                self.style().standardIcon(icon), tr(title))
            self.categories.addItem(item)
            self.category_pages.append(page)

        self.no_results = QtWidgets.QLabel(tr('No matching settings'))
        self.no_results.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pages.addWidget(self.no_results)
        self.categories.setCurrentRow(0)

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
        self.filter_settings('')

    def on_category_changed(self, row):
        if 0 <= row < len(self.category_pages):
            self.pages.setCurrentWidget(self.category_pages[row])

    def filter_settings(self, text):
        query = text.casefold().strip()
        visible_rows = []
        for row, page in enumerate(self.category_pages):
            category_matches = query in tr(page.category_title).casefold()
            visible_widgets = []
            for setting_widget in page.searchable_widgets:
                searchable = ' '.join((
                    tr(setting_widget.TITLE or ''),
                    tr(setting_widget.HELPTEXT or ''),
                )).casefold()
                visible = not query or category_matches or query in searchable
                setting_widget.setVisible(visible)
                if visible:
                    visible_widgets.append(setting_widget)
            visible = not query or category_matches or bool(visible_widgets)
            self.categories.item(row).setHidden(not visible)
            if visible:
                visible_rows.append(row)

        current_row = self.categories.currentRow()
        if current_row not in visible_rows:
            self.categories.setCurrentRow(
                visible_rows[0] if visible_rows else -1)
        if visible_rows:
            self.pages.setCurrentWidget(
                self.category_pages[self.categories.currentRow()])
        else:
            self.pages.setCurrentWidget(self.no_results)

    def open_controls_dialog(self):
        from xref.widgets.controls import ControlsDialog
        dialog = ControlsDialog(self)
        dialog.exec()

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
