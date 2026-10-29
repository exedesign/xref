0.4.0-dev (unreleased)
======================

Renamed to XRef
---------------

* The project is now called **XRef**: window title, About dialog, package
  name (``xref``), settings file, log file and documentation.
* Boards are saved as ``.xref``. Boards saved by older versions (and by
  BeeRef) use ``.bee`` and still open; use *File -> Save As* to convert.
* Existing settings are migrated automatically on first start.
* The licence (GPL-3.0) and the original BeeRef copyright notices are kept.

Added
-----

* Added a setting to change the default memory limit for individual
  images. If a big image won't load, increase this limit. This
  setting can be overridden by Qt's default environment variable
  QT_IMAGEIO_MAXALLOC
* Display error messages when images can't be loaded from bee files
* Added option to export all images from scene (File -> Export Images)
* Added a confirmation dialog when attempting to close unsaved files.
  The confirmation dialog can be disalbed in:
  Settings -> Miscellaneous -> Confirm when closing an unsaved file
* Add option to arrange by filename (Arrange -> Square (by filename))
* Added a setting to choose the default arrange method on importing
  images in batch.
  (Settings -> Settings -> Images & Items -> Default Arrange Method).
* Added the ability to open image files from command line. If the
  first command line arg is a bee file, it will be opened and all
  further files will be ignored, as previously. If the first argument
  isn't a bee file, all files will be treated as images and inserted
  as if opened with "Insert -> Images".
* Added support for adding videos to a scene (Insert -> Video, or by
  dragging & dropping video files). Videos are stored in bee files
  as their original file and can be played back directly in the scene.
* Added support for multi-page PDFs (Insert -> Images / PDFs, or by
  dragging & dropping PDF files). PDFs work like videos: hovering over a
  page flips through the pages (the red vertical playhead on the progress
  bar shows and sets the page), the arrows and mouse wheel change the page,
  and the page you stopped on is the one shown later, also after saving and
  reloading the scene. The original PDF is stored in the scene (and sent to
  the other machines in a collaboration session), so every page is
  rendered at full quality.
* XRef now has a frameless, PureRef-like window: no title bar, double click
  on the empty canvas switches to full screen (F11 toggles it, Escape leaves
  it) and *View -> Always On Top* keeps the window above other applications.
  Every edge and corner of the window can be dragged to resize it, and the
  band just inside an edge moves the window (10 px by default, configurable
  in Settings -> Miscellaneous -> Window Edge Move Area). Ctrl+Alt+drag and
  Ctrl+M still move the window. The title bar and the always-on-top state
  are remembered between sessions.
* Videos and PDFs: a single left click now pins the frame or page under
  the pointer (a small padlock in the corner shows it), so moving the
  mouse over the item no longer scrubs or flips through it. The next
  single click starts browsing again; dragging the item keeps its frame.
* Dragging selected media out of the window now starts a normal OS
  drag & drop, so media can be copied into other applications or
  folders (images as files or image data, videos as files, PDFs as
  files, text as text). The originals stay in place, so dragging out
  copies instead of moving.
* Fixed repaint trails: while items were dragged, old link curves and
  selection outlines were left behind on the canvas. The view now
  repaints the affected region (and the whole viewport while links are
  shown).
* Improved drag & drop: dropping text or HTML (e.g. from a browser,
  text editor or chat window) now inserts a text item at the drop
  position, dropping a text-like file (.txt, .md, .csv, .json, source
  code, .srt, ...) inserts its contents, and links dropped from a
  browser are inserted as text. Images, videos and .bee files keep
  working as before, and unsupported drops now give a clear message
  instead of failing silently.
* Shared boards keep working when the host goes away: the host
  designates a successor, which continues the session under the same
  session code and the other peers reconnect to it automatically. When
  the host stops sharing on purpose, the session ends for everyone.
* Shared media is distributed to every peer in its original form:
  images keep their original resolution (the old 2400 px downscale is
  gone) and their original file bytes, videos are copied to every
  machine so they can be played there, and large files are streamed in
  chunks with checksums. Crop and grayscale are shared as flags, so
  every machine shows the same thing.
* Added autosave (Settings -> Miscellaneous -> Autosave) with a
  configurable interval, so long sessions are not lost. Autosave only
  writes boards that already have a file and never interrupts with
  dialogs.
* Added shared board sessions (Collaborate menu), so several XRef
  installations on the same network can work on one board together -
  the idea is similar to PowerToys' "Mouse Without Borders", but sharing
  the canvas instead of the pointer. One user starts a session
  (Collaborate -> Share Board, Ctrl+Shift+H) and gets a session code
  such as ``K7M4Q-9PXE2``; the others join with that code only
  (Ctrl+Shift+J) - no IP addresses or port numbers are needed. Items,
  images, videos (by path), texts, drawings, transforms and node links
  are kept in sync automatically; a joining user receives the current
  board. The shared board is not saved automatically - use File -> Save
  As to keep a copy.
* Sharing is secured: the session code is stretched with PBKDF2 and is
  never transmitted (joiners find the host by broadcasting a one-way
  hash of it), both sides prove knowledge of the code with HMAC during
  the handshake, all board data is encrypted and authenticated
  (SHAKE-256 keystream + HMAC-SHA256), tampered or replayed frames are
  rejected, repeated wrong attempts are rate limited, and the host is
  asked to approve every peer before it joins
  (Collaborate -> Ask Before Peers Join). Collaborate -> Show Session
  Code displays the current code again.
* Fixed the video player controls not reacting to clicks: the buttons
  and the volume slider no longer depend on the hover state, and the
  controls also stay visible while the video is selected.
* Added WebP as an option for the image storage format
  (Settings -> Images & Items -> Image Storage Format -> Always WebP),
  and WebP is now available in the "Export Scene to Image" dialog.
* Reworked videos: they are now played directly from their source
  location (bee files store a reference instead of a copy). The first
  frame is shown as a preview, moving the mouse horizontally over the
  video scrubs through it (like DaVinci Resolve), and hovering shows
  media player controls: a single play/pause button, a mute button and
  a volume slider, plus the current time. There is no seek bar: the
  position is set by moving the mouse over the video (the red playhead
  line) or by clicking it. The preview stays pinned to the position
  where playback was last stopped.
  Double-click toggles play/pause; Ctrl+Shift+Space does the same. The
  mute state and volume are saved with the item.
* Added node-editor style links between media to visualize the
  relationship between them (parent -> child, drawn as curved arrows
  with an arrow head). Link an item by dragging from its round link
  port (shown on hover/selection and marked with a "+"), by Shift+drag
  from the item, or via Tools -> Link Selected Items (Ctrl+L). The
  link port appears on the edge nearest to the pointer as a small
  glowing socket. Links are saved in bee files and survive undo/redo.
* Links can be removed in three ways: click a link to select it (it is
  highlighted) and press Delete, drag from a link port onto empty
  space, or use Tools -> Remove Links from Selected Items
  (Ctrl+Shift+L). Removing a link never deletes the media items.
* Holding Ctrl while dragging a parent media now moves all linked
  child media together with it as a group (one undo step).
* Added a pen/draw mode for adding freehand notes and sketches to the
  scene. Toggle it via Tools -> Draw, Ctrl+Shift+D, or by tapping the
  Alt key twice in quick succession; Esc goes back to the selector.
  Strokes are smoothed (quadratic interpolation) and drawn with round
  caps, so they look like a brush. The brush colour (Tools -> Pen
  Colour) and size (Tools -> Brush Thin/Normal/Thick/Huge) can be
  changed and are also applied to selected strokes; the size stays
  constant on screen at any zoom level. Strokes can be selected, moved,
  restyled and deleted, and are saved in bee files.

Fixed
-----

* Fixed a case where adding/importing an image would hang when the image
  contained unsupported exif data (#111)
* Fixed a hang when saving an open bee file that had been removed
  since being opened
* Shortcuts now only trigger once when holding down the key
  combination to avoid inconstistend program states and potential
  crashes (by DarkDefender)
* Fixed a crash when pressing the crop shortcut while dragging an image
  (by DarkDefender)


Changed
-------

* Arrange Horiszontal/Vertical now also sort by filename instead of
  the previous seemingly random behaviour


0.3.3 - 2024-05-05
==================

Added
-----

* Moving the window from within XRef now changes to a diffent cursor from
  the default arrow cursor.
* Added a color sampler which can copy colors from images to the
  clipboard in hex format (Images -> Sample Color)
* Added notification when attempting to paste from an empty or
  unusable clipboard
* Added panning via scrollwheel:
  * Scroll wheel + Shift + Ctrl: pan vertically
  * Scroll wheel + Shift: pan horizontally
* Make mouse and mouse wheel controls configurable
  (Settings -> Keyboard & Mouse)


Fixed
-----

* Fixed a crash when pressing the keyboard shortcut for New Scene
  while in the process of doing a rubberband selection.
* The checkmark of the menu entry Images -> Grayscale is now updating
  correctly depending on the selected images.
* Removed black line under marching ants outline of crop mode, which
  would scale with the image and get potentially very thick.
* Fixed a crash when importing images with unsupported exif orientation info
* Fixed threading issue when importing images (causing potential
  hangs/weird behaviour)
* Fixed an intermittent crash when invoking New Scene
* Fixed bee files hanging on to disk space of deleted images (issue #99)
* Fixed Drag @ Drop from pinterest feed (by Randommist)
* Fixed pasted items being inserted behind existing items



0.3.2 - 2024-01-21
==================

Added
-----

* For arranging, a gap between images can now be configured in the
  settings.
* The opacity of images can be changed (Images -> Change Opacity).
* Images can be set to display as grayscale (Images -> Grayscale).
* The scene can now also be exported as SVG
* Keyboard shortcuts can now be edited from within XRef (Settings ->
  Keyboard Shortcuts). The KeyboardSettings.ini file will now only
  store values which are changed from the default, since it's no longer
  needed as a reference.
* Settings dialog now displays icons to indicate changes from default
  values


Fixed
-----

* Scene Export: Fix output image size and margins when scene had been
  scaled or moved.
* Scene Export: Selecting filename without file extension now
  automatically appends the extension from the selected filter instead
  of resulting in a confusing error message.
* The exemption from antialias/smoothing for images displayed at large
  zoom now also works on images that are flipped horizontally


Changed
-------

* Improved performance of Select All/Deselect All



0.3.1 - 2023-12-10
==================

Added
-----

* Images can now be stored JPG or PNG inside the bee file. By default,
  small images and images with an alpha channel will be stored as PNG,
  the rest as JPG. In the newly created settings dialog, this
  behaviour can be changed to always use PNG (the former behaviour) or
  always JPG. To apply this behaviour to already saved images in
  existing bee files, you can save them as new files.
* Enabled antialiasing/smoothing. Images that are being displayed at a
  large zoom factor are exempt to make sure that icons, pixel sprites
  etc can be viewed correctly.
* A scene can now be exported to a single image (File -> Export Scene...)
* Alternative way to move the XRef window without the title bar:
  View -> Move Window (or press "M")


Changed
-------

* Editing of text items will now be undoable after leaving edit mode
* Empty text items will be deleted after leaving edit mode
* Text edit mode can now be aborted with Escape
* "Save as" will now open pre-select the folder of the currently opened file
* "Save" and "Save as" are now inactive when the scene is empty


Fixed
-----

* Fixed a bug where the binary data of deleted images would still hang
  around in the bee file.
* The shortcut to move the XRef window (Ctrl + Alt + Drag)
  now works on an empty scene
* Crash when copying an item from a bee file, opening a new scene and
  pasting the image into it.


0.3.0 - 2023-11-23
==================

Added
-----

* Image cropping (Go to "Transform -> Crop", or press Shift + C)
* Show list of recent files on welcome screen
* Keyboard shortcuts can now be configured via a settings file.
  Go to "Settings -> Open Settings Folder" and edit KeyboardSettings.ini
* Remember window geometry when closing (by David Andrs)

Fixed
-----

* Various typos (by luzpaz)
* Ensure that small items always have an area in the middle for
  moving/editing that doesn't trigger transform actions
* Ensure that the first click to select an item doesn't immediately trigger
  transform actions


0.2.0 - 2021-09-06
==================

Note that bee files from version 0.2.0 won't open in XRef 0.1.x.

Added
-----

* You can now add plain text notes and paste text from the clipboard
* You can now open bee files from finder on MacOS (by David Andrs)
* Dragging bee files onto an empty scene will now open them
* Adding the first image(s) to a new scene centers the view

Changed
-------

* Make debug log file less verbose
* The program is now bundled as a single executable file (issue #4)

Fixed
-----

* Hovering over the scale handles of very narrow items now displays
  correct cursor orientation
* Fix a rare crash while displaying selection handles


0.1.1 - 2021-07-18
==================

Changed
-------

* Flipping an image now happens on mouse press instead of mouse release
* About dialog points to new website xref.org
* Menus and dialogs now have a dark style to match the optics of the canvas

Fixed
-----

* Double click to zoom an item and double-clicking again should now always
  correctly go back to the previous position
* The outline of the rubberband selection now stays the same size
  regardless of zoom


0.1.0 - 2021-07-10
==================

First release!
