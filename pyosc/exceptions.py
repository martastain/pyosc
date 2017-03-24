from .utils import getUrlStr

class OSCError(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message

class OSCClientError(OSCError):
    pass


class OSCServerError(OSCError):
    pass


class NoCallbackError(OSCServerError):
    """
    This error is raised (by an OSCServer)
    when an OSCMessage with an 'unmatched' address-pattern
    is received, and no 'default' handler is registered.
    """
    def __init__(self, pattern):
        self.message = "No callback registered to handle OSC-address '%s'" % pattern


class NotSubscribedError(OSCClientError):
    """
    This error is raised (by an OSCMultiClient) when an attempt is made to unsubscribe a host
    that isn't subscribed.
    """
    def __init__(self, addr, prefix=None):
        if prefix:
            url = getUrlStr(addr, prefix)
        else:
            url = getUrlStr(addr, '')
        self.message = "Target osc://%s is not subscribed" % url


