#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import json
import arrow

class Melcloud:

    def __init__(self):
        self.headers = {
            "Content-Type":"application/json",
            "Host":"app.melcloud.com",
            "Cache-Control":"no-cache"
            }
        self.session = requests.Session()

    def login(self, user, password):

        data = {
            "Email":user,
            "Password":password,
            "Language":18,   # Swedish
            "AppVersion":"1.23.4.0"
            }

        r = self.session.post("https://app.melcloud.com/Mitsubishi.Wifi.Client/Login/ClientLogin", headers=self.headers, data=json.dumps(data))

        out= json.loads(r.text)
        token = out['LoginData']['ContextKey']
        self.headers["X-MitsContextKey"]=token
        self.devices = dict()
        self.ata = dict()

    def _getDevices(self):

        r = self.session.get("https://app.melcloud.com/Mitsubishi.Wifi.Client/User/Listdevices", headers=self.headers)
        entries = json.loads(r.text)

        allDevices = []

        for entry in entries:
            allDevices += entry["Structure"]["Devices"]

            for area in entry["Structure"]["Areas"]:
                allDevices += area["Devices"]

            for floor in entry["Structure"]["Floors"]:
                allDevices +=  floor["Devices"]

                for area in floor["Areas"]:
                    allDevices += area["Devices"]

        for aa in allDevices:
            self.devices[aa["DeviceName"]] = {}
            self.devices[aa["DeviceName"]]["DeviceID"] = aa["DeviceID"]
            self.devices[aa["DeviceName"]]["BuildingID"] = aa["BuildingID"]
            self.devices[aa["DeviceName"]]["CurrentEnergyConsumed"] = aa["Device"]["CurrentEnergyConsumed"]
            self.devices[aa["DeviceName"]]["LastTimeStamp"] = arrow.get(aa["Device"]["LastTimeStamp"]).format("YYYY-MM-DD HH:mm")



    def getOneDevice(self, deviceID, buildingID):

        params = {
                "id": deviceID,
                "buildingID": buildingID
                }

        r = self.session.get("https://app.melcloud.com/Mitsubishi.Wifi.Client/Device/Get", headers=self.headers, params = params)
        self.ata = json.loads(r.text)

        for device in self.devices:
            if (self.devices[device]["DeviceID"] == self.ata["DeviceID"]):
                devName = device

        self.devices[devName]["RoomTemp"] = self.ata["RoomTemperature"]

        self.devices[devName]["CurrentState"] = dict()
        if (self.ata["Power"]) :
            self.devices[devName]["CurrentState"]["P"] = 1
        else:
            self.devices[devName]["CurrentState"]["P"] = 0
        self.devices[devName]["CurrentState"]["M"] = self.ata["OperationMode"]
        self.devices[devName]["CurrentState"]["T"] = self.ata["SetTemperature"]
        self.devices[devName]["CurrentState"]["F"] = self.ata["SetFanSpeed"]
        self.devices[devName]["CurrentState"]["V"] = self.ata["VaneVertical"]
        self.devices[devName]["CurrentState"]["H"] = self.ata["VaneHorizontal"]


    def getAllDevice(self):

        self._getDevices()

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

        powerModeTranslate = {
                0 : False,
                1 : True
                }

        operationModeTranslate  = {
                0 : 1,  # Heat
                1 : 3,  # AC
                2 : 8,  # Auto
                4 : 7,  # Fan
                5 : 2   # Dry
                }

        horizontalVaneTranslate = {
               0 : 0,   #_Auto
               1 : 1,   # Pos 1
               2 : 2,   # Pos 2
               3 : 3,   # Pos 3
               4 : 4,   # Pos 4
               5 : 5,   # Pos 5
               6 : 8,   # Split
               7 : 12   # Swing
               }

        verticalVaneTranslate = {
               0 : 0,   #_Auto
               1 : 1,   # Pos 1
               2 : 2,   # Pos 2
               3 : 3,   # Pos 3
               4 : 4,   # Pos 4
               5 : 5,   # Pos 5
               6 : 7    # Swing
               }

        self.ata["DeviceID"] = self.devices[deviceName]["DeviceID"]
        #self.ata["EffectiveFlags"] = 8

        if desiredState.get("P") != None:
            self.ata["Power"] = powerModeTranslate[desiredState["P"]]
            self.ata["EffectiveFlags"] |= 0x01

        if desiredState.get("M") != None:
            self.ata["OperationMode"] = operationModeTranslate[desiredState["M"]]
            self.ata["EffectiveFlags"] |= 0x02

        if desiredState.get("T") != None:
           self.ata["SetTemperature"] = desiredState["T"]
           self.ata["EffectiveFlags"] |= 0x04

        if desiredState.get("F") != None:
            self.ata["SetFanSpeed"] = desiredState["F"]
            self.ata["EffectiveFlags"] |= 0x08

        if desiredState.get("V") != None:
            self.ata["VaneVertical"] = verticalVaneTranslate[desiredState["V"]]
            self.ata["EffectiveFlags"] |= 0x10

        if desiredState.get("H") != None:
            self.ata["VaneHorizontal"] = horizontalVaneTranslate[desiredState["H"]]
            self.ata["EffectiveFlags"] |= 0x100

        r = self.session.post(" https://app.melcloud.com/Mitsubishi.Wifi.Client/Device/SetAta", headers=self.headers, data=json.dumps(self.ata))
        self.ata = json.loads(r.text)
        self.ata["EffectiveFlags"] = 0


