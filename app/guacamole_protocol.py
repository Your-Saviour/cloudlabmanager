"""
Guacamole wire protocol utilities.

The Guacamole protocol uses length-prefixed text format:
  opcode.arg1,arg2,...,argN;
where each element is prefixed with its character length and a dot.
"""

import asyncio


def encode_element(value: str) -> str:
    """Encode a single protocol element: '3.rdp'"""
    return f"{len(value)}.{value}"


def encode_instruction(opcode: str, *args: str) -> str:
    """Encode a full Guacamole instruction.

    Example: encode_instruction("select", "rdp") -> "6.select,3.rdp;"
    """
    parts = [encode_element(opcode)]
    for arg in args:
        parts.append(encode_element(arg))
    return ",".join(parts) + ";"


async def read_instruction(reader: asyncio.StreamReader) -> tuple[str, list[str]]:
    """Read one Guacamole instruction from a TCP stream.

    Returns (opcode, [arg1, arg2, ...]).
    Raises ConnectionError if the stream ends unexpectedly.
    """
    elements: list[str] = []

    while True:
        # Read the length prefix (digits before the dot)
        length_str = b""
        while True:
            ch = await reader.readexactly(1)
            if ch == b".":
                break
            length_str += ch

        length = int(length_str)
        value = (await reader.readexactly(length)).decode("utf-8")
        elements.append(value)

        # Read the delimiter: comma (more elements) or semicolon (end)
        delim = await reader.readexactly(1)
        if delim == b";":
            break

    opcode = elements[0]
    args = elements[1:]
    return opcode, args


def build_rdp_handshake(
    hostname: str,
    port: str = "3389",
    username: str = "",
    password: str = "",
    domain: str = "",
    width: str = "1024",
    height: str = "768",
    dpi: str = "96",
) -> tuple[list[str], dict[str, str]]:
    """Build the Guacamole select instruction and RDP connection parameters.

    Returns (instructions, params) where:
      - instructions: list of encoded instructions to send to guacd initially
      - params: dict of RDP connection parameters for build_connect_instruction
    """
    select = encode_instruction("select", "rdp")
    return [select], {
        "hostname": hostname,
        "port": port,
        "username": username,
        "password": password,
        "domain": domain,
        "width": width,
        "height": height,
        "dpi": dpi,
        "security": "any",
        "ignore-cert": "true",
        "resize-method": "display-update",
        "enable-wallpaper": "false",
        "enable-font-smoothing": "true",
        "disable-audio": "true",
    }


def build_connect_instruction(guacd_args: list[str], params: dict[str, str]) -> str:
    """Build the connect instruction using the arg names guacd sent us.

    guacd sends an 'args' instruction listing the parameter names it expects.
    We fill in our values for each, leaving blanks for unknown params.
    """
    values = []
    for arg_name in guacd_args:
        values.append(params.get(arg_name, ""))
    return encode_instruction("connect", *values)
