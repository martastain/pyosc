from .encode import *
from .decode import *

__all__ = ["OSCMessage", "OSCBundle"]

class OSCMessage(object):
    def __init__(self, address="", *args):
        """Instantiate a new OSCMessage.
        The OSC-address can be specified with the 'address' argument.
        The rest of the arguments are appended as data.
        """
        self.clear(address)
        if len(args)>0:
            self.append(*args)

    def setAddress(self, address):
        """Set or change the OSC-address
        """
        self.address = address

    def clear(self, address=""):
        """Clear (or set a new) OSC-address and clear any arguments appended so far
        """
        self.address  = address
        self.clearData()

    def clearData(self):
        """Clear any arguments appended so far
        """
        self.typetags = ","
        self.message  = ""

    def append(self, argument, typehint=None):
        """Appends data to the message, updating the typetags based on
        the argument's type. If the argument is a blob (counted
        string) pass in 'b' as typehint.
        'argument' may also be a list or tuple, in which case its elements
        will get appended one-by-one, all using the provided typehint
        """
        if type(argument) == types.DictType:
            argument = argument.items()
        elif isinstance(argument, OSCMessage):
            raise TypeError("Can only append 'OSCMessage' to 'OSCBundle'")
        if hasattr(argument, '__iter__'):
            for arg in argument:
                self.append(arg, typehint)
            return
        if typehint == 'b':
            binary = OSCBlob(argument)
            tag = 'b'
        elif typehint == 't':
            binary = OSCTimeTag(argument)
            tag = 't'
        else:
            tag, binary = OSCArgument(argument, typehint)
        self.typetags += tag
        self.message += binary

    def getBinary(self):
        """Returns the binary representation of the message
        """
        binary = OSCString(self.address)
        binary += OSCString(self.typetags)
        binary += self.message
        return binary

    def __repr__(self):
        """Returns a string containing the decode Message
        """
        return str(decodeOSC(self.getBinary()))

    def __str__(self):
        """Returns the Message's address and contents as a string.
        """
        return "%s %s" % (self.address, str(self.values()))

    def __len__(self):
        """Returns the number of arguments appended so far
        """
        return (len(self.typetags) - 1)

    def __eq__(self, other):
        """Return True if two OSCMessages have the same address & content
        """
        if not isinstance(other, self.__class__):
                return False
        return (self.address == other.address) and (self.typetags == other.typetags) and (self.message == other.message)

    def __ne__(self, other):
        """Return (not self.__eq__(other))
        """
        return not self.__eq__(other)

    def __add__(self, values):
        """Returns a copy of self, with the contents of 'values' appended
        (see the 'extend()' method, below)
        """
        msg = self.copy()
        msg.extend(values)
        return msg

    def __iadd__(self, values):
        """Appends the contents of 'values'
        (equivalent to 'extend()', below)
        Returns self
        """
        self.extend(values)
        return self

    def __radd__(self, values):
        """Appends the contents of this OSCMessage to 'values'
        Returns the extended 'values' (list or tuple)
        """
        out = list(values)
        out.extend(self.values())
        if type(values) == types.TupleType:
                return tuple(out)
        return out

    def _reencode(self, items):
        """Erase & rebuild the OSCMessage contents from the given
        list of (typehint, value) tuples"""
        self.clearData()
        for item in items:
            self.append(item[1], item[0])

    def values(self):
        """Returns a list of the arguments appended so far
        """
        return decodeOSC(self.getBinary())[2:]

    def tags(self):
        """Returns a list of typetags of the appended arguments
        """
        return list(self.typetags.lstrip(','))

    def items(self):
        """Returns a list of (typetag, value) tuples for
        the arguments appended so far
        """
        out = []
        values = self.values()
        typetags = self.tags()
        for i in range(len(values)):
                out.append((typetags[i], values[i]))
        return out

    def __contains__(self, val):
        """Test if the given value appears in the OSCMessage's arguments
        """
        return (val in self.values())

    def __getitem__(self, i):
        """Returns the indicated argument (or slice)
        """
        return self.values()[i]

    def __delitem__(self, i):
        """Removes the indicated argument (or slice)
        """
        items = self.items()
        del items[i]
        self._reencode(items)

    def _buildItemList(self, values, typehint=None):
        if isinstance(values, OSCMessage):
            items = values.items()
        elif type(values) == types.ListType:
            items = []
            for val in values:
                if type(val) == types.TupleType:
                    items.append(val[:2])
                else:
                    items.append((typehint, val))
        elif type(values) == types.TupleType:
            items = [values[:2]]
        else:
            items = [(typehint, values)]
        return items

    def __setitem__(self, i, val):
        """Set indicatated argument (or slice) to a new value.
        'val' can be a single int/float/string, or a (typehint, value) tuple.
        Or, if 'i' is a slice, a list of these or another OSCMessage.
        """
        items = self.items()
        new_items = self._buildItemList(val)
        if type(i) != types.SliceType:
            if len(new_items) != 1:
                raise TypeError("single-item assignment expects a single value or a (typetag, value) tuple")
            new_items = new_items[0]
        items[i] = new_items
        self._reencode(items)

    def setItem(self, i, val, typehint=None):
        """Set indicated argument to a new value (with typehint)
        """
        items = self.items()
        items[i] = (typehint, val)
        self._reencode(items)

    def copy(self):
        """Returns a deep copy of this OSCMessage
        """
        msg = self.__class__(self.address)
        msg.typetags = self.typetags
        msg.message = self.message
        return msg

    def count(self, val):
        """Returns the number of times the given value occurs in the OSCMessage's arguments
        """
        return self.values().count(val)

    def index(self, val):
        """Returns the index of the first occurence of the given value in the OSCMessage's arguments.
        Raises ValueError if val isn't found
        """
        return self.values().index(val)

    def extend(self, values):
        """Append the contents of 'values' to this OSCMessage.
        'values' can be another OSCMessage, or a list/tuple of ints/floats/strings
        """
        items = self.items() + self._buildItemList(values)
        self._reencode(items)

    def insert(self, i, val, typehint = None):
        """Insert given value (with optional typehint) into the OSCMessage
        at the given index.
        """
        items = self.items()
        for item in reversed(self._buildItemList(val)):
                items.insert(i, item)
        self._reencode(items)

    def popitem(self, i):
        """Delete the indicated argument from the OSCMessage, and return it
        as a (typetag, value) tuple.
        """
        items = self.items()
        item = items.pop(i)
        self._reencode(items)
        return item

    def pop(self, i):
        """Delete the indicated argument from the OSCMessage, and return it.
        """
        return self.popitem(i)[1]

    def reverse(self):
        """Reverses the arguments of the OSCMessage (in place)
        """
        items = self.items()
        items.reverse()
        self._reencode(items)

    def remove(self, val):
        """Removes the first argument with the given value from the OSCMessage.
        Raises ValueError if val isn't found.
        """
        items = self.items()
        # this is not very efficient...
        i = 0
        for (t, v) in items:
            if (v == val):
                break
            i += 1
        else:
            raise ValueError("'%s' not in OSCMessage" % str(m))
        # but more efficient than first calling self.values().index(val),
        # then calling self.items(), which would in turn call self.values() again...
        del items[i]
        self._reencode(items)

    def __iter__(self):
        """Returns an iterator of the OSCMessage's arguments
        """
        return iter(self.values())

    def __reversed__(self):
        """Returns a reverse iterator of the OSCMessage's arguments
        """
        return reversed(self.values())

    def itervalues(self):
        """Returns an iterator of the OSCMessage's arguments
        """
        return iter(self.values())

    def iteritems(self):
        """Returns an iterator of the OSCMessage's arguments as
        (typetag, value) tuples
        """
        return iter(self.items())

    def itertags(self):
        """Returns an iterator of the OSCMessage's arguments' typetags
        """
        return iter(self.tags())




class OSCBundle(OSCMessage):
    """Builds a 'bundle' of OSC messages.

    OSCBundle objects are container objects for building OSC-bundles of OSC-messages.
    An OSC-bundle is a special kind of OSC-message which contains a list of OSC-messages
    (And yes, OSC-bundles may contain other OSC-bundles...)

    OSCBundle objects behave much the same as OSCMessage objects, with these exceptions:
      - if an item or items to be appended or inserted are not OSCMessage objects,
      OSCMessage objectss are created to encapsulate the item(s)
      - an OSC-bundle does not have an address of its own, only the contained OSC-messages do.
      The OSCBundle's 'address' is inherited by any OSCMessage the OSCBundle object creates.
      - OSC-bundles have a timetag to tell the receiver when the bundle should be processed.
      The default timetag value (0) means 'immediately'
    """
    def __init__(self, address="", time=0):
        """Instantiate a new OSCBundle.
        The default OSC-address for newly created OSCMessages
        can be specified with the 'address' argument
        The bundle's timetag can be set with the 'time' argument
        """
        super(OSCBundle, self).__init__(address)
        self.timetag = time

    def __str__(self):
        """Returns the Bundle's contents (and timetag, if nonzero) as a string.
        """
        if (self.timetag > 0.):
            out = "#bundle (%s) [" % self.getTimeTagStr()
        else:
            out = "#bundle ["
        if self.__len__():
            for val in self.values():
                    out += "%s, " % str(val)
            out = out[:-2]		# strip trailing space and comma
        return out + "]"

    def setTimeTag(self, time):
        """Set or change the OSCBundle's TimeTag
        In 'Python Time', that's floating seconds since the Epoch
        """
        if time >= 0:
            self.timetag = time

    def getTimeTagStr(self):
        """Return the TimeTag as a human-readable string
        """
        fract, secs = math.modf(self.timetag)
        out = time.ctime(secs)[11:19]
        out += ("%.3f" % fract)[1:]
        return out

    def append(self, argument, typehint = None):
        """Appends data to the bundle, creating an OSCMessage to encapsulate
        the provided argument unless this is already an OSCMessage.
        Any newly created OSCMessage inherits the OSCBundle's address at the time of creation.
        If 'argument' is an iterable, its elements will be encapsuated by a single OSCMessage.
        Finally, 'argument' can be (or contain) a dict, which will be 'converted' to an OSCMessage;
          - if 'addr' appears in the dict, its value overrides the OSCBundle's address
          - if 'args' appears in the dict, its value(s) become the OSCMessage's arguments
        """
        if isinstance(argument, OSCMessage):
            binary = OSCBlob(argument.getBinary())
        else:
            msg = OSCMessage(self.address)
            if type(argument) == types.DictType:
                if 'addr' in argument:
                        msg.setAddress(argument['addr'])
                if 'args' in argument:
                        msg.append(argument['args'], typehint)
            else:
                msg.append(argument, typehint)
            binary = OSCBlob(msg.getBinary())
        self.message += binary
        self.typetags += 'b'

    def getBinary(self):
        """Returns the binary representation of the message
        """
        binary = OSCString("#bundle")
        binary += OSCTimeTag(self.timetag)
        binary += self.message
        return binary

    def _reencapsulate(self, decoded):
        if decoded[0] == "#bundle":
            msg = OSCBundle()
            msg.setTimeTag(decoded[1])
            for submsg in decoded[2:]:
                msg.append(self._reencapsulate(submsg))
        else:
            msg = OSCMessage(decoded[0])
            tags = decoded[1].lstrip(',')
            for i in range(len(tags)):
                msg.append(decoded[2+i], tags[i])
        return msg

    def values(self):
        """Returns a list of the OSCMessages appended so far
        """
        out = []
        for decoded in decodeOSC(self.getBinary())[2:]:
        	out.append(self._reencapsulate(decoded))
        return out

    def __eq__(self, other):
        """Return True if two OSCBundles have the same timetag & content
        """
        if not isinstance(other, self.__class__):
        	return False
        return (self.timetag == other.timetag) and (self.typetags == other.typetags) and (self.message == other.message)

    def copy(self):
        """Returns a deep copy of this OSCBundle
        """
        copy = super(OSCBundle, self).copy()
        copy.timetag = self.timetag
        return copy
