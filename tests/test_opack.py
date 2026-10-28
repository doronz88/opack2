from datetime import datetime, timezone

import arrow
import pytest
from bytestruct import BinaryParseError

from opack2.exceptions import InvalidTypeError
from opack2.opack import dumps, loads


def do_test_dumps_loads(loaded_value, expected_dumped_value):
    dumped_value = dumps(loaded_value)
    assert dumped_value == expected_dumped_value
    assert loads(dumped_value) == loaded_value


def test_bool():
    do_test_dumps_loads(True, b'\x01')
    do_test_dumps_loads(False, b'\x02')


def test_datetime():
    do_test_dumps_loads(datetime(year=1970, month=1, day=1, tzinfo=timezone.utc), b'\x06\x00\x00\x00 l\t\xdfA')


def test_string():
    do_test_dumps_loads('a', b'Aa'),
    do_test_dumps_loads('a' * 33, b'a!' + b'a' * 33),
    do_test_dumps_loads('a' * 2 ** 8, b'b\x01\x00' + b'a' * 2 ** 8),


def test_number():
    do_test_dumps_loads(1, b'\t'),
    do_test_dumps_loads(40, b'0('),
    do_test_dumps_loads(2 ** 8, b'1\x00\x01'),
    do_test_dumps_loads(0x7fff, b'1\xff\x7f'),
    do_test_dumps_loads(0x8000, b'2\x00\x80\x00\x00'),
    do_test_dumps_loads(2 ** 32, b'3\x00\x00\x00\x00\x01\x00\x00\x00'),
    do_test_dumps_loads(2 ** 53, b'3\x00\x00\x00\x00\x00\x00 \x00'),
    do_test_dumps_loads(-1, b'5\x00\x00\x80\xbf'),
    do_test_dumps_loads(1.2, b'6333333\xf3?'),


def test_bytes():
    do_test_dumps_loads(b'\x01', b'q\x01'),
    do_test_dumps_loads(b'\x01' * 33, b'\x91!' + b'\x01' * 33),
    do_test_dumps_loads(b'\x01' * 2 ** 8, b'\x92\x01\x00' + b'\x01' * 2 ** 8),
    do_test_dumps_loads(b'\x01' * 2 ** 16, b'\x93\x00\x01\x00\x00' + b'\x01' * 2 ** 16),


def test_list():
    do_test_dumps_loads([1], b'\xd1\t'),
    do_test_dumps_loads([1] * 15, b'\xdf\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\x03'),
    do_test_dumps_loads([True, False, 1, -1, [1], {5: 5}, b'a', 2 ** 8, True, -100, False, True, 0.3, 'hello', 'world'],
                        b'\xdf\x01\x02\t5\x00\x00\x80\xbf\xd1\t\xe1\r\rqa1\x00\x01\x015\x00\x00\xc8\xc2\x02'
                        b'\x016333333\xd3?EhelloEworld\x03')


def test_dict():
    do_test_dumps_loads({1: 1}, b'\xe1\t\t'),
    do_test_dumps_loads({1: 1, 'a': 'b', 2: {2: 3}, 3: b'hello', 4: b'a' * 20, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9, 10: 10,
                         11: ['a', True, b'a'],
                         12: False, 13: True, 14: -1, 15: 0.1},
                        b'\xef\t\tAaAb\n\xe1\n\x0b\x0buhello\x0c\x84aaaaaaaaaaaaaaaaaaaa\r\r\x0e\x0e\x0f\x0f\x10\x10'
                        b'\x11\x11\x12\x12\x13\xd3Aa\x01qa\x14\x02\x15\x01\x165\x00\x00\x80\xbf\x176\x9a\x99\x99\x99'
                        b'\x99\x99\xb9?\x03\x03')


def test_invalid_input():
    try:
        loads(b'\x04\x04')
        assert False
    except InvalidTypeError:
        pass


def test_datetime_parses_to_arrow():
    parsed = loads(b'\x06\x00\x00\x00 l\t\xdfA')
    assert isinstance(parsed, arrow.Arrow)
    assert parsed == arrow.Arrow(1970, 1, 1)


def test_terminated_dict_discards_terminator_value():
    assert loads(b'\xef\t\t\x03Aa') == {1: 1}


def test_terminated_list_empty():
    assert loads(b'\xdf\x03') == []


def test_truncated_input():
    for data in (b'', b'2\x00', b'b\x01', b'\xd2\t', b'\xdf\t', b'\xe1\t'):
        with pytest.raises(BinaryParseError):
            loads(data)


def test_invalid_utf8():
    with pytest.raises(BinaryParseError):
        loads(b'A\xff')


def test_int16():
    assert loads(b'\x31\x01\x02') == 0x201
    assert loads(b'\x31\xff\xff') == -1


def test_back_reference_string():
    # A pair record whose name matches its model, as encoded by CoreUtils
    assert loads(b'\xe2DnameFiPhoneEmodel\xa1') == {'name': 'iPhone', 'model': 'iPhone'}
    assert loads(b'\xe1\x41a\xa0') == {'a': 'a'}


def test_back_reference_bytes():
    assert loads(b'\xd2r\x01\x02\xa0') == [b'\x01\x02', b'\x01\x02']


def test_back_reference_numbers():
    # Integers outside the inline range are referenceable whatever their width, and so are floats
    assert loads(b'\xd61\xc8\x00\xa01,\x01\xa16\x00\x00\x00\x00\x00\x00\xf8?\xa2') == [200, 200, 300, 300, 1.5, 1.5]


def test_back_reference_nested():
    # Keys and values enter the table in decoding order: 'a', 'xy', 'b', then b'\x01\x02'
    assert loads(b'\xe2AaBxyAb\xd3\xe1\xa0r\x01\x02\xa3\xa1') == \
        {'a': 'xy', 'b': [{'a': b'\x01\x02'}, b'\x01\x02', 'xy']}
    assert loads(b'\xd3\xd1Aq\xe1\xa0\xa0\xa0') == [['q'], {'q': 'q'}, 'q']


def test_back_reference_skips_unreferenceable_objects():
    # Empty strings, single-byte data, booleans, small integers and containers never enter the table
    assert loads(b'\xd7@qx\x01\x09\xd1AaAb\xa1') == ['', b'x', True, 1, ['a'], 'b', 'b']
    for data in (b'\xd2@\xa0', b'\xd2qx\xa0', b'\xd2\x01\xa0', b'\xd20\x05\xa0', b'\xd2\xd0\xa0'):
        with pytest.raises(BinaryParseError):
            loads(data)


def test_back_reference_repeats_are_appended():
    assert loads(b'\xd3AaAa\xa1') == ['a', 'a', 'a']


def test_back_reference_multi_byte_index():
    strings = [f's{i}' for i in range(300)]
    parts = [b'\xdf'] + [dumps(s) for s in strings]
    parts += [bytes([0xa0 + i]) for i in range(0x21)]
    parts += [b'\xc1' + bytes([i]) for i in range(0x21, 0x100)]
    parts += [b'\xc2' + i.to_bytes(2, 'little') for i in range(0x100, 300)]
    assert loads(b''.join(parts) + b'\x03') == strings + strings
    # The index width is the tag minus 0xc0
    for tag, width in ((0xc1, 1), (0xc2, 2), (0xc3, 3), (0xc4, 4)):
        assert loads(bytes([0xd4, 0x41, 0x61, 0x41, 0x62, tag]) + (1).to_bytes(width, 'little') + b'Az') == \
            ['a', 'b', 'b', 'z']


def test_back_reference_out_of_range():
    for data in (b'\xa0', b'\xd2Aa\xa1', b'\xd2Aa\xc1\x01', b'\xd1\xc2\x00'):
        with pytest.raises(BinaryParseError):
            loads(data)
