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

from enum import IntEnum


class PcaState(IntEnum):
    online = 0
    standalone = 1
    standby = 2
    pass


pca_state = PcaState.online
print('pca_state: {}'.format(pca_state))

if pca_state not in PcaState:
    print('pca_state: {}, False'.format(pca_state))
else:
    print('pca_state: {}, True'.format(pca_state))

pca_state = 10
print('pca_state: {}'.format(pca_state))

if pca_state not in PcaState:
    print('pca_state: {}, False'.format(pca_state))
else:
    print('pca_state: {}, True'.format(pca_state))

pca_state_s = 'online'
if pca_state_s.lower() not in PcaState.__dict__.keys():
    print('pca_state_s: {}, False'.format(pca_state_s))
    pca_state = PcaState[pca_state_s.lower()]
    print('pca_state: {}, True'.format(pca_state))
else:
    print('pca_state_s: {}, True'.format(pca_state_s))
    pca_state = PcaState[pca_state_s.lower()]
    print('pca_state: {}, True'.format(pca_state))

pca_state_s = 'ONLINE'
if pca_state_s.lower() not in PcaState.__dict__.keys():
    print('pca_state_s: {}, False'.format(pca_state_s))
    pca_state = PcaState[pca_state_s.lower()]
    print('pca_state: {}, True'.format(pca_state))
else:
    print('pca_state_s: {}, True'.format(pca_state_s))
    pca_state = PcaState[pca_state_s.lower()]
    print('pca_state: {}, True'.format(pca_state))


pca_state_s = 'SOME_THING_ELSE'
if pca_state_s.lower() not in PcaState.__dict__.keys():
    print('pca_state_s: {}, False'.format(pca_state_s))
    pca_state = PcaState.online
    print('pca_state: {}, True'.format(pca_state))
else:
    print('pca_state_s: {}, True'.format(pca_state_s))
    pca_state = PcaState[pca_state_s.lower()]
    print('pca_state: {}, True'.format(pca_state))
