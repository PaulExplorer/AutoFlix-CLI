import jsbeautifier
from jsbeautifier.unpackers import packer


def deobfuscate(code: str) -> str:
    """
    Deobfuscate a JavaScript code.
    """
    if packer.detect(code):
        code = packer.unpack(code)
    return jsbeautifier.beautify(code)
