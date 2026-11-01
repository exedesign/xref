.. image:: images/xref-logo.png
   :alt: XRef
   :width: 220px
   :align: center

XRef — A Reference Board for Images, Videos and Ideas
======================================================

XRef lets you quickly arrange your reference images, videos, PDFs and 3D
models and view them while you create. Its minimal interface is designed
not to get in the way of your creative process.

XRef is a fork of `BeeRef <https://github.com/rbreu/beeref>`_ by Rebecca Breu,
extended with video playback, multi-page PDFs, node-style links between
references, a pen for notes and sketches, shared boards and a Turkish
interface.

Features
--------

* Reference images (PNG, JPG, WebP, GIF, ...), videos (MP4, MOV, WebM, ...),
  multi-page PDFs and 3D models (OBJ, STL, PLY, GLB, glTF, USDZ and binary
  FBX)
* Frameless, PureRef-like window: double click the empty canvas for full
  screen, an always-on-top mode, resizable edges and a 10 px move band along
  every edge; minimize/full screen/close buttons appear in the top right
  corner after a short delay. Each scene can remember its own window
  position and size, stored inside the board file
  (Settings -> View -> Remember Scene Layouts)
* Infinite canvas with pan, zoom, rotate, flip, crop, arrange (including
  randomly) and normalize; the canvas colour and a background grid (lines or
  dots) with optional item snapping are configurable
* Video playback with a DaVinci-Resolve-like hover scrub (red playhead), a
  remembered preview frame, play/pause, mute and volume controls; a single
  click locks the frame under the pointer
* PDFs behave like videos: hover to flip through the pages, the last shown page
  is remembered and restored when the board is opened again; a single click
  locks the page
* 3D models are rendered in software (no 3D engine needed): rotate by moving
  the mouse over the model, click to pin the view, wheel to zoom; heavy
  models are reduced automatically and the quality is adjustable
  (Settings -> 3D Viewer)
* Media titles: images, videos, PDFs and models can show their file name on
  the canvas (Settings -> Miscellaneous -> Show Media Titles)
* Node-editor style links between items: **Shift+drag** from one item to
  another, or use Tools -> Link Selected Items; linked children can be moved
  together with Ctrl+drag; click a link to select it, Delete removes it
* Pen mode for freehand notes and sketches (Alt double-tap): brush colour and
  four brush sizes, smooth strokes, plus shape tools (rectangles, ellipses
  with Shift for squares/circles, straight lines)
* Text notes, opacity, grayscale and colour gamut view
* Duplicate (Ctrl+D) copies the selection with a small offset
* Drag & drop of images, videos, PDFs, 3D models, boards, text, HTML, text
  files and links; dragging a selection out of the window copies it to other
  applications
* Shared boards over the local network, paired with a session code (no IP
  addresses): authenticated, encrypted, with host approval, and the session
  continues on another peer if the host goes away. *Create Web Link*
  (Collaborate menu) opens a **live WebRTC mirror** of the board in any
  browser: guests see the canvas as video, control it with their own mouse
  and keyboard, get a random guest name (shown on the host's desktop at
  their cursor) and can drop media files straight into the browser - each
  upload shows a progress placeholder on the board. Guests may only delete
  the items they created themselves. *Create Web Link (Internet)* exposes the
  board outside the local network through a plain-SSH tunnel (localhost.run)
* Turkish and English interface (Settings -> Miscellaneous -> Language)
* Autosave with a configurable interval

Installation
------------

**Windows**: download the standalone ``XRef-<version>-windows-x86_64.exe``
from the `Releases <https://github.com/exedesign/xref/releases>`_ page and
run it - no installation required.

XRef also runs on Windows, Linux and macOS and needs Python 3.9 - 3.12 with
PyQt6.

.. code-block:: console

   pip install git+https://github.com/exedesign/xref.git
   xref

To run it from a checkout:

.. code-block:: console

   pip install -r requirements/dev.txt
   python -m xref

Board files
-----------

Boards are saved as ``.xref`` files, a SQLite database. Boards saved by older
versions (and by BeeRef) use ``.bee`` and open as usual; use *File -> Save As*
to store them in the new format.

Images are embedded as PNG, JPG or WebP (depending on the "Image Storage
Format" setting). Videos are referenced by their source path instead of being
copied, and are only embedded when the original file is no longer available.
PDFs are always embedded in full, so every page can be rendered at any size.
Images (and any embedded videos) live in an ``sqlar`` table, so they can be
extracted with the `sqlite command line program
<https://www.sqlite.org/cli.html>`_:

.. code-block:: console

   sqlite3 myfile.xref -Axv

Troubleshooting
---------------

You can access the log output via *Help -> Show Debug Log*.

License
-------

XRef is free software, licensed under the GNU General Public License v3. It is
based on BeeRef, Copyright (C) 2021-2024 Rebecca Breu, and keeps the original
copyright and license notices.
