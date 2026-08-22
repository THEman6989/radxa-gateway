#!/usr/bin/env python3
"""Hold KDE suspend policy while stdin stays open.

This is the same PowerDevil InterruptSession-only mechanism used by the
ComfyUI queue guard. It blocks automatic suspend without blocking display
blanking. On release it resets Plasma's idle age once.
"""

from __future__ import annotations

import sys
import time

SERVICE = "org.kde.Solid.PowerManagement"
PATH = "/org/kde/Solid/PowerManagement/PolicyAgent"
POLICY_INTERFACE = "org.kde.Solid.PowerManagement.PolicyAgent"
SCREENSAVER_SERVICE = "org.freedesktop.ScreenSaver"
SCREENSAVER_PATH = "/ScreenSaver"
SCREENSAVER_INTERFACE = "org.freedesktop.ScreenSaver"
INTERRUPT_SESSION = 1
CHANGE_SCREEN_SETTINGS = 4
POWERDEVIL_ENFORCEMENT_DELAY_SECONDS = 5.5


def _screen_policy_unchanged(before: bool, after: bool) -> bool:
    """Never introduce a new display/screen-settings inhibition."""
    return before or not after


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: plasma_suspend_helper.py APPLICATION REASON", file=sys.stderr)
        return 2

    import dbus

    application, reason = sys.argv[1:]
    bus = dbus.SessionBus()
    proxy = bus.get_object(SERVICE, PATH)
    interface = dbus.Interface(proxy, dbus_interface=POLICY_INTERFACE)
    screen_blocked_before = bool(interface.HasInhibition(CHANGE_SCREEN_SETTINGS))
    cookie = interface.AddInhibition(
        dbus.UInt32(INTERRUPT_SESSION), application, reason
    )

    try:
        time.sleep(POWERDEVIL_ENFORCEMENT_DELAY_SECONDS)
        suspend_blocked = bool(interface.HasInhibition(INTERRUPT_SESSION))
        screen_blocked_after = bool(interface.HasInhibition(CHANGE_SCREEN_SETTINGS))
        if not suspend_blocked or not _screen_policy_unchanged(
            screen_blocked_before, screen_blocked_after
        ):
            print(
                "PowerDevil did not establish suspend-only inhibition "
                f"(suspend={suspend_blocked}, "
                f"screen_before={screen_blocked_before}, "
                f"screen_after={screen_blocked_after})",
                file=sys.stderr,
            )
            return 1

        print(int(cookie), flush=True)
        # The Radxa owns stdin. Newline means normal release; EOF is fail-safe.
        sys.stdin.readline()
        return 0
    finally:
        try:
            interface.ReleaseInhibition(cookie)
        except Exception:
            pass
        try:
            screen_proxy = bus.get_object(SCREENSAVER_SERVICE, SCREENSAVER_PATH)
            screen = dbus.Interface(
                screen_proxy, dbus_interface=SCREENSAVER_INTERFACE
            )
            screen.SimulateUserActivity()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
