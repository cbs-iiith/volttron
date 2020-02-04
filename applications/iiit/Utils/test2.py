# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2020, Sam Babu, Godithi.
# All rights reserved.
#
#
# IIIT Hyderabad

#}}}

#Sam

import sys

from ispace_msg import ISPACE_Msg, MessageType
from ispace_msg_utils import get_default_pp_msg
from copy import copy

tmp1 = get_default_pp_msg('192.168.1.4', 'device-1')
tmp2 = get_default_pp_msg('192.168.1.4', 'device-2')
tmp3 = get_default_pp_msg('192.168.1.4', 'device-3')
print 'step {}: {}'.format(1, tmp1)
print 'step {}: {}'.format(2, tmp2)
print 'step {}: {}'.format(3, tmp3)
tmp1.set_value(.10)
tmp2.set_value(.20)
tmp3.set_value(.30)
print 'step {}: {}'.format(4, tmp1)
tmp1 = tmp1 + .10
print 'step {}: {}'.format(5, tmp1)
#tmp2 = 0.20 + tmp2
#print 'step {}: {}'.format(6, tmp2)
tmp3 += 0.3
print 'step {}: {}'.format(7, tmp3)
