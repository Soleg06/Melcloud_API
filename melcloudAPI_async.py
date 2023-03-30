#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
from pprint import pprint

import aiohttp
import arrow
import ujson


class Melcloud:

    devices = {}

    def __init__(self):
        self.headers = {
            "Content-Type": "application/json",
            "Host": "app.melcloud.com",
            "Cache-Control": "no-cache"
        }

        self.powerModeTranslate = {
            0: False,
            1: True
        }

        self.operationModeTranslate = {
            0: 1,  # Heat
            1: 3,  # AC
            2: 8,  # Auto
            4: 7,  # Fan
            5: 2   # Dry
        }

        self.horizontalVaneTranslate = {
            0: 0,  # _Auto
            1: 1,   # Pos 1
            2: 2,   # Pos 2
            3: 3,   # Pos 3
            4: 4,   # Pos 4
            5: 5,   # Pos 5
            6: 8,   # Split
            7: 12   # Swing
        }

        self.verticalVaneTranslate = {
            0: 0,  # _Auto
            1: 1,   # Pos 1
            2: 2,   # Pos 2
            3: 3,   # Pos 3
            4: 4,   # Pos 4
            5: 5,   # Pos 5
            6: 7    # Swing
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
        except Exception as e:
            print(f"Error occurred: {e}")
            return None

    async def login(self, user, password):
        data = {
            "Email": user,
            "Password": password,
            "Language": 18,
            "AppVersion": "1.23.4.0"
        }

        self.devices = dict()
        self.ata = dict()

        try:
            out = await self._doSession(method="POST", url="/Mitsubishi.Wifi.Client/Login/ClientLogin", headers=self.headers, data=ujson.dumps(data))
            token = out['LoginData']['ContextKey']
            self.tokenExpires = arrow.get(out['LoginData']['Expiry']).to("Europe/Stockholm")
            self.headers["X-MitsContextKey"] = token

        except Exception as e:
            print(e)

    async def _validateToken(self):
        now = arrow.now("Europe/Stockholm")
        if now >= self.tokenExpires:
            print("login again")
            await self.login()

    def _lookupValue(self, di, value):
        # result = [k for k in di.items() if k[1] == value][0][0]
        for key, val in di.items():
            if val == value:
                return key
        return None

    async def logout(self):
        # await self.session.close()
        pass

    async def getDevices(self):
        if not self.devices:
            await self._validateToken()
            try:
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

                for aa in allDevices:
                    self.devices[aa["DeviceName"]] = {}
                    self.devices[aa["DeviceName"]]["DeviceID"] = aa["DeviceID"]
                    self.devices[aa["DeviceName"]]["BuildingID"] = aa["BuildingID"]
                    self.devices[aa["DeviceName"]]["CurrentEnergyConsumed"] = aa["Device"]["CurrentEnergyConsumed"]
                    self.devices[aa["DeviceName"]]["LastTimeStamp"] = arrow.get(aa["Device"]["LastTimeStamp"]).format("YYYY-MM-DD HH:mm")

            except Exception as e:
                print(e)

    async def getOneDevice(self, devName, deviceID, buildingID):
        params = {
            "id": deviceID,
            "buildingID": buildingID
        }

        try:
            self.ata = await self._doSession(method="GET", url="/Mitsubishi.Wifi.Client/Device/Get", headers=self.headers, params=params)

            # for device in self.devices:
            #    if (self.devices[device]["DeviceID"] == self.ata["DeviceID"]):
            #        devName = device

            self.devices[devName]["RoomTemp"] = self.ata["RoomTemperature"]

            # print(f"P  {self.ata['Power']}")
            # print(f"M  {self.ata['OperationMode']}")
            # print(f"T  {self.ata['SetTemperature']}")
            # print(f"F  {self.ata['SetFanSpeed']}")
            # print(f"V  {self.ata['VaneVertical']}")
            # print(f"H  {self.ata['VaneHorizontal']}")

            self.devices[devName]["CurrentState"] = dict()
            self.devices[devName]["CurrentState"]["P"] = self._lookupValue(self.powerModeTranslate, self.ata["Power"])
            self.devices[devName]["CurrentState"]["M"] = self._lookupValue(self.operationModeTranslate, self.ata["OperationMode"])
            self.devices[devName]["CurrentState"]["T"] = self.ata["SetTemperature"]
            self.devices[devName]["CurrentState"]["F"] = self.ata["SetFanSpeed"]
            self.devices[devName]["CurrentState"]["V"] = self._lookupValue(self.verticalVaneTranslate, self.ata["VaneVertical"])
            self.devices[devName]["CurrentState"]["H"] = self._lookupValue(self.horizontalVaneTranslate, self.ata["VaneHorizontal"])
            self.devices[devName]["hasPendingCommand"] = self.ata["HasPendingCommand"]

        except Exception as e:
            print(e)

    async def getAllDevice(self):
        await self._validateToken()
        await self.getDevices()

        for device_k, device_v in self.devices.items():
            await self.getOneDevice(device_k, device_v["DeviceID"], device_v["BuildingID"])

        return self.devices

    async def getDevicesInfo(self):
        return self.devices

    async def printDevicesInfo(self):
        for device in self.devices:
            print(f"{device} :")
            print(f"DeviceID: {self.devices[device]['DeviceID']}")
            print(f"BuildingID: {self.devices[device]['BuildingID']}")
            print(f"CurrentEnergyConsumed: {self.devices[device]['CurrentEnergyConsumed']}")
            print(f"LastTimeStamp: {self.devices[device]['LastTimeStamp']}")
            print(f"RoomTemperature: {self.devices[device]['RoomTemp']}")
            print(f"""P : {self.devices[device]["CurrentState"]['P']}, M : {self.devices[device]["CurrentState"]['M']}, T : {self.devices[device]["CurrentState"]['T']}, F : {self.devices[device]["CurrentState"]['F']}, V : {self.devices[device]["CurrentState"]['V']}, H : {self.devices[device]["CurrentState"]['H']}""")
            print("\n")

    async def setOneDeviceInfo(self, deviceName, desiredState):
        await self._validateToken()
        try:
            self.ata["DeviceID"] = self.devices[deviceName]["DeviceID"]
            # self.ata["EffectiveFlags"] = 8

            if desiredState.get("P") is not None:
                self.ata["Power"] = self.powerModeTranslate[desiredState["P"]]
                self.ata["EffectiveFlags"] |= 0x01

            if desiredState.get("M") is not None:
                self.ata["OperationMode"] = self.operationModeTranslate[desiredState["M"]]
                self.ata["EffectiveFlags"] |= 0x02

            if desiredState.get("T") is not None:
                self.ata["SetTemperature"] = desiredState["T"]
                self.ata["EffectiveFlags"] |= 0x04

            if desiredState.get("F") is not None:
                self.ata["SetFanSpeed"] = desiredState["F"]
                self.ata["EffectiveFlags"] |= 0x08

            if desiredState.get("V") is not None:
                self.ata["VaneVertical"] = self.verticalVaneTranslate[desiredState["V"]]
                self.ata["EffectiveFlags"] |= 0x10

            if desiredState.get("H") is not None:
                self.ata["VaneHorizontal"] = self.horizontalVaneTranslate[desiredState["H"]]
                self.ata["EffectiveFlags"] |= 0x100

            await asyncio.sleep(60)
            self.ata = await self._doSession(method="POST", url="/Mitsubishi.Wifi.Client/Device/SetAta", headers=self.headers, data=ujson.dumps(self.ata))

            self.ata["EffectiveFlags"] = 0

        except Exception as e:
            print(e)

        return self.ata
