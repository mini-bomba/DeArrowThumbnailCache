import math
import random


def random_hex(length: int) -> str:
    byte_count = math.ceil(length / 2)
    return random.randbytes(byte_count).hex()[:length]
