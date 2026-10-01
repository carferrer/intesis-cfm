"""Constants for the IntesisBox integration."""

DOMAIN = "intesisbox"
CONNECT_TIMEOUT = 20
RECONNECT_DELAY = 5
MAX_RECONNECT_DELAY = 60
KEEPALIVE_INTERVAL = 45
POLL_INTERVAL = 300
# The WMP device needs commands during initialization to be spaced apart.
COMMAND_INTERVAL = 1
MAX_LINE_LENGTH = 8192
