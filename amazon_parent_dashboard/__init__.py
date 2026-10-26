"""Unofficial client for https://parents.amazon.com (Amazon Kids Parent Dashboard).

Built from a browser HAR capture. Endpoints confirmed by the HAR:

    POST /ajax/set-offscreen-time      pause / resume devices
    PUT  /ajax/set-bonus-time          bonus time
    GET  /ajax/get-adjusted-time-limits?childDirectedId=...

NOT covered by the HAR (see TODOs below):
    * how to list children / map names -> directed IDs
    * the response shape of get-adjusted-time-limits
    * where the x-amzn-csrf token comes from (best-effort scrape of the home page)

Auth: the HAR had its cookies stripped, so this takes your logged-in
amazon.com cookies from the constructor or the AMAZON_PARENTS_COOKIES env var
(either a JSON object or a "name=value; name=value" header string).
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Union

import pytz
import requests

import config

BASE_URL = "https://parents.amazon.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
)

# Best-effort guesses for where the page embeds the CSRF token. Unverified.
_CSRF_PATTERNS = [
    re.compile(r'"csrfToken"\s*:\s*"([^"]+)"'),
    re.compile(r'"x-amzn-csrf"\s*:\s*"([^"]+)"', re.I),
    re.compile(r'<meta[^>]+name=["\']x-amzn-csrf["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)', re.I),
]


class ParentDashboardError(Exception):
    pass


class AuthError(ParentDashboardError):
    pass


def _parse_cookies(raw: Union[str, Dict[str, str]]) -> Dict[str, str]:
    if isinstance(raw, dict):
        return raw
    raw = raw.strip()
    if raw.startswith("{"):
        return json.loads(raw)
    cookies = {}
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


class ParentDashboard:
    def __init__(
            self,
            cookies: Optional[Union[str, Dict[str, str]]] = None,
            csrf_token: Optional[str] = 'placeholder',  # this will be populated automatically on a failed request.
            children: Optional[Dict[str, str]] = None,
            time_zone: str = "America/New_York",
    ):
        """
        :param cookies: logged-in amazon.com cookies (dict, JSON string, or
            "k=v; k=v" string). Falls back to $AMAZON_PARENTS_COOKIES.
        :param csrf_token: optional x-amzn-csrf value. If omitted, uses
            $AMAZON_PARENTS_CSRF_TOKEN or scrapes it from the home page.
        :param children: mapping of child name -> directed ID
            (e.g. {"Alex": "amzn1.account.AEZ5..."}). The IDs appear in the
            request bodies in the browser network tab.
        :param time_zone: IANA zone sent with bonus-time requests.
        """
        raw = cookies or os.environ.get("AMAZON_PARENTS_COOKIES")
        if not raw:
            raise AuthError(
                "No cookies. Pass cookies=... or set AMAZON_PARENTS_COOKIES."
            )
        self._session = requests.Session()
        self._session.headers.update(
            {
                "user-agent": USER_AGENT,
                "accept": "application/json, text/plain, */*",
                "origin": BASE_URL,
                "referer": BASE_URL + "/",
            }
        )
        self._session.cookies.update(_parse_cookies(raw))
        self._csrf = csrf_token or os.environ.get("AMAZON_PARENTS_CSRF_TOKEN")
        if self._csrf:
            self._session.cookies.set("ft-panda-csrf-token", self._csrf)
        self._children: Optional[Dict[str, str]] = dict(children) if children else None
        self._time_zone = time_zone

    # ------------------------------------------------------------------ http

    def discover_child_directed_ids(self) -> Dict[str, str]:
        """Discover child names and directed IDs from the dashboard HTML."""

        response = self._request(
            method='get',
            path=f"/",
        )
        response.raise_for_status()

        if "signin" in response.url.lower():
            raise AuthError("Cookies are expired or invalid.")

        # Extract the JSON string passed to JSON.parse(...).
        match = re.search(
            r"window\.__PREFETCHED_HOUSEHOLD\s*=\s*"
            r"JSON\.parse\('((?:\\.|[^'\\])*)'\)\s*;",
            response.text,
        )

        if not match:
            raise ParentDashboardError(
                "Could not find __PREFETCHED_HOUSEHOLD in the dashboard HTML."
            )

        # The JavaScript string contains escaped JSON. Decode the string
        # before parsing the resulting JSON object.
        household_json = json.loads(f'"{match.group(1)}"')
        household = json.loads(household_json)

        children = {
            member["firstName"]: member["directedId"]
            for member in household.get("members", [])
            if member.get("role") == "CHILD"
               and member.get("firstName")
               and member.get("directedId")
        }

        if not children:
            raise ParentDashboardError(
                "No children were found in the household data."
            )

        print("Discovered children:")
        for name, directed_id in children.items():
            print(f"  {name}: {directed_id}")

        print("\nUse this mapping in your configuration:")
        print("child_name_id_map = {")
        for name, directed_id in children.items():
            print(f'    "{name}": "{directed_id}",')
        print("}")

        self._children = children
        return children

    def _refresh_csrf(self) -> None:
        print('Refreshing CSRF token', BASE_URL)
        resp = self._session.get(BASE_URL + "/")
        print('resp.text=', resp.text)
        if "signin" in resp.url:
            raise AuthError("Cookies are expired or invalid (redirected to sign-in).")
        for pattern in _CSRF_PATTERNS:
            m = pattern.search(resp.text)
            if m:
                self._csrf = m.group(1)
                self._session.cookies.set("ft-panda-csrf-token", self._csrf)
                return
        raise AuthError(
            "Couldn't find the CSRF token in the home page. Copy the "
            "'x-amzn-csrf' request header from your browser and pass "
            "csrf_token=... instead."
        )

    def _request(self, method: str, path: str, *, params=None, body=None,
                 _retry: bool = True) -> requests.Response:
        print('_request=', method, path, params, body)
        if not self._csrf:
            self._refresh_csrf()


        resp = self._session.request(
            method,
            BASE_URL + path,
            params=params,
            json=body,
            headers={"x-amzn-csrf": self._csrf},
        )
        print('139 resp.text=', resp.text)
        if "signin" in resp.url:
            raise AuthError("Cookies are expired or invalid (redirected to sign-in).")
        if resp.status_code in (401, 403) and _retry and method.upper() in {
            "GET", "HEAD", "OPTIONS"
        }:
            previous_csrf = self._csrf
            try:
                print('_request response=', resp.status_code, resp.text)
                print('_request response.headers=', resp.headers)
                self._refresh_csrf()
            except AuthError as exc:
                raise AuthError(
                    f"{method} {path} -> {resp.status_code}; "
                    f"CSRF refresh failed: {exc}; response: {resp.text[:200]}"
                ) from exc
            if self._csrf != previous_csrf:
                return self._request(
                    method, path, params=params, body=body, _retry=False
                )
        if not resp.ok:
            print('160 _request response=', resp.status_code, resp.text)
            print('161 _request response.headers=', resp.headers)
            raise ParentDashboardError(
                f"{method} {path} -> {resp.status_code}: {resp.text[:200]}"
            )
        return resp

    # -------------------------------------------------------------- children

    def _load_children(self) -> Dict[str, str]:
        """Return child names mapped to their Amazon directed IDs."""
        if self._children is None:
            self.discover_child_directed_ids()
        return self._children

    def _child_id(self, child_name: str) -> str:
        children = self._load_children()
        for name, directed_id in children.items():
            if name.lower() == child_name.lower():
                return directed_id
        raise KeyError(f"Unknown child {child_name!r}; known: {list(children)}")

    # ------------------------------------------------------------ public API

    def get_children(self) -> List[str]:
        '''
        Return the names of the children
        :return:
        '''
        return list(self._load_children())

    def add_bonus_time(self, child_name: str, minutes: int) -> None:
        '''
        Add bonus time to the child

        Note: the endpoint is "set-bonus-time" and the UI row is labelled
        "update bonus time", so this may SET the bonus to `minutes` rather
        than add to an existing bonus. Verify by calling it twice.
        :param child_name:
        :param minutes:
        :return: bool response.ok
        '''
        if minutes <= 0:
            raise ValueError("minutes must be positive")
        resp = self._request(
            "PUT",
            "/ajax/set-bonus-time",
            body={
                "childDirectedId": self._child_id(child_name),
                "currentTime": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.%f"
                )[:-3] + "Z",
                "currentTimeZone": self._time_zone,
                "bonusTimeConfigurationType": "Duration",
                "bonusTimeDurationInMinutes": int(minutes),
            },
        )
        return resp.ok

    def get_time_limits(self, child_name: str) -> dict:
        """Raw JSON from /ajax/get-adjusted-time-limits (shape not in the HAR)."""
        resp = self._request(
            "GET",
            "/ajax/get-adjusted-time-limits",
            params={"childDirectedId": self._child_id(child_name)},
        )
        return resp.json()

    def get_max_screentime(self, child_name: str) -> Optional[int]:
        '''
        Get today's screentime limit in minutes, or None if the child has no
        time limit enabled for today.

        Response shape (confirmed from a capture): {"periodConfigurations":
        [{"type": "DayOfWeek", "name": "Monday", "enabled": bool,
        "timeLimits": {"contentTimeLimitsEnabled": bool,
        "contentTimeLimits": {...}}, ...}, ...]}
        :param child_name:
        :return:
        '''
        data = self.get_time_limits(child_name)
        weekday = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                   "Saturday", "Sunday"][datetime.now(pytz.timezone(self._time_zone)).weekday()]
        day = next(
            (p for p in data.get("periodConfigurations", [])
             if p.get("type") == "DayOfWeek" and p.get("name") == weekday),
            None,
        )
        if day is None:
            raise ParentDashboardError(f"No {weekday} entry in time-limit response")
        limits = day.get("timeLimits", {})
        if not day.get("enabled") or not limits.get("contentTimeLimitsEnabled"):
            return None
        content_time_limits = limits.get("contentTimeLimits", {})
        total_minutes = content_time_limits.get("ALL")
        if not isinstance(total_minutes, int) or isinstance(total_minutes, bool):
            raise ParentDashboardError(
                "Enabled content time limits are missing an integer 'ALL' value: "
                f"{content_time_limits!r}"
            )
        return total_minutes

    def pause_devices(self, child_name: str, minutes: int) -> None:
        '''
        Pause/lock the devices for the child

        The HAR only shows 60 minutes (the UI picks from a dropdown); other
        durations are untested.
        :param child_name:
        :param minutes:
        :return:
        '''
        if minutes <= 0:
            raise ValueError("minutes must be positive")
        self._request(
            "POST",
            "/ajax/set-offscreen-time",
            body={
                "directedIds": [self._child_id(child_name)],
                "expirationTimeInSeconds": int(minutes) * 60,
            },
        )

    def resume_devices(self, child_name: str):
        '''
        Resume/unlock the devices for the child
        :param child_name:
        :return:
        '''
        self._request(
            "POST",
            "/ajax/set-offscreen-time",
            body={
                "directedIds": [self._child_id(child_name)],
                "expirationTimeInSeconds": -1,
            },
        )


if __name__ == "__main__":
    import helper

    pd = ParentDashboard(
        cookies=helper.get_cookie_dict(config.cookie_string),
    )

    child_name = config.child_name
    max_time = pd.get_max_screentime(child_name)
    print(f'Max time for {child_name} is {max_time}')

    # is_success = pd.add_bonus_time(child_name, 15)
    # print(f'{"successfully" if is_success else "failed"} added bonus time to {child_name}')
