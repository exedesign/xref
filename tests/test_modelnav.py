"""Tests for the three.js style OrbitControls port."""

import math

import pytest

from xref import modelnav


def make_state(up_axis='Z', radius=5.0, phi=math.radians(60.0),
               theta=math.radians(45.0), target=(0.0, 0.0, 0.0),
               view_angle=45.0):
    controls = modelnav.OrbitControls(up_axis=up_axis)
    offset = controls._offset_from(radius, phi, theta)
    position = [target[index] + offset[index] for index in range(3)]
    return {
        'position': position,
        'focal_point': [float(v) for v in target],
        'view_up': list(controls.up),
        'view_angle': view_angle,
    }


def make_controls(up_axis='Z', **settings):
    controls = modelnav.OrbitControls(up_axis=up_axis, **settings)
    controls.state = make_state(up_axis=up_axis)
    return controls


def distance(state):
    return math.sqrt(sum(
        (state['position'][index] - state['focal_point'][index]) ** 2
        for index in range(3)))


def settle(controls, limit=600):
    for _ in range(limit):
        state, pending = controls.update()
        if not pending:
            return state
    raise AssertionError('controls never settled')


# -- Defaults and bindings --------------------------------------------------

def test_defaults_match_three_js():
    controls = modelnav.OrbitControls()

    assert controls.enable_damping is True
    assert controls.damping_factor == 0.05
    assert controls.rotate_speed == 1.0
    assert controls.zoom_speed == 1.0
    assert controls.pan_speed == 1.0
    assert controls.screen_space_panning is True
    assert controls.zoom_to_cursor is False
    assert controls.auto_rotate is False
    assert controls.min_distance == 0.0
    assert controls.max_distance == math.inf
    assert controls.min_polar_angle == 0.0
    assert controls.max_polar_angle == math.pi


def test_mouse_buttons_match_three_js():
    assert modelnav.OrbitControls.mouse_buttons == {
        'left': modelnav.ROTATE,
        'middle': modelnav.DOLLY,
        'right': modelnav.PAN,
    }


@pytest.mark.parametrize('modifiers, expected', [
    ((), modelnav.ROTATE),
    (('ctrl',), modelnav.PAN),
    (('meta',), modelnav.PAN),
    (('shift',), modelnav.PAN),
])
def test_left_button_swaps_to_pan_with_modifiers(modifiers, expected):
    controls = make_controls()

    assert controls.action_for('left', modifiers) == expected


@pytest.mark.parametrize('modifiers, expected', [
    ((), modelnav.PAN),
    (('ctrl',), modelnav.ROTATE),
    (('shift',), modelnav.ROTATE),
])
def test_right_button_swaps_to_rotate_with_modifiers(modifiers, expected):
    controls = make_controls()

    assert controls.action_for('right', modifiers) == expected


@pytest.mark.parametrize('modifiers', [(), ('ctrl',), ('shift',)])
def test_middle_button_never_swaps(modifiers):
    controls = make_controls()

    assert controls.action_for('middle', modifiers) == modelnav.DOLLY


def test_unknown_button_has_no_action():
    controls = make_controls()

    assert controls.action_for('back') is None


def test_disabled_actions_are_not_swapped():
    controls = make_controls(enable_pan=False)

    assert controls.action_for('left', ('shift',)) is None


# -- Orbit ------------------------------------------------------------------

@pytest.mark.parametrize('up_axis', ['X', 'Y', 'Z'])
def test_rotate_keeps_the_distance_and_orbits(up_axis):
    controls = make_controls(up_axis)
    controls.enable_damping = False
    before = controls.snapshot()

    controls.rotate(40, 0, 400)
    after, _ = controls.update()

    assert distance(after) == pytest.approx(distance(before))
    assert after['position'] != pytest.approx(before['position'])
    # Without damping the whole delta is consumed in one update().
    assert controls._delta_theta == pytest.approx(0.0, abs=1e-12)


def test_rotate_uses_the_viewport_height_for_both_axes():
    controls = make_controls()
    controls.enable_damping = False

    controls.rotate(0, 100, 400)

    assert controls._delta_phi == pytest.approx(-2 * math.pi * 100 / 400)


def test_rotate_moves_the_camera_but_keeps_the_target():
    controls = make_controls()
    controls.enable_damping = False
    target = list(controls.target)

    controls.rotate(60, 30, 300)
    after, _ = controls.update()

    assert after['focal_point'] == pytest.approx(target)


def test_damping_moves_a_fraction_of_the_delta_each_frame():
    controls = make_controls()
    before = controls.snapshot()
    controls.rotate(120, 0, 300)

    first, pending = controls.update()

    assert pending
    # Only damping_factor of the delta is applied on the first frame.
    moved = (first['position'][0] - before['position'][0]) ** 2 \
        + (first['position'][1] - before['position'][1]) ** 2
    assert moved > 0
    assert controls._delta_theta == pytest.approx(
        -2 * math.pi * 120 / 300 * (1 - 0.05))


def test_damping_settles_and_stops_pending():
    controls = make_controls()
    controls.rotate(120, 60, 300)

    _first, pending = controls.update()
    assert pending

    final = settle(controls)

    assert controls._delta_theta == pytest.approx(0.0, abs=1e-5)
    assert controls._delta_phi == pytest.approx(0.0, abs=1e-5)
    assert distance(final) == pytest.approx(5.0, rel=1e-6)


def test_polar_angle_is_clamped_away_from_the_poles():
    controls = make_controls()
    controls.enable_damping = False

    controls.rotate(0, 4000, 200)
    state, _ = controls.update()

    _radius, phi, _theta = controls._spherical()
    assert phi >= modelnav.EPS
    assert phi <= math.pi - modelnav.EPS
    # Looking straight down the up axis keeps a usable up vector.
    assert state['view_up'] == pytest.approx([0.0, 1.0, 0.0], abs=1e-4)


def test_azimuth_limits_are_respected():
    controls = make_controls(min_azimuth_angle=0.0, max_azimuth_angle=0.0)
    controls.enable_damping = False
    controls.rotate(200, 0, 400)

    controls.update()

    _radius, _phi, theta = controls._spherical()
    assert theta == pytest.approx(0.0, abs=1e-9)


# -- Dolly ------------------------------------------------------------------

def test_dolly_in_and_out_use_the_three_js_zoom_scale():
    controls = make_controls()

    controls.dolly_in()
    state, _ = controls.update()
    assert distance(state) == pytest.approx(5.0 * 0.95)

    controls.dolly_out()
    state, _ = controls.update()
    assert distance(state) == pytest.approx(5.0)


def test_zoom_scale_follows_zoom_speed():
    controls = make_controls(zoom_speed=2.0)

    assert controls.zoom_scale() == pytest.approx(0.95 ** 2)


def test_wheel_steps_accumulate():
    controls = make_controls()

    controls.wheel(3)
    state, _ = controls.update()

    assert distance(state) == pytest.approx(5.0 * 0.95 ** 3)


def test_wheel_backwards_zooms_out():
    controls = make_controls()

    controls.wheel(-2)
    state, _ = controls.update()

    assert distance(state) == pytest.approx(5.0 * (1 / 0.95 ** 2))


def test_min_and_max_distance_clamp_the_dolly():
    controls = make_controls(min_distance=2.0, max_distance=6.0)

    for _ in range(20):
        controls.dolly_in()
        controls.update()
    assert distance(controls.snapshot()) == pytest.approx(2.0)

    for _ in range(40):
        controls.dolly_out()
        controls.update()
    assert distance(controls.snapshot()) == pytest.approx(6.0)


def test_zoom_to_cursor_pulls_the_target_towards_the_camera():
    controls = make_controls(zoom_to_cursor=True)
    target_before = list(controls.target)

    controls.wheel(4)
    state, _ = controls.update()

    assert state['focal_point'] != pytest.approx(target_before)
    assert distance(state) == pytest.approx(5.0 * 0.95 ** 4)


def test_zoom_to_cursor_off_keeps_the_target():
    controls = make_controls()
    target_before = list(controls.target)

    controls.wheel(4)
    state, _ = controls.update()

    assert state['focal_point'] == pytest.approx(target_before)


# -- Pan --------------------------------------------------------------------

def test_pan_moves_the_target_in_screen_space():
    controls = make_controls()
    controls.enable_damping = False
    height = 500.0
    distance_before = 5.0
    _forward, right, up = controls._screen_basis()

    controls.pan(100, 0, height)
    state, _ = controls.update()

    # Three.js: 2 * distance * tan(fov/2) / clientHeight per pixel.
    factor = 2 * distance_before * math.tan(math.radians(45.0) / 2) / height
    expected = [-100 * factor * right[index]
                + 0 * factor * up[index] for index in range(3)]
    assert state['focal_point'] == pytest.approx(expected)
    assert distance(state) == pytest.approx(distance_before)


def test_pan_is_rigid_and_damped():
    controls = make_controls()
    before = controls.snapshot()

    controls.pan(0, 60, 400)
    first, pending = controls.update()

    assert pending
    moved = [first['position'][index] - before['position'][index]
             for index in range(3)]
    target_moved = [
        first['focal_point'][index] - before['focal_point'][index]
        for index in range(3)]
    assert target_moved == pytest.approx(moved)

    final = settle(controls)
    assert distance(final) == pytest.approx(distance(before))


def test_pan_can_be_disabled():
    controls = make_controls(enable_pan=False)
    before = controls.snapshot()

    controls.pan(100, 100, 400)
    state, _ = controls.update()

    assert state['focal_point'] == pytest.approx(before['focal_point'])


# -- Axis snaps (three.js ViewHelper) ---------------------------------------

@pytest.mark.parametrize('up_axis, axis, positive, expected_offset, '
                         'expected_up', [
                             ('Z', 'z', True, (0, 0, 5), (0, 1, 0)),
                             ('Z', 'z', False, (0, 0, -5), (0, 1, 0)),
                             ('Z', 'x', True, (5, 0, 0), (0, 0, 1)),
                             ('Z', 'y', False, (0, -5, 0), (0, 0, 1)),
                             ('Y', 'y', True, (0, 5, 0), (0, 0, 1)),
                             ('Y', 'x', True, (5, 0, 0), (0, 1, 0)),
                             ('X', 'x', True, (5, 0, 0), (0, 1, 0)),
                             ('X', 'z', True, (0, 0, 5), (1, 0, 0)),
                         ])
def test_snap_to_axis_aligns_and_keeps_the_distance(
        up_axis, axis, positive, expected_offset, expected_up):
    controls = make_controls(up_axis)

    controls.snap_to_axis(axis, positive)
    state = settle(controls)

    assert distance(state) == pytest.approx(5.0)
    offset = [state['position'][index] - state['focal_point'][index]
              for index in range(3)]
    # The polar angle is kept EPS away from the pole (Spherical.makeSafe),
    # which leaves a sub-micron residual that is invisible on screen.
    assert offset == pytest.approx(list(expected_offset), abs=1e-4)
    assert state['view_up'] == pytest.approx(list(expected_up), abs=1e-4)


def test_snap_without_animation_is_instant():
    controls = make_controls()

    state = controls.snap_to_axis('x', True, animate=False)

    assert not controls.is_snapping
    assert state['position'][0] == pytest.approx(5.0, abs=1e-6)


def test_snap_reports_pending_until_it_finishes():
    controls = make_controls()

    controls.snap_to_axis('x', True)
    assert controls.is_snapping
    assert controls.update()[1] is True

    settle(controls)
    assert not controls.is_snapping


def test_snap_takes_the_short_way_around():
    controls = modelnav.OrbitControls(up_axis='Z')
    controls.state = make_state(theta=math.radians(-170.0))
    controls.enable_damping = False

    controls.snap_to_axis('x', True)
    controls.update()

    # +X sits at +90 degrees; from -170 the snap must swing through -180.
    _radius, _phi, theta = controls._spherical()
    assert -math.pi - 1e-6 <= theta <= math.radians(-90.0) + 1e-6


def test_snap_rejects_unknown_axes():
    controls = make_controls()

    with pytest.raises(ValueError, match='Unsupported camera axis'):
        controls.snap_to_axis('w', True)


# -- Construction ------------------------------------------------------------

def test_unknown_up_axis_is_rejected():
    with pytest.raises(ValueError, match='Unsupported model up axis'):
        modelnav.OrbitControls(up_axis='Q')


def test_unknown_setting_is_rejected():
    with pytest.raises(AttributeError, match='Unknown OrbitControls setting'):
        modelnav.OrbitControls(up_any='Q')


def test_settings_are_applied():
    controls = modelnav.OrbitControls(
        damping_factor=0.1, zoom_speed=2.0, min_distance=1.0)

    assert controls.damping_factor == 0.1
    assert controls.zoom_speed == 2.0
    assert controls.min_distance == 1.0


def test_snapshot_and_restore_round_trip():
    controls = make_controls()
    snapshot = controls.snapshot()

    controls.rotate(90, 45, 300)
    settle(controls)
    controls.restore(snapshot)

    assert controls.snapshot() == snapshot


def test_update_without_state_is_safe():
    controls = modelnav.OrbitControls()

    assert controls.update() == (None, False)
    assert controls.snapshot() is None
