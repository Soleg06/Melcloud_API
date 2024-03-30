#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import structlog

import aiohttp
import arrow
import ujson
import copy

# from API.staffstuff_asyncio import MyLock


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
    validateSemaphore = asyncio.Semaphore(1)
    doSessionSemaphore = asyncio.Semaphore(1)
    RETRIES = 3
    RETRY_DELAY = 10  # seconds

    def __init__(self, user, password):
        self.username = user
        self.password = password
        self.headers = {
            "Content-Type": "application/json",
            "Host": "app.melcloud.com",
            "Cache-Control": "no-cache"
        }
        self.session = aiohttp.ClientSession(base_url="https://app.melcloud.com")

    async def _doSession(self, method, url, headers, data=None, params=None, auth=None):
        out = {}
        for i in range(self.RETRIES):
            try:
                async with Melcloud.doSessionSemaphore:
                    await asyncio.sleep(1)
                    async with self.session.request(method=method, url=url, headers=headers, data=data, params=params, auth=auth) as response:
                        try:
                            return await response.json()
                        except:
                            return await response.text()

            except Exception as e:
                self.log.error("Exception in _doRequest", error=e)
                if i < self.RETRIES - 1:
                    self.log.warning(f"Retrying in {self.RETRY_DELAY} seconds...")
                    await asyncio.sleep(self.RETRY_DELAY)
                else:
                    self.log.warning("Max retries reached. Attempting logon...")
                    await self.login()
                    i = -1

    async def login(self):
        for i in range(self.RETRIES):
            try:
                self.log.info("trying login")
                data = {"Email": self.username,
                        "Password": self.password,
                        "Language": 18,
                        "AppVersion": "1.23.4.0"}

                out = await self._doSession(method="POST", url="/Mitsubishi.Wifi.Client/Login/ClientLogin", headers=self.headers, data=ujson.dumps(data))
                if out is not None and 'LoginData' in out:
                    token = out['LoginData']['ContextKey']
                    self.log.info("login success")
                    self.tokenExpires = arrow.get(out['LoginData']['Expiry']).to("Europe/Stockholm")
                    self.headers["X-MitsContextKey"] = token
                    if not Melcloud.devices:
                        await self.getDevices()
                    break

            except Exception as e:
                self.log.error("Melcloud exception in login",  out=out, error=e)

            if i < self.RETRIES - 1:
                self.log.info(f"Melcloud retrying login in {self.RETRY_DELAY} seconds...")
                await asyncio.sleep(self.RETRY_DELAY)

    async def _validateToken(self):
        now = arrow.now("Europe/Stockholm")
        async with Melcloud.validateSemaphore:
            if now >= self.tokenExpires:
                self.log.info("Melcloud logging in again")
                await self.login()

    def _lookupValue(self, di, value):
        for key, val in di.items():
            if val == value:
                return key
        return None

    async def logout(self):
        self.log.info("logout")
        await self.session.close()

    async def getDevices(self):
        try:
            await self._validateToken()
            entries = await self._doSession(method="GET", url="/Mitsubishi.Wifi.Client/User/Listdevices", headers=self.headers)

            allDevices = []
            for entry in entries:
                allDevices += entry["Structure"]["Devices"]

                for area in entry["Structure"]["Areas"]:
                    allDevices += area["Devices"]

                for floor in entry["Structure"]["Floors"]:
                    allDevices += floor["Devices"]

                    for area in floor["Areas"]:
                        allDevices += area["Devices"]

            for device in allDevices:
                deviceName = device["DeviceName"]
                Melcloud.devices[deviceName] = {"DeviceID": device["DeviceID"],
                                                "BuildingID": device["BuildingID"],
                                                "CurrentEnergyConsumed": device["Device"]["CurrentEnergyConsumed"],
                                                "LastTimeStamp": arrow.get(device["Device"]["LastTimeStamp"]).format("YYYY-MM-DD HH:mm:ss")}

        except Exception as e:
            self.log.error("Exception in getDevices", error=e)

    async def getOneDevice(self, deviceName):
        try:
            await self._validateToken()
            if not Melcloud.devices:
                await self.getDevices()

            params = {"id": Melcloud.devices[deviceName]['DeviceID'],
                      "buildingID": Melcloud.devices[deviceName]['BuildingID']}

            Melcloud.ata[deviceName] = await self._doSession(method="GET", url="/Mitsubishi.Wifi.Client/Device/Get", headers=self.headers, params=params)

            self.devices[deviceName] = {"RoomTemp": Melcloud.ata[deviceName]["RoomTemperature"],
                                        "LastCommunication": arrow.get(Melcloud.ata[deviceName]["LastCommunication"]).to("Europe/Stockholm").format("YYYY-MM-DD HH:mm:ss"),
                                        "hasPendingCommand": Melcloud.ata[deviceName]["HasPendingCommand"],
                                        "CurrentState": {"P": self._lookupValue(self.powerModeTranslate, Melcloud.ata[deviceName]["Power"]),
                                                         "M": self._lookupValue(self.operationModeTranslate, Melcloud.ata[deviceName]["OperationMode"]),
                                                         "T": Melcloud.ata[deviceName]["SetTemperature"],
                                                         "F": Melcloud.ata[deviceName]["SetFanSpeed"],
                                                         "V": self._lookupValue(self.verticalVaneTranslate, Melcloud.ata[deviceName]["VaneVertical"]),
                                                         "H": self._lookupValue(self.horizontalVaneTranslate, Melcloud.ata[deviceName]["VaneHorizontal"])}}

            # return self.devices[deviceName]["CurrentState"]
            return copy.deepcopy(self.devices[deviceName])

        except Exception as e:
            self.log.error("Exception in getOneDevice", deviceName=deviceName, error=e)

    async def getAllDevice(self):
        await self._validateToken()
        if not Melcloud.devices:
            await self.getDevices()

        for device_k, device_v in Melcloud.devices.items():
            await self.getOneDevice(device_k)

        return Melcloud.devices

    async def getDevicesInfo(self):
        return Melcloud.devices

    def printDevicesInfo(self):
        for device in Melcloud.devices:
            self.printOneDevicesInfo(device)

    def printOneDevicesInfo(self, deviceName):
        print(f"{deviceName} :")
        print(f"DeviceID: {Melcloud.devices[deviceName]['DeviceID']}")
        print(f"BuildingID: {Melcloud.devices[deviceName]['BuildingID']}")
        print(f"CurrentEnergyConsumed: {Melcloud.devices[deviceName]['CurrentEnergyConsumed']}")
        print(f"LastTimeStamp: {Melcloud.devices[deviceName]['LastTimeStamp']}")
        print(f"RoomTemperature: {Melcloud.devices[deviceName]['RoomTemp']}")
        print(f"""P : {Melcloud.devices[deviceName]["CurrentState"]['P']}, M : {Melcloud.devices[deviceName]["CurrentState"]['M']}, T : {Melcloud.devices[deviceName]["CurrentState"]['T']}, F : {Melcloud.devices[deviceName]["CurrentState"]['F']}, V : {Melcloud.devices[deviceName]["CurrentState"]['V']}, H : {Melcloud.devices[deviceName]["CurrentState"]['H']}""")
        print(f"hasPendingCommand: {Melcloud.devices[deviceName]['hasPendingCommand']}")
        print("\n")

    async def setOneDeviceInfo(self, deviceName, desiredState):
        try:
            await self._validateToken()
            # Melcloud.ata[deviceName]["DeviceID"] = Melcloud.devices[deviceName]["DeviceID"]

            if desiredState.get("P") is not None:
                Melcloud.ata[deviceName]["Power"] = self.powerModeTranslate[desiredState["P"]]
                Melcloud.ata[deviceName]["EffectiveFlags"] |= 0x01

            if desiredState.get("M") is not None:
                Melcloud.ata[deviceName]["OperationMode"] = self.operationModeTranslate[desiredState["M"]]
                Melcloud.ata[deviceName]["EffectiveFlags"] |= 0x02

            if desiredState.get("T") is not None:
                Melcloud.ata[deviceName]["SetTemperature"] = desiredState["T"]
                Melcloud.ata[deviceName]["EffectiveFlags"] |= 0x04

            if desiredState.get("F") is not None:
                Melcloud.ata[deviceName]["SetFanSpeed"] = desiredState["F"]
                Melcloud.ata[deviceName]["EffectiveFlags"] |= 0x08

            if desiredState.get("V") is not None:
                Melcloud.ata[deviceName]["VaneVertical"] = self.verticalVaneTranslate[desiredState["V"]]
                Melcloud.ata[deviceName]["EffectiveFlags"] |= 0x10

            if desiredState.get("H") is not None:
                Melcloud.ata[deviceName]["VaneHorizontal"] = self.horizontalVaneTranslate[desiredState["H"]]
                Melcloud.ata[deviceName]["EffectiveFlags"] |= 0x100

            # await asyncio.sleep(60)
            Melcloud.ata[deviceName] = await self._doSession(method="POST", url="/Mitsubishi.Wifi.Client/Device/SetAta", headers=self.headers, data=ujson.dumps(Melcloud.ata[deviceName]))

            Melcloud.ata[deviceName]["EffectiveFlags"] = 0

            return "OK"

        except Exception as e:
            self.log.error("Exception in setOneDeviceInfo", deviceName=deviceName, error=e)
            return False
