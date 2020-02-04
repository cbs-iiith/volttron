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
print tmp1
tmp1.set_value(20)
tmp1 = tmp1 + 10
print tmp1