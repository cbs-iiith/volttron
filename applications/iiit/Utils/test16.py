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

from ispace_msg_utils import get_default_pp_msg
from random import randint

tmp1 = get_default_pp_msg('192.168.1.4', 'device-1')
tmp2 = get_default_pp_msg('192.168.1.4', 'device-2')
tmp3 = get_default_pp_msg('192.168.1.4', 'device-3')
tmp4 = get_default_pp_msg('192.168.1.4', 'device-4')

tmp1.set_price_id(randint(0, 99999999))
tmp2.set_price_id(randint(0, 99999999))
tmp3.set_price_id(randint(0, 99999999))
tmp4.set_price_id(randint(0, 99999999))

check = True if tmp1 in [tmp1, tmp2, tmp3] else False
print('check:{}, pp msg id: {}, list: {}'.format(check, tmp1.get_price_id(),
                                                 [tmp1.get_price_id(),
                                                  tmp2.get_price_id(),
                                                  tmp3.get_price_id()]))

check = True if tmp4 in [tmp1, tmp2, tmp3] else False
print('check:{}, pp msg id: {}, list: {}'.format(check, tmp4.get_price_id(),
                                                 [tmp1.get_price_id(),
                                                  tmp2.get_price_id(),
                                                  tmp3.get_price_id()]))
