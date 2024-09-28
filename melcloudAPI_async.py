#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio

import arrow
import structlog
import ujson

from API.apihandlers import APIMelcloud


class Melcloud:

    log = structlog.get_logger(__name__)

    powerModeTranslate = {0: False,
                          1: True}

    operationModeTranslate = {0: 1,  # Heat
                              1: 3,  # AC
                              2: 8,  # Auto
                              4: 7,  # Fan
                              5: 2}   # Dry

    horizontalVaneTranslate = {0: 0,   # _Auto
                               1: 1,   # Pos 1
                               2: 2,   # Pos 2
                               3: 3,   # Pos 3
                               4: 4,   # Pos 4
                               5: 5,   # Pos 5
                               6: 8,   # Split
                               7: 12}   # Swing

    verticalVaneTranslate = {0: 0,   # _Auto
                             1: 1,   # Pos 1
                             2: 2,   # Pos 2
                             3: 3,   # Pos 3
                             4: 4,   # Pos 4
                             5: 5,   # Pos 5
                             6: 7}    # Swing

    devices = {}
    ata = {}
    getDevicesLock = asyncio.Lock()
    setOneDeviceLock = asyncio.Lock()
    getOneDeviceLock = asyncio.Lock()
    deviceLock = asyncio.Lock()
    ataLock = asyncio.Lock()
    mc = None
    apiHandler = None
    TIME_ZONE = "Europe/Stockholm"
    DATE_FORMAT = "YYYY-MM-DD HH:mm:ss"
    deviceInfoFileName = "/home/staffan/olis/olis_melcloud/deviceinfofile.txt"
    deviceFileRead = False

    def __init__(self):
        pass

    @classmethod
    async def create(cls, username, password, commonSession=None):
        try:
            if cls.mc is None:
                cls.mc = cls()
                if cls.apiHandler is None:
                    cls.apiHandler = await APIMelcloud.create(name="Melcloud",
                                                              commonSession=commonSession,
                                                              tokenFileName="/home/staffan/olis/olis_melcloud/tokenfile.txt",
                                                              lastSessionFileName="/home/staffan/olis/olis_melcloud/lastsessionfile.txt",
                                                              headers={"Content-Type": "application/json",
                                                                       "Host": "app.melcloud.com",
                                                                       "Cache-Control": "no-cache"},
                                                              data={"Email": username,
                                                                    "Password": password,
                                                                    "Language": 18,
                                                                    "AppVersion": "1.32.1.0",
                                                                    "Persist": False,
                                                                    "CaptchaResponse": None},
                                                              loginUrls=["/Mitsubishi.Wifi.Client/Login/ClientLogin"],
                                                              BASE_URL="https://app.melcloud.com",
                                                              RETRIES=3,
                                                              RETRY_DELAY=300,
                                                              THROTTLE_DELAY=300,
                                                              THROTTLE_ERROR_DELAY=3*60*60)

                # if await cls.mc.apiHandler.login():
                #    await cls.mc.getPlant()
            return cls.mc

        except Exception as e:
            cls.log.error(f"Melcloud request error", error=e)
            return None

    async def logout(self):
        await self.apiHandler.logout()

    @ staticmethod
    def _lookupValue(di, value):
        for key, val in di.items():
            if val == value:
                return key
        return None

    @ classmethod
    async def _getDevice(cls, deviceName=None, subkey=None):
        async with cls.deviceLock:
            # if cls.devices is None:
            #    return None

            # if deviceName is None and subkey is None:
            #    return cls.devices

            # if deviceName is not None:
            #    if subkey is None:
            #        return cls.devices[deviceName]
            #    else:
            #        return cls.devices[deviceName].get(subkey)

            if cls.devices is None:
                return None

            if deviceName is None:
                return cls.devices

            device = cls.devices.get(deviceName)
            if device is None:
                return None

            if subkey is None:
                return device

            return device.get(subkey)

    @ classmethod
    async def _setDevice(cls,  newValue, deviceName=None, subkey=None):
        async with cls.deviceLock:
            if deviceName is not None:
                if subkey is None:
                    cls.devices[deviceName] = newValue
                else:
                    cls.devices[deviceName][subkey] = newValue
            else:
                cls.devices = newValue

    @ classmethod
    async def _getAta(cls, deviceName, subkey=None):
        async with cls.ataLock:
            if cls.ata is None or deviceName not in cls.ata:
                return None
            if subkey is None:
                return cls.ata[deviceName]
            else:
                return cls.ata[deviceName].get(subkey)

    @ classmethod
    async def _setAta(cls, deviceName, newValue, subkey=None, mask=None):
        async with cls.ataLock:
            if subkey is None:
                if mask is None:
                    cls.ata[deviceName] = newValue
                else:
                    cls.ata[deviceName] |= mask
            else:
                if mask is None:
                    cls.ata[deviceName][subkey] = newValue
                else:
                    cls.ata[deviceName][subkey] |= mask

    @ classmethod
    async def getDevices(cls):
        try:
            async with cls.getDevicesLock:
                if await cls._getDevice():  # exit if devices already set
                    return

                if not cls.deviceFileRead:
                    _deviceFromFile = await cls.apiHandler._readFileAsync(cls.deviceInfoFileName)

                if not cls.deviceFileRead and _deviceFromFile:
                    cls.log.info("Melcloud setting devices from file")
                    cls.deviceFileRead = True
                    await cls._setDevice(_deviceFromFile.get("devices"))

                else:
                    cls.log.info("Melcloud trying getDevices")
                    entries = await cls.apiHandler.doSession(method="GET", url="/Mitsubishi.Wifi.Client/User/Listdevices")

                    allDevices = []
                    for entry in entries:
                        allDevices += entry["Structure"]["Devices"]

                        for area in entry["Structure"]["Areas"]:
                            allDevices += area["Devices"]

                        for floor in entry["Structure"]["Floors"]:
                            allDevices += floor["Devices"]
                            for area in floor["Areas"]:
                                allDevices += area["Devices"]

                    for dev in allDevices:
                        deviceName = dev["DeviceName"]
                        await cls._setDevice({"DeviceID": dev["DeviceID"],
                                             "BuildingID": dev["BuildingID"],
                                              "CurrentEnergyConsumed": dev["Device"]["CurrentEnergyConsumed"],
                                              "LastTimeStamp": arrow.get(dev["Device"]["LastTimeStamp"]).format(cls.DATE_FORMAT)},
                                             deviceName)

                        cls.log.info("Melcloud writing devices to file")
                        await cls.apiHandler._writeFileAsync(cls.deviceInfoFileName, {"devices": cls.devices})

        except Exception as e:
            cls.log.error("Exception in getDevices", error=e)

    @ classmethod
    async def getOneDevice(cls, deviceName):
        try:
            async with cls.getOneDeviceLock:
                cls.log.info("Melcloud trying getOneDevice")

                await cls.getDevices()

                params = {"id": await cls._getDevice(deviceName, subkey='DeviceID'),
                          "buildingID": await cls._getDevice(deviceName, subkey='BuildingID')}

                _result = await cls.apiHandler.doSession(method="GET", url="/Mitsubishi.Wifi.Client/Device/Get", params=params)
                await cls._setAta(deviceName, _result)
                cls.log.info("Melcloud finished getOneDevice")

        except Exception as e:
            cls.log.error("Exception in getOneDevice", deviceName=deviceName, error=e)

    @classmethod
    async def getAllDevice(cls):
        await cls.getDevices()
        out = {}
        _dev = await cls._getDevice()
        for dev in _dev:
            out[dev] = await cls.getOneDeviceInfo(dev)
        return out

    @classmethod
    async def getOneDeviceInfo(cls, deviceName):
        # if not await cls._getAta(deviceName):
        await cls.getOneDevice(deviceName)

        return await cls._returnOneAtaInfo(deviceName)

    @classmethod
    async def getDevicesInfo(cls):
        return await cls._getDevice()

    @classmethod
    async def _returnOneAtaInfo(cls, deviceName):
        return {"RoomTemp": await cls._getAta(deviceName, subkey="RoomTemperature"),
                "LastCommunication": arrow.get(await cls._getAta(deviceName, subkey="LastCommunication")).to(cls.TIME_ZONE).format(cls.DATE_FORMAT),
                "hasPendingCommand": await cls._getAta(deviceName, subkey="HasPendingCommand"),
                "CurrentState": {"P": cls._lookupValue(cls.powerModeTranslate, await cls._getAta(deviceName, subkey="Power")),
                                 "M": cls._lookupValue(cls.operationModeTranslate, await cls._getAta(deviceName, subkey="OperationMode")),
                                 "T": await cls._getAta(deviceName, subkey="SetTemperature"),
                                 "F": await cls._getAta(deviceName, subkey="SetFanSpeed"),
                                 "V": cls._lookupValue(cls.verticalVaneTranslate, await cls._getAta(deviceName, subkey="VaneVertical")),
                                 "H": cls._lookupValue(cls.horizontalVaneTranslate, await cls._getAta(deviceName, subkey="VaneHorizontal"))}}

    @classmethod
    async def printDevicesInfo(cls):
        _dev = await cls._getDevice()
        for dev in _dev:
            cls.printOneDevicesInfo(dev)

    @classmethod
    async def printOneDevicesInfo(cls, deviceName):
        _dev = await cls._getDevice()
        print(f"{deviceName} :")
        print(f"DeviceID: {_dev['DeviceID']}")
        print(f"BuildingID: {_dev['BuildingID']}")
        print(f"CurrentEnergyConsumed: {_dev['CurrentEnergyConsumed']}")
        print(f"LastTimeStamp: {_dev['LastTimeStamp']}")
        print(f"RoomTemperature: {_dev['RoomTemp']}")
        print(f"""P : {_dev["CurrentState"]['P']}, M : {_dev["CurrentState"]['M']}, T : {_dev["CurrentState"]['T']}, F : {_dev["CurrentState"]['F']}, V : {_dev["CurrentState"]['V']}, H : {_dev["CurrentState"]['H']}""")
        print(f"hasPendingCommand: {_dev['hasPendingCommand']}")
        print("\n")

    @classmethod
    async def setOneDeviceInfo(cls, deviceName, desiredState):
        try:
            async with cls.setOneDeviceLock:
                cls.log.info("Melcloud trying setOneDeviceInfo")

                if not await cls._getAta(deviceName):
                    await cls.getOneDevice(deviceName)

                # await cls.apiHandler._validateToken()

                # Melcloud.ata[deviceName]["DeviceID"] = Melcloud.devices[deviceName]["DeviceID"]
                if desiredState.get("P") is not None:
                    await cls._setAta(deviceName, cls.powerModeTranslate[desiredState["P"]], subkey="Power")
                    await cls._setAta(deviceName, newValue=None, mask=0x01, subkey="EffectiveFlags")

                if desiredState.get("M") is not None:
                    await cls._setAta(deviceName, cls.operationModeTranslate[desiredState["M"]], subkey="OperationMode")
                    await cls._setAta(deviceName, newValue=None, mask=0x02, subkey="EffectiveFlags")

                if desiredState.get("T") is not None:
                    await cls._setAta(deviceName, desiredState["T"], subkey="SetTemperature")
                    await cls._setAta(deviceName, newValue=None, mask=0x04, subkey="EffectiveFlags")

                if desiredState.get("F") is not None:
                    await cls._setAta(deviceName, desiredState["F"], subkey="SetFanSpeed")
                    await cls._setAta(deviceName, newValue=None, mask=0x08, subkey="EffectiveFlags")

                if desiredState.get("V") is not None:
                    await cls._setAta(deviceName, cls.verticalVaneTranslate[desiredState["V"]], subkey="VaneVertical")
                    await cls._setAta(deviceName, newValue=None, mask=0x10, subkey="EffectiveFlags")

                if desiredState.get("H") is not None:
                    await cls._setAta(deviceName, cls.horizontalVaneTranslate[desiredState["H"]], subkey="VaneHorizontal")
                    await cls._setAta(deviceName, newValue=None, mask=0x100, subkey="EffectiveFlags")

                _result = await cls.apiHandler.doSession(method="POST", url="/Mitsubishi.Wifi.Client/Device/SetAta", data=ujson.dumps(cls.ata[deviceName]))
                await cls._setAta(deviceName, _result)
                cls.log.info("Melcloud finished setOneDeviceInfo")

                await cls._setAta(deviceName, 0, subkey="EffectiveFlags")

                return "OK"

        except Exception as e:
            cls.log.error("Exception in setOneDeviceInfo", deviceName=deviceName, error=e)
            return False
