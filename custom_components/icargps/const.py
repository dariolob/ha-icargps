"""Constants for the iCar GPS (icargps.net) integration."""

from typing import Final

DOMAIN: Final = "icargps"

BASE_URL: Final = "http://www.icargps.net"

LOGIN_URL: Final = f"{BASE_URL}/loginpage/icargps/index.aspx?language=en-us"
DEVICES_URL: Final = f"{BASE_URL}/Ajax/DevicesAjax.asmx/GetDevicesByUserID"
EXCEPTIONS_URL: Final = (
    f"{BASE_URL}/Ajax/ExceptionMessageAjax.asmx/GetExceptionMessageByDeviceIDNew2017"
)
GETAPP_URL: Final = f"{BASE_URL}/getapp.aspx"

# --- Command channel: the Yiwen "openapiv3" app API -------------------
# The tenant's app-API endpoint is published by the platform itself at
# /getapp.aspx (currently https://app2.gps18.com/openapiv3.asmx). This is
# the API the "iCar GPS" mobile app uses and the ONLY channel that
# actually delivers commands to the IK122T Pro (model 504) — verified
# end-to-end on 2026-11-10 (SLXKDM ACKed "Success!" in ~1 s).
OPENAPI_BASE_FALLBACK: Final = "https://app2.gps18.com/openapiv3.asmx/"

# Framework-level app key accepted by the openapiv3 Login (shared by the
# white-label apps of this platform; verified working for the ICAR tenant).
APP_KEY: Final = "7DU2DJFDR8321"
APP_LOGINAPP: Final = "icar gps"
APP_LOGIN_TYPE: Final = 1  # 1 = login by IMEI/SN + device password

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
