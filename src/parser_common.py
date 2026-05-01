'''
    common type parser

    2013-03-14
    2014-05-31 : string을 signal로 변경한다. 
'''
import shlex
import re
import sys
from pyparsing import *


varray = ['std_%sbit_array'%i for i in range(64)]

# basic definition
colon = Suppress(':')
semicolon = Suppress(';')
comma = Suppress(',')
equal = Suppress('=')
filename = Word(alphanums+'_/\\.')
lparen,rparen,lbrace,rbrace,backtick = map(Suppress, '(){}`')
number = Word(nums)
words = Word(alphanums + "\n\"\t ~!@#$%^&*()_+=-{}[]|:;'?/<>,.")
var = Word(alphas, alphanums+'_')

def getVectorWidth(prange,symbol_dict) : 
    ' prange : dict of from,to and dir '
    # print(symbol_dict)

    return get_vector_value(prange['from'],symbol_dict) - get_vector_value(prange['to'],symbol_dict) + 1  

def getArrayWidthLength(ptype, prange, symbol_dict) : 
    ' std_16bit_array(7 downto 0)등에서 16, 8을 return 한다. '
    # varray = ['std_%sbit_array'%i for i in range(64)]
    width = varray.index(ptype)
    assert width != -1

    length = getVectorWidth(prange,symbol_dict)
    return width, length

def get_vector_value(expr, symbol_dict):
    ''
    term = number | Word(alphanums+'_') 
    operator = oneOf('- +')
    parse = term('left') + Optional(operator('op') + term('right'))

    o = parse.parseString(expr)
    
    lvalue = int(o.left) if o.left not in symbol_dict else int(symbol_dict[o.left])

    if len(o) == 1 : 
        return lvalue
    else : 
        rvalue = int(o.right) if o.right not in symbol_dict else int(symbol_dict[o.right])
        if o.op == '+' : 
            return lvalue + rvalue
        elif o.op == '-' : 
            return lvalue - rvalue
        else : 
            return -1



def _signal_parser() : 
    identifier = Word(alphas, alphanums+'_')
    number = Word(nums)
    _slice_term = CharsNotIn(':[]')
    anyword = Word(alphanums+'()_+-*[]<|')

    # _init_def = Optional(Suppress(':=') + anyword)
    _init_def = Optional(Suppress(oneOf(':= =')) + anyword)
    logic  = identifier('id') + NotAny('[') + _init_def('init') 

    vector = (identifier('id') + Suppress('[') + _slice_term('slice1') + Optional(Suppress(':') + _slice_term('slice2')) 
           + Suppress(']') + NotAny('[') + _init_def('init')  
           )

    # array
    array  = (identifier('id') + Suppress('[') + _slice_term('slice1') + Suppress(']') 
           # + Suppress('[') + _slice_term('slice2') + Suppress(']') # + _init_def('init')  
           + Suppress('[') + _slice_term('slice2') + Suppress(']') + _init_def('init')
           )

    statement = ( logic('logic')
                | vector('vector')
                | array('array')
                ) + stringEnd
    return statement

_signal_ps = _signal_parser()

def str2signal_names(sig_s : str,io_str=None) : 
    ' return signal names '
    sig_names = []
    for s in (i.strip() for i in re.split(r'[,]\s*',sig_s) if i.strip() != ''):
        if s=='':continue
        sig = _signal_ps.parseString(s)
        sig_names.append(sig.id)

    return sig_names        

def _str2signals(sig_s : str, array_flag) : 
    ' return code strings which can make signals '

    if 1 :
        s = sig_s.strip()

        sig = _signal_ps.parseString(s)

        # init value
        if sig.init : 
            init = sig.init[0]
        else:
            init = "float('nan')" # not a number
        #  
        if 'logic' in sig : code = "hs.BitVector(name='%s',init=%s)" % (sig.id, init)

        elif 'vector' in sig :  # 1D vector
            if sig.slice2 : # slice로 주어짐
                code = "hs.Vector(%s-%s+1,start_bit=%s, name='%s',init=%s)" % (
                        sig.slice1,sig.slice2,sig.slice2, sig.id, init)
            else : # width 로 주어짐 
                code = "hs.Vector(%s,name='%s',init=%s)" % (sig.slice1, sig.id, init)

        elif 'array' in sig : 
            if not array_flag : 
                # port의 2D는 Array가 아닌 MultiVector로 변경한다.
                # code = "hs.MultiVector((%s,%s),name='%s')" % (sig.slice1,sig.slice2,sig.id)
                code = "hs.MultiVector((%s,%s),name='%s',init=%s)" % (sig.slice1,sig.slice2,sig.id,init)

            else :  # logic의 2D는 Array로 구현한다.
                # code = "hs.Array(%s,%s,name='%s')" % (sig.slice1,sig.slice2,sig.id)
                code = "hs.Array(%s,%s,name='%s',init=%s)" % (sig.slice1,sig.slice2,sig.id,init)


    return code, sig.id

def str2signals(sig_s : str,array_flag) : 
    ' called from port definition '
    code, name = _str2signals(sig_s,array_flag) 
    code = '%s = %s' % (name, code)
    return code, name



if __name__ == '__main__' : 
    ''
    # cmd = ('a,b:=1','c[3:1]:=4','d[12]','e[4][16]') 
    cmd = ('a,b:=1','c[15:2]:=4','d[12]:=0x1234','e[4][16]','f[8][16]:=[1,2]') 

    for k in cmd : 
        print(str2signals(k))
        # for i in str2signals(k) : 
        #     print(type(i), i.name, i.reset_value, '=>', i.width, len(i))




