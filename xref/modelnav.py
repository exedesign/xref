#!/usr/bin/env python3

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

"""three.js style 3D navigation.

This is a port of three.js' ``OrbitControls``
(``examples/jsm/controls/OrbitControls.js``) that works on plain camera
state dictionaries instead of a ``THREE.Camera``. Names, defaults, the
mouse bindings, the damping model and the actual maths are kept identical
to three.js so the viewer navigates exactly like the three.js examples.

Only the parts that need a WebGL context (pointer events, DOM listeners)
are left to the caller; the Qt layer feeds pointer deltas in and calls
:meth:`OrbitControls.update` once per frame.
"""

import math

#: Drag action names, matching three.js' ``MOUSE`` enum.
ROTATE = 'rotate'
DOLLY = 'dolly'
PAN = 'pan'

#: three.js ``_EPS``, used to keep the polar angle off the poles.
EPS = 1e-6

_TWO_PI = 2.0 * math.pi

#: Up axis -> ``(up, right, forward)`` with ``forward = right x up``.
#: ``right``/``forward`` form the azimuth plane used by ``Spherical``.
_AXES = {
    'Z': ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
    'Y': ((0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    'X': ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
}

#: View up used when looking straight down the up axis. three.js relies on
#: a matrix nudge here; a fixed secondary axis is deterministic instead.
_TOP_UP = {
    'Z': (0.0, 1.0, 0.0),
    'Y': (0.0, 0.0, 1.0),
    'X': (0.0, 1.0, 0.0),
}


MOUSE_BUTTONS = {'left': ROTATE, 'middle': DOLLY, 'right': PAN}


def action_for(button, modifiers=(), enable_rotate=True, enable_pan=True):
    """three.js ``onMouseDown()`` mapping, without a controls instance.

    ``Ctrl``, ``Meta`` and ``Shift`` swap rotate and pan; dolly is never
    swapped and disabled actions resolve to ``None``.
    """

    action = MOUSE_BUTTONS.get(button)
    if action is None:
        return None
    if not any(name in modifiers for name in ('ctrl', 'meta', 'shift')):
        if action == ROTATE and not enable_rotate:
            return None
        if action == PAN and not enable_pan:
            return None
        return action
    if action == ROTATE:
        return PAN if enable_pan else None
    if action == PAN:
        return ROTATE if enable_rotate else None
    return action


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(vector, factor):
    return (vector[0] * factor, vector[1] * factor, vector[2] * factor)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _length(vector):
    return math.sqrt(_dot(vector, vector))


def _normalize(vector):
    length = _length(vector)
    if length <= EPS:
        return (0.0, 0.0, 0.0)
    return _scale(vector, 1.0 / length)


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))



class OrbitControls:
    """Orbit, dolly and pan around a target, like three.js.

    The camera is described by a plain dictionary with the same keys as the
    ``f3d`` camera state::

        {'position': [x, y, z], 'focal_point': [x, y, z],
         'view_up': [x, y, z], 'view_angle': degrees}

    ``focal_point`` plays the role of OrbitControls' ``target``.
    """

    #: three.js defaults from the `OrbitControls` constructor.
    enable_damping = True
    damping_factor = 0.05
    enable_zoom = True
    zoom_speed = 1.0
    enable_rotate = True
    rotate_speed = 1.0
    enable_pan = True
    pan_speed = 1.0
    screen_space_panning = True
    zoom_to_cursor = False
    auto_rotate = False
    auto_rotate_speed = 2.0
    min_distance = 0.0
    max_distance = math.inf
    min_polar_angle = 0.0
    max_polar_angle = math.pi
    min_azimuth_angle = -math.inf
    max_azimuth_angle = math.inf

    #: three.js' default mouse mapping (``this.mouseButtons``).
    mouse_buttons = {'left': ROTATE, 'middle': DOLLY, 'right': PAN}

    #: Duration of an axis snap, in milliseconds.
    SNAP_DURATION_MS = 220

    def __init__(self, up_axis='Z', state=None, **settings):
        if up_axis not in _AXES:
            raise ValueError(f'Unsupported model up axis: {up_axis}')
        self.up_axis = up_axis
        self.up, self.right, self.forward = _AXES[up_axis]
        self.top_up = _TOP_UP[up_axis]
        for name, value in settings.items():
            if not hasattr(type(self), name):
                raise AttributeError(f'Unknown OrbitControls setting: {name}')
            setattr(self, name, value)
        self.state = self._copy_state(state)
        #: Accumulated rotation while damping is being applied.
        self._delta_theta = 0.0
        self._delta_phi = 0.0
        #: Accumulated pan translation (OrbitControls' ``panOffset``).
        self._pan_offset = [0.0, 0.0, 0.0]
        #: Pending dolly factor (OrbitControls' ``scale``).
        self._scale = 1.0
        #: Whether the pending dolly should keep the cursor point fixed.
        self._zoom_to_cursor_pending = False
        #: Active axis snap animation, see :meth:`snap_to_axis`.
        self._snap = None
        self._snap_elapsed = 0.0

    # -- Camera state ------------------------------------------------------

    @staticmethod
    def _copy_state(state):
        if state is None:
            return None
        return {
            'position': [float(v) for v in state['position']],
            'focal_point': [float(v) for v in state['focal_point']],
            'view_up': [float(v) for v in state['view_up']],
            'view_angle': float(state['view_angle']),
        }

    def snapshot(self):
        """The current camera state as a plain dictionary."""

        return self._copy_state(self.state)

    def restore(self, state):
        """Replaces the camera state, e.g. after loading a saved view."""

        self.state = self._copy_state(state)
        self.cancel_pending()
        self._zoom_to_cursor_pending = False
        self._snap = None

    def reset(self, state):
        """``controls.reset()``: jump to ``state`` and clear all motion."""

        self.restore(self._copy_state(state))
        self._snap = None
        return self.snapshot()

    def cancel_pending(self):
        """Drops damped motion, like releasing the pointer in three.js."""

        self._delta_theta = 0.0
        self._delta_phi = 0.0
        self._pan_offset = [0.0, 0.0, 0.0]
        self._scale = 1.0

    @property
    def target(self):
        if self.state is None:
            return [0.0, 0.0, 0.0]
        return list(self.state['focal_point'])

    @target.setter
    def target(self, value):
        if self.state is not None:
            self.state['focal_point'] = [float(v) for v in value]

    @property
    def view_angle(self):
        if self.state is None:
            return 45.0
        return float(self.state['view_angle'])

    def distance(self):
        """Current distance between the camera and the target."""

        if self.state is None:
            return 0.0
        return _length(_sub(self.state['position'],
                            self.state['focal_point']))

    # -- Spherical helpers -------------------------------------------------

    def _spherical(self):
        """``Spherical.setFromVector3()`` in the controls' up space."""

        offset = _sub(self.state['position'], self.state['focal_point'])
        radius = _length(offset)
        if radius <= EPS:
            return radius, math.pi / 2.0, 0.0
        phi = math.acos(_clamp(_dot(offset, self.up) / radius, -1.0, 1.0))
        theta = math.atan2(
            _dot(offset, self.right), _dot(offset, self.forward))
        return radius, phi, theta

    def _offset_from(self, radius, phi, theta):
        """``Spherical.setFromSpherical()`` in the controls' up space."""

        sin_phi = math.sin(phi)
        vertical = _scale(self.up, radius * math.cos(phi))
        azimuth = _add(_scale(self.forward, radius * sin_phi * math.cos(theta)),
                       _scale(self.right, radius * sin_phi * math.sin(theta)))
        return _add(vertical, azimuth)

    def _view_forward(self):
        return _normalize(
            _sub(self.state['focal_point'], self.state['position']))

    def _screen_basis(self):
        """Screen right/up from the camera matrix, as OrbitControls uses."""

        forward = self._view_forward()
        right = _normalize(_cross(forward, self.state['view_up']))
        if _length(right) <= EPS:
            right = _normalize(_cross(forward, self.top_up))
        if _length(right) <= EPS:
            right = self.right
        up = _normalize(_cross(right, forward))
        if _length(up) <= EPS:
            up = self.up
        return forward, right, up

    # -- Pointer API -------------------------------------------------------

    def zoom_scale(self):
        """``_getZoomScale()``: the dolly factor of a single wheel notch."""

        return 0.95 ** float(self.zoom_speed)

    def rotate(self, delta_x, delta_y, viewport_height):
        """``_handleMouseMoveRotate()``: orbit by a pointer delta."""

        if not self.enable_rotate or viewport_height <= 0:
            return self.snapshot()
        factor = _TWO_PI / float(viewport_height)
        self._delta_theta -= factor * float(delta_x) * self.rotate_speed
        self._delta_phi -= factor * float(delta_y) * self.rotate_speed
        self._snap = None
        return self.snapshot()

    def dolly(self, scale):
        """``_dollyIn()``/``_dollyOut()`` with an explicit factor."""

        if not self.enable_zoom:
            return self.snapshot()
        self._scale *= max(EPS, float(scale))
        return self.snapshot()

    def dolly_in(self):
        return self.dolly(self.zoom_scale())

    def dolly_out(self):
        return self.dolly(1.0 / self.zoom_scale())

    def wheel(self, steps):
        """``_handleMouseWheel()``: positive ``steps`` zoom in, negative out."""

        steps = float(steps)
        if not steps or self.state is None:
            return self.snapshot()
        self._scale *= self.zoom_scale() ** steps
        self._zoom_to_cursor_pending = bool(self.zoom_to_cursor)
        return self.snapshot()

    def pan(self, delta_x, delta_y, viewport_height):
        """``_handleMouseMovePan()``: screen-space pan by a pointer delta."""

        if not self.enable_pan or viewport_height <= 0:
            return self.snapshot()
        if self.state is None:
            return None
        _, right, up = self._screen_basis()
        distance = self.distance()
        if distance <= EPS:
            return self.snapshot()
        target_distance = distance * math.tan(
            math.radians(self.view_angle) / 2.0)
        factor = (2.0 * target_distance / float(viewport_height)
                  * float(self.pan_speed))
        translation = _add(_scale(right, -float(delta_x) * factor),
                           _scale(up, float(delta_y) * factor))
        self._pan_offset = list(_add(tuple(self._pan_offset), translation))
        self._snap = None
        return self.snapshot()

    def action_for(self, button, modifiers=()):
        """The action a mouse button triggers for this instance."""

        return action_for(button, modifiers,
                          enable_rotate=self.enable_rotate,
                          enable_pan=self.enable_pan)

    # -- Frame update ------------------------------------------------------

    def update(self, elapsed_ms=16.0):
        """``OrbitControls.update()``: advance damped motion one frame.

        Returns ``(state, pending)``. ``pending`` is ``True`` while the
        damped motion or an axis snap still needs more frames, which is
        what keeps the render timer alive.
        """

        if self.state is None:
            return None, False
        if self._snap is not None:
            return self._advance_snap(elapsed_ms)
        radius, phi, theta = self._spherical()
        if self.auto_rotate:
            self._delta_theta -= self._auto_rotate_angle(elapsed_ms)
        damping = _clamp(float(self.damping_factor), 0.0, 1.0)
        if self.enable_damping:
            theta += self._delta_theta * damping
            phi += self._delta_phi * damping
        else:
            theta += self._delta_theta
            phi += self._delta_phi
        theta = _clamp(theta, self.min_azimuth_angle,
                       self.max_azimuth_angle)
        phi = _clamp(phi, self.min_polar_angle - EPS, self.max_polar_angle)
        # Spherical.makeSafe()
        phi = _clamp(phi, EPS, math.pi - EPS)
        target = tuple(self.state['focal_point'])
        if self.enable_damping:
            target = _add(target,
                          _scale(tuple(self._pan_offset), damping))
        else:
            target = _add(target, tuple(self._pan_offset))
        radius = _clamp(radius * self._scale,
                        self.min_distance, self.max_distance)
        if radius <= EPS:
            radius = max(EPS, self.min_distance or EPS)
        if self._zoom_to_cursor_pending:
            # three.js moves the target along the dolly direction by the
            # distance gained, so the camera stays put and the point under
            # the cursor keeps its screen position.
            self._zoom_to_cursor_pending = False
            offset = _sub(self.state['position'], target)
            gained = _length(offset) - radius
            direction = _normalize(offset)
            if abs(gained) > EPS and _length(direction) > EPS:
                target = _add(target, _scale(direction, gained))
        offset = self._offset_from(radius, phi, theta)
        position = _add(target, offset)
        self.state['focal_point'] = [float(v) for v in target]
        self.state['position'] = [float(v) for v in position]
        self.state['view_up'] = list(self._view_up(position, target))
        if self.enable_damping:
            decay = 1.0 - damping
            self._delta_theta *= decay
            self._delta_phi *= decay
            self._pan_offset = [value * decay
                                for value in self._pan_offset]
        else:
            self.cancel_pending()
        self._scale = 1.0
        pending = (abs(self._delta_theta) > 1e-5
                   or abs(self._delta_phi) > 1e-5
                   or any(abs(value) > 1e-5 for value in self._pan_offset)
                   or bool(self.auto_rotate))
        return self.snapshot(), pending

    def _auto_rotate_angle(self, elapsed_ms):
        """``getAutoRotationAngle()`` for a frame-based integration."""

        frames = max(0.0, float(elapsed_ms)) / (1000.0 / 60.0)
        return (_TWO_PI / 60.0 / 60.0 * float(self.auto_rotate_speed)
                * frames)

    def _view_up(self, position, target):
        """``object.lookAt(target)``: the up axis orthogonalized."""

        forward = _normalize(_sub(tuple(target), tuple(position)))
        up = _sub(self.up, _scale(forward, _dot(self.up, forward)))
        if _length(up) <= 1e-4:
            up = _sub(self.top_up,
                      _scale(forward, _dot(self.top_up, forward)))
        up = _normalize(up)
        if _length(up) <= EPS:
            return self.up
        return up

    # -- Axis views (three.js ViewHelper) ----------------------------------

    @property
    def is_snapping(self):
        return self._snap is not None

    def snap_to_axis(self, axis, positive=True, animate=True):
        """Align the camera with a world axis, like ``ViewHelper`` does."""

        axes = {
            'x': (1.0, 0.0, 0.0),
            'y': (0.0, 1.0, 0.0),
            'z': (0.0, 0.0, 1.0),
        }
        if axis not in axes:
            raise ValueError(f'Unsupported camera axis: {axis}')
        if self.state is None:
            return None
        direction = axes[axis]
        if not positive:
            direction = tuple(-value for value in direction)
        radius, phi, theta = self._spherical()
        polar = _clamp(_dot(direction, self.up), -1.0, 1.0)
        target_phi = _clamp(math.acos(polar), EPS, math.pi - EPS)
        horizontal = _sub(direction,
                          _scale(self.up, _dot(direction, self.up)))
        if _length(horizontal) <= 1e-6:
            target_theta = theta
        else:
            target_theta = math.atan2(_dot(horizontal, self.right),
                                      _dot(horizontal, self.forward))
        # Take the shortest way around the azimuth, like the tween does.
        while target_theta - theta > math.pi:
            target_theta -= _TWO_PI
        while theta - target_theta > math.pi:
            target_theta += _TWO_PI
        self.cancel_pending()
        if not animate:
            self._apply_snap(radius, target_phi, target_theta)
            return self.snapshot()
        self._snap = (radius, phi, theta, radius, target_phi, target_theta)
        self._snap_elapsed = 0.0
        return self.snapshot()

    def _apply_snap(self, radius, phi, theta):
        target = tuple(self.state['focal_point'])
        position = _add(target, self._offset_from(radius, phi, theta))
        self.state['position'] = [float(v) for v in position]
        self.state['view_up'] = list(self._view_up(position, target))

    def _advance_snap(self, elapsed_ms):
        (start_radius, start_phi, start_theta,
         radius, phi, theta) = self._snap
        self._snap_elapsed += max(0.0, float(elapsed_ms))
        duration = max(1.0, float(self.SNAP_DURATION_MS))
        progress = _clamp(self._snap_elapsed / duration, 0.0, 1.0)
        eased = progress * progress * (3.0 - 2.0 * progress)
        self._apply_snap(
            start_radius + (radius - start_radius) * eased,
            start_phi + (phi - start_phi) * eased,
            start_theta + (theta - start_theta) * eased)
        if progress >= 1.0:
            self._snap = None
            return self.snapshot(), False
        return self.snapshot(), True
