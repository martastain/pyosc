import math
import struct

from .common import *

def OSCString(next):
    OSCstringLength = math.ceil((len(next)+1) / 4.0) * 4
    return struct.pack(">%ds" % (OSCstringLength), str(next))

def OSCBlob(next):
    if type(next) in types.StringTypes:
        OSCblobLength = math.ceil((len(next)) / 4.0) * 4
        binary = struct.pack(">i%ds" % (OSCblobLength), OSCblobLength, next)
    else:
        binary = ""
    return binary


def OSCArgument(next, typehint=None):
    if not typehint:
        if type(next) in FloatTypes:
            binary  = struct.pack(">f", float(next))
            tag = 'f'
        elif type(next) in IntTypes:
            binary  = struct.pack(">i", int(next))
            tag = 'i'
        else:
            binary  = OSCString(next)
            tag = 's'

    elif typehint == 'd':
        try:
            binary  = struct.pack(">d", float(next))
            tag = 'd'
        except ValueError:
            binary  = OSCString(next)
            tag = 's'

    elif typehint == 'f':
        try:
            binary  = struct.pack(">f", float(next))
            tag = 'f'
        except ValueError:
            binary  = OSCString(next)
            tag = 's'
    elif typehint == 'i':
        try:
            binary  = struct.pack(">i", int(next))
            tag = 'i'
        except ValueError:
            binary  = OSCString(next)
            tag = 's'
    else:
        binary  = OSCString(next)
        tag = 's'
    return (tag, binary)



def OSCTimeTag(time):
    if time > 0:
        fract, secs = math.modf(time)
        secs = secs - NTP_epoch
        binary = struct.pack('>LL', long(secs), long(fract * NTP_units_per_second))
    else:
        binary = struct.pack('>LL', 0, 1)
    return binary
