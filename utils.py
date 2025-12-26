def hex_to_nibbles_le(hex_str: str):
    """
    Return nibble list (0..15) little-endian: rightmost hex digit first.
    This matches the pack method below.
    """
    s = hex_str.strip().replace("0x", "").replace("_", "").upper()
    return [int(ch, 16) for ch in reversed(s)]


def pack_nibbles_le(nibbles):
    """
    Pack nibble list into integer: nibbles[0] -> bits[3:0], nibbles[1] -> bits[7:4], ...
    """
    x = 0
    for i, v in enumerate(nibbles):
        x |= (int(v) & 0xF) << (4 * i)
    return x
