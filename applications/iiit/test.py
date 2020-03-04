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


# https://www.geeksforgeeks.org/python-creating-multidimensional-dictionary/
def multi_dict(K, type):
    if K == 1:
        d = defaultdict(type)
    else:
        d = defaultdict(lambda: multi_dict(K - 1, type))
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


def get_idx_device_id(device_id):
    if device_id not in h_opt_tap_idx:
        h_opt_tap_idx.append(device_id)
    return h_opt_tap_idx.index(device_id)


# Initialize dictionary
h_opt_tap = {}

# printing original dictionary 
print("The original dictionary : " + str(h_opt_tap))

# Using defaultdict() 
# Creating Multidimensional dictionary 
# calling function 
h_opt_tap = multi_dict(3, list)

h_opt_tap[d_1][ap_cat_1][0] = 1.0
h_opt_tap[d_1][ap_cat_1][1] = 2.0
h_opt_tap[d_1][ap_cat_1][3] = 3.0
h_opt_tap[d_1][ap_cat_2][0] = 4.0
h_opt_tap[d_1][ap_cat_3][0] = 5.0
h_opt_tap[d_2][ap_cat_3][0] = 6.0
h_opt_tap[d_2][ap_cat_3][0] = 7.0
h_opt_tap[d_2][ap_cat_1][0] = 8.0
h_opt_tap[d_2][ap_cat_2][0] = 9.0
h_opt_tap[d_4][ap_cat_3][0] = 10.0

# printing result  
print("Dictionary after nesting : " + str(dict(h_opt_tap)))

tmp = [v for k, v in h_opt_tap[d_1].items()]
print(" Count h_opt_tap[d_1][ap_cat_1]:" + str(len(tmp)))

temp = [v for k, v in h_opt_tap[d_1][ap_cat_1].items()]
print(" Total h_opt_tap[d_1][ap_cat_1]:" + str(sum(temp)))
print(" Count h_opt_tap[d_1][ap_cat_1]:" + str(len(temp)))

# idx = get_idx_device_id(d_1)
# h_opt_tap[idx].append[ap_cat_1]
