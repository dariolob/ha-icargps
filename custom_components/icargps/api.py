"""API client for the icargps.net tracking platform.

Two channels are used:

* **Telemetry** — the platform's own web site (icargps.net, ASP.NET
  WebForms + ASMX JSON endpoints, session-gated by a classic postback
  login). Used for position, battery, status and alarm history.
* **Commands** — the ``openapiv3.asmx`` app API (the same one the
  "iCar GPS" Android app talks to). Discovered via the tenant's
  ``/getapp.aspx`` endpoint (currently ``https://app2.gps18.com/openapiv3.asmx``).
  The old web endpoints (SendCommand / SendCommandByPhone) accept
  commands for the IK122T Pro (model 504) but never deliver them.

  ⚠️ Delivery contract (verified live on 2026-11-10, SLXKLS physically
  executed by the collar 3/3): the ``SendCommandByAPP`` request must
  contain EXACTLY the six form fields the app sends — ``Key``, ``SN``,
  ``DeviceID``, ``CommandType``, ``Model``, ``Paramter``. Adding ANY
  extra field (e.g. ``Language`` or ``Key2018``) makes the platform
  queue the command and even ACK it ("Success!") while NEVER delivering
  it to the collar. The "Success!" ACK itself is not proof of execution
  either: the server can fabricate it for undelivered commands. Only
  physical execution on the device counts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import (
    APP_LOGINAPP,
    APP_KEY,
    APP_LOGIN_TYPE,
    DEVICES_URL,
    EXCEPTIONS_URL,
    GETAPP_URL,
    LOGIN_URL,
    OPENAPI_BASE_FALLBACK,
)

_LOGGER = logging.getLogger(__name__)

_VIEWSTATE_RE = re.compile(r'name="__VIEWSTATE"[^>]*value="([^"]*)"')
_GENERATOR_RE = re.compile(r'name="__VIEWSTATEGENERATOR"[^>]*value="([^"]*)"')
_EVENTVAL_RE = re.compile(r'name="__EVENTVALIDATION"[^>]*value="([^"]*)"')
_MONITOR_RE = re.compile(r"location\.href='(/Monitor\.aspx[^']*)'")
_USERID_RE = re.compile(r"map\.aspx\?id=(\d+)")
_DEVICEID_RE = re.compile(r"deviceID=(\d+)")
_PSEUDO_KEY_RE = re.compile(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)")
_ASMX_STRING_RE = re.compile(r"<string[^>]*>(.*)</string>", re.S)


class ICarAuthError(Exception):
    """Authentication failed (wrong credentials or expired session)."""


class ICarApiError(Exception):
    """Unexpected platform response."""


def parse_d_payload(payload_text: str) -> dict[str, Any] | None:
    """Parse the platform's ``{"d": "{...}"}`` pseudo-JSON envelope.

    The inner string is JSON-like but with unquoted keys; quoting them makes
    it valid JSON. Returns ``None`` when ``d`` is empty (lost session).
    """
    try:
        outer = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise ICarApiError(f"Invalid response envelope: {exc}") from exc
    inner = outer.get("d", "") if isinstance(outer, dict) else ""
    if isinstance(inner, str) and not inner:
        return None
    if not isinstance(inner, str):
        # Some endpoints (SendCommand*) return a bare integer in "d".
        return inner
    fixed = _PSEUDO_KEY_RE.sub(lambda m: f'{m.group(1)}"{m.group(2)}"{m.group(3)}', inner)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError as exc:
        raise ICarApiError(f"Cannot parse payload: {exc}") from exc


def _q(value: Any) -> str:
    """Escape a value for the platform's single-quoted pseudo-JSON fields."""
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


# Legacy numeric result codes of the web SendCommand endpoint (kept for the
# generic service; the app channel no longer uses them).
SEND_RESULT_CODES: dict[int, str] = {
    -1: "Command null",
    1: "Target not exist",
    2: "Device offline",
    3: "Failed to send command",
    4: "Command saved (queued, delivered on next device connection)",
    5: "Failed to send command",
    6: "Command has been saved",
    -99: "Wrong password",
}


@dataclass
class SendResult:
    """Outcome of a command."""

    command: str
    code: int
    queued: bool = False  # accepted by the platform command queue
    saved: bool = False  # accepted for delivery on next device connection
    message: str = ""
    response_text: str | None = None
    command_id: int | None = None


class ICarApi:
    """Client for the icargps.net web API (telemetry) and the
    Yiwen openapiv3 app API (commands)."""

    def __init__(
        self,
        session: ClientSession,
        sn: str,
        password: str,
        tz: str = "1:00",
    ) -> None:
        self._session = session
        self.sn = sn
        self._password = password
        self.tz = tz
        self.user_id: int | None = None
        self.device_id: int | None = None
        self.model: int | None = None
        self.device_name: str | None = None
        # App (openapiv3) channel state
        self._openapi_base: str | None = None
        self._app_key2018: str | None = None
        self.app_device_id: int | None = None

    # ------------------------------------------------------------------
    # Web platform (telemetry) helpers
    # ------------------------------------------------------------------

    @property
    def _asmx_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "http://www.icargps.net/map.aspx",
        }

    async def _asmx_call(self, url: str, body: str) -> dict[str, Any] | None:
        async with self._session.post(url, data=body, headers=self._asmx_headers) as resp:
            text = await resp.text()
        return parse_d_payload(text)

    # ------------------------------------------------------------------
    # App (openapiv3) helpers
    # ------------------------------------------------------------------

    async def _openapi_url(self) -> str:
        """Return the tenant's openapiv3 base URL, discovering it once."""
        if self._openapi_base:
            return self._openapi_base
        base = OPENAPI_BASE_FALLBACK
        try:
            async with self._session.get(GETAPP_URL, timeout=10) as resp:
                text = (await resp.text()).strip()
            if text.startswith("http") and "openapiv3" in text:
                base = text if text.endswith("/") else text + "/"
                _LOGGER.debug("openapiv3 URL discovered via getapp.aspx: %s", base)
            else:
                _LOGGER.debug("getapp.aspx unexpected payload %r, using fallback", text[:80])
        except (ClientError, asyncio.TimeoutError) as exc:
            _LOGGER.debug("getapp.aspx discovery failed (%s), using fallback", exc)
        self._openapi_base = base
        return base

    async def _openapi_post(self, method: str, fields: dict[str, str]) -> str:
        """POST form-urlencoded fields to an openapiv3 method.

        Returns the text inside the ASMX ``<string>`` envelope.
        """
        url = f"{await self._openapi_url()}{method}"
        async with self._session.post(
            url,
            data=fields,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "okhttp/3.12.0",
            },
        ) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise ICarApiError(f"openapiv3 {method} returned HTTP {resp.status}: {text[:120]}")
        m = _ASMX_STRING_RE.search(text)
        if not m:
            raise ICarApiError(f"openapiv3 {method} returned unexpected envelope: {text[:120]}")
        return m.group(1)

    @staticmethod
    def _parse_openapi_json(raw: str) -> dict[str, Any]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ICarApiError(f"openapiv3 returned invalid JSON: {raw[:120]}") from exc
        if not isinstance(data, dict):
            raise ICarApiError(f"openapiv3 returned unexpected payload: {raw[:120]}")
        return data

    async def async_app_login(self) -> None:
        """Login against the openapiv3 app API (as the mobile app does).

        Stores the per-device session key (``key2018``) and the app-side
        device id.  Raises ICarAuthError on wrong credentials / key.
        """
        raw = await self._openapi_post(
            "Login",
            {
                "Key": APP_KEY,
                "Name": self.sn,
                "Pass": self._password,
                "LoginType": str(APP_LOGIN_TYPE),
                "LoginAPP": APP_LOGINAPP,
                "GMT": self.tz,
            },
        )
        data = self._parse_openapi_json(raw)
        state = str(data.get("state"))
        if state != "0" or not (data.get("deviceInfo") or {}):
            raise ICarAuthError(f"App-API login failed (state {state})")
        info = data["deviceInfo"]
        self._app_key2018 = info.get("key2018")
        try:
            self.app_device_id = int(info.get("deviceID"))
        except (TypeError, ValueError) as exc:
            raise ICarApiError("App-API login response has no deviceID") from exc
        if not self._app_key2018:
            raise ICarAuthError("App-API login response has no key2018")
        _LOGGER.debug("App-API login ok (app device id %s)", self.app_device_id)

    async def async_get_tracking(self) -> dict[str, Any]:
        """Fetch the live position via the openapiv3 GetTracking call."""
        if not self._app_key2018:
            await self.async_app_login()
        raw = await self._openapi_post(
            "GetTracking",
            {
                "Key": self._app_key2018 or "",
                "DeviceID": str(self.app_device_id),
                "MapType": "Google",
                "TimeZones": self.tz,
                "Model": str(self.model or 0),
                "Language": "en_US",
            },
        )
        return self._parse_openapi_json(raw)

    # ------------------------------------------------------------------
    # Authentication (web platform)
    # ------------------------------------------------------------------

    async def async_login(self) -> None:
        """Log in and discover user_id / device_id for this device SN."""
        async with self._session.get(LOGIN_URL) as resp:
            html = await resp.text()
        viewstate = _VIEWSTATE_RE.search(html)
        generator = _GENERATOR_RE.search(html)
        eventval = _EVENTVAL_RE.search(html)
        if not viewstate or not eventval:
            raise ICarApiError("Cannot parse login page (platform layout changed?)")

        form = {
            "__VIEWSTATE": viewstate.group(1),
            "__VIEWSTATEGENERATOR": generator.group(1) if generator else "",
            "__EVENTVALIDATION": eventval.group(1),
            "LType": "1",
            "txtImeiNo": self.sn,
            "txtImeiPassword": self._password,
            "hidYiwenGUID2": "",
            "btnLogin": "Login",
        }
        async with self._session.post(LOGIN_URL, data=form) as resp:
            html = await resp.text()
        # Success = the page redirects to /Monitor.aspx. Do NOT test for
        # "loginFaildN()": those strings appear in EVERY login response,
        # including successful ones (the login page re-renders with its JS
        # function definitions "function loginFaildN() { ... }"). Only the
        # invocation "loginFaildN()" without the "function " prefix means
        # the credentials were rejected.
        monitor = _MONITOR_RE.search(html)
        if monitor is None:
            if re.search(r"(?<!function )loginFaild", html):
                raise ICarAuthError("Wrong ID No./password")
            raise ICarApiError("Unexpected login response (no redirect found)")

        async with self._session.get(f"http://www.icargps.net{monitor.group(1)}") as resp:
            html = await resp.text()
        user = _USERID_RE.search(html)
        device = _DEVICEID_RE.search(html)
        if not user or not device:
            raise ICarApiError("Cannot discover user/device id from monitor page")
        self.user_id = int(user.group(1))
        self.device_id = int(device.group(1))

        # First full fetch discovers model and device name.
        dev = await self.async_get_device(first=True)
        try:
            self.model = int(dev.get("model") or 0) or None
        except (TypeError, ValueError):
            self.model = None
        self.device_name = dev.get("name") or f"ICAR {self.sn}"

    # ------------------------------------------------------------------
    # Telemetry (web platform)
    # ------------------------------------------------------------------

    async def async_get_device(self, first: bool = False) -> dict[str, Any]:
        """Fetch the device record (position, status, data context)."""
        if self.user_id is None or self.device_id is None:
            raise ICarAuthError("Not logged in")
        body = (
            f"{{UserID:{self.user_id},isFirst:{'true' if first else 'false'},"
            f"TimeZones:'{_q(self.tz)}',DeviceID:{self.device_id}}}"
        )
        data = await self._asmx_call(DEVICES_URL, body)
        if data is None:
            raise ICarAuthError("Session expired")
        devices = data.get("devices") or []
        for dev in devices:
            try:
                if int(dev.get("id", -1)) == self.device_id:
                    return dev
            except (TypeError, ValueError):
                continue
        if devices:
            return devices[0]
        raise ICarApiError("Device not found on platform")

    async def async_get_exceptions(self, watermark: str) -> tuple[list[dict[str, Any]], str]:
        """Fetch alarms newer than the watermark.

        Returns ``(alarms, new_watermark)``. The watermark round-trips in
        server-side UTC; pass back the returned value verbatim.
        """
        if self.device_id is None:
            raise ICarAuthError("Not logged in")
        body = (
            f"{{DeviceID:{self.device_id},LastCreated:'{_q(watermark)}',"
            f"TimeZones:'{_q(self.tz)}'}}"
        )
        data = await self._asmx_call(EXCEPTIONS_URL, body)
        if data is None:
            raise ICarAuthError("Session expired")
        alarms = data.get("ems") or []
        new_watermark = data.get("lastCreated") or watermark
        return alarms, new_watermark

    # ------------------------------------------------------------------
    # Commands (openapiv3 app channel)
    # ------------------------------------------------------------------

    async def async_send_command(
        self,
        command: str,
        params: str = "",
        wait_response: bool = True,
    ) -> SendResult:
        """Send a command via the openapiv3 app channel (SendCommandByAPP).

        This is the only channel that delivers commands to the IK122T Pro
        (model 504). Verified live on 2026-11-10: SLXKLS with this exact
        request was physically executed by the collar 3/3.

        The request body must contain ONLY the six fields the app sends
        (``Key, SN, DeviceID, CommandType, Model, Paramter``): any extra
        field makes the platform queue and even ACK the command without
        delivering it — see the module docstring.

        ``params`` carries the command parameters — e.g. the shock level
        for SLXKZDXG, empty for SLXKLS (sound).
        """
        if self._app_key2018 is None or self.app_device_id is None:
            await self.async_app_login()

        try:
            return await self._async_send_command_app(command, params, wait_response)
        except _AppSessionExpired:
            # key2018 is per-login and invalidated by any newer login;
            # re-login once and retry.
            _LOGGER.debug("App-API session expired, re-logging in")
            await self.async_app_login()
            return await self._async_send_command_app(command, params, wait_response)

    async def _async_send_command_app(
        self, command: str, params: str, wait_response: bool
    ) -> SendResult:
        raw = await self._openapi_post(
            "SendCommandByAPP",
            {
                "SN": self.sn,
                "DeviceID": str(self.app_device_id),
                "CommandType": command,
                "Model": str(self.model or 0),
                "Paramter": params,
                "Key": self._app_key2018 or "",
            },
        )
        # Success: a bare numeric CommandID. Failure: a JSON state code.
        raw_stripped = raw.strip()
        try:
            command_id = int(raw_stripped)
        except ValueError:
            data = self._parse_openapi_json(raw_stripped)
            state = str(data.get("state", ""))
            if state == "3001":
                raise _AppSessionExpired()  # noqa: TRY300 (internal control flow)
            raise ICarApiError(f"Command {command} rejected (state {state})")

        result = SendResult(
            command=command,
            code=command_id,
            queued=True,
            message="Command queued via app API",
            command_id=command_id,
        )
        if wait_response:
            result.response_text = await self._wait_app_response(command_id)
            if result.response_text:
                # NOTE: this ACK ("Success!") is the platform's claim that
                # the command was delivered — it is NOT proof of physical
                # execution (the server can fabricate it for commands it
                # never delivered).
                result.message = f"Platform ACK: {result.response_text}"
        return result

    async def _wait_app_response(
        self, command_id: int, attempts: int = 4, delay: float = 2.0
    ) -> str | None:
        """Poll openapiv3 GetResponse for the device ACK of a command.

        The ACK is advisory only: the platform can report "Success!" for
        commands it never actually delivered to the collar.
        """
        for attempt in range(attempts):
            try:
                raw = await self._openapi_post(
                    "GetResponse",
                    {
                        "CommandID": str(command_id),
                        "TimeZones": self.tz,
                        "Key": self._app_key2018 or "",
                    },
                )
                data = self._parse_openapi_json(raw)
                state = str(data.get("state", ""))
                if state == "3001":
                    # Either the session went stale or the command is too
                    # old to be in the response table; stop polling.
                    return None
                if str(data.get("isResponse")) == "1":
                    return data.get("responseMsg") or data.get("responseText") or "OK"
            except (ClientError, ICarApiError) as exc:
                _LOGGER.debug("GetResponse attempt %s failed: %s", attempt, exc)
            await asyncio.sleep(delay)
        return None


class _AppSessionExpired(Exception):
    """Internal: the openapiv3 session key (key2018) is no longer valid."""
