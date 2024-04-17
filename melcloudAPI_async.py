#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio

import os
import ujson

import aiohttp
import arrow
import structlog


class Melcloud:

    log = structlog.get_logger(__name__)

    powerModeTranslate = {
        0: False,
        1: True}

    operationModeTranslate = {
        0: 1,  # Heat
        1: 3,  # AC
        2: 8,  # Auto
        4: 7,  # Fan
        5: 2}   # Dry

    horizontalVaneTranslate = {
        0: 0,   # _Auto
        1: 1,   # Pos 1
        2: 2,   # Pos 2
        3: 3,   # Pos 3
        4: 4,   # Pos 4
        5: 5,   # Pos 5
        6: 8,   # Split
        7: 12}   # Swing

    verticalVaneTranslate = {
        0: 0,   # _Auto
        1: 1,   # Pos 1
        2: 2,   # Pos 2
        3: 3,   # Pos 3
        4: 4,   # Pos 4
        5: 5,   # Pos 5
        6: 7}    # Swing

    devices = {}
    ata = {}
    validateLock = asyncio.Lock()
    doSessionLock = asyncio.Lock()
    loginLock = asyncio.Lock()
    getDevicesLock = asyncio.Lock()
    setOneDeviceLock = asyncio.Lock()
    getOneDeviceLock = asyncio.Lock()
    fileReadLock = asyncio.Lock()
    fileWriteLock = asyncio.Lock()
    deviceLock = asyncio.Lock()
    ataLock = asyncio.Lock()
    RETRIES = 3
    RETRY_DELAY = 300  # seconds
    ERROR_DELAY = 3*60*60  # seconds
    data = None
    headers = {"Content-Type": "application/json",
               "Host": "app.melcloud.com",
               "Cache-Control": "no-cache"}

    tokenFileName = "/home/staffan/olis/olis_melcloud/tokenfile.txt"
    tokenFileRead = False
    tokenExpires = None

    deviceInfoFileName = "/home/staffan/olis/olis_melcloud/deviceinfofile.txt"
    deviceFileRead = False

    lastSessionFileName = "/home/staffan/olis/olis_melcloud/lastsessionfile.txt"
    # lastSessionFileRead = False

    session = aiohttp.ClientSession(base_url="https://app.melcloud.com")

    def __init__(self, user, password):
        Melcloud.data = {"Email": user,
                         "Password": password,
                         "Language": 18,
                         "AppVersion": "1.32.1.0",
                         "Persist": False,
                         "CaptchaResponse": None}

    @classmethod
    async def _readFileAsync(cls, filename):
        async with cls.fileReadLock:
            if os.path.exists(filename):
                with open(filename, mode="r") as file:
                    contents = ujson.load(file)
                    return contents

    @classmethod
    async def _writeFileAsync(cls, filename, contents):
        async with cls.fileWriteLock:
            with open(filename, mode="w") as file:
                ujson.dump(contents, file)

    @classmethod
    async def _getDevice(cls, deviceName=None, subkey=None):
        async with cls.deviceLock:
            if cls.devices is None or deviceName not in cls.devices:
                return None
            if deviceName is not None:
                if subkey is None:
                    return cls.devices[deviceName]
                else:
                    return cls.devices[deviceName].get(subkey)
            else:
                return cls.devices

    @classmethod
    async def _setDevice(cls,  newValue, deviceName=None, subkey=None):
        async with cls.deviceLock:
            if deviceName is not None:
                if subkey is None:
                    cls.devices[deviceName] = newValue
                else:
                    cls.devices[deviceName][subkey] = newValue
            else:
                cls.devices = newValue

    @classmethod
    async def _getAta(cls, deviceName, subkey=None):
        async with cls.ataLock:
            if cls.ata is None or deviceName not in cls.ata:
                return None
            if subkey is None:
                return cls.ata[deviceName]
            else:
                return cls.ata[deviceName].get(subkey)

    @classmethod
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

    @classmethod
    async def _doSession(cls, loginCall=False, **params):
        async with cls.doSessionLock:
            if not (loginCall or await cls._tokenValid()):
                return

            _lastSessionFromFile = await cls._readFileAsync(cls.lastSessionFileName)

            if _lastSessionFromFile:
                cls.log.info("Melcloud reading lastsession time from file")
                _lastSessionTime = arrow.get(_lastSessionFromFile.get("lastSessionTime"), tzinfo=("Europe/Stockholm"))
                _lastStatus = _lastSessionFromFile.get("lastStatus")
                _delayToNextCall = cls.ERROR_DELAY if _lastStatus != 200 else cls.RETRY_DELAY
                _nextCallTime = _lastSessionTime.shift(seconds=_delayToNextCall)
                _now = arrow.now("Europe/Stockholm")
                if _nextCallTime > _now:
                    _delaySeconds = (_nextCallTime - _now).seconds
                    cls.log.info(f"Melcloud sleeping {_delaySeconds} before next possible call")
                    await asyncio.sleep(_delaySeconds)

            for i in range(cls.RETRIES):
                try:
                    async with cls.session.request(**params) as response:
                        cls.log.info("Melcloud writing lastsession time to file")
                        await cls._writeFileAsync(cls.lastSessionFileName, {"lastSessionTime": arrow.now("Europe/Stockholm").format("YYYY-MM-DD HH:mm:ss"), "lastStatus": 200})
                        if response.status == 429:
                            _result = await response.text()
                            cls.log.error(f"Melcloud got status 429 reply...", result=_result)
                        else:
                            _result = await response.json()

                        return _result

                except Exception as e:
                    cls.log.error("Exception in _doSession", error=e)
                    if i > cls.RETRIES-1:  # Check if more retries are allowed
                        cls.log.warning(f"Retrying in {cls.RETRY_DELAY} seconds...")

                    else:
                        cls.log.warning("Max retries reached. Attempting logon...")
                        await cls.login()
                        break

    @classmethod
    async def _validateToken(cls):
        if not await cls._tokenValid():
            await cls.login()

    @classmethod
    async def _tokenValid(cls):
        now = arrow.now("Europe/Stockholm")
        async with cls.validateLock:
            if cls.tokenExpires is None or now >= cls.tokenExpires:
                return False
        return True

    @staticmethod
    def _lookupValue(di, value):
        for key, val in di.items():
            if val == value:
                return key
        return None

    @classmethod
    async def login(cls):
        async with cls.loginLock:
            for i in range(cls.RETRIES):
                try:
                    if await cls._tokenValid():
                        break

                    if not cls.tokenFileRead:
                        _tokenFromFile = await cls._readFileAsync(cls.tokenFileName)

                    if not cls.tokenFileRead and _tokenFromFile:
                        if "token" in _tokenFromFile:
                            cls.log.info("Melcloud setting token from file")
                            _token = _tokenFromFile.get("token")
                            cls.headers["X-MitsContextKey"] = _token if _token else None
                            cls.tokenExpires = arrow.get(_tokenFromFile.get("tokenExpires"), tzinfo=("Europe/Stockholm"))
                            cls.tokenFileRead = True
                            if not await cls._tokenValid():
                                cls.log.info("Melcloud token from file has expired")
                                continue
                        else:
                            cls.tokenFileRead = True
                            cls.log.warning("Melcloud token file damaged")
                            continue
                    else:
                        cls.log.info("Melcloud trying login")
                        out = await cls._doSession(loginCall=True, method="POST", url="/Mitsubishi.Wifi.Client/Login/ClientLogin", headers=cls.headers, data=ujson.dumps(cls.data))
                        if out is not None and 'LoginData' in out:
                            _token = out['LoginData']['ContextKey']
                            cls.headers["X-MitsContextKey"] = _token
                            cls.tokenExpires = arrow.get(out['LoginData']['Expiry']).to("Europe/Stockholm")
                            cls.log.info("Melcloud writing token to file")
                            await cls._writeFileAsync(cls.tokenFileName, {"token": _token, "tokenExpires": cls.tokenExpires.format("YYYY-MM-DD HH:mm:ss")})
                            if _token:
                                cls.log.info("Melcloud login success")
                                break
                        else:
                            if i > cls.RETRIES-1:  # Check if more retries are allowed
                                cls.log.warning(f"Retrying in {cls.RETRY_DELAY} seconds...")

                except Exception as e:
                    cls.log.error("Melcloud exception in login",  out=out, error=e)
                    if i > cls.RETRIES-1:  # Check if more retries are allowed
                        cls.log.warning(f"Retrying in {cls.RETRY_DELAY} seconds...")

                    else:
                        cls.log.warning("Max retries reached. Attempting logon...")
                        break

            # if not cls.devices and await cls._tokenValid():
                # asyncio.create_task(cls.getDevices())
                # await cls.getDevices()

    @classmethod
    async def logout(cls):
        cls.log.info("logout")
        await cls.session.close()

    @classmethod
    async def getDevices(cls):
        try:
            async with cls.getDevicesLock:
                if await cls._getDevice():  # exit if devices already set
                    return

                await cls._validateToken()

                if not cls.deviceFileRead:
                    _deviceFromFile = await cls._readFileAsync(cls.deviceInfoFileName)

                if not cls.deviceFileRead and _deviceFromFile:
                    cls.log.info("Melcloud setting devices from file")
                    cls.deviceFileRead = True
                    await cls._setDevice(_deviceFromFile.get("devices"))

                else:
                    cls.log.info("Melcloud trying getDevices")
                    entries = await cls._doSession(method="GET", url="/Mitsubishi.Wifi.Client/User/Listdevices", headers=cls.headers)

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
                                              "LastTimeStamp": arrow.get(dev["Device"]["LastTimeStamp"]).format("YYYY-MM-DD HH:mm:ss")},
                                             deviceName)

                        cls.log.info("Melcloud writing devices to file")
                        await cls._writeFileAsync(cls.deviceInfoFileName, {"devices": cls.devices})

        except Exception as e:
            cls.log.error("Exception in getDevices", error=e)

    @classmethod
    async def getOneDevice(cls, deviceName):
        try:
            async with cls.getOneDeviceLock:
                cls.log.info("Melcloud trying getOneDevice", devices=cls.devices)

                await cls._validateToken()
                await cls.getDevices()

                params = {"id": await cls._getDevice(deviceName, subkey='DeviceID'),
                          "buildingID": await cls._getDevice(deviceName, subkey='BuildingID')}

                _result = await cls._doSession(method="GET", url="/Mitsubishi.Wifi.Client/Device/Get", headers=cls.headers, params=params)
                await cls._setAta(deviceName, _result)
                cls.log.info("Melcloud finished getOneDevice")

        except Exception as e:
            cls.log.error("Exception in getOneDevice", deviceName=deviceName, error=e)

    @classmethod
    async def getAllDevice(cls):
        await cls._validateToken()
        await cls.getDevices()

        _dev = await cls._getDevice()
        for dev in _dev:
            await cls.getOneDeviceInfo(dev)

    @classmethod
    async def getOneDeviceInfo(cls, deviceName):
        if not await cls._getAta(deviceName):
            await cls.getOneDevice(deviceName)

        return await cls._returnOneAtaInfo(deviceName)

    @classmethod
    async def getDevicesInfo(cls):
        return await cls._getDevice()

    @classmethod
    async def _returnOneAtaInfo(cls, deviceName):
        return {"RoomTemp": await cls._getAta(deviceName, subkey="RoomTemperature"),
                "LastCommunication": arrow.get(await cls._getAta(deviceName, subkey="LastCommunication")).to("Europe/Stockholm").format("YYYY-MM-DD HH:mm:ss"),
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

                await cls._validateToken()

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

                _result = await cls._doSession(method="POST", url="/Mitsubishi.Wifi.Client/Device/SetAta", headers=cls.headers, data=ujson.dumps(cls.ata[deviceName]))
                await cls._setAta(deviceName, _result)
                cls.log.info("Melcloud finished setOneDeviceInfo")

                await cls._setAta(deviceName, 0, subkey="EffectiveFlags")

                return "OK"

        except Exception as e:
            cls.log.error("Exception in setOneDeviceInfo", deviceName=deviceName, error=e)
            return False
