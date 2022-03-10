# Melcloud_API

A one-file python3 program for reading and changing status of Mitsubishi HVAC devices through Melcloud API. This work is based on the good work of https://github.com/vilppuvuorinen/pymelcloud

The program can be places in your own integration as one file, it doesen't requiere any installations

Please find example usage in the example file. The funcions usally return dicts that I have found the be useful in my other intregrations.

Settting the desired state to the HVAC uses the name of the HVAC and a dict with the state you want to change to such as this:

{"P":0, "M":1, "T":21, "F":3, "H":0, "V":0}

where

P : Power           (0 = off, 1 = on)
M : Mode            (0 = Heat, 1 = AC, 2 = Auto, 4 = Fan, 5 = Dry)
T : Temperature     (10 -30 degrees)
F : Fan             (0=auto, 1-4 fan modes)
V : Vertical vane   (0 = auto, 6 = split, 7 = swing, 1-5 vane positions)
H : Horizontal vane (0 = auto, 7 = swing, 1-5 vane positions)


note you only need to send the state that you want changed:
i.e if you want to change Fan to state 4 you just send

{"F":3}
