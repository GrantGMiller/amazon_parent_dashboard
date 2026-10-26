Amazon Kids Parent Dashboard Client
====================================

Overview
--------

This module provides an unofficial Python client for the Amazon Kids Parent
Dashboard at https://parents.amazon.com.

It was developed from browser network captures and uses Parent Dashboard
endpoints that are not documented as a public API. Amazon may change these
endpoints, request formats, authentication requirements, or response formats
at any time.

The client currently supports:

* Retrieve the children names.
* Reading a child's time-limit configuration.
* Getting the current day's maximum screen-time limit.
* Adding bonus time for a child.
* Pausing and resuming a child's devices.

Authentication requires you to copy cookies from an already authenticated Amazon session. This
module does not implement an OAuth flow or guarantee automatic renewal of an
expired session.

Requirements/Dependencies
-------------------------

* Python 3.8 or newer.
* ``requests``
* ``pytz``


Authentication
--------------

The constructor accepts cookies in one of three formats:

#. A Python dictionary mapping cookie names to cookie values.
#. A JSON string representing that dictionary.
#. A cookie-header string containing semicolon-separated ``name=value`` pairs.

You can pass cookies directly::

    from parent_dashboard import ParentDashboard

    cookies = {
        "session-id": "YOUR_SESSION_ID",
        "session-token": "YOUR_SESSION_TOKEN",
        # Add the other cookies required by your current session.
    }

    dashboard = ParentDashboard(
        cookies=cookies,
    )

The example cookie names above are illustrative. Copy the required cookie
pairs from your own authenticated browser session; the exact set may vary.

**Keep cookies secret.** Treat them like passwords: do not
commit them to source control, include them in bug reports, or print them in
logs. Use environment variables or a secrets manager and restrict access to
the server account running the client.


Basic usage
-----------

Get configured child names::

    print(dashboard.get_children())

Read the raw time-limit response for a child::

    limits = dashboard.get_time_limits("Toby Flenderson")
    print(limits)

Get the current day's screen-time limit in minutes::

    max_minutes = dashboard.get_max_screentime("Dwight Schrute")
    if max_minutes is None:
        print("No enabled screen-time limit was found for today.")
    else:
        print(f"Today's limit: {max_minutes} minutes")

``get_max_screentime`` uses the configured time zone to choose the current
weekday. It returns ``None`` when the day's schedule or content-time limits
are disabled. Otherwise it expects the response to contain an integer value
under ``timeLimits.contentTimeLimits.ALL`` for the matching day.

Set bonus time::

    dashboard.add_bonus_time("Stanley Hudson", 15)

The current implementation sends a ``PUT`` request to
``/ajax/set-bonus-time`` with a duration of 15 minutes. **Despite the method
name, it is not yet confirmed whether the endpoint adds 15 minutes to an
existing bonus or sets the bonus duration to 15 minutes.** Verify this behavior
carefully in the Parent Dashboard before relying on repeated calls. Do not
assume calling it twice safely adds twice as much time.

Pause devices for a child for 60 minutes::

    dashboard.pause_devices("Andy Bernard", 60)

Resume devices for a child::

    dashboard.resume_devices("Lizzard King")



Time zone
---------

The constructor defaults to ``America/New_York``::

    dashboard = ParentDashboard(
        cookies=cookies,
        time_zone="America/New_York",
    )

The time zone is sent with bonus-time requests and is also used to determine
the weekday in ``get_max_screentime``. Use an appropriate IANA time-zone name
for your household.

Constructor reference
---------------------

``ParentDashboard(cookies=None, time_zone="America/New_York")``

``cookies``
    Cookie dictionary, JSON string, or semicolon-separated cookie-header
    string. If omitted, the client reads ``AMAZON_PARENTS_COOKIES``. If neither
    is set, construction raises ``AuthError``.

``time_zone``
    IANA time-zone string used for bonus-time requests and weekday selection.

Public methods
--------------

``get_children()``
    Return the configured child names as a list. This does not discover
    children from Amazon; it returns the names supplied in ``children``.

``get_time_limits(child_name)``
    Return the raw JSON response from the adjusted-time-limits endpoint.

``get_max_screentime(child_name)``
    Return today's enabled ``ALL`` content-time limit in minutes, or ``None``
    when the relevant limits are disabled. Raises ``ParentDashboardError`` if
    the expected response structure is missing.

``add_bonus_time(child_name, minutes)``
    Send a bonus-time configuration request. ``minutes`` must be positive.
    Whether the endpoint adds to or replaces the current bonus has not been
    confirmed.

``pause_devices(child_name, minutes)``
    Request that the child's devices be paused for the requested number of
    minutes. ``minutes`` must be positive.

``resume_devices(child_name)``
    Request that the child's devices be resumed.

Exceptions
----------

``ParentDashboardError``
    Base exception for client errors, unexpected responses, and HTTP failures.

``AuthError``
    Raised when cookies are missing/invalid, the request is redirected to
    sign-in, or CSRF-token retrieval fails.

``KeyError``
    Raised by child lookup when the requested name is not in the configured
    mapping.

``ValueError``
    Raised when a pause or bonus duration is not positive.

Running the module directly
---------------------------

The module's ``__main__`` example expects a local ``config`` module containing
at least these attributes::

    cookie_string
    child_name_id_map
    child_name

It also expects a ``helper`` module with a ``get_cookie_dict`` function.
The example reads the selected child's maximum screen-time limit. Adapt these
names to your own configuration, and do not commit real authentication
credentials to a repository.

Automation and server deployment
--------------------------------

For a scheduled job, keep your rule logic separate from the client. For
example::

    from parent_dashboard import ParentDashboard

    dashboard = ParentDashboard(
        time_zone="America/New_York",
    )

    child_name = "Bobby D. Tables"
    max_minutes = dashboard.get_max_screentime(child_name)

    # Insert your own decision logic here.
    # Only call add_bonus_time after verifying the endpoint's semantics.

Run the script using a scheduler such as ``systemd`` or cron. In production:

* Store credentials in environment variables or a secrets manager.
* Run the job as a dedicated, unprivileged Linux user.
* Log decisions and outcomes, but never log cookies, CSRF tokens, or full
  authentication headers.
* Handle ``AuthError`` and notify the administrator when manual sign-in is
  required.
* Add persistent state or an idempotency record so a retried job does not
  accidentally award the same bonus more than once.
* Test with a small, controlled bonus and verify the result in the Parent
  Dashboard before enabling automatic awards.
* Do not assume that a browser session will remain valid indefinitely. This
  client does not implement supported OAuth refresh-token handling.

Example error handling::

    from parent_dashboard import AuthError, ParentDashboardError

    try:
        dashboard.add_bonus_time("Kevin Malone", 10)
    except AuthError as exc:
        # Notify yourself that the session needs attention.
        print(f"Authentication needs attention: {exc}")
    except ParentDashboardError as exc:
        print(f"Parent Dashboard request failed: {exc}")

Troubleshooting
---------------

**``AuthError: No cookies``**

Pass ``cookies=...`` or set ``AMAZON_PARENTS_COOKIES``.

**Redirected to sign-in / invalid cookies**

The session may have expired or been revoked. Obtain a fresh authenticated
session and update the configured cookies. The client cannot guarantee
automatic reauthentication.

**HTTP 401 or 403**

The session may be invalid or the endpoint may
require a different request format. For eligible read-only requests, the
client attempts one CSRF refresh and retry. It does not automatically retry
state-changing requests.

**Unexpected time-limit response**

Inspect the raw result of ``get_time_limits(child_name)``. The parser in
``get_max_screentime`` expects ``periodConfigurations`` with a matching
``DayOfWeek`` entry and an integer ``ALL`` value.

Limitations and disclaimer
--------------------------

This is an unofficial client built from browser network captures. It is not
an Amazon-supported SDK, and the endpoints are not guaranteed to remain
available or compatible. The client does not currently discover child IDs,
guarantee session renewal, or verify whether setting bonus time is additive.
Use it only with an account and devices you are authorized to manage, and
verify changes in the Parent Dashboard.
