import melcloudAPI
from pprint import pprint

mc = melcloudAPI.Melcloud()
mc.login("firstname.lastname@someting.com","**********")
pprint(mc.getAllDevice())

mc.printDevicesInfo()

mc.setOneDeviceInfo("Vp_nere", {"P":0, "M":1, "T":21, "F":3, "H":0, "V":0})
mc.setOneDeviceInfo("Vp_nere", {"T":21})
mc.setOneDeviceInfo("Vp_uppe", {"P":1})
