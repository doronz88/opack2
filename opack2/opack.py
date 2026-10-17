from typing import Any, Mapping, Tuple

import arrow
from bytestruct import U8, U16_BE, BinaryParseError, ByteReader, Scalar

from opack2.object_types import OBJ_TYPE_MAP, OPackObjectType, TerminatorObject

MAC_EPOCH = arrow.Arrow(1904, 1, 1)

TERMINATOR_TYPE = 3
F64_LE = Scalar('<d')
INT_FORMATS = {0x30: U8, 0x32: Scalar('<I'), 0x33: Scalar('<Q'), 0x35: Scalar('<f'), 0x36: F64_LE}
# Indexed by how far the type is past the inline-length range (0x60 for strings, 0x90 for bytes)
LENGTH_FORMATS = {1: U8, 2: U16_BE, 3: Scalar('>I'), 4: Scalar('>Q')}
STRING_INLINE_MAX = 0x60
BYTES_INLINE_MAX = 0x90


def _read_data(reader: ByteReader, obj_type: int, inline_base: int, inline_max: int) -> bytes:
    if obj_type <= inline_max:
        size = obj_type - inline_base
    else:
        size = reader.unpack_one(LENGTH_FORMATS[obj_type - inline_max])
    return reader.read(size)


def _read_scalar(reader: ByteReader, obj_type: int, kind: OPackObjectType) -> Any:
    if kind == OPackObjectType.BOOL:
        return obj_type == 1
    if kind == OPackObjectType.TERMINATOR:
        return None
    if kind == OPackObjectType.TIMESTAMP:
        return MAC_EPOCH.shift(seconds=reader.unpack_one(F64_LE))
    if kind == OPackObjectType.INT:
        fmt = INT_FORMATS.get(obj_type)
        return obj_type - 8 if fmt is None else reader.unpack_one(fmt)
    if kind == OPackObjectType.STRING:
        offset = reader.absolute
        try:
            return _read_data(reader, obj_type, 0x40, STRING_INLINE_MAX).decode('utf8')
        except UnicodeDecodeError as e:
            raise BinaryParseError(f'invalid UTF-8 in string: {e}', offset=offset) from e
    return _read_data(reader, obj_type, 0x70, BYTES_INLINE_MAX)


def _read(reader: ByteReader) -> Tuple[int, Any]:
    """ Read one object, returning its type byte (to detect terminators) and its value """
    obj_type = reader.unpack_one(U8)
    kind = OPackObjectType.get_type(obj_type)
    if kind == OPackObjectType.ARRAY_LENGTHED:
        return obj_type, [_read(reader)[1] for _ in range(obj_type - 0xD0)]
    if kind == OPackObjectType.ARRAY_TERMINATED:
        array = []
        while True:
            element_type, element = _read(reader)
            if element_type == TERMINATOR_TYPE:
                return obj_type, array
            array.append(element)
    if kind == OPackObjectType.DICT_LENGTHED:
        items = [(_read(reader)[1], _read(reader)[1]) for _ in range(obj_type - 0xE0)]
        return obj_type, dict(items)
    if kind == OPackObjectType.DICT_TERMINATED:
        # The terminator key is followed by a value object, which is discarded
        items = []
        while True:
            key_type, key = _read(reader)
            value = _read(reader)[1]
            if key_type == TERMINATOR_TYPE:
                return obj_type, dict(items)
            items.append((key, value))
    return obj_type, _read_scalar(reader, obj_type, kind)


def _build_data(data: bytes, obj_type: int, inline_max: int) -> bytes:
    if obj_type <= inline_max:
        return data
    return LENGTH_FORMATS[obj_type - inline_max].build(len(data)) + data


def _build(obj) -> bytes:
    for type in OBJ_TYPE_MAP:
        if isinstance(obj, type):
            obj_type = OBJ_TYPE_MAP[type](obj)
            if isinstance(obj_type, tuple):
                obj_type, obj = obj_type
            break
    kind = OPackObjectType.get_type(obj_type)
    header = U8.build(obj_type)
    if kind == OPackObjectType.BOOL or kind == OPackObjectType.TERMINATOR:
        return header
    if kind == OPackObjectType.TIMESTAMP:
        return header + F64_LE.build(int((obj - MAC_EPOCH).total_seconds()))
    if kind == OPackObjectType.INT:
        fmt = INT_FORMATS.get(obj_type)
        return header if fmt is None else header + fmt.build(obj)
    if kind == OPackObjectType.STRING:
        return header + _build_data(obj.encode('utf8'), obj_type, STRING_INLINE_MAX)
    if kind == OPackObjectType.BYTES:
        return header + _build_data(obj, obj_type, BYTES_INLINE_MAX)
    # Containers: a list of elements, or of (key, value) items for dictionaries. Terminated containers end with a
    # TerminatorObject (a pair of them for dictionaries), and nothing after the first terminator is written.
    is_dict = kind == OPackObjectType.DICT_LENGTHED or kind == OPackObjectType.DICT_TERMINATED
    terminated = kind == OPackObjectType.ARRAY_TERMINATED or kind == OPackObjectType.DICT_TERMINATED
    parts = [header]
    for element in obj:
        if is_dict:
            key, value = element
            parts.append(_build(key))
            parts.append(_build(value))
            element = key
        else:
            parts.append(_build(element))
        if terminated and isinstance(element, TerminatorObject):
            break
    return b''.join(parts)


def loads(opack_bytes: bytes) -> Mapping:
    return _read(ByteReader(opack_bytes))[1]


def dumps(obj) -> bytes:
    return _build(obj)
