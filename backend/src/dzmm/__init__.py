__version__ = "0.16.0"

# Android/Mac remote-client protocol. This version is independent from the
# desktop application version so clients can reject incompatible API shapes.
REMOTE_API_VERSION = 1
REMOTE_CAPABILITIES = (
    "pair_request",
    "pair_qr",
    "pair_pin",
    "session_hydration",
)
