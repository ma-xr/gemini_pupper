"""Part 2: Walk. TODO 2 (check_move), TODO 3 (the turn and move tools), then TODO 4 (arc).

Read it top to bottom: check_move (yours) decides whether a move is allowed;
walk (finished: read it) does a move on the robot; turn, move and arc (yours)
are what Gemini calls, and they call walk.

    "walk forward" -> move (TODO 3) -> walk -> check_move (TODO 2) -> the job, later
"""

from __future__ import annotations

import math

from basics import PREPARES_MOVE
from part3_follow import prepare_to_move
from robot_api import FELL_MESSAGE, LIMITS, LLM_CMD_RATE, LOCOMOTION, LOCOMOTION_CONTROLLER, MoveLimits, Result, Robot, not_written, with_note  # noqa: F401
from tool_registry import Param, tool

# "Run" means at least this fast, in m/s (the locomotion policy switches to its
# running gait above about 0.5 m/s).
RUN_MIN_SPEED = 1.0
RUN_DEFAULT_SPEED = 1.2
# The default walking and turning speeds come from robot.speeds(): 0.4 m/s and
# 60 deg/s in locomotion mode, and a walking trick's own (the spider's are slower).


# ============================================================ what the robot does
def check_move(vx: float, vy: float, wz_deg: float, duration: float, limits: MoveLimits = LIMITS) -> str | None:
    """None if the robot may make this move, else the reason it may not.

    vx forward m/s, vy left m/s, wz_deg counter-clockwise deg/s, duration in s.

    TODO 2 (Part 2) ------------------------------------------------------------
    Gemini reads:        the string you return, word for word, as the tool's
                         reply. "too fast" leaves Gemini guessing; "too fast:
                         |vx|<=1.5 m/s" lets it retry at a speed that works.
    Must always be true: refuse anything too fast, too slow to move at all, a
                         duration that isn't more than 0 and at most
                         duration_max, and a move that would travel farther
                         than distance_max. Look at every field of MoveLimits
                         (robot/robot_api.py).
    Why here:            the tool descriptions ask Gemini to stay within the
                         limits; this makes sure of it.
    Tests check:         - good moves (even exactly at a limit) -> None
                         - each bad move -> a non-empty reason
                         - the reason contains the limit's number, as Python
                           prints it: vx_max "1.5", vy_max "0.5", wz_max
                           "114.0", duration_max "20.0", distance_max "7.0".
                           Passes: f"... at most {limits.duration_max} s"
                           Fails:  "too long", or "{limits.duration_max:.0f}" ("20")
    Test:                python3 lab/test.py todo2
    """
    # ========== TODO 2: YOUR CODE HERE ==========
    # Check the rules one at a time, and return the first reason you find.
    # Each reason says what was wrong AND the limit, e.g. f"too fast: limits are |vx|<={limits.vx_max} m/s, ..."
    # 1. Too fast: abs(vx) > limits.vx_max, or abs(vy) > limits.vy_max, or abs(wz_deg) > limits.wz_max.
    # 2. Too slow to move at all: vx, vy AND wz_deg are ALL below their minimums (vx_min, vy_min, wz_min).
    #    (Only all three: a turn in place has vx = vy = 0, and that is fine.)
    # 3. The duration must be more than 0 and at most limits.duration_max.
    # 4. Too far: speed * duration > limits.distance_max, where speed = (vx**2 + vy**2) ** 0.5.
    # 5. Nothing wrong: return None.
    if abs(vx) > limits.vx_max or abs(vy) > limits.vy_max or abs(wz_deg) > limits.wz_max:
        return (
            f"too fast: limits are |vx|<={limits.vx_max} m/s, |vy|<={limits.vy_max} m/s, "
            f"|wz|<={limits.wz_max} deg/s"
        )
    if abs(vx) < limits.vx_min and abs(vy) < limits.vy_min and abs(wz_deg) < limits.wz_min:
        return (
            f"too slow to move: use |vx|>={limits.vx_min} m/s, |vy|>={limits.vy_min} m/s, "
            f"or |wz|>={limits.wz_min} deg/s"
        )
    if duration <= 0 or duration > limits.duration_max:
        return f"bad duration {duration:g} s: must be more than 0 and at most {limits.duration_max} s"
    distance = (vx**2 + vy**2) ** 0.5 * duration
    if distance > limits.distance_max:
        return f"too far: {distance:.2f} m, one move goes at most {limits.distance_max} m"
    return None
    # ====================================


async def walk(robot: Robot, vx: float, vy: float, wz_deg: float, duration: float) -> Result:
    """Walk at (vx, vy, wz_deg) for duration seconds, then stand still (finished: read it).

    vx forward m/s, vy left m/s, wz_deg counter-clockwise deg/s. Your turn and
    move tools (TODO 3) call this. It is stand_up's shape (basics.py), with a
    loop in the job. Two things to notice:

    - Why send the speed again and again? The locomotion policy doesn't take
      "walk for 2 seconds"; it takes a speed, over and over. In between sits
      cmd_vel_mux (the node that lets the joystick win over Gemini), and it
      forgets a speed it hasn't heard for 0.5 s, so a crashed program can't
      leave Pupper walking forever. So the job sends it LLM_CMD_RATE (20) times
      a second for the whole walk, then a zero to stand still.
    - Why check robot.fallen three times? The robot may already have fallen when
      Gemini asks (1), may fall while this job waits in line (2), or while it
      walks (3). Each time, Gemini should hear FELL_MESSAGE, not "moved".
    - Who walks, and how fast? Usually the locomotion policy. But in a trick
      that walks in its own stance (the spider, Part 6), its own walking policy
      does, with its own limits (robot.speeds(): from its trick.yaml), so a move
      that is too fast for it is refused with its numbers. Both depend on the
      state Pupper will be in when the job runs: robot.state_after_queue, the
      same now-question as Part 5.
    """
    # NOW, before anything is queued:
    speeds = robot.speeds()  # the limits where Pupper will be (a walking trick has its own)
    refused = check_move(vx, vy, wz_deg, duration, speeds.limits)  # your TODO 2: is this move allowed?
    if refused:
        return Result(False, refused + speeds.where)  # Gemini hears why; nothing is queued
    note = await prepare_to_move(robot)  # get ready: does nothing until your TODO 5 (Part 3)
    state = robot.state_after_queue  # where Pupper will be when this job runs
    walker = robot.walking_controller(state)  # the locomotion policy, or a walking trick's own
    then = state if walker != LOCOMOTION_CONTROLLER else LOCOMOTION  # a walking trick stays in its stance
    if robot.fallen:  # (1)
        return Result(False, FELL_MESSAGE)

    async def job() -> Result:  # LATER, when the queue gets to it
        if robot.fallen:  # (2)
            return Result(False, FELL_MESSAGE)
        res = await robot.switch_to(walker)  # the policy that walks takes the legs (if it hasn't already)
        if not res.ok:
            return res
        end = robot.now() + duration
        while robot.now() < end - 1e-6:  # keep the mux input alive (1e-6: no extra step from rounding)
            if robot.fallen:  # (3)
                robot.send_speed(0, 0, 0)
                return Result(False, FELL_MESSAGE)
            robot.send_speed(vx, vy, wz_deg)
            await robot.sleep(1.0 / LLM_CMD_RATE)  # never time.sleep: it would freeze the server
        robot.send_speed(0, 0, 0)  # stand still
        return Result(True, f"moved {what} for {duration:.2f} s")  # the outcome (debug log)

    # What Gemini hears NOW: the job was accepted.
    what = f"vx={vx:g} vy={vy:g} wz={wz_deg:.3g}"  # 45.836623610465864 -> 45.8: Gemini reads this
    return with_note(note, await robot.queue(f"move {what} {duration:.3g}s", job, duration, then=then))


# ============================================================ what Gemini reads
# TODO 3: write turn first, then move: what Gemini reads (the description and every
# parameter's description) and their bodies.
#   - turn is the warm-up: one number to work out (which way), one call. It shows
#     you the whole path: Gemini's words -> numbers -> walk -> the robot.
#   - move is the real challenge: four parameters, defaults, and the "run" rule.
#   - Put the robot's real limits in the words: LIMITS.vx_max and the others
#     (robot/robot_api.py), RUN_MIN_SPEED, and the defaults. Add PREPARES_MOVE.
#   Tests check:
#   - each tool's description is 20+ characters, and every parameter is described
#   - turn left sends +wz, right -wz, about the angle asked for, with vx = vy = 0
#   - move's words contain the number LIMITS.vx_max ("1.5") and the word "follow"
#     (from PREPARES_MOVE). Passes: f"... up to {LIMITS.vx_max} m/s" + PREPARES_MOVE
#   - the move examples below send exactly those speeds
#   - move("right", run=True) says it walked: the reply says "walk".
#     Passes: "Sideways never runs; walking instead. move vx=0 vy=-0.4 ... queued"
#     Fails:  "move vx=0 vy=-0.4 ... queued" (Gemini then tells them it's running)
#   - a move check_move refuses comes back as a failure with check_move's reason
#   Test: python3 lab/test.py todo3  (turn is checked first, on its own)
# ========== TODO 3: YOUR CODE HERE ==========
@tool(
    "turn",
    "Turn in place to the left or right, without walking forward or sideways."
    " Use it for 'turn around', 'face left', or the sharp corners of a shape."
    " Pupper turns at about 60 deg/s, so 90 degrees takes 1.5 s." + PREPARES_MOVE,
    direction=Param("string", "Which way to turn: 'left' (counter-clockwise) or 'right' (clockwise).", enum=["left", "right"]),
    angle=Param(
        "number",
        "How far to turn, in degrees, 0-360. Default 90. Examples: 90 for a quarter turn"
        " or a square's corner, 120 for a triangle's corner, 180 to turn around, 360 for a full spin.",
        required=False,
    ),
)
async def turn_tool(robot: Robot, direction: str, angle: float = 90.0) -> Result:
    turn_speed = robot.speeds().turn  # 60 deg/s walking; a walking trick has its own
    wz_deg = turn_speed if direction == "left" else -turn_speed  # + is left (counter-clockwise)
    seconds = abs(angle) / turn_speed  # 90 deg at 60 deg/s takes 1.5 s
    return await walk(robot, 0.0, 0.0, wz_deg, seconds)


@tool(
    "move",
    "Walk or run in a straight line: forward, backward, or sideways (left, right), without turning."
    f" Walking speed is {LIMITS.vx_min}-{LIMITS.vx_max} m/s forward or backward (default 0.4 m/s),"
    f" and {LIMITS.vy_min}-{LIMITS.vy_max} m/s sideways. Running is forward or backward only, at"
    f" {RUN_MIN_SPEED}-{LIMITS.vx_max} m/s (default {RUN_DEFAULT_SPEED} m/s); sideways never runs."
    f" One move lasts at most {LIMITS.duration_max} s and goes at most {LIMITS.distance_max} m:"
    " split longer trips into several moves." + PREPARES_MOVE,
    direction=Param(
        "string", "Which way to go: 'forward', 'backward', 'left' or 'right' (sideways).",
        enum=["forward", "backward", "left", "right"],
    ),
    run=Param(
        "boolean",
        f"True to run (forward or backward only), at least {RUN_MIN_SPEED} m/s. Default false (walk).",
        required=False,
    ),
    speed=Param(
        "number",
        f"Speed in m/s. Default 0.4 walking, {RUN_DEFAULT_SPEED} running."
        f" Walk {LIMITS.vx_min}-{LIMITS.vx_max} forward/backward, {LIMITS.vy_min}-{LIMITS.vy_max} sideways;"
        f" run {RUN_MIN_SPEED}-{LIMITS.vx_max}.",
        required=False,
    ),
    duration=Param(
        "number",
        f"How long to move, in seconds, more than 0 and at most {LIMITS.duration_max}. Default 1.5."
        " Distance = speed x duration: 2 m at 0.4 m/s is 5 s; 1 m at 0.4 m/s is 2.5 s.",
        required=False,
    ),
)
async def move_tool(
    robot: Robot,
    direction: str,
    run: bool = False,
    speed: float | None = None,
    duration: float = 1.5,
) -> Result:
    sideways = direction in ("left", "right")
    # 1. One speed. Running is only forward or backward, and means at least RUN_MIN_SPEED.
    if run and not sideways:
        speed = RUN_DEFAULT_SPEED if speed is None else max(speed, RUN_MIN_SPEED)
    elif speed is None:
        speed = robot.speeds().walk  # 0.4 m/s walking; a walking trick has its own
    # 2. Split it by direction (+x forward, +y LEFT).
    vx, vy = {
        "forward": (speed, 0.0),
        "backward": (-speed, 0.0),
        "left": (0.0, speed),
        "right": (0.0, -speed),
    }[direction]
    # 3. If we changed what Gemini asked for, say so.
    note = "Sideways never runs; walking instead." if run and sideways else ""
    return with_note(note, await walk(robot, vx, vy, 0.0, duration))
# ====================================


# TODO 4: the arc tool: walk forward and turn at the same time, along part of a
# circle. turn sends only a turning speed and move only a straight one, so
# "go in a circle" was move, stop, turn, move. walk takes vx and wz_deg together,
# and the locomotion policy can do both at once: arc is how Gemini asks for it.
#   Now:                 work out vx and wz_deg from the radius and the speed, then
#                        walk (walk checks the move with check_move and queues it).
#   Gemini reads:        the words, to pick a radius the robot can do; then the
#                        reply: walk's, or why there is no arc (a negative radius,
#                        a speed of 0 or less, or too tight a circle for that
#                        speed), or check_move's reason (too long, too far).
#   Must always be true: an arc the robot can't do never moves it and never crashes.
#   Radius 0 is a sharp corner, not an error: Gemini plans a whole shape and sends
#   every call at once, and it often asks for corners as arc(radius=0). Refuse
#   them, and the sides still run: a rectangle becomes a straight line. So radius
#   0 turns in place (like turn), and the reply says so.
#   The math: around a circle of radius r (m) at speed v (m/s),
#     wz_deg = math.degrees(v / r)   (+ to the left, - to the right)
#     seconds = abs(angle) / abs(wz_deg)
#     e.g. 90 deg at 0.4 m/s around r = 0.5 m: wz = 45.8 deg/s for 1.96 s (0.79 m)
#   Put the real limits in the words: the robot turns at most LIMITS.wz_max deg/s,
#   so at speed v the radius must be at least v / math.radians(LIMITS.wz_max); one
#   arc goes at most LIMITS.distance_max m. Add PREPARES_MOVE.
#   Tests check:
#   - arc's description is 20+ characters, and every parameter is described
#   - its words contain LIMITS.distance_max ("7.0") and "follow" (from PREPARES_MOVE).
#     Passes: f"... One arc goes at most {LIMITS.distance_max} m." + PREPARES_MOVE
#     Fails:  "Walk in a curve." (Gemini then asks for circles the robot refuses)
#   - arc("left", angle=90, radius=0.5) sends vx = +0.4, vy = 0 and wz = +45.8 deg/s,
#     and turns about 90 deg; arc("right", ...) sends a negative wz, still forward
#   - arc("left", speed=0.6, radius=1.0) sends vx = 0.6 and wz = +34.4 deg/s
#   - arc("left", angle=90, radius=0) turns in place, left, about 90 deg, and the
#     reply says "place".
#     Passes: "Radius 0: turned in place (a sharp corner). move vx=0 ... queued"
#     Fails:  a crash (division by zero), or a refusal
#   - arc("left", radius=-1) is a failure that says "radius", and sends nothing
#   - arc("left", radius=0.1) is too tight (229 deg/s): a failure that says "radius"
#     and gives the smallest radius that works at that speed (0.2-0.3 m at 0.4 m/s).
#     Passes: "too tight: at 0.4 m/s the radius must be at least 0.25 m"
#     Fails:  check_move's "too fast: ... |wz|<=114.0 deg/s" (Gemini can't tell the
#             radius is the problem, and sends the same arc again), or a success
#             that quietly turned slower
#   Test: python3 lab/test.py todo4
# ========== TODO 4: YOUR CODE HERE ==========
@tool(
    "arc",
    "Walk forward and turn at the same time, around part of a circle: for curves, circles,"
    " U-turns, and going around someone. The tighter the circle, the faster Pupper must turn,"
    f" and it turns at most {LIMITS.wz_max} deg/s: so the radius must be at least"
    f" {0.4 / math.radians(LIMITS.wz_max):.2f} m at a walk (0.4 m/s) and"
    f" {RUN_DEFAULT_SPEED / math.radians(LIMITS.wz_max):.2f} m at a run ({RUN_DEFAULT_SPEED} m/s)."
    f" One arc goes at most {LIMITS.distance_max} m of path (a full circle of radius 1 m is 6.3 m)."
    " Not for straight sides or sharp corners (a square, a star): use move and turn for those,"
    " or radius 0 for a corner." + PREPARES_MOVE,
    direction=Param("string", "Which way to curve: 'left' (counter-clockwise) or 'right' (clockwise).", enum=["left", "right"]),
    angle=Param(
        "number",
        "How much of the circle to go around, in degrees (required). 90 a quarter circle,"
        " 180 a U-turn, 360 a full circle.",
    ),
    radius=Param(
        "number",
        "Radius of the circle in metres, default 0.5. 0 means a sharp corner (turn in place)."
        f" At least {0.4 / math.radians(LIMITS.wz_max):.2f} m at a walk.",
        required=False,
    ),
    speed=Param(
        "number",
        f"Forward speed in m/s, default 0.4, at most {LIMITS.vx_max}. Path length = radius x angle"
        " in radians: a full circle of radius 1 m is 6.3 m, 15.7 s at 0.4 m/s.",
        required=False,
    ),
)
async def arc_tool(
    robot: Robot,
    direction: str,
    angle: float,
    radius: float = 0.5,
    speed: float | None = None,
) -> Result:
    speeds = robot.speeds()  # the speeds and limits where Pupper will be
    if speed is None:
        speed = speeds.walk  # 0.4 m/s walking
    sign = 1 if direction == "left" else -1  # + is left (counter-clockwise)
    # 1. No circle to follow.
    if radius < 0:
        return Result(False, f"no arc: radius must be 0 m or more (got {radius:g} m)")
    if speed <= 0:
        return Result(False, f"no arc: speed must be more than 0 m/s (got {speed:g} m/s)")
    if radius == 0:  # a sharp corner: turn in place, like turn
        seconds = abs(angle) / speeds.turn
        return with_note("Radius 0: turned in place (a sharp corner).", await walk(robot, 0.0, 0.0, sign * speeds.turn, seconds))
    # 2. Too tight for this speed: say which radius works.
    wz_max = speeds.limits.wz_max
    if math.degrees(speed / radius) > wz_max:
        r = speed / math.radians(wz_max)
        return Result(False, f"too tight: at {speed:g} m/s the radius must be at least {math.ceil(r * 100) / 100} m")
    # 3-5. The math, then walk (which checks the move with check_move and queues it).
    wz_deg = sign * math.degrees(speed / radius)
    seconds = abs(angle) / abs(wz_deg)
    return await walk(robot, speed, 0.0, wz_deg, seconds)
# ====================================
