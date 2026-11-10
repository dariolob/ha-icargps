"""API client for the icargps.net tracking platform.

The platform is an ASP.NET WebForms application with ASMX JSON endpoints.
Everything is session-gated: the session cookie is obtained with a classic
ASP.NET postback login and the API calls must reproduce the browser's
pseudo-JSON payloads (unquoted object keys) byte for byte.
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
    DEVICES_URL,
    EXCEPTIONS_URL,
    GET_RESPONSE_URL,
    LOGIN_URL,
    SEND_COMMAND_BY_PHONE_URL,
)

_LOGGER = logging.getLogger(__name__)

_VIEWSTATE_RE = re.compile(r'name="__VIEWSTATE"[^>]*value="([^"]*)"')
_GENERATOR_RE = re.compile(r'name="__VIEWSTATEGENERATOR"[^>]*value="([^"]*)"')
_EVENTVAL_RE = re.compile(r'name="__EVENTVALIDATION"[^>]*value="([^"]*)"')
_MONITOR_RE = re.compile(r"location\.href='(/Monitor\.aspx[^']*)'")
_USERID_RE = re.compile(r"map\.aspx\?id=(\d+)")
_DEVICEID_RE = re.compile(r"deviceID=(\d+)")
_PSEUDO_KEY_RE = re.compile(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)")


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


# Numeric result codes of SendCommand/SendCommandByPhone (from the
# platform's own JS).
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
    queued: bool = False  # accepted and delivered (command id > 10)
    saved: bool = False  # accepted but queued for next device connection
    message: str = ""
    response_text: str | None = None
    command_id: int | None = None


class ICarApi:
    """Minimal client for the icargps.net web API."""

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

    # ------------------------------------------------------------------
    # Low level helpers
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

    async def _asmx_call_raw(self, url: str, body: str) -> Any:
        """POST and return the raw parsed outer JSON (for integer results)."""
        async with self._session.post(url, data=body, headers=self._asmx_headers) as resp:
            text = await resp.text()
        try:
            return json.loads(text).get("d")
        except json.JSONDecodeError as exc:
            raise ICarApiError(f"Invalid response: {exc}") from exc

    # ------------------------------------------------------------------
    # Authentication
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
    # Telemetry
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
    # Commands
    # ------------------------------------------------------------------

    async def async_send_command(
        self,
        command: str,
        params: str = "",
        wait_response: bool = True,
    ) -> SendResult:
        """Send a command to the device via the platform's phone-command queue.

        The IK122T Pro (model 504) does NOT accept commands through the
        plain SendCommand endpoint: the platform answers code 4 ("Command
        has been saved") but never dispatches them (verified 2026-11-10:
        such commands never even appear in the command queue, even with
        the collar online). The SendCommandByPhone queue is the one the
        mobile app uses: the command immediately appears in the queue as
        sent (verified end-to-end with SLXKDM).

        ``params`` carries the Phones field — e.g. the shock level for
        SLXKZDXG, empty for SLXKDM (find).
        """
        if self.user_id is None or self.device_id is None:
            raise ICarAuthError("Not logged in")
        body = (
            f"{{SN:'{_q(self.sn)}',DeviceID:{self.device_id},"
            f"CommandType:'{_q(command)}',Model:{self.model or 0},"
            f"Phones:'{_q(params)}',UserID:{self.user_id},"
            f"Pass:'{_q(self._password)}',LoginType:2}}"
        )
        try:
            result = await self._asmx_call_raw(SEND_COMMAND_BY_PHONE_URL, body)
            code = int(result)
        except (TypeError, ValueError) as exc:
            raise ICarApiError(f"Unexpected command result: {result!r}") from exc

        if code > 10:
            res = SendResult(
                command=command,
                code=code,
                queued=True,
                message="Command queued",
                command_id=code,
            )
            if wait_response:
                res.response_text = await self._wait_response(code)
            return res

        return SendResult(
            command=command,
            code=code,
            saved=code in (4, 6),
            message=SEND_RESULT_CODES.get(code, f"Platform returned code {code}"),
        )

    async def _wait_response(self, command_id: int, attempts: int = 6, delay: float = 2.0) -> str | None:
        """Poll GetResponse for the device ACK of a queued command."""
        body = f"{{CommandID:{command_id},TimeZones:'{_q(self.tz)}'}}"
        for _ in range(attempts):
            try:
                data = await self._asmx_call(GET_RESPONSE_URL, body)
            except (ClientError, ICarApiError):
                data = None
            if data:
                is_response = data.get("isResponse")
                text = data.get("responseText")
                if str(is_response) == "1":
                    return text or "OK"
            await asyncio.sleep(delay)
        return None
