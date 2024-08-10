import dataclasses
import datetime
import enum
import logging
import socket
import struct

from .config import get_config

config = get_config()
logger = logging.getLogger("nsig")
_global_nsig: 'NsigHelper | None' = None
U16 = 2**16
U32 = 2**32
request_base = "!BI"
response_base = "!II"
force_update_request = request_base
force_update_response = "!H"
get_signature_timestamp_request = request_base
get_signature_timestamp_response = "!Q"
player_status_request = request_base
player_status_response = "!?I"
player_update_timestamp_request = request_base
player_update_timestamp_response = "!Q"


# decorator modifies the input function in two ways:
# 1. any errors raised will set an errored attribute on the instance
# 2. if the errored attribute is set when calling the decorated func, the reset_connection() func is called first
def track_errors(func):
    def decorated(self, *args, **kwargs):
        if self.errored:
            logger.warning("NsigHelper is in an errored state: resetting connection")
            self.reset_connection()
        try:
            return func(self, *args, **kwargs)
        except NsigSafeError:  # this does not require a connection reset
            raise
        except BaseException:
            self.errored = True
            raise
    return decorated


class ForceUpdateResult(enum.Enum):
    UPDATED = enum.auto()
    ALREADY_UP_TO_DATE = enum.auto()
    FAILED = enum.auto()
    UNKNOWN = enum.auto()


@dataclasses.dataclass(init=True, repr=True, eq=True, order=False, frozen=True, kw_only=True, slots=True)
class PlayerStatus:
    has_player: bool
    player_id: int | None


class NsigError(Exception):
    pass


class NsigSafeError(NsigError):
    pass


class NsigHelper:
    connection: socket.socket | None
    _next_request_id: int
    errored: bool

    def __init__(self):
        self._next_request_id = 0
        self.errored = True
        if config.yt_auth.nsig_helper.tcp is not None:
            self.connection = socket.create_connection(config.yt_auth.nsig_helper.tcp)
        elif config.yt_auth.nsig_helper.unix is not None:
            self.connection = socket.socket(family=socket.AF_UNIX, type=socket.SOCK_STREAM)
            self.connection.connect(str(config.yt_auth.nsig_helper.unix))
        else:
            raise NsigError("No address for NsigHelper was configured")
        self.errored = False

    @staticmethod
    def get_instance() -> 'NsigHelper':
        global _global_nsig
        if _global_nsig is None:
            _global_nsig = NsigHelper()
        return _global_nsig

    def reset_connection(self):
        self.connection.close()
        if config.yt_auth.nsig_helper.tcp is not None:
            self.connection = socket.create_connection(config.yt_auth.nsig_helper.tcp)
        elif config.yt_auth.nsig_helper.unix is not None:
            self.connection = socket.socket(family=socket.AF_UNIX, type=socket.SOCK_STREAM)
            self.connection.connect(str(config.yt_auth.nsig_helper.unix))
        else:
            raise NsigError("No address for NsigHelper was configured")
        self.errored = False

    # this changes every time it's queried!
    # plz query once and assign to a local variable
    @property
    def request_id(self) -> int:
        new = self._next_request_id
        self._next_request_id = (self._next_request_id + 1) % U32
        return new

    def _receive_response(self, expected_rid: int) -> bytes:
        expected_size = struct.calcsize(response_base)
        resp = self.connection.recv(expected_size)
        if len(resp) == 0:
            raise NsigError("Nsig Helper has disconnected")
        if len(resp) != expected_size:
            raise NsigError(f"Wrong amount of data read; expected: {expected_size} bytes, got: {len(resp)} bytes")

        (request_id, size) = struct.unpack(response_base, resp)
        if request_id != expected_rid:
            raise NsigError(f"Wrong request ID received; expected: {expected_rid}, got: {request_id}")
        if size == 0:
            return b''

        # might want to recv multiple times if size is big
        resp2 = self.connection.recv(size)
        if len(resp2) == 0:
            raise NsigError("Nsig Helper has disconnected")
        if len(resp2) != size:
            raise NsigError(f"Wrong amount of data read; expected: {size} bytes, got: {len(resp2)} bytes")
        return resp2

    @track_errors
    def force_update(self) -> ForceUpdateResult:
        request_id = self.request_id
        request = struct.pack(force_update_request, 0x00, request_id)
        self.connection.sendall(request)

        response = self._receive_response(request_id)
        (status,) = struct.unpack(force_update_response, response)
        if status == 0xF44F:
            return ForceUpdateResult.UPDATED
        if status == 0xFFFF:
            return ForceUpdateResult.ALREADY_UP_TO_DATE
        if status == 0x0000:
            return ForceUpdateResult.FAILED
        return ForceUpdateResult.UNKNOWN

    @track_errors
    def decrypt_nsig(self, n: str) -> str:
        n = n.encode("utf-8")
        if len(n) >= U16:
            raise NsigSafeError(f"Provided n string was too long; max size: {U16-1}, actual size: {len(n)}")

        request_id = self.request_id
        request = struct.pack(f"{request_base}H{len(n)}s", 0x01, request_id, len(n), n)
        self.connection.sendall(request)

        response = self._receive_response(request_id)
        (size,) = struct.unpack("!H", response[:2])
        if size == 0:
            raise NsigSafeError("Failed to decrypt nsig")
        (size, decrypted_nsig) = struct.unpack(f"!H{size}s", response)

        return decrypted_nsig.decode("utf-8")

    @track_errors
    def decrypt_sig(self, s: str) -> str:
        s = s.encode("utf-8")
        if len(s) >= U16:
            raise NsigSafeError(f"Provided s string was too long; max size: {U16-1}, actual size: {len(s)}")

        request_id = self.request_id
        request = struct.pack(f"{request_base}H{len(s)}s", 0x02, request_id, len(s), s)
        self.connection.sendall(request)

        response = self._receive_response(request_id)
        (size,) = struct.unpack("!H", response[:2])
        if size == 0:
            raise NsigSafeError("Failed to decrypt sig")
        (size, decrypted_nsig) = struct.unpack(f"!H{size}s", response)

        return decrypted_nsig.decode("utf-8")

    @track_errors
    def get_signature_timestamp(self) -> int | None:
        request_id = self.request_id
        request = struct.pack(get_signature_timestamp_request, 0x03, request_id)
        self.connection.sendall(request)

        response = self._receive_response(request_id)
        (timestamp,) = struct.unpack(get_signature_timestamp_response, response)
        if timestamp == 0:
            return None
        return timestamp

    @track_errors
    def player_status(self) -> PlayerStatus:
        request_id = self.request_id
        request = struct.pack(player_status_request, 0x04, request_id)
        self.connection.sendall(request)

        response = self._receive_response(request_id)
        (has_player, player_id) = struct.unpack(player_status_response, response)
        return PlayerStatus(
            has_player=has_player,
            player_id=player_id if has_player else None,
        )

    @track_errors
    def player_update_timestamp(self) -> datetime.timedelta:
        request_id = self.request_id
        request = struct.pack(player_update_timestamp_request, 0x05, request_id)
        self.connection.sendall(request)

        response = self._receive_response(request_id)
        (timestamp,) = struct.unpack(player_update_timestamp_response, response)
        return datetime.timedelta(seconds=timestamp)
