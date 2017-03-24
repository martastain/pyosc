import math
import re
import socket, select,  struct, sys, threading, time, types, array, errno, inspect

try:
    from SocketServer import UDPServer, DatagramRequestHandler, ThreadingMixIn, StreamRequestHandler, TCPServer
except ImportError:
    from socketserver import UDPServer, DatagramRequestHandler, ThreadingMixIn, StreamRequestHandler, TCPServer

from .utils import *
from .messages import *
from .decode import *
from .encode import *


class OSCClient(object):
    """Simple OSC Client. Handles the sending of OSC-Packets (OSCMessage or OSCBundle) via a UDP-socket
    """
    # set outgoing socket buffer size
    sndbuf_size = 4096 * 8

    def __init__(self, server=None):
        """Construct an OSC Client.
          - server: Local OSCServer-instance this client will use the socket of for transmissions.
          If none is supplied, a socket will be created.
        """
        self.socket = None
        self.setServer(server)
        self.client_address = None

    def _setSocket(self, skt):
        """Set and configure client socket"""
        if self.socket != None:
            self.close()
        self.socket = skt
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, self.sndbuf_size)
        self._fd = self.socket.fileno()

    def _ensureConnected(self, address):
        """Make sure client has a socket connected to address"""
        if not self.socket:
            if len(address) == 4:
                address_family = socket.AF_INET6
            else:
                address_family = socket.AF_INET
            self._setSocket(socket.socket(address_family, socket.SOCK_DGRAM))
        self.socket.connect(address)

    def setServer(self, server):
        """Associate this Client with given server.
        The Client will send from the Server's socket.
        The Server will use this Client instance to send replies.
        """
        if server == None:
            if hasattr(self,'server') and self.server:
                if self.server.client != self:
                    raise OSCClientError("Internal inconsistency")
                self.server.client.close()
                self.server.client = None
            self.server = None
            return
        if not isinstance(server, OSCServer):
            raise ValueError("'server' argument is not a valid OSCServer object")
        self._setSocket(server.socket.dup())
        self.server = server
        if self.server.client != None:
            self.server.client.close()
        self.server.client = self

    def close(self):
        """Disconnect & close the Client's socket
        """
        if self.socket != None:
            self.socket.close()
            self.socket = None

    def __str__(self):
        """Returns a string containing this Client's Class-name, software-version
        and the remote-address it is connected to (if any)
        """
        out = self.__class__.__name__
        out += " v%s.%s-%s" % version
        addr = self.address()
        if addr:
            out += " connected to osc://%s" % getUrlStr(addr)
        else:
            out += " (unconnected)"
        return out

    def __eq__(self, other):
        """Compare function.
        """
        if not isinstance(other, self.__class__):
            return False
        if self.socket and other.socket:
            sockEqual = cmp(self.socket._sock, other.socket._sock)
        else:
            sockEqual = (self.socket == None and other.socket == None)
        if not sockEqual:
            return False
        if  self.server and other.server:
            return cmp(self.server, other.server)
        else:
            return self.server == None and other.server == None

    def __ne__(self, other):
        """Compare function.
        """
        return not self.__eq__(other)

    def address(self):
        """Returns a (host,port) tuple of the remote server this client is
        connected to or None if not connected to any server.
        """
        try:
            if self.socket:
                return self.socket.getpeername()
            else:
                return None
        except socket.error:
            return None

    def connect(self, address):
        """Bind to a specific OSC server:
        the 'address' argument is a (host, port) tuple
          - host:  hostname of the remote OSC server,
          - port:  UDP-port the remote OSC server listens to.
        """
        try:
            self._ensureConnected(address)
            self.client_address = address
        except socket.error as e:
            self.client_address = None
            raise OSCClientError("SocketError: %s" % str(e))
        if self.server != None:
            self.server.return_port = address[1]

    def sendto(self, msg, address, timeout=None):
        """Send the given OSCMessage to the specified address.
          - msg:  OSCMessage (or OSCBundle) to be sent
          - address:  (host, port) tuple specifing remote server to send the message to
          - timeout:  A timeout value for attempting to send. If timeout == None,
                this call blocks until socket is available for writing.
        Raises OSCClientError when timing out while waiting for the socket.
        """
        if not isinstance(msg, OSCMessage):
            raise TypeError("'msg' argument is not an OSCMessage or OSCBundle object")
        ret = select.select([],[self._fd], [], timeout)
        try:
            ret[1].index(self._fd)
        except:
            # for the very rare case this might happen
            raise OSCClientError("Timed out waiting for file descriptor")
        try:
            self._ensureConnected(address)
            self.socket.sendall(msg.getBinary())
            if self.client_address:
                self.socket.connect(self.client_address)
        except socket.error as e:
            if e[0] in (7, 65):	# 7 = 'no address associated with nodename',  65 = 'no route to host'
                raise e
            else:
                raise OSCClientError("while sending to %s: %s" % (str(address), str(e)))

    def send(self, msg, timeout=None):
        """Send the given OSCMessage.
        The Client must be already connected.
          - msg:  OSCMessage (or OSCBundle) to be sent
          - timeout:  A timeout value for attempting to send. If timeout == None,
                this call blocks until socket is available for writing.
        Raises OSCClientError when timing out while waiting for the socket,
        or when the Client isn't connected to a remote server.
        """
        if not isinstance(msg, OSCMessage):
            raise TypeError("'msg' argument is not an OSCMessage or OSCBundle object")

        if not self.socket:
                raise OSCClientError("Called send() on non-connected client")
        ret = select.select([],[self._fd], [], timeout)
        try:
            ret[1].index(self._fd)
        except:
            # for the very rare case this might happen
            raise OSCClientError("Timed out waiting for file descriptor")
        try:
            self.socket.sendall(msg.getBinary())
        except socket.error as e:
            if e[0] in (7, 65):	# 7 = 'no address associated with nodename',  65 = 'no route to host'
                    raise e
            else:
                    raise OSCClientError("while sending: %s" % str(e))

######
#
# OSCMultiClient class
#
######

class OSCMultiClient(OSCClient):
    """'Multiple-Unicast' OSC Client. Handles the sending of OSC-Packets (OSCMessage or OSCBundle) via a UDP-socket
    This client keeps a dict of 'OSCTargets'. and sends each OSCMessage to each OSCTarget
    The OSCTargets are simply (host, port) tuples, and may be associated with an OSC-address prefix.
    the OSCTarget's prefix gets prepended to each OSCMessage sent to that target.
    """
    def __init__(self, server=None):
        """Construct a "Multi" OSC Client.
          - server: Local OSCServer-instance this client will use the socket of for transmissions.
          If none is supplied, a socket will be created.
        """
        super(OSCMultiClient, self).__init__(server)

        self.targets = {}

    def _searchHostAddr(self, host):
        """Search the subscribed OSCTargets for (the first occurence of) given host.
        Returns a (host, port) tuple
        """
        try:
            host = socket.gethostbyname(host)
        except socket.error:
            pass

        for addr in self.targets.keys():
            if host == addr[0]:
                return addr
        raise NotSubscribedError((host, None))

    def _updateFilters(self, dst, src):
        """Update a 'filters' dict with values form another 'filters' dict:
         - src[a] == True and dst[a] == False:	del dst[a]
         - src[a] == False and dst[a] == True:	del dst[a]
         - a not in dst:  dst[a] == src[a]
        """
        if '/*' in src.keys():			# reset filters
            dst.clear()				# 'match everything' == no filters
            if not src.pop('/*'):
                dst['/*'] = False	# 'match nothing'
        for (addr, bool) in src.items():
            if (addr in dst.keys()) and (dst[addr] != bool):
                del dst[addr]
            else:
                dst[addr] = bool

    def _setTarget(self, address, prefix=None, filters=None):
        """Add (i.e. subscribe) a new OSCTarget, or change the prefix for an existing OSCTarget.
            - address ((host, port) tuple): IP-address & UDP-port
            - prefix (string): The OSC-address prefix prepended to the address of each OSCMessage
          sent to this OSCTarget (optional)
        """
        if address not in self.targets.keys():
            self.targets[address] = ["",{}]
        if prefix != None:
            if len(prefix):
                # make sure prefix starts with ONE '/', and does not end with '/'
                prefix = '/' + prefix.strip('/')
            self.targets[address][0] = prefix
        if filters != None:
            if type(filters) in StringTypes:
                (_, filters) = parseFilterStr(filters)
            elif type(filters) not in DictTypes:
                raise TypeError("'filters' argument must be a dict with {addr:bool} entries")
            self._updateFilters(self.targets[address][1], filters)

    def setOSCTarget(self, address, prefix=None, filters=None):
        """Add (i.e. subscribe) a new OSCTarget, or change the prefix for an existing OSCTarget.
          the 'address' argument can be a ((host, port) tuple) : The target server address & UDP-port
            or a 'host' (string) : The host will be looked-up
          - prefix (string): The OSC-address prefix prepended to the address of each OSCMessage
          sent to this OSCTarget (optional)
        """
        if type(address) in StringTypes:
            address = self._searchHostAddr(address)

        elif (type(address) in TupleTypes):
            (host, port) = address[:2]
            try:
                host = socket.gethostbyname(host)
            except:
                pass
            address = (host, port)
        else:
            raise TypeError("'address' argument must be a (host, port) tuple or a 'host' string")
        self._setTarget(address, prefix, filters)

    def setOSCTargetFromStr(self, url):
        """Adds or modifies a subscribed OSCTarget from the given string, which should be in the
        '<host>:<port>[/<prefix>] [+/<filter>]|[-/<filter>] ...' format.
        """
        (addr, tail) = parseUrlStr(url)
        (prefix, filters) = parseFilterStr(tail)
        self._setTarget(addr, prefix, filters)

    def _delTarget(self, address, prefix=None):
        """Delete the specified OSCTarget from the Client's dict.
        the 'address' argument must be a (host, port) tuple.
        If the 'prefix' argument is given, the Target is only deleted if the address and prefix match.
        """
        try:
            if prefix == None:
                del self.targets[address]
            elif prefix == self.targets[address][0]:
                del self.targets[address]
        except KeyError:
            raise NotSubscribedError(address, prefix)

    def delOSCTarget(self, address, prefix=None):
        """Delete the specified OSCTarget from the Client's dict.
        the 'address' argument can be a ((host, port) tuple), or a hostname.
        If the 'prefix' argument is given, the Target is only deleted if the address and prefix match.
        """
        if type(address) in StringTypes:
            address = self._searchHostAddr(address)
        if type(address) in TupleTypes:
            (host, port) = address[:2]
            try:
                host = socket.gethostbyname(host)
            except socket.error:
                pass
            address = (host, port)
            self._delTarget(address, prefix)

    def hasOSCTarget(self, address, prefix=None):
        """Return True if the given OSCTarget exists in the Client's dict.
        the 'address' argument can be a ((host, port) tuple), or a hostname.
        If the 'prefix' argument is given, the return-value is only True if the address and prefix match.
        """
        if type(address) in StringTypes:
            address = self._searchHostAddr(address)
        if type(address) in TupleTypes:
            (host, port) = address[:2]
            try:
                host = socket.gethostbyname(host)
            except socket.error:
                pass
            address = (host, port)
            if address in self.targets.keys():
                if prefix == None:
                    return True
                elif prefix == self.targets[address][0]:
                    return True
        return False

    def getOSCTargets(self):
        """Returns the dict of OSCTargets: {addr:[prefix, filters], ...}
        """
        out = {}
        for ((host, port), pf) in self.targets.items():
            try:
                (host, _, _) = socket.gethostbyaddr(host)
            except socket.error:
                pass
            out[(host, port)] = pf
        return out

    def getOSCTarget(self, address):
        """Returns the OSCTarget matching the given address as a ((host, port), [prefix, filters]) tuple.
        'address' can be a (host, port) tuple, or a 'host' (string), in which case the first matching OSCTarget is returned
        Returns (None, ['',{}]) if address not found.
        """
        if type(address) in StringTypes:
            address = self._searchHostAddr(address)
        if (type(address) in TupleTypes):
            (host, port) = address[:2]
            try:
                host = socket.gethostbyname(host)
            except socket.error:
                pass
            address = (host, port)
            if (address in self.targets.keys()):
                try:
                    (host, _, _) = socket.gethostbyaddr(host)
                except socket.error:
                    pass
                return ((host, port), self.targets[address])
        return (None, ['',{}])

    def clearOSCTargets(self):
        """Erases all OSCTargets from the Client's dict
        """
        self.targets = {}

    def updateOSCTargets(self, dict):
        """Update the Client's OSCTargets dict with the contents of 'dict'
        The given dict's items MUST be of the form
          { (host, port):[prefix, filters], ... }
        """
        for ((host, port), (prefix, filters)) in dict.items():
            val = [prefix, {}]
            self._updateFilters(val[1], filters)
            try:
                    host = socket.gethostbyname(host)
            except socket.error:
                    pass
            self.targets[(host, port)] = val

    def getOSCTargetStr(self, address):
        """Returns the OSCTarget matching the given address as a ('osc://<host>:<port>[<prefix>]', ['<filter-string>', ...])' tuple.
        'address' can be a (host, port) tuple, or a 'host' (string), in which case the first matching OSCTarget is returned
        Returns (None, []) if address not found.
        """
        (addr, (prefix, filters)) = self.getOSCTarget(address)
        if addr == None:
                return (None, [])
        return ("osc://%s" % getUrlStr(addr, prefix), getFilterStr(filters))

    def getOSCTargetStrings(self):
        """Returns a list of all OSCTargets as ('osc://<host>:<port>[<prefix>]', ['<filter-string>', ...])' tuples.
        """
        out = []
        for (addr, (prefix, filters)) in self.targets.items():
                out.append(("osc://%s" % getUrlStr(addr, prefix), getFilterStr(filters)))
        return out

    def connect(self, address):
        """The OSCMultiClient isn't allowed to connect to any specific
        address.
        """
        return NotImplemented

    def sendto(self, msg, address, timeout=None):
        """Send the given OSCMessage.
        The specified address is ignored. Instead this method calls send() to
        send the message to all subscribed clients.
          - msg:  OSCMessage (or OSCBundle) to be sent
          - address:  (host, port) tuple specifing remote server to send the message to
          - timeout:  A timeout value for attempting to send. If timeout == None,
                this call blocks until socket is available for writing.
        Raises OSCClientError when timing out while waiting for the socket.
        """
        self.send(msg, timeout)

    def _filterMessage(self, filters, msg):
        """Checks the given OSCMessge against the given filters.
        'filters' is a dict containing OSC-address:bool pairs.
        If 'msg' is an OSCBundle, recursively filters its constituents.
        Returns None if the message is to be filtered, else returns the message.
        or
        Returns a copy of the OSCBundle with the filtered messages removed.
        """
        if isinstance(msg, OSCBundle):
            out = msg.copy()
            msgs = out.values()
            out.clearData()
            for m in msgs:
                m = self._filterMessage(filters, m)
                if m:		# this catches 'None' and empty bundles.
                    out.append(m)
        elif isinstance(msg, OSCMessage):
            if '/*' in filters.keys():
                if filters['/*']:
                    out = msg
                else:
                    out = None
            elif False in filters.values():
                out = msg
            else:
                out = None
        else:
            raise TypeError("'msg' argument is not an OSCMessage or OSCBundle object")
        expr = getRegEx(msg.address)
        for addr in filters.keys():
            if addr == '/*':
                continue
            match = expr.match(addr)
            if match and (match.end() == len(addr)):
                if filters[addr]:
                    out = msg
                else:
                    out = None
                break
        return out

    def _prefixAddress(self, prefix, msg):
        """Makes a copy of the given OSCMessage, then prepends the given prefix to
        The message's OSC-address.
        If 'msg' is an OSCBundle, recursively prepends the prefix to its constituents.
        """
        out = msg.copy()

        if isinstance(msg, OSCBundle):
            msgs = out.values()
            out.clearData()
            for m in msgs:
                out.append(self._prefixAddress(prefix, m))

        elif isinstance(msg, OSCMessage):
            out.setAddress(prefix + out.address)

        else:
            raise TypeError("'msg' argument is not an OSCMessage or OSCBundle object")
        return out

    def send(self, msg, timeout=None):
        """Send the given OSCMessage to all subscribed OSCTargets
          - msg:  OSCMessage (or OSCBundle) to be sent
          - timeout:  A timeout value for attempting to send. If timeout == None,
                this call blocks until socket is available for writing.
        Raises OSCClientError when timing out while waiting for	the socket.
        """
        for (address, (prefix, filters)) in self.targets.items():
            if len(filters):
                out = self._filterMessage(filters, msg)
                if not out:			# this catches 'None' and empty bundles.
                        continue
            else:
                out = msg

            if len(prefix):
                out = self._prefixAddress(prefix, msg)

            binary = out.getBinary()

            ret = select.select([],[self._fd], [], timeout)
            try:
                ret[1].index(self._fd)
            except:
                # for the very rare case this might happen
                raise OSCClientError("Timed out waiting for file descriptor")

            try:
                while len(binary):
                    sent = self.socket.sendto(binary, address)
                    binary = binary[sent:]

            except socket.error as e:
                if e[0] in (7, 65):	# 7 = 'no address associated with nodename',  65 = 'no route to host'
                    raise e
                else:
                    raise OSCClientError("while sending to %s: %s" % (str(address), str(e)))

class OSCAddressSpace:
    def __init__(self):
        self.callbacks = {}

    def addMsgHandler(self, address, callback):
        """Register a handler for an OSC-address
          - 'address' is the OSC address-string.
        the address-string should start with '/' and may not contain '*'
          - 'callback' is the function called for incoming OSCMessages that match 'address'.
        The callback-function will be called with the same arguments as the 'msgPrinter_handler' below
        """
        for chk in '*?,[]{}# ':
            if chk in address:
                raise OSCServerError("OSC-address string may not contain any characters in '*?,[]{}# '")
        if type(callback) not in CallableTypes:
            raise OSCServerError("Message callback '%s' is not callable" % repr(callback))
        if address != 'default':
            address = '/' + address.strip('/')
        self.callbacks[address] = callback

    def delMsgHandler(self, address):
        """Remove the registered handler for the given OSC-address
        """
        del self.callbacks[address]

    def getOSCAddressSpace(self):
        """Returns a list containing all OSC-addresses registerd with this Server.
        """
        return self.callbacks.keys()

    def dispatchMessage(self, pattern, tags, data, client_address):
        """Attmept to match the given OSC-address pattern, which may contain '*',
        against all callbacks registered with the OSCServer.
        Calls the matching callback and returns whatever it returns.
        If no match is found, and a 'default' callback is registered, it calls that one,
        or raises NoCallbackError if a 'default' callback is not registered.

          - pattern (string):  The OSC-address of the receied message
          - tags (string):  The OSC-typetags of the receied message's arguments, without ','
          - data (list):  The message arguments
        """
        if len(tags) != len(data):
            raise OSCServerError("Malformed OSC-message; got %d typetags [%s] vs. %d values" % (len(tags), tags, len(data)))

        expr = getRegEx(pattern)

        replies = []
        matched = 0
        for addr in self.callbacks.keys():
            match = expr.match(addr)
            if match and (match.end() == len(addr)):
                reply = self.callbacks[addr](pattern, tags, data, client_address)
                matched += 1
                if isinstance(reply, OSCMessage):
                    replies.append(reply)
                elif reply != None:
                    raise TypeError("Message-callback %s did not return OSCMessage or None: %s" % (self.server.callbacks[addr], type(reply)))

        if matched == 0:
            if 'default' in self.callbacks:
                reply = self.callbacks['default'](pattern, tags, data, client_address)
                if isinstance(reply, OSCMessage):
                    replies.append(reply)
                elif reply != None:
                    raise TypeError("Message-callback %s did not return OSCMessage or None: %s" % (self.server.callbacks['default'], type(reply)))
            else:
                raise NoCallbackError(pattern)
        return replies

######
#
# OSCRequestHandler classes
#
######
class OSCRequestHandler(DatagramRequestHandler):
	"""RequestHandler class for the OSCServer
	"""
	def setup(self):
		"""Prepare RequestHandler.
		Unpacks request as (packet, source socket address)
		Creates an empty list for replies.
		"""
		(self.packet, self.socket) = self.request
		self.replies = []

	def _unbundle(self, decoded):
		"""Recursive bundle-unpacking function"""
		if decoded[0] != "#bundle":
			self.replies += self.server.dispatchMessage(decoded[0], decoded[1][1:], decoded[2:], self.client_address)
			return

		now = time.time()
		timetag = decoded[1]
		if (timetag > 0.) and (timetag > now):
			time.sleep(timetag - now)

		for msg in decoded[2:]:
			self._unbundle(msg)

	def handle(self):
		"""Handle incoming OSCMessage
		"""
		decoded = decodeOSC(self.packet)
		if not len(decoded):
			return

		self._unbundle(decoded)

	def finish(self):
		"""Finish handling OSCMessage.
		Send any reply returned by the callback(s) back to the originating client
		as an OSCMessage or OSCBundle
		"""
		if self.server.return_port:
			self.client_address = (self.client_address[0], self.server.return_port)

		if len(self.replies) > 1:
			msg = OSCBundle()
			for reply in self.replies:
				msg.append(reply)
		elif len(self.replies) == 1:
			msg = self.replies[0]
		else:
			return

		self.server.client.sendto(msg, self.client_address)


class ThreadingOSCRequestHandler(OSCRequestHandler):
	"""Multi-threaded OSCRequestHandler;
	Starts a new RequestHandler thread for each unbundled OSCMessage
	"""
	def _unbundle(self, decoded):
		"""Recursive bundle-unpacking function
		This version starts a new thread for each sub-Bundle found in the Bundle,
		then waits for all its children to finish.
		"""
		if decoded[0] != "#bundle":
			self.replies += self.server.dispatchMessage(decoded[0], decoded[1][1:], decoded[2:], self.client_address)
			return

		now = time.time()
		timetag = decoded[1]
		if (timetag > 0.) and (timetag > now):
			time.sleep(timetag - now)
			now = time.time()

		children = []

		for msg in decoded[2:]:
			t = threading.Thread(target = self._unbundle, args = (msg,))
			t.start()
			children.append(t)

		# wait for all children to terminate
		for t in children:
			t.join()

######
#
# OSCServer classes
#
######
class OSCServer(UDPServer, OSCAddressSpace):
	"""A Synchronous OSCServer
	Serves one request at-a-time, until the OSCServer is closed.
	The OSC address-pattern is matched against a set of OSC-adresses
	that have been registered to the server with a callback-function.
	If the adress-pattern of the message machtes the registered address of a callback,
	that function is called.
	"""

	# set the RequestHandlerClass, will be overridden by ForkingOSCServer & ThreadingOSCServer
	RequestHandlerClass = OSCRequestHandler

	# define a socket timeout, so the serve_forever loop can actually exit.
	socket_timeout = 1

	# DEBUG: print error-tracebacks (to stderr)?
	print_tracebacks = False

	def __init__(self, server_address, client=None, return_port=0):
		"""Instantiate an OSCServer.
		  - server_address ((host, port) tuple): the local host & UDP-port
		  the server listens on
		  - client (OSCClient instance): The OSCClient used to send replies from this server.
		  If none is supplied (default) an OSCClient will be created.
		  - return_port (int): if supplied, sets the default UDP destination-port
		  for replies coming from this server.
		"""
		UDPServer.__init__(self, server_address, self.RequestHandlerClass)
		OSCAddressSpace.__init__(self)

		self.setReturnPort(return_port)
		self.error_prefix = ""
		self.info_prefix = "/info"

		self.socket.settimeout(self.socket_timeout)

		self.running = False
		self.client = None

		if client == None:
			self.client = OSCClient(server=self)
		else:
			self.setClient(client)

	def setClient(self, client):
		"""Associate this Server with a new local Client instance, closing the Client this Server is currently using.
		"""
		if not isinstance(client, OSCClient):
			raise ValueError("'client' argument is not a valid OSCClient object")

		if client.server != None:
			raise OSCServerError("Provided OSCClient already has an OSCServer-instance: %s" % str(client.server))

		# Server socket is already listening at this point, so we can't use the client's socket.
		# we'll have to force our socket on the client...
		client_address = client.address()	# client may be already connected
		client.close()				# shut-down that socket

		# force our socket upon the client
		client.setServer(self)

		if client_address:
			client.connect(client_address)
			if not self.return_port:
				self.return_port = client_address[1]

	def serve_forever(self):
		"""Handle one request at a time until server is closed."""
		self.running = True
		while self.running:
			self.handle_request()	# this times-out when no data arrives.

	def close(self):
		"""Stops serving requests, closes server (socket), closes used client
		"""
		self.running = False
		self.client.close()
		self.server_close()

	def __str__(self):
		"""Returns a string containing this Server's Class-name, software-version and local bound address (if any)
		"""
		out = self.__class__.__name__
		out += " v%s.%s-%s" % version
		addr = self.address()
		if addr:
			out += " listening on osc://%s" % getUrlStr(addr)
		else:
			out += " (unbound)"

		return out

	def __eq__(self, other):
		"""Compare function.
		"""
		if not isinstance(other, self.__class__):
			return False

		return cmp(self.socket._sock, other.socket._sock)

	def __ne__(self, other):
		"""Compare function.
		"""
		return not self.__eq__(other)

	def address(self):
		"""Returns a (host,port) tuple of the local address this server is bound to,
		or None if not bound to any address.
		"""
		try:
			return self.socket.getsockname()
		except socket.error:
			return None

	def setReturnPort(self, port):
		"""Set the destination UDP-port for replies returning from this server to the remote client
		"""
		if (port > 1024) and (port < 65536):
			self.return_port = port
		else:
			self.return_port = None


	def setSrvInfoPrefix(self, pattern):
		"""Set the first part of OSC-address (pattern) this server will use to reply to server-info requests.
		"""
		if len(pattern):
			pattern = '/' + pattern.strip('/')

		self.info_prefix = pattern

	def setSrvErrorPrefix(self, pattern=""):
		"""Set the OSC-address (pattern) this server will use to report errors occuring during
		received message handling to the remote client.

		If pattern is empty (default), server-errors are not reported back to the client.
		"""
		if len(pattern):
			pattern = '/' + pattern.strip('/')

		self.error_prefix = pattern

	def addDefaultHandlers(self, prefix="", info_prefix="/info", error_prefix="/error"):
		"""Register a default set of OSC-address handlers with this Server:
		- 'default' ->  noCallback_handler
		the given prefix is prepended to all other callbacks registered by this method:
		- '<prefix><info_prefix' ->  serverInfo_handler
		- '<prefix><error_prefix> ->  msgPrinter_handler
		- '<prefix>/print' ->  msgPrinter_handler
		and, if the used Client supports it;
		- '<prefix>/subscribe' -> subscription_handler
		- '<prefix>/unsubscribe' -> subscription_handler

		Note: the given 'error_prefix' argument is also set as default 'error_prefix' for error-messages
		*sent from* this server. This is ok, because error-messages generally do not elicit a reply from the receiver.

		To do this with the serverInfo-prefixes would be a bad idea, because if a request received on '/info' (for example)
		would send replies to '/info', this could potentially cause a never-ending loop of messages!
		Do *not* set the 'info_prefix' here (for incoming serverinfo requests) to the same value as given to
		the setSrvInfoPrefix() method (for *replies* to incoming serverinfo requests).
		For example, use '/info' for incoming requests, and '/inforeply' or '/serverinfo' or even just '/print' as the
		info-reply prefix.
		"""
		self.error_prefix = error_prefix
		self.addMsgHandler('default', self.noCallback_handler)
		self.addMsgHandler(prefix + info_prefix, self.serverInfo_handler)
		self.addMsgHandler(prefix + error_prefix, self.msgPrinter_handler)
		self.addMsgHandler(prefix + '/print', self.msgPrinter_handler)

		if isinstance(self.client, OSCMultiClient):
			self.addMsgHandler(prefix + '/subscribe', self.subscription_handler)
			self.addMsgHandler(prefix + '/unsubscribe', self.subscription_handler)

	def printErr(self, txt):
		"""Writes 'OSCServer: txt' to sys.stderr
		"""
		sys.stderr.write("OSCServer: %s\n" % txt)

	def sendOSCerror(self, txt, client_address):
		"""Sends 'txt', encapsulated in an OSCMessage to the default 'error_prefix' OSC-addres.
		Message is sent to the given client_address, with the default 'return_port' overriding
		the client_address' port, if defined.
		"""
		lines = txt.split('\n')
		if len(lines) == 1:
			msg = OSCMessage(self.error_prefix)
			msg.append(lines[0])
		elif len(lines) > 1:
			msg = OSCBundle(self.error_prefix)
			for line in lines:
				msg.append(line)
		else:
			return

		if self.return_port:
			client_address = (client_address[0], self.return_port)

		self.client.sendto(msg, client_address)

	def reportErr(self, txt, client_address):
		"""Writes 'OSCServer: txt' to sys.stderr
		If self.error_prefix is defined, sends 'txt' as an OSC error-message to the client(s)
		(see printErr() and sendOSCerror())
		"""
		self.printErr(txt)

		if len(self.error_prefix):
			self.sendOSCerror(txt, client_address)

	def sendOSCinfo(self, txt, client_address):
		"""Sends 'txt', encapsulated in an OSCMessage to the default 'info_prefix' OSC-addres.
		Message is sent to the given client_address, with the default 'return_port' overriding
		the client_address' port, if defined.
		"""
		lines = txt.split('\n')
		if len(lines) == 1:
			msg = OSCMessage(self.info_prefix)
			msg.append(lines[0])
		elif len(lines) > 1:
			msg = OSCBundle(self.info_prefix)
			for line in lines:
				msg.append(line)
		else:
			return

		if self.return_port:
			client_address = (client_address[0], self.return_port)

		self.client.sendto(msg, client_address)

	###
	# Message-Handler callback functions
	###

	def handle_error(self, request, client_address):
		"""Handle an exception in the Server's callbacks gracefully.
		Writes the error to sys.stderr and, if the error_prefix (see setSrvErrorPrefix()) is set,
		sends the error-message as reply to the client
		"""
		(e_type, e) = sys.exc_info()[:2]
		self.printErr("%s on request from %s: %s" % (e_type.__name__, getUrlStr(client_address), str(e)))

		if self.print_tracebacks:
			import traceback
			traceback.print_exc() # XXX But this goes to stderr!

		if len(self.error_prefix):
			self.sendOSCerror("%s: %s" % (e_type.__name__, str(e)), client_address)

	def noCallback_handler(self, addr, tags, data, client_address):
		"""Example handler for OSCMessages.
		All registerd handlers must accept these three arguments:
		- addr (string): The OSC-address pattern of the received Message
		  (the 'addr' string has already been matched against the handler's registerd OSC-address,
		  but may contain '*'s & such)
		- tags (string):  The OSC-typetags of the received message's arguments. (without the preceding comma)
		- data (list): The OSCMessage's arguments
		  Note that len(tags) == len(data)
		- client_address ((host, port) tuple): the host & port this message originated from.

		a Message-handler function may return None, but it could also return an OSCMessage (or OSCBundle),
		which then gets sent back to the client.

		This handler prints a "No callback registered to handle ..." message.
		Returns None
		"""
		self.reportErr("No callback registered to handle OSC-address '%s'" % addr, client_address)

	def msgPrinter_handler(self, addr, tags, data, client_address):
		"""Example handler for OSCMessages.
		All registerd handlers must accept these three arguments:
		- addr (string): The OSC-address pattern of the received Message
		  (the 'addr' string has already been matched against the handler's registerd OSC-address,
		  but may contain '*'s & such)
		- tags (string):  The OSC-typetags of the received message's arguments. (without the preceding comma)
		- data (list): The OSCMessage's arguments
		  Note that len(tags) == len(data)
		- client_address ((host, port) tuple): the host & port this message originated from.

		a Message-handler function may return None, but it could also return an OSCMessage (or OSCBundle),
		which then gets sent back to the client.

		This handler prints the received message.
		Returns None
		"""
		txt = "OSCMessage '%s' from %s: " % (addr, getUrlStr(client_address))
		txt += str(data)

		self.printErr(txt)	# strip trailing comma & space

	def serverInfo_handler(self, addr, tags, data, client_address):
		"""Example handler for OSCMessages.
		All registerd handlers must accept these three arguments:
		- addr (string): The OSC-address pattern of the received Message
		  (the 'addr' string has already been matched against the handler's registerd OSC-address,
		  but may contain '*'s & such)
		- tags (string):  The OSC-typetags of the received message's arguments. (without the preceding comma)
		- data (list): The OSCMessage's arguments
		  Note that len(tags) == len(data)
		- client_address ((host, port) tuple): the host & port this message originated from.

		a Message-handler function may return None, but it could also return an OSCMessage (or OSCBundle),
		which then gets sent back to the client.

		This handler returns a reply to the client, which can contain various bits of information
		about this server, depending on the first argument of the received OSC-message:
		- 'help' | 'info' :  Reply contains server type & version info, plus a list of
		  available 'commands' understood by this handler
		- 'list' | 'ls' :  Reply is a bundle of 'address <string>' messages, listing the server's
		  OSC address-space.
		- 'clients' | 'targets' :  Reply is a bundle of 'target osc://<host>:<port>[<prefix>] [<filter>] [...]'
		  messages, listing the local Client-instance's subscribed remote clients.
		"""
		if len(data) == 0:
			return None

		cmd = data.pop(0)

		reply = None
		if cmd in ('help', 'info'):
			reply = OSCBundle(self.info_prefix)
			reply.append(('server', str(self)))
			reply.append(('info_command', "ls | list : list OSC address-space"))
			reply.append(('info_command', "clients | targets : list subscribed clients"))
		elif cmd in ('ls', 'list'):
			reply = OSCBundle(self.info_prefix)
			for addr in self.callbacks.keys():
				reply.append(('address', addr))
		elif cmd in ('clients', 'targets'):
			if hasattr(self.client, 'getOSCTargetStrings'):
				reply = OSCBundle(self.info_prefix)
				for trg in self.client.getOSCTargetStrings():
					reply.append(('target',) + trg)
			else:
				cli_addr = self.client.address()
				if cli_addr:
					reply = OSCMessage(self.info_prefix)
					reply.append(('target', "osc://%s/" % getUrlStr(cli_addr)))
		else:
			self.reportErr("unrecognized command '%s' in /info request from osc://%s. Try 'help'" % (cmd, getUrlStr(client_address)), client_address)

		return reply

	def _subscribe(self, data, client_address):
		"""Handle the actual subscription. the provided 'data' is concatenated together to form a
		'<host>:<port>[<prefix>] [<filter>] [...]' string, which is then passed to
		parseUrlStr() & parseFilterStr() to actually retreive <host>, <port>, etc.

		This 'long way 'round' approach (almost) guarantees that the subscription works,
		regardless of how the bits of the <url> are encoded in 'data'.
		"""
		url = ""
		have_port = False
		for item in data:
			if (type(item) == IntType) and not have_port:
				url += ":%d" % item
				have_port = True
			elif type(item) in StringTypes:
				url += item

		(addr, tail) = parseUrlStr(url)
		(prefix, filters) = parseFilterStr(tail)

		if addr != None:
			(host, port) = addr
			if not host:
				host = client_address[0]
			if not port:
				port = client_address[1]
			addr = (host, port)
		else:
			addr = client_address

		self.client._setTarget(addr, prefix, filters)

		trg = self.client.getOSCTargetStr(addr)
		if trg[0] != None:
			reply = OSCMessage(self.info_prefix)
			reply.append(('target',) + trg)
			return reply

	def _unsubscribe(self, data, client_address):
		"""Handle the actual unsubscription. the provided 'data' is concatenated together to form a
		'<host>:<port>[<prefix>]' string, which is then passed to
		parseUrlStr() to actually retreive <host>, <port> & <prefix>.

		This 'long way 'round' approach (almost) guarantees that the unsubscription works,
		regardless of how the bits of the <url> are encoded in 'data'.
		"""
		url = ""
		have_port = False
		for item in data:
			if (type(item) == IntType) and not have_port:
				url += ":%d" % item
				have_port = True
			elif type(item) in StringTypes:
				url += item

		(addr, _) = parseUrlStr(url)

		if addr == None:
			addr = client_address
		else:
			(host, port) = addr
			if not host:
				host = client_address[0]
			if not port:
				try:
					(host, port) = self.client._searchHostAddr(host)
				except NotSubscribedError:
					port = client_address[1]

			addr = (host, port)

		try:
			self.client._delTarget(addr)
		except NotSubscribedError as e:
			txt = "%s: %s" % (e.__class__.__name__, str(e))
			self.printErr(txt)

			reply = OSCMessage(self.error_prefix)
			reply.append(txt)
			return reply

	def subscription_handler(self, addr, tags, data, client_address):
		"""Handle 'subscribe' / 'unsubscribe' requests from remote hosts,
		if the local Client supports this (i.e. OSCMultiClient).

		Supported commands:
		- 'help' | 'info' :  Reply contains server type & version info, plus a list of
		  available 'commands' understood by this handler
		- 'list' | 'ls' :  Reply is a bundle of 'target osc://<host>:<port>[<prefix>] [<filter>] [...]'
		  messages, listing the local Client-instance's subscribed remote clients.
		- '[subscribe | listen | sendto | target] <url> [<filter> ...] :  Subscribe remote client/server at <url>,
		  and/or set message-filters for messages being sent to the subscribed host, with the optional <filter>
		  arguments. Filters are given as OSC-addresses (or '*') prefixed by a '+' (send matching messages) or
		  a '-' (don't send matching messages). The wildcard '*', '+*' or '+/*' means 'send all' / 'filter none',
		  and '-*' or '-/*' means 'send none' / 'filter all' (which is not the same as unsubscribing!)
		  Reply is an OSCMessage with the (new) subscription; 'target osc://<host>:<port>[<prefix>] [<filter>] [...]'
		- '[unsubscribe | silence | nosend | deltarget] <url> :  Unsubscribe remote client/server at <url>
		  If the given <url> isn't subscribed, a NotSubscribedError-message is printed (and possibly sent)

		The <url> given to the subscribe/unsubscribe handler should be of the form:
		'[osc://][<host>][:<port>][<prefix>]', where any or all components can be omitted.

		If <host> is not specified, the IP-address of the message's source is used.
		If <port> is not specified, the <host> is first looked up in the list of subscribed hosts, and if found,
		the associated port is used.
		If <port> is not specified and <host> is not yet subscribed, the message's source-port is used.
		If <prefix> is specified on subscription, <prefix> is prepended to the OSC-address of all messages
		sent to the subscribed host.
		If <prefix> is specified on unsubscription, the subscribed host is only unsubscribed if the host,
		port and prefix all match the subscription.
		If <prefix> is not specified on unsubscription, the subscribed host is unsubscribed if the host and port
		match the subscription.
		"""
		if not isinstance(self.client, OSCMultiClient):
			raise OSCServerError("Local %s does not support subsctiptions or message-filtering" % self.client.__class__.__name__)

		addr_cmd = addr.split('/')[-1]

		if len(data):
			if data[0] in ('help', 'info'):
				reply = OSCBundle(self.info_prefix)
				reply.append(('server', str(self)))
				reply.append(('subscribe_command', "ls | list : list subscribed targets"))
				reply.append(('subscribe_command', "[subscribe | listen | sendto | target] <url> [<filter> ...] : subscribe to messages, set filters"))
				reply.append(('subscribe_command', "[unsubscribe | silence | nosend | deltarget] <url> : unsubscribe from messages"))
				return reply

			if data[0] in ('ls', 'list'):
				reply = OSCBundle(self.info_prefix)
				for trg in self.client.getOSCTargetStrings():
					reply.append(('target',) + trg)
				return reply

			if data[0] in ('subscribe', 'listen', 'sendto', 'target'):
				return self._subscribe(data[1:], client_address)

			if data[0] in ('unsubscribe', 'silence', 'nosend', 'deltarget'):
				return self._unsubscribe(data[1:], client_address)

		if addr_cmd in ('subscribe', 'listen', 'sendto', 'target'):
			return self._subscribe(data, client_address)

		if addr_cmd in ('unsubscribe', 'silence', 'nosend', 'deltarget'):
			return self._unsubscribe(data, client_address)


class ThreadingOSCServer(ThreadingMixIn, OSCServer):
	"""An Asynchronous OSCServer.
	This server starts a new thread to handle each incoming request.
	"""
	# set the RequestHandlerClass, will be overridden by ForkingOSCServer & ThreadingOSCServer
	RequestHandlerClass = ThreadingOSCRequestHandler

######
#
# OSCError classes
#
######
######
#
# OSC over streaming transport layers (usually TCP)
#
# Note from the OSC 1.0 specifications about streaming protocols:
#
# The underlying network that delivers an OSC packet is responsible for
# delivering both the contents and the size to the OSC application. An OSC
# packet can be naturally represented by a datagram by a network protocol such
# as UDP. In a stream-based protocol such as TCP, the stream should begin with
# an int32 giving the size of the first packet, followed by the contents of the
# first packet, followed by the size of the second packet, etc.
#
# The contents of an OSC packet must be either an OSC Message or an OSC Bundle.
# The first byte of the packet's contents unambiguously distinguishes between
# these two alternatives.
#
######

class OSCStreamRequestHandler(StreamRequestHandler, OSCAddressSpace):
	""" This is the central class of a streaming OSC server. If a client
	connects to the server, the server instantiates a OSCStreamRequestHandler
	for each new connection. This is fundamentally different to a packet
	oriented server which has a single address space for all connections.
	This connection based (streaming) OSC server maintains an address space
	for each single connection, because usually tcp server spawn a new thread
	or process for each new connection. This would generate severe
	multithreading synchronization problems when each thread would operate on
	the same address space object. Therefore: To implement a streaming/TCP OSC
	server a custom handler must be implemented which implements the
	setupAddressSpace member in which it creates its own address space for this
	very connection. This has been done within the testbench and can serve as
	inspiration.
	"""
	def __init__(self, request, client_address, server):
		""" Initialize all base classes. The address space must be initialized
		before the stream request handler because the initialization function
		of the stream request handler calls the setup member which again
		requires an already initialized address space.
		"""
		self._txMutex = threading.Lock()
		OSCAddressSpace.__init__(self)
		StreamRequestHandler.__init__(self, request, client_address, server)

	def _unbundle(self, decoded):
		"""Recursive bundle-unpacking function"""
		if decoded[0] != "#bundle":
			self.replies += self.dispatchMessage(decoded[0], decoded[1][1:], decoded[2:], self.client_address)
			return

		now = time.time()
		timetag = decoded[1]
		if (timetag > 0.) and (timetag > now):
			time.sleep(timetag - now)

		for msg in decoded[2:]:
			self._unbundle(msg)

	def setup(self):
		StreamRequestHandler.setup(self)
		print ("SERVER: New client connection.")
		self.setupAddressSpace()
		self.server._clientRegister(self)

	def setupAddressSpace(self):
		""" Override this function to customize your address space. """
		pass

	def finish(self):
		StreamRequestHandler.finish(self)
		self.server._clientUnregister(self)
		print ("SERVER: Client connection handled.")
	def _transmit(self, data):
		sent = 0
		while sent < len(data):
			tmp = self.connection.send(data[sent:])
			if tmp == 0:
				return False
			sent += tmp
		return True
	def _transmitMsg(self, msg):
		"""Send an OSC message over a streaming socket. Raises exception if it
		should fail. If everything is transmitted properly, True is returned. If
		socket has been closed, False.
		"""
		if not isinstance(msg, OSCMessage):
			raise TypeError("'msg' argument is not an OSCMessage or OSCBundle object")

		try:
			binary = msg.getBinary()
			length = len(binary)
			# prepend length of packet before the actual message (big endian)
			len_big_endian = array.array('c', '\0' * 4)
			struct.pack_into(">L", len_big_endian, 0, length)
			len_big_endian = len_big_endian.tostring()
			if self._transmit(len_big_endian) and self._transmit(binary):
				return True
			return False
		except socket.error as e:
			if e[0] == errno.EPIPE: # broken pipe
				return False
			raise e

	def _receive(self, count):
		""" Receive a certain amount of data from the socket and return it. If the
		remote end should be closed in the meanwhile None is returned.
		"""
		chunk = self.connection.recv(count)
		if not chunk or len(chunk) == 0:
			return None
		while len(chunk) < count:
			tmp = self.connection.recv(count - len(chunk))
			if not tmp or len(tmp) == 0:
				return None
			chunk = chunk + tmp
		return chunk

	def _receiveMsg(self):
		""" Receive OSC message from a socket and decode.
		If an error occurs, None is returned, else the message.
		"""
		# get OSC packet size from stream which is prepended each transmission
		chunk = self._receive(4)
		if chunk == None:
			print ("SERVER: Socket has been closed.")
			return None
		# extract message length from big endian unsigned long (32 bit)
		slen = struct.unpack(">L", chunk)[0]
		# receive the actual message
		chunk = self._receive(slen)
		if chunk == None:
			print ("SERVER: Socket has been closed.")
			return None
		# decode OSC data and dispatch
		msg = decodeOSC(chunk)
		if msg == None:
			raise OSCError("SERVER: Message decoding failed.")
		return msg

	def handle(self):
		"""
		Handle a connection.
		"""
		# set socket blocking to avoid "resource currently not available"
		# exceptions, because the connection socket inherits the settings
		# from the listening socket and this times out from time to time
		# in order to provide a way to shut the server down. But we want
		# clean and blocking behaviour here
		self.connection.settimeout(None)

		print ("SERVER: Entered server loop")
		try:
			while True:
				decoded = self._receiveMsg()
				if decoded == None:
					return
				elif len(decoded) <= 0:
					# if message decoding fails we try to stay in sync but print a message
					print ("OSC stream server: Spurious message received.")
					continue

				self.replies = []
				self._unbundle(decoded)

				if len(self.replies) > 1:
					msg = OSCBundle()
					for reply in self.replies:
						msg.append(reply)
				elif len(self.replies) == 1:
					msg = self.replies[0]
				else:
					# no replies, continue receiving
					continue
				self._txMutex.acquire()
				txOk = self._transmitMsg(msg)
				self._txMutex.release()
				if not txOk:
					break

		except socket.error as e:
			if e[0] == errno.ECONNRESET:
				# if connection has been reset by client, we do not care much
				# about it, we just assume our duty fullfilled
				print ("SERVER: Connection has been reset by peer.")
			else:
				raise e

	def sendOSC(self, oscData):
		""" This member can be used to transmit OSC messages or OSC bundles
		over the client/server connection. It is thread save.
		"""
		self._txMutex.acquire()
		result = self._transmitMsg(oscData)
		self._txMutex.release()
		return result





class OSCStreamingServer(TCPServer):
    """ A connection oriented (TCP/IP) OSC server.
    """

    # define a socket timeout, so the serve_forever loop can actually exit.
    # with 2.6 and server.shutdown this wouldn't be necessary
    socket_timeout = 1

    # this is the class which handles a new connection. Override this for a
    # useful customized server. See the testbench for an example
    RequestHandlerClass = OSCStreamRequestHandler

    def __init__(self, address):
        """Instantiate an OSCStreamingServer.
          - server_address ((host, port) tuple): the local host & UDP-port
          the server listens for new connections.
        """
        self._clientList = []
        self._clientListMutex = threading.Lock()
        TCPServer.__init__(self, address, self.RequestHandlerClass)
        self.socket.settimeout(self.socket_timeout)

    def serve_forever(self):
        """Handle one request at a time until server is closed.
        Had to add this since 2.5 does not support server.shutdown()
        """
        self.running = True
        while self.running:
            self.handle_request()	# this times-out when no data arrives.

    def start(self):
        """ Start the server thread. """
        self._server_thread = threading.Thread(target=self.serve_forever)
        self._server_thread.setDaemon(True)
        self._server_thread.start()

    def stop(self):
        """ Stop the server thread and close the socket. """
        self.running = False
        self._server_thread.join()
        self.server_close()
        # 2.6 only
        #self.shutdown()

    def _clientRegister(self, client):
        """ Gets called by each request/connection handler when connection is
        established to add itself to the client list
        """
        self._clientListMutex.acquire()
        self._clientList.append(client)
        self._clientListMutex.release()

    def _clientUnregister(self, client):
        """ Gets called by each request/connection handler when connection is
        lost to remove itself from the client list
        """
        self._clientListMutex.acquire()
        self._clientList.remove(client)
        self._clientListMutex.release()

    def broadcastToClients(self, oscData):
        """ Send OSC message or bundle to all connected clients. """
        result = True
        for client in self._clientList:
                result = result and client.sendOSC(oscData)
        return result


class OSCStreamingServerThreading(ThreadingMixIn, OSCStreamingServer):
	pass
	""" Implements a server which spawns a separate thread for each incoming
	connection. Care must be taken since the OSC address space is for all
	the same.
	"""

class OSCStreamingClient(OSCAddressSpace):
	""" OSC streaming client.
	A streaming client establishes a connection to a streaming server but must
	be able to handle replies by the server as well. To accomplish this the
	receiving takes place in a secondary thread, because no one knows if we
	have to expect a reply or not, i.e. synchronous architecture doesn't make
	much sense.
	Replies will be matched against the local address space. If message
	handlers access code of the main thread (where the client messages are sent
	to the server) care must be taken e.g. by installing sychronization
	mechanisms or by using an event dispatcher which can handle events
	originating from other threads.
	"""
	# set outgoing socket buffer size
	sndbuf_size = 4096 * 8
	rcvbuf_size = 4096 * 8

	def __init__(self):
		self._txMutex = threading.Lock()
		OSCAddressSpace.__init__(self)
		self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, self.sndbuf_size)
		self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.rcvbuf_size)
		self.socket.settimeout(1.0)
		self._running = False

	def _receiveWithTimeout(self, count):
		chunk = str()
		while len(chunk) < count:
			try:
				tmp = self.socket.recv(count - len(chunk))
			except socket.timeout:
				if not self._running:
					print ("CLIENT: Socket timed out and termination requested.")
					return None
				else:
					continue
			except socket.error as e:
				if e[0] == errno.ECONNRESET:
					print ("CLIENT: Connection reset by peer.")
					return None
				else:
					raise e
			if not tmp or len(tmp) == 0:
				print ("CLIENT: Socket has been closed.")
				return None
			chunk = chunk + tmp
		return chunk

	def _receiveMsgWithTimeout(self):
		""" Receive OSC message from a socket and decode.
		If an error occurs, None is returned, else the message.
		"""
		# get OSC packet size from stream which is prepended each transmission
		chunk = self._receiveWithTimeout(4)
		if not chunk:
			return None
		# extract message length from big endian unsigned long (32 bit)
		slen = struct.unpack(">L", chunk)[0]
		# receive the actual message
		chunk = self._receiveWithTimeout(slen)
		if not chunk:
			return None
		# decode OSC content
		msg = decodeOSC(chunk)
		if msg == None:
			raise OSCError("CLIENT: Message decoding failed.")
		return msg

	def _receiving_thread_entry(self):
		print ("CLIENT: Entered receiving thread.")
		self._running = True
		while self._running:
			decoded = self._receiveMsgWithTimeout()
			if not decoded:
				break
			elif len(decoded) <= 0:
				continue

			self.replies = []
			self._unbundle(decoded)
			if len(self.replies) > 1:
				msg = OSCBundle()
				for reply in self.replies:
					msg.append(reply)
			elif len(self.replies) == 1:
				msg = self.replies[0]
			else:
				continue
			self._txMutex.acquire()
			txOk = self._transmitMsgWithTimeout(msg)
			self._txMutex.release()
			if not txOk:
				break
		print ("CLIENT: Receiving thread terminated.")

	def _unbundle(self, decoded):
		if decoded[0] != "#bundle":
			self.replies += self.dispatchMessage(decoded[0], decoded[1][1:], decoded[2:], self.socket.getpeername())
			return

		now = time.time()
		timetag = decoded[1]
		if (timetag > 0.) and (timetag > now):
			time.sleep(timetag - now)

		for msg in decoded[2:]:
			self._unbundle(msg)

	def connect(self, address):
		self.socket.connect(address)
		self.receiving_thread = threading.Thread(target=self._receiving_thread_entry)
		self.receiving_thread.start()

	def close(self):
		# let socket time out
		self._running = False
		self.receiving_thread.join()
		self.socket.close()

	def _transmitWithTimeout(self, data):
		sent = 0
		while sent < len(data):
			try:
				tmp = self.socket.send(data[sent:])
			except socket.timeout:
				if not self._running:
					print ("CLIENT: Socket timed out and termination requested.")
					return False
				else:
					continue
			except socket.error as e:
				if e[0] == errno.ECONNRESET:
					print ("CLIENT: Connection reset by peer.")
					return False
				else:
					raise e
			if tmp == 0:
				return False
			sent += tmp
		return True

	def _transmitMsgWithTimeout(self, msg):
		if not isinstance(msg, OSCMessage):
			raise TypeError("'msg' argument is not an OSCMessage or OSCBundle object")
		binary = msg.getBinary()
		length = len(binary)
		# prepend length of packet before the actual message (big endian)
		len_big_endian = array.array('c', '\0' * 4)
		struct.pack_into(">L", len_big_endian, 0, length)
		len_big_endian = len_big_endian.tostring()
		if self._transmitWithTimeout(len_big_endian) and self._transmitWithTimeout(binary):
			return True
		else:
			return False

	def sendOSC(self, msg):
		"""Send an OSC message or bundle to the server. Returns True on success.
		"""
		self._txMutex.acquire()
		txOk = self._transmitMsgWithTimeout(msg)
		self._txMutex.release()
		return txOk

	def __str__(self):
		"""Returns a string containing this Client's Class-name, software-version
		and the remote-address it is connected to (if any)
		"""
		out = self.__class__.__name__
		out += " v%s.%s-%s" % version
		addr = self.socket.getpeername()
		if addr:
			out += " connected to osc://%s" % getUrlStr(addr)
		else:
			out += " (unconnected)"

		return out

	def __eq__(self, other):
		"""Compare function.
		"""
		if not isinstance(other, self.__class__):
			return False

		isequal = cmp(self.socket._sock, other.socket._sock)
		if isequal and self.server and other.server:
			return cmp(self.server, other.server)

		return isequal

	def __ne__(self, other):
		"""Compare function.
		"""
		return not self.__eq__(other)
