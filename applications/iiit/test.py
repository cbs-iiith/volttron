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

from collections import defaultdict
from applications.iiit.Utils.ispace_utils import Runningstats


# https://www.geeksforgeeks.org/python-creating-multidimensional-dictionary/
def multi_dict(dimensions, data_type):
    if dimensions == 1:
        d = Runningstats(120)
    else:
        d = defaultdict(lambda: multi_dict(dimensions - 1, data_type))
    return d


# historical values
h_opt_tap = {}

d_1 = 'device-1'
d_2 = 'device-2'
d_3 = 'device-3'
d_4 = 'device-4'
d_5 = 'device-5'

ap_cat_1 = 'cooling'
ap_cat_2 = 'lighting'
ap_cat_3 = 'electrical'

# printing original dictionary
print("The original dictionary : " + str(h_opt_tap))

# Using defaultdict()
# Creating Multidimensional dictionary 
# calling function
h_opt_tap = multi_dict(3, list)

h_opt_tap[d_1][ap_cat_1].push(1.0)
h_opt_tap[d_1][ap_cat_1].push(2.0)
h_opt_tap[d_1][ap_cat_1].push(3.0)
h_opt_tap[d_1][ap_cat_2].push(4.0)
h_opt_tap[d_1][ap_cat_3].push(5.0)
h_opt_tap[d_2][ap_cat_3].push(6.0)
h_opt_tap[d_2][ap_cat_3].push(7.0)
h_opt_tap[d_2][ap_cat_1].push(8.0)
h_opt_tap[d_2][ap_cat_2].push(9.0)
h_opt_tap[d_4][ap_cat_3].push(10.0)

# printing result
print("Dictionary after nesting : " + str(dict(h_opt_tap)))

# tmp = [v for k, v in h_opt_tap[d_1].items()]
for k, v in h_opt_tap.items():
    print('k: {}'.format(k))
    for k1, v1 in v.items():
        print('k1: {}, v1.mean(): {}'.format(k1,v1.mean()))

# for k, v in h_opt_tap[d_1].items():
#    print('k: {}, v: {}'.format(k,v))

# print(" Count h_opt_tap[d_1][ap_cat_1]:" + str(tmp.mean()))

# temp = [v for k, v in h_opt_tap[d_1][ap_cat_1].items()]
# print(" Total h_opt_tap[d_1][ap_cat_1]:" + str(sum(temp)))
# print(" Count h_opt_tap[d_1][ap_cat_1]:" + str(len(temp)))

# idx = get_idx_device_id(d_1)
# h_opt_tap[idx].append[ap_cat_1]
