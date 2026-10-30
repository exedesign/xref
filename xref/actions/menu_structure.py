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

MENU_SEPARATOR = 0

menu_structure = [
    {
        'menu': '&File',
        'items': [
            'new_scene',
            'open',
            {
                'menu': 'Open &Recent',
                'items': '_build_recent_files',
            },
            MENU_SEPARATOR,
            'save',
            'open_scene_location',
            'save_as',
            'export_scene',
            'export_images',
            MENU_SEPARATOR,
            'quit',
        ],
    },
    {
        'menu': '&Edit',
        'items': [
            'undo',
            'redo',
            MENU_SEPARATOR,
            'select_all',
            'deselect_all',
            MENU_SEPARATOR,
            'cut',
            'copy',
            'paste',            'duplicate',

            'delete',
            MENU_SEPARATOR,
            'raise_to_top',
            'lower_to_bottom',
        ],
    },
    {
        'menu': '&View',
        'items': [
            'fit_scene',
            'fit_selection',
            MENU_SEPARATOR,
            'fullscreen',
            'always_on_top',
            'show_scrollbars',
            'show_menubar',
            'show_titlebar',
            MENU_SEPARATOR,
            'move_window',
        ],
    },
    {
        'menu': '&Insert',
        'items': [
            'insert_images',
            'insert_video',
            'insert_text',
        ],
    },
    {
        'menu': '&Transform',
        'items': [
            'crop',
            'flip_horizontally',
            'flip_vertically',
            MENU_SEPARATOR,
            'reset_scale',
            'reset_rotation',
            'reset_flip',
            'reset_crop',
            'reset_transforms',
        ],
    },
    {
        'menu': '&Normalize',
        'items': [
            'normalize_height',
            'normalize_width',
            'normalize_size',
        ],
    },
    {
        'menu': '&Arrange',
        'items': [
            'arrange_optimal',
            'arrange_horizontal',
            'arrange_vertical',
            'arrange_square',            'arrange_randomly',

        ],
    },
    {
        'menu': '&Images',
        'items': [
            'change_opacity',
            'grayscale',
            MENU_SEPARATOR,
            'show_color_gamut',
            'sample_color',
        ],
    },
    {
        'menu': '&Video',
        'items': [
            'play_video',
        ],
    },
    {
        'menu': '&Tools',
        'items': [
            'toggle_draw',
            'pen_tool_freehand',
            'pen_tool_rect',
            'pen_tool_ellipse',
            'pen_tool_line',
            'pen_color',
            'pen_width_thin',
            'pen_width_normal',
            'pen_width_thick',
            'pen_width_huge',
            MENU_SEPARATOR,
            'link_items',
            'unlink_items',
        ],
    },
    {
        'menu': '&Collaborate',
        'items': [
            'collab_host',
            'collab_join',
            MENU_SEPARATOR,
            'collab_code',
            'collab_approval',
            MENU_SEPARATOR,
            'collab_leave',
        ],
    },
    {
        'menu': '&Settings',
        'items': [
            'settings',
            'keyboard_settings',
            'open_settings_dir',
        ],
    },
    {
        'menu': '&Help',
        'items': [
            'help',
            'about',
            'debuglog',
        ],
    },
]
