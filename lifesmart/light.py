"""Support for LifeSmart Gateway Light."""
import binascii
import logging
import struct
from typing import Any
import urllib.request
import json
import time
import hashlib
from homeassistant.components.light import (
    ATTR_HS_COLOR,
    LightEntity,
    ENTITY_ID_FORMAT,
    ColorMode,
    LightEntityFeature,
)
import homeassistant.util.color as color_util
from .helpers import safe_get
from homeassistant.core import callback
from .const import DEVICE_DATA_KEY, DYN_EFFECT_LIST, DYN_EFFECT_MAP

from . import LifeSmartDevice

_LOGGER = logging.getLogger(__name__)

QUANTUM_TYPES = ["OD_WE_QUAN",
                 ]

SPOT_TYPES = ["MSL_IRCTL",
              "OD_WE_IRCTL",
              "SL_SPOT"]


def _parse_color_value(value: int, has_white: bool) -> tuple:
    """
    将一个32位整数颜色值解析为RGB或RGBW元组。

    颜色格式假定为：
    - bits 0-7:   Blue
    - bits 8-15:  Green
    - bits 16-23: Red
    - bits 24-31: White (如果 has_white 为 True) 或 亮度/效果标志
    """
    blue = value & 0xFF
    green = (value >> 8) & 0xFF
    red = (value >> 16) & 0xFF

    if has_white:
        white = (value >> 24) & 0xFF
        return (red, green, blue, white)
    return (red, green, blue)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Perform the setup for LifeSmart devices."""
    if discovery_info is None:
        return
    dev = discovery_info.get("dev")
    param = discovery_info.get("param")
    devices = []
    for idx in dev['data']:
        if idx in ["RGB", "RGBW", "dark", "dark1", "dark2", "dark3", "bright", "bright1", "bright2", "bright"]:
            devices.append(LifeSmartLight(dev, idx, dev['data'][idx], param))
    add_entities(devices)


class LifeSmartLight(LifeSmartDevice, LightEntity):
    """Representation of a LifeSmartLight."""

    def __init__(self, dev, idx, val, param):
        """Initialize the LifeSmartLight."""
        super().__init__(dev, idx, val, param)
        self.entity_id = ENTITY_ID_FORMAT.format(
            (dev['devtype'] + "_" + dev['agt'] + "_" + dev['me'] + "_" + idx).lower().replace("-", ""))
        self._unique_id = self.entity_id
        ## set _sub_key to None
        self._sub_key = None

        device_data = safe_get(dev, DEVICE_DATA_KEY, default={})
        if self._sub_key:
            self._sub_data = safe_get(device_data, self._sub_key, default={})
        else:
            self._sub_data = device_data        

        # _LOGGER.info("light: %s added..",str(self.entity_id))
        # if val['type'] % 2 == 1:
        #     self._state = True
        # else:
        #     self._state = False
        value = val['val']
        if value == 0:
            self._hs = None
        else:
            rgbhexstr = "%x" % value
            rgbhexstr = rgbhexstr.zfill(8)
            rgbhex = bytes.fromhex(rgbhexstr)
            rgba = struct.unpack("BBBB", rgbhex)
            rgb = rgba[1:]
            self._hs = color_util.color_RGB_to_hs(*rgb)
            _LOGGER.info("hs_rgb: %s", str(self._hs))
        
        self._initialize_state()

    @callback
    def _initialize_state(self) -> None:
        """初始化SPOT RGB灯状态。"""
        sub_data = self._sub_data
        self._attr_is_on = safe_get(sub_data, "type", default=0) % 2 == 1
        self._state = self._attr_is_on

        # currently only check MSL_IRCTL
        if (self._devtype in ['MSL_IRCTL']):
            self._attr_supported_features = LightEntityFeature.EFFECT
            self._attr_color_mode = ColorMode.RGBW
            self._attr_supported_color_modes = {ColorMode.RGBW}
            self._attr_effect_list = DYN_EFFECT_LIST
            self._attr_brightness = 255 if self._attr_is_on else 0

            if (val := safe_get(sub_data, "val")) is not None:
                if (val >> 24) & 0xFF > 0:
                    self._attr_effect = next(
                        (k for k, v in DYN_EFFECT_MAP.items() if v == val), None
                    )
                else:
                    self._attr_effect = None
                self._attr_rgb_color = _parse_color_value(val, has_white=False)

    async def async_added_to_hass(self):
        if self._devtype not in SPOT_TYPES:
            return
        rmdata = {}
        rmlist = await self.hass.async_add_executor_job(LifeSmartLight._lifesmart_GetRemoteList, self)
        for ai in rmlist:
            rms = await self.hass.async_add_executor_job(LifeSmartLight._lifesmart_GetRemotes, self, ai)
            rms['category'] = rmlist[ai]['category']
            rms['brand'] = rmlist[ai]['brand']
            rmdata[ai] = rms
        self._attributes.setdefault('remotelist', rmdata)

    # @property
    # def is_on(self):
    #     """Return true if it is on."""
    #     return self._state

    @property
    def hs_color(self):
        """Return the hs color value."""
        return self._hs

    def turn_on(self, **kwargs):
        """Turn the light on."""
        if ATTR_HS_COLOR in kwargs:
            self._hs = kwargs[ATTR_HS_COLOR]

        rgb = color_util.color_hs_to_RGB(*self._hs)
        rgba = (0,) + rgb
        rgbhex = binascii.hexlify(struct.pack("BBBB", *rgba)).decode("ASCII")
        rgbhex = int(rgbhex, 16)

        if super()._lifesmart_epset(self, "0xff", rgbhex, self._idx) == 0:
            self._state = True
            self._attr_is_on = True
            self.schedule_update_ha_state()

    def turn_off(self, **kwargs):
        """Turn the light off."""
        if super()._lifesmart_epset(self, "0x80", 0, self._idx) == 0:
            self._state = False
            self._attr_is_on = False
            self.schedule_update_ha_state()

    @staticmethod
    def _lifesmart_GetRemoteList(self):
        appkey = self._appkey
        apptoken = self._apptoken
        usertoken = self._usertoken
        userid = self._userid
        agt = self._agt
        url = f"https://{self._apidomain}/app/irapi.GetRemoteList"
        tick = int(time.time())
        sdata = "method:GetRemoteList,agt:"+agt+",time:" + \
            str(tick)+",userid:"+userid+",usertoken:" + \
            usertoken+",appkey:"+appkey+",apptoken:"+apptoken
        sign = hashlib.md5(sdata.encode(encoding='UTF-8')).hexdigest()
        send_values = {
            "id": 1,
            "method": "GetRemoteList",
            "params": {
                "agt": agt
            },
            "system": {
                "ver": "1.0",
                "lang": "en",
                "userid": userid,
                "appkey": appkey,
                "time": tick,
                "sign": sign
            }
        }

        header = {'Content-Type': 'application/json'}
        send_data = json.dumps(send_values)
        req = urllib.request.Request(url=url, data=send_data.encode(
            'utf-8'), headers=header, method='POST')
        response: dict[str, Any] = json.loads(
            urllib.request.urlopen(req).read().decode('utf-8'))
        return response['message']

    @ staticmethod
    def _lifesmart_GetRemotes(self, ai):
        appkey = self._appkey
        apptoken = self._apptoken
        usertoken = self._usertoken
        userid = self._userid
        agt = self._agt
        url = f"https://{self._apidomain}/app/irapi.GetRemote"
        tick = int(time.time())
        sdata = "method:GetRemote,agt:"+agt+",ai:"+ai+",needKeys:2,time:" + \
            str(tick)+",userid:"+userid+",usertoken:" + \
            usertoken+",appkey:"+appkey+",apptoken:"+apptoken
        sign = hashlib.md5(sdata.encode(encoding='UTF-8')).hexdigest()
        send_values = {
            "id": 1,
            "method": "GetRemote",
            "params": {
                "agt": agt,
                "ai": ai,
                "needKeys": 2
            },
            "system": {
                "ver": "1.0",
                "lang": "en",
                "userid": userid,
                "appkey": appkey,
                "time": tick,
                "sign": sign
            }
        }
        header = {'Content-Type': 'application/json'}
        send_data = json.dumps(send_values)
        req = urllib.request.Request(url=url, data=send_data.encode(
            'utf-8'), headers=header, method='POST')
        response: dict[str, Any] = json.loads(
            urllib.request.urlopen(req).read().decode('utf-8'))
        return response['message']['codes']
