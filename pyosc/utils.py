import re
import socket


def hexDump(bytes):
    """
    Useful utility; prints the string in hexadecimal.
    """
    print ("byte   0  1  2  3  4  5  6  7  8  9  A  B  C  D  E  F")
    num = len(bytes)
    for i in range(num):
        if (i) % 16 == 0:
            line = "%02X0 : " % (i/16)
        line += "%02X " % ord(bytes[i])
        if (i+1) % 16 == 0:
            print ("%s: %s" % (line, repr(bytes[i-15:i+1])))
            line = ""
    bytes_left = num % 16
    if bytes_left:
        print ("%s: %s" % (line.ljust(54), repr(bytes[-bytes_left:])))



def getUrlStr(*args):
    """
    Convert provided arguments to a string in 'host:port/prefix' format
    Args can be:
     - (host, port)
     - (host, port), prefix
     - host, port
     - host, port, prefix
    """

    if not len(args):
        return ""

    if type(args[0]) == tuple:
        host = args[0][0]
        port = args[0][1]
        args = args[1:]
    else:
        host = args[0]
        port = args[1]
        args = args[2:]

    if len(args):
        prefix = args[0]
    else:
        prefix = ""

    if len(host) and (host != '0.0.0.0'):
        try:
            (host, _, _) = socket.gethostbyaddr(host)
        except socket.error:
            pass
    else:
        host = 'localhost'

    if type(port) == int:
        return "%s:%d%s" % (host, port, prefix)
    else:
        return host + prefix



def parseUrlStr(url):
	"""Convert provided string in 'host:port/prefix' format to it's components
	Returns ((host, port), prefix)
	"""
	if not (type(url) in StringTypes and len(url)):
		return (None, '')

	i = url.find("://")
	if i > -1:
		url = url[i+3:]

	i = url.find(':')
	if i > -1:
		host = url[:i].strip()
		tail = url[i+1:].strip()
	else:
		host = ''
		tail = url

	for i in range(len(tail)):
		if not tail[i].isdigit():
			break
	else:
		i += 1

	portstr = tail[:i].strip()
	tail = tail[i:].strip()

	found = len(tail)
	for c in ('/', '+', '-', '*'):
		i = tail.find(c)
		if (i > -1) and (i < found):
			found = i

	head = tail[:found].strip()
	prefix = tail[found:].strip()

	prefix = prefix.strip('/')
	if len(prefix) and prefix[0] not in ('+', '-', '*'):
		prefix = '/' + prefix

	if len(head) and not len(host):
		host = head

	if len(host):
		try:
			host = socket.gethostbyname(host)
		except socket.error:
			pass

	try:
		port = int(portstr)
	except ValueError:
		port = None

	return ((host, port), prefix)


######
#
# FilterString Utility functions
#
######

def parseFilterStr(args):
	"""Convert Message-Filter settings in '+<addr> -<addr> ...' format to a dict of the form
	{ '<addr>':True, '<addr>':False, ... }
	Returns a list: ['<prefix>', filters]
	"""
	out = {}

	if type(args) in StringTypes:
		args = [args]

	prefix = None
	for arg in args:
		head = None
		for plus in arg.split('+'):
			minus = plus.split('-')
			plusfs = minus.pop(0).strip()
			if len(plusfs):
				plusfs = '/' + plusfs.strip('/')

			if (head == None) and (plusfs != "/*"):
				head = plusfs
			elif len(plusfs):
				if plusfs == '/*':
					out = { '/*':True }	# reset all previous filters
				else:
					out[plusfs] = True

			for minusfs in minus:
				minusfs = minusfs.strip()
				if len(minusfs):
					minusfs = '/' + minusfs.strip('/')
					if minusfs == '/*':
						out = { '/*':False }	# reset all previous filters
					else:
						out[minusfs] = False

		if prefix == None:
			prefix = head

	return [prefix, out]



def getFilterStr(filters):
    """Return the given 'filters' dict as a list of
    '+<addr>' | '-<addr>' filter-strings
    """
    if not len(filters):
        return []
    if '/*' in filters.keys():
        if filters['/*']:
            out = ["+/*"]
        else:
            out = ["-/*"]
    else:
        if False in filters.values():
            out = ["+/*"]
        else:
            out = ["-/*"]
    for (addr, bool) in filters.items():
        if addr == '/*':
            continue
        if bool:
            out.append("+%s" % addr)
        else:
            out.append("-%s" % addr)
    return out



def getRegEx(pattern):
    """Compiles and returns a 'regular expression' object for the given address-pattern.
    """
    # Translate OSC-address syntax to python 're' syntax
    pattern = pattern.replace(".", r"\.")		# first, escape all '.'s in the pattern.
    pattern = pattern.replace("(", r"\(")		# escape all '('s.
    pattern = pattern.replace(")", r"\)")		# escape all ')'s.
    pattern = pattern.replace("*", r".*")		# replace a '*' by '.*' (match 0 or more characters)
#    OSCtrans = string.maketrans("{,}?","(|).")
#    pattern = pattern.translate(OSCtrans)		# change '?' to '.' and '{,}' to '(|)'
    pattern = pattern.replace("{,}", "(|)")
    pattern = pattern.replace("?", ".")
    return re.compile(pattern)
