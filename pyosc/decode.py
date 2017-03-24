import string
import math
import struct

def _readString(data):
    length   = string.find(data,"\0")
    nextData = int(math.ceil((length+1) / 4.0) * 4)
    return (data[0:length], data[nextData:])

def _readBlob(data):
    length   = struct.unpack(">i", data[0:4])[0]
    nextData = int(math.ceil((length) / 4.0) * 4) + 4
    return (data[4:length+4], data[nextData:])

def _readInt(data):
    if(len(data)<4):
        print ("Error: too few bytes for int", data, len(data))
        rest = data
        integer = 0
    else:
        integer = struct.unpack(">i", data[0:4])[0]
        rest	= data[4:]

    return (integer, rest)

def _readLong(data):
    high, low = struct.unpack(">ll", data[0:8])
    big = (long(high) << 32) + low
    rest = data[8:]
    return (big, rest)

def _readTimeTag(data):
    high, low = struct.unpack(">LL", data[0:8])
    if (high == 0) and (low <= 1):
        time = 0.0
    else:
        time = int(NTP_epoch + high) + float(low / NTP_units_per_second)
    rest = data[8:]
    return (time, rest)

def _readFloat(data):
    if(len(data)<4):
        print ("Error: too few bytes for float", data, len(data))
        rest = data
        float = 0
    else:
        float = struct.unpack(">f", data[0:4])[0]
        rest  = data[4:]
    return (float, rest)

def _readDouble(data):
    if(len(data)<8):
        print ("Error: too few bytes for double", data, len(data))
        rest = data
        float = 0
    else:
        float = struct.unpack(">d", data[0:8])[0]
        rest  = data[8:]
    return (float, rest)

def _readTwos(data):
    if(len(data)<2):
        print ("Error: too few bytes for double", data, len(data))
        rest = data
        val = 0
    else:
        val = struct.unpack(">q", data[0:8])[0]
        rest  = data[8:]
    return (val, rest)

def _readTrue(data):
    return (True, "")

def _readFalse(data):
    return (True, "")

def _readNone(data):
    return (None, "")


def decodeOSC(data):
    """Converts a binary OSC message to a Python list."""
    table = {
            "i" : _readInt,
            "f" : _readFloat,
            "s" : _readString,
            "b" : _readBlob,
            "d" : _readDouble,
            "t" : _readTimeTag,
            "h" : _readTwos,
            "T" : _readTrue,
            "F" : _readFalse,
            "N" : _readNone,
        }
    decoded = []
    address,  rest = _readString(data)
    if address.startswith(","):
        typetags = address
        address = ""
    else:
        typetags = ""

    if address == "#bundle":
        time, rest = _readTimeTag(rest)
        decoded.append(address)
        decoded.append(time)
        while len(rest)>0:
            length, rest = _readInt(rest)
            decoded.append(decodeOSC(rest[:length]))
            rest = rest[length:]

    elif len(rest)>0:
        if not len(typetags):
            typetags, rest = _readString(rest)
        decoded.append(address)
        decoded.append(typetags)
        if typetags.startswith(","):
            for tag in typetags[1:]:
                value, rest = table[tag](rest)
                decoded.append(value)
        else:
            raise OSCError("OSCMessage's typetag-string lacks the magic ','")

    return decoded
