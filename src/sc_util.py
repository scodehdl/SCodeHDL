'''
    Utility functions for scode
'''
import sys
import math
import hashlib
import numpy as np

import _s2


def min_bits(n):
    ' n을 표현하는 최소 bits number '
    import hsignal as hs
    if isinstance(n, (hs.LogicBase, hs.LogicSlice, hs.VectorCombine, hs.SignalConstant)):
        return n.width

    if type(n) == float:
        n = int(math.ceil(n))
    elif isinstance(n, hs.ArithmeticOperator):
        return max(min_bits(n.op1), min_bits(n.op2))
    elif isinstance(n, hs.InvertOperator):
        return min_bits(n.op1)
    else:  # n maybe numpy int32
        n = int(n)

    return n.bit_length()


def max_bits_of_list(src):
    ''' 주어진 list item의 maximum bits를 구한다.
        source에는 Signal instance 또는 number가 들어갈 수 있다.
    '''
    import hsignal as hs
    r = [0] * len(src)
    for i, s in enumerate(src):
        if type(s) in [int, float]:
            r[i] = min_bits(s)
        elif isinstance(s, (hs.LogicBase, hs.LogicSlice, hs.SignalConstant, hs.LogicExpr)):
            r[i] = s.width
        elif isinstance(s, np.generic):  # numpy scalar type
            r[i] = min_bits(int(s))
        else:
            print("max_bits_of_list error : %s", s, file=sys.stderr)
            _s2.debug_view("max_bits_of_list : unknown type(%s)" % s)

    return max(r)


def slice_width(a, b):
    if a >= b:
        return a - b + 1
    else:
        return b - a + 1


def calc_hash_value(s):
    return hashlib.md5(bytes(s, 'ascii')).hexdigest()[0:8]
