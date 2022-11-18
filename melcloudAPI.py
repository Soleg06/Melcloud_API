#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pprint import pprint

import arrow
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

DEFAULT_TIMEOUT = 20  # seconds

class TimeoutHTTPAdapter(HTTPAdapter):

    def __init__(self, *args, **kwargs):
        self.timeout = DEFAULT_TIMEOUT
        if "timeout" in kwargs:
            self.timeout = kwargs["timeout"]
            del kwargs["timeout"]
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        timeout = kwargs.get("timeout")
        if timeout is None:
            kwargs["timeout"] = self.timeout
        return super().send(request, **kwargs)


class Melcloud:

    def __init__(self):
        self.session = requests.Session()

        assert_status_hook = lambda response, * \
            args, **kwargs: response.raise_for_status()
        self.session.hooks["response"].append(assert_status_hook)

        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "¨TRACE", "POST"])

        self.session.mount("http://", TimeoutHTTPAdapter(max_retries=retry_strategy))
        self.session.mount("https://", TimeoutHTTPAdapter(max_retries=retry_strategy))

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

    def login(self, user, password):

        data = {
            "Email": user,
            "Password": password,
            "Language": 18,
            "AppVersion": "1.23.4.0"
        }

        self.devices = dict()
        self.ata = dict()

        try:
            response = self.session.post("https://app.melcloud.com/Mitsubishi.Wifi.Client/Login/ClientLogin", headers=self.headers, data=json.dumps(data))
            # response.raise_for_status()
            out = json.loads(response.text)
            # pprint(out)
            token = out['LoginData']['ContextKey']
            self.headers["X-MitsContextKey"] = token

        except Exception as e:
            print(e)

    def _lookupValue(self, di, value):
        result = [k for k in di.items() if k[1] == value][0][0]
        return result

    def getDevices(self):

        try:
            response = self.session.get("https://app.melcloud.com/Mitsubishi.Wifi.Client/User/Listdevices", headers=self.headers)
            # response.raise_for_status()
            entries = json.loads(response.text)

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

    def getOneDevice(self, deviceID, buildingID):

        params = {
            "id": deviceID,
            "buildingID": buildingID
        }

        try:
            response = self.session.get("https://app.melcloud.com/Mitsubishi.Wifi.Client/Device/Get", headers=self.headers, params=params)
            # response.raise_for_status()
            self.ata = json.loads(response.text)

            for device in self.devices:
                if (self.devices[device]["DeviceID"] == self.ata["DeviceID"]):
                    devName = device

            self.devices[devName]["RoomTemp"] = self.ata["RoomTemperature"]

            #print(f"P  {self.ata['Power']}")
            #print(f"M  {self.ata['OperationMode']}")
            #print(f"T  {self.ata['SetTemperature']}")
            #print(f"F  {self.ata['SetFanSpeed']}")
            #print(f"V  {self.ata['VaneVertical']}")
            #print(f"H  {self.ata['VaneHorizontal']}")

            self.devices[devName]["CurrentState"] = dict()
            self.devices[devName]["CurrentState"]["P"] = self._lookupValue(self.powerModeTranslate, self.ata["Power"])
            self.devices[devName]["CurrentState"]["M"] = self._lookupValue(self.operationModeTranslate, self.ata["OperationMode"])
            self.devices[devName]["CurrentState"]["T"] = self.ata["SetTemperature"]
            self.devices[devName]["CurrentState"]["F"] = self.ata["SetFanSpeed"]
            self.devices[devName]["CurrentState"]["V"] = self._lookupValue(self.verticalVaneTranslate, self.ata["VaneVertical"])
            self.devices[devName]["CurrentState"]["H"] = self._lookupValue(self.horizontalVaneTranslate, self.ata["VaneHorizontal"])

        except Exception as e:
            print(e)

    def getAllDevice(self):

        self.getDevices()

        for device in self.devices:
            self.getOneDevice(self.devices[device]["DeviceID"], self.devices[device]["BuildingID"])

        return self.devices


    def getDevicesInfo(self):

        return self.devices

    def printDevicesInfo(self):

        for device in self.devices:
            print(f"{device} :")
            print(f"DeviceID: {self.devices[device]['DeviceID']}")
            print(f"BuildingID: {self.devices[device]['BuildingID']}")
            print(f"CurrentEnergyConsumed: {self.devices[device]['CurrentEnergyConsumed']}")
            print(f"LastTimeStamp: {self.devices[device]['LastTimeStamp']}")
            print(f"RoomTemperature: {self.devices[device]['RoomTemp']}")
            print(f"""P : {self.devices[device]["CurrentState"]['P']}, M : {self.devices[device]["CurrentState"]['M']}, T : {self.devices[device]["CurrentState"]['T']}, F : {self.devices[device]["CurrentState"]['F']}, V : {self.devices[device]["CurrentState"]['V']}, H : {self.devices[device]["CurrentState"]['H']}""")
            print("\n")

    def setOneDeviceInfo(self, deviceName, desiredState):

        try:
            self.ata["DeviceID"] = self.devices[deviceName]["DeviceID"]
            #self.ata["EffectiveFlags"] = 8

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

            response = self.session.post(" https://app.melcloud.com/Mitsubishi.Wifi.Client/Device/SetAta", headers=self.headers, data=json.dumps(self.ata))
            # response.raise_for_status()
            self.ata = json.loads(response.text)
            self.ata["EffectiveFlags"] = 0

        except Exception as e:
            print(e)

        return self.ata
