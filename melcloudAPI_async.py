#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import structlog

import aiohttp
import arrow
import ujson

from API.staffstuff_asyncio import MyLock


class Melcloud:
    
    log = structlog.get_logger(__name__)

    powerModeTranslate = {
        0: False,
        1: True
    }

    operationModeTranslate = {
        0: 1,  # Heat
        1: 3,  # AC
        2: 8,  # Auto
        4: 7,  # Fan
        5: 2   # Dry
    }

    horizontalVaneTranslate = {
        0: 0,   # _Auto
        1: 1,   # Pos 1
        2: 2,   # Pos 2
        3: 3,   # Pos 3
        4: 4,   # Pos 4
        5: 5,   # Pos 5
        6: 8,   # Split
        7: 12   # Swing
    }

    verticalVaneTranslate = {
        0: 0,   # _Auto
        1: 1,   # Pos 1
        2: 2,   # Pos 2
        3: 3,   # Pos 3
        4: 4,   # Pos 4
        5: 5,   # Pos 5
        6: 7    # Swing
    }

    devices = {}
    ata = {}
    validateLock = MyLock()

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
        try:
            await asyncio.sleep(1)
            async with self.session.request(method=method, url=url, headers=headers, data=data, params=params, auth=auth) as response:
                try:
                    return await response.json()
                except:
                    return await response.text()
                
        except aiohttp.ClientConnectorError as e:
            self.log.error("Exception in _doSession Failed to connect to host", error=e)
            pass
                
        except Exception as e:
            self.log.error("Exception in _doSession", error=e)
            return None

    async def login(self):
        data = {
            "Email": self.username,
            "Password": self.password,
            "Language": 18,
            "AppVersion": "1.23.4.0"
        }

        try:
            out = await self._doSession(method="POST", url="/Mitsubishi.Wifi.Client/Login/ClientLogin", headers=self.headers, data=ujson.dumps(data))
            token = out['LoginData']['ContextKey']
            self.tokenExpires = arrow.get(out['LoginData']['Expiry']).to("Europe/Stockholm")
            self.headers["X-MitsContextKey"] = token
            if not Melcloud.devices:
                await self.getDevices()

        except Exception as e:
            self.log.error("Exception in login", error=e)

    async def _validateToken(self):
        now = arrow.now("Europe/Stockholm")
        await Melcloud.validateLock.acquire()
        if now >= self.tokenExpires:
            self.log.info("Melcloud logging in again")
            await self.login()
        Melcloud.validateLock.release()

    def _lookupValue(self, di, value):
        for key, val in di.items():
            if val == value:
                return key
        return None

    async def logout(self):
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
                                                "LastTimeStamp": arrow.get(device["Device"]["LastTimeStamp"]).format("YYYY-MM-DD HH:mm:ss")
                                                }

        except Exception as e:
            self.log.error("Exception in getDevices", error=e)

    async def getOneDevice(self, deviceName):
        params = {
            "id": Melcloud.devices[deviceName]['DeviceID'],
            "buildingID": Melcloud.devices[deviceName]['BuildingID']
        }
        try:
            await self._validateToken()
            Melcloud.ata[deviceName] = await self._doSession(method="GET", url="/Mitsubishi.Wifi.Client/Device/Get", headers=self.headers, params=params)

            self.devices[deviceName]["RoomTemp"] = Melcloud.ata[deviceName]["RoomTemperature"]
            self.devices[deviceName]["hasPendingCommand"] = Melcloud.ata[deviceName]["HasPendingCommand"]
            self.devices[deviceName]["CurrentState"] = {"P": self._lookupValue(self.powerModeTranslate, Melcloud.ata[deviceName]["Power"]),
                                                        "M": self._lookupValue(self.operationModeTranslate, Melcloud.ata[deviceName]["OperationMode"]),
                                                        "T": Melcloud.ata[deviceName]["SetTemperature"],
                                                        "F": Melcloud.ata[deviceName]["SetFanSpeed"],
                                                        "V": self._lookupValue(self.verticalVaneTranslate, Melcloud.ata[deviceName]["VaneVertical"]),
                                                        "H": self._lookupValue(self.horizontalVaneTranslate, Melcloud.ata[deviceName]["VaneHorizontal"])
                                                        }

        except Exception as e:
            self.log.error("Exception in getOneDevice", error=e)

        #return self.devices[deviceName]["CurrentState"]
        return self.devices[deviceName].copy()

    # async def getAllDevice(self):
    #    await self._validateToken()
    #    await self.getDevices()

    #    for device_k, device_v in Melcloud.devices.items():
    #        await self.getOneDevice(device_k, device_v["DeviceID"], device_v["BuildingID"])

    #    return Melcloud.devices

    async def getDevicesInfo(self):
        return Melcloud.devices

    # def printDevicesInfo(self):
    #    for device in Melcloud.devices:
    #        print(f"{device} :")
    #        print(f"DeviceID: {Melcloud.devices[device]['DeviceID']}")
    #        print(f"BuildingID: {Melcloud.devices[device]['BuildingID']}")
    #        print(f"CurrentEnergyConsumed: {Melcloud.devices[device]['CurrentEnergyConsumed']}")
    #        print(f"LastTimeStamp: {Melcloud.devices[device]['LastTimeStamp']}")
    #        print(f"RoomTemperature: {Melcloud.devices[device]['RoomTemp']}")
    #        print(f"""P : {Melcloud.devices[device]["CurrentState"]['P']}, M : {Melcloud.devices[device]["CurrentState"]['M']}, T : {Melcloud.devices[device]["CurrentState"]['T']}, F : {Melcloud.devices[device]["CurrentState"]['F']}, V : {Melcloud.devices[device]["CurrentState"]['V']}, H : {Melcloud.devices[device]["CurrentState"]['H']}""")
    #        print("\n")

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

            return desiredState

        except Exception as e:
            self.log.error("Exception in setOneDeviceInfo", error=e)
            return False
