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

from copy import copy

from ispace_msg_utils import get_default_pp_msg

tmp1 = get_default_pp_msg('192.168.1.4', 'device-1')
tmp2 = get_default_pp_msg('192.168.1.4', 'device-2')
tmp3 = get_default_pp_msg('192.168.1.4', 'device-3')
tmp4 = get_default_pp_msg('192.168.1.4', 'device-4')
tmp5 = get_default_pp_msg('192.168.1.4', 'device-5')
tmp6 = get_default_pp_msg('192.168.1.4', 'device-6')

messages_list = [tmp1, tmp2, tmp3, tmp4, tmp5, tmp6]
del_count = 0

messages = copy(messages_list)
print('messages:')
msg_count = len(messages_list)
for idx, pp_msg in enumerate(messages_list):
    print('           msg_no: {} of {}, message: {}'.format(idx + 1, msg_count,
                                                            pp_msg))

msg_count = len(messages)
for idx, pp_msg in enumerate(messages):
    print('processing msg {:d}/{:d}'.format(idx + 1, msg_count))
    if (pp_msg.get_src_device_id() == 'device-2'
            or pp_msg.get_src_device_id() == 'device-5'
    ):
        del messages_list[idx - del_count]
        del_count += 1
    continue

print('messages:')
msg_count = len(messages_list)
for idx, pp_msg in enumerate(messages_list):
    print('           msg_no: {} of {}, message: {}'.format(idx + 1, msg_count,
                                                            pp_msg))
