import sys
import types
import calendar

FloatTypes = [float]
IntTypes = [int]
StringTypes = [str]
DictTypes = [dict]
TupleTypes = [tuple]
CallableTypes = [types.FunctionType, types.MethodType]

if sys.version_info[:2] >= (3, 0):
    PYTHON_VERSION = 3
    decode_if_py3 = lambda x: x.decode("utf-8")
    encode_if_py3 = lambda x: bytes(x, "utf-8")
    StringTypes = [str]
else:
    PYTHON_VERSION = 2
    decode_if_py3 = lambda x: x
    encode_if_py3 = lambda x: x
    StringTypes = [str, unicode]

version = ("0.3","6", "$Rev: 6382 $"[6:-2])

NTP_epoch = calendar.timegm((1900,1,1,0,0,0)) # NTP time started in 1 Jan 1900
NTP_units_per_second = 0x100000000 # about 232 picoseconds

#
# numpy/scipy support:
#

try:
    from numpy import typeDict
    for ftype in ['float32', 'float64', 'float128']:
        try:
            FloatTypes.append(typeDict[ftype])
        except KeyError:
            pass

    for itype in ['int8', 'int16', 'int32', 'int64']:
        try:
            IntTypes.append(typeDict[itype])
            IntTypes.append(typeDict['u' + itype])
        except KeyError:
            pass
    del typeDict, ftype, itype
except ImportError:
	pass

