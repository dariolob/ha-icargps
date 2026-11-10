"""Constants for the iCar GPS (icargps.net) integration."""

from typing import Final

DOMAIN: Final = "icargps"

BASE_URL: Final = "http://www.icargps.net"

LOGIN_URL: Final = f"{BASE_URL}/loginpage/icargps/index.aspx?language=en-us"
DEVICES_URL: Final = f"{BASE_URL}/Ajax/DevicesAjax.asmx/GetDevicesByUserID"
EXCEPTIONS_URL: Final = (
    f"{BASE_URL}/Ajax/ExceptionMessageAjax.asmx/GetExceptionMessageByDeviceIDNew2017"
)
SEND_COMMAND_URL: Final = f"{BASE_URL}/Ajax/CommandQueueAjax.asmx/SendCommand"
GET_RESPONSE_URL: Final = f"{BASE_URL}/Ajax/CommandQueueAjax.asmx/GetResponse"

# Config fields
CONF_SN: Final = "sn"
CONF_PASSWORD: Final = "password"
CONF_TZ: Final = "tz"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_SHOCK_LEVEL: Final = "shock_level"
CONF_WATERMARK: Final = "alarm_watermark"

DEFAULT_TZ: Final = "1:00"
DEFAULT_SCAN_INTERVAL: Final = 120
DEFAULT_SHOCK_LEVEL: Final = 1

# Commands (verified on the IK122T Pro, model 504)
CMD_FIND: Final = "SLXKDM"  # "find dog": buzzer + light for ~1 minute
CMD_SHOCK: Final = "SLXKZDXG"  # vibration + e-shock; level passed in params

# Alarm notification types observed on the IK122T Pro:
# 1 = exit geofence, 2 = enter geofence (note = geofence name),
# 3 = other alarm (vibration/bark), others unknown
ALARM_TYPE_MAP: Final = {
    1: "geofence_exit",
    2: "geofence_enter",
    3: "alarm",
}

EVENT_COMMAND_RESULT: Final = f"{DOMAIN}_command_result"
