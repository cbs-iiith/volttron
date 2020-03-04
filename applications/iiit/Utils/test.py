# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2020, Sam Babu, Godithi.
# All rights reserved.
#
#
# IIIT Hyderabad

# }}}

# Sam

import sys
from copy import copy

from ispace_msg_utils import get_default_pp_msg

tmp1 = get_default_pp_msg('192.168.1.4', 'device-1')
tmp1.set_src_ip("first time.")
print('tmp1.get_src_ip(): {}'.format(tmp1.get_src_ip()))
tmp2 = tmp1
tmp2.set_src_ip("second time.")

print('**************************************')
print('tmp1.get_src_ip(): {}'.format(tmp1.get_src_ip()))
print('tmp2.get_src_ip(): {}'.format(tmp2.get_src_ip()))
print('**************************************')
print('tmp3 = copy(tmp1)')
tmp3 = copy(tmp1)
tmp1.set_src_ip("third.1 time.")
tmp2.set_src_ip("third.2 time.")
print('tmp1.get_src_ip(): {}'.format(tmp1.get_src_ip()))
print('tmp2.get_src_ip(): {}'.format(tmp2.get_src_ip()))
print('tmp3.get_src_ip(): {}'.format(tmp3.get_src_ip()))
print('**************************************')
tmp1 = None
tmp2.set_src_ip("fouth time.")
# print('tmp1.get_src_ip(): {}'.format(tmp1.get_src_ip()))
print('tmp2.get_src_ip(): {}'.format(tmp2.get_src_ip()))
print('tmp3.get_src_ip(): {}'.format(tmp3.get_src_ip()))
print('**************************************')
tmp1 = get_default_pp_msg('192.168.1.4', 'device-1')
tmp1.set_src_ip("first time.")
tmp2.set_src_ip("fifth time.")
print('tmp1.get_src_ip(): {}'.format(tmp1.get_src_ip()))
print('tmp2.get_src_ip(): {}'.format(tmp2.get_src_ip()))
print('tmp3.get_src_ip(): {}'.format(tmp3.get_src_ip()))
print('**************************************')

print('outside d1 tmp1 ref_count: {}'.format(sys.getrefcount(tmp1)))


def fn(tmp1):
    # global tmp1
    print('inside d1 tmp1 ref_count: {}'.format(sys.getrefcount(tmp1)))
    pp_msg = tmp1
    print('inside d2 tmp1 ref_count: {}'.format(sys.getrefcount(tmp1)))
    tmp6 = get_default_pp_msg('192.168.1.4', 'device-1')
    print('inside d3 tmp6 ref_count: {}'.format(sys.getrefcount(tmp6)))
    return tmp6


tmp7 = fn(tmp1)
print('outside d2 , tmp1 ref_count: {}'.format(sys.getrefcount(tmp1)))
print('inside d4 tmp7 ref_count: {}'.format(sys.getrefcount(tmp7)))
print('**************************************')
print('tmp1: {}'.format(tmp1))
print('tmp2: {}'.format(tmp2))
print('tmp3: {}'.format(tmp3))
# print('tmp4: {}'.format(tmp4))
# print('tmp5: {}'.format(tmp5))
# print('tmp6: {}'.format(tmp6))
print('tmp7: {}'.format(tmp7))
