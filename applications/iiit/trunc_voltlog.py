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


S_STR = '2017-05-05'

f = open('volttron.log', 'r')
g = open('v-' + S_STR + '.log', 'w')

for line in f:
    if S_STR in line:
        # print line
        g.write(line)
f.close()
g.close()
