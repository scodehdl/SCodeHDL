'''
    scode signal class definition
    2014-05-05 
    2014-05-11 : SignalConstant class 단순화 시킴
    2014-05-12 : Group class 추가
    2014-05-19 : change class name  Operator -> Expression -> LogicExpr (2015-08-13)
    2014-05-21 : Signal Class에서 assignment에 해당되는 부분 mixin으로 분리
    2014-05-21 : Signal class의 reset_value keyword를 init으로 변경
    2014-05-29 : values의 width가 dst에 비해 적을 때는 0을 채운다.
    2014-06-02 : reset_value : init으로 변경하고, set 가능하게 변경
    2014-10-01 : stay_signal_instancd_id() added
    2015-04-27 : FunctionExpr added
    2015-04-28 : multiplier 지원
    2015-09-07 : slice에 LogicBase 사용 지원
    2015-09-09 : vector width에 string지원한다. VHDL에서 generic인 경우 width를 결정할 수 없다.  
    2015-09-22 : IModule에 uut_id 관리
    2015-10-22 : Logic -> BitVector
    2016-01-23 : make SwitchAssignment class
    2016-02-10 : support minus slicing
    2016-02-26 : for generate
'''
import os,sys
import collections
import functools 
import itertools 
import traceback
from contextlib import contextmanager
from enum import Enum
import copy
import numpy as np


import _s2
import parser_common


MINUS_INDEX = True

class SigValueType:
    def __init__(self,code) :
        ''
        self.code = code

SIG_UNDEFINED = SigValueType('X')
SIG_HIGH_IMPEDANCE = SigValueType('Z')
SIG_OPEN = SigValueType('open')

signal_pool = {}

# _target는 Signal assignment가 수행될 때, statement가 포함되는 HDLObject를 나타낸다.  
_target = None
_module = None

def get_assign_target(): return _target
def set_assign_target(p,top_module=False) : 
    global _target
    _target = p

    if top_module : 
        global _module
        _module = p

def get_module(): return _module


# signal type 
class SigType(Enum):
    logic = 1
    unsigned = 2
    signed = 3

class LogicDir(Enum):
    downto = 0      # little endian
    to = 1          # big endian

class IOport(Enum):
    INP      = 0
    OUTP     = 1
    INOUTP   = 2
    DYNAMICP = 3   # not used yet (2017/9/28)

INP      = IOport.INP
OUTP     = IOport.OUTP
INOUTP   = IOport.INOUTP
DYNAMICP = IOport.DYNAMICP

#-------------------------------------------------------------------------
# assignment class 
#-------------------------------------------------------------------------
class AssignMixin : 
    ' <<, <= '
    
    def __lshift__(self, data) : 
        ' <<  : make statement for variable '
        assert not isinstance(self,SignalUnspecified), ' << cannot be used with the unspecified logic. Define [%s]' % self.name   
    
        return self.assign_variable(data)

    def _auto_define(self,name,data):
        ' define (self <= data) and assign '
        # self, data가 모두 SignalUnspecified인 경우 error 처리
        # assert not isinstance(self,SignalUnspecified) or not isinstance(data,SignalUnspecified),"Both could not be unspecified"

        mod = get_module()

        # automatic logic definition
        if isinstance(data,(LogicBase,LogicSlice,VectorCombine,InvertOperator,StateType,StateItem)):
            # print(name,"<<<",data,data.isvector(),file=sys.stderr)
            if data.islogic() : 
                mod.namespace[name] = BitVector(name=name)
            elif data.isvector() : 
                if isinstance(data, MultiVector) :
                    mod.namespace[name] = MultiVector(data.shape, name=name)
                else : 
                    mod.namespace[name] = Vector(data.width, name=name)
            elif data.isarray() : 
                mod.namespace[name] = Array(len(data), data.width, name=name)
            elif isinstance(data, StateLogic):
                mod.namespace[name] = StateLogic(data.state_type, name=name)
            elif isinstance(data, StateItem):
                # print(data,file=sys.stderr)
                mod.namespace[name] = StateLogic(data.state_type, name=name)
            else : 
                assert 0, 'autodefine error => unknown type (%s)' % type(data)

        elif isinstance(data,SignalConstant):
            if data.width == 1:
                mod.namespace[name] = BitVector(name=name)
            elif not data.array_flag : 
                mod.namespace[name] = Vector(data.width, name=name)
            else : 
                ' array는 추후 지원 '

        elif isinstance(data,ArithmeticOperator):
            mod.namespace[name] = Vector(max(min_bits(data.op1),min_bits(data.op2)), name=name)

        elif isinstance(data,BooleanOperator) :
            ' bitwise operation만 call된다. '
            w = data.bitwise_width
            if w == 1:
                mod.namespace[name] = BitVector(name=name)
            else :
                mod.namespace[name] = Vector(w, name=name)

        elif isinstance(data,(tuple)) :
            w = _calc_max_width(data)
            mod.namespace[name] = Vector(w, name=name)

        # assign statement를 만들어 module에 추가한다.  
        new_sig = mod.namespace[self.name]
        self.parent.assign(SignalAssignment(new_sig, data))

    def _cvt_boolean_false_assign(self,condition):
        for i,operand in enumerate(condition.operands) : 
            if isinstance(operand, SignalAssignment):
                condition.operands[i] = _cvt_assign_2_leexpr(operand)
            elif isinstance(operand, BooleanOperator):
                self._cvt_boolean_false_assign(operand)


    def __le__(self,data): 
        ''' make statement for signal
        2013-10-30 assignment인지 if 문장에서 사용하는 condition인 LE 인지 구분하는 코드 추가

        parent가 HDLModule, SeqBlock, IfBlockCondition이 아닌 경우는 모두 LE로 변경해야 한다. 
        다만 위의 경우라도 , data가 tuple에 들어가 있으면 LE로 변경한다. 
        '''
        mod = get_module()

        self.parent = get_assign_target()


        if type(data)==tuple:
            # condition에 <= 가 있는지 check, 원하는 것은 LE인데, SignalAssignment로 변환되어 있다.
            conditions = [i for i in data[1::2]]

            data = list(data)

            for i, condition in enumerate(data[1::2]) : 
                # print(i,condition,file=sys.stderr)
                if isinstance(condition,SignalAssignment) : 
                    data[1+i*2] = _cvt_assign_2_leexpr(condition)
                elif isinstance(condition,BooleanOperator) :
                    self._cvt_boolean_false_assign(condition)

            data = tuple(data)

        if isinstance(self.parent, IfBlock) : 
            ' LE로 변경 '
            return  LeExpr(self,_cvt2signal(self,data))
 
        # unspecified class는 Array를 상속한다. (a[0][10]가 같은 2차원 indexing을 해결하기 위해)
        # 1st run에서는 둘 다 unspecified라도, 2nd run에서 data는 type이 결정된다.
        if isinstance(self,SignalUnspecified) and not isinstance(data,SignalUnspecified): 
            ' source는 unspecified가 아니고 dst가 unspecified이다. '

            def _dst_2_logic(data) : 
                w = _calc_max_width(data)
                if w==1 : 
                    data = BitVector()
                else:
                    data = Vector(w)
                return data

            if isinstance(data,(LogicBase,LogicSlice,VectorCombine,SignalConstant,StateItem)):
                ' self <= data, unspecified를 source와 동일하게 설정한다. '
                self._auto_define(self.name, data)

            elif type(data) is tuple:
                ' self <= (0,prf==1,1) '

                if len(data) == 1 : 
                    self._auto_define(self.name, data[0])
                elif isinstance(data[0],StateItem) : 
                    self._auto_define(self.name, data[0])

                elif isinstance(data[1],(LogicBase,LogicSlice,VectorCombine,LogicExpr)) : # sc의 조건문임을 확인 
                    data = _dst_2_logic(data)
                    self._auto_define(self.name,data)

            elif isinstance(data, (InvertOperator,ArithmeticOperator,BooleanOperator)) :
                self._auto_define(self.name,data)

            elif type(data) == int : 
                ''
                if data==0 : 
                    s = SignalConstant(data,1)
                else : 
                    s = SignalConstant(data,min_bits(data))
 
                self._auto_define(self.name,s)

                # constant인 경우 추후 width가 다시 결정될 수 있다. 
                mod.namespace[self.name].width_not_defined = True

            else : 
                print('source(%s) is unknown type'%data,file=sys.stderr)

        elif self.width_not_defined :
            ' auto define에 의해 width가 변경될 수 있다.'
            if isinstance(data,(SignalConstant,Vector)) : 
                if self.width < data.width : 
                    self._auto_define(self.name,data)
            elif isinstance(data,(tuple)) : 
                ''
                if self.width < _calc_max_width(data) : 
                    self._auto_define(self.name,data)
            else : 
                return self.assign(data)
        else :  
            return self.assign(data)


    def __ge__(self,other): 
        ''' 
        아래와 같이 condition에서 __ge__가 발생한다. 
        dout_valid <= (s_deci_valid, s_deci_cut_cnt >= deci_cut_cnt, 0)
        a <= (1, 0x03 <= count, 0) 
        a <= (1, count >= 0x03 , 0) 
        '''
        return GeExpr(self,_cvt2signal(self,other))

    def _assign_statement(self,data,AssignClass):
        ' self <= data '

        # source에 period property가 있으면 복사한다. clock period 복사하여 simulation에 이용한다. 
        if hasattr(data,'period'):
            self.period = data.period


        # 
        statement = AssignClass(self,data)

        parent = get_assign_target()
        if parent :  # tests인 경우, parent가 설정 안 되어 있음.
            parent.assign(statement)

        return statement

    def assign(self,data):
        ''' set statement for signal, __le__에서 call된다. 
        '''
        return self._assign_statement(data,SignalAssignment)

    def assign_variable(self,data):
        ''' set statement for variable 
        '''
        # <<는 combination logic에 사용하지 못함
        target = get_assign_target()
        if target == get_module():
            _raise_error("<< should be used in sequence block")

        return self._assign_statement(data,VariableAssignment)

class AndOrXorMixin : 
    # &, | , ^
    def __and__(self,other) : return AndExpr(self,_cvt2signal(self,other))
    def __or__(self,other) : return OrExpr(self,_cvt2signal(self,other))
    def __xor__(self,other) : return XorExpr(self,_cvt2signal(self,other))

    def __rand__(self,other) : return AndExpr(_cvt2signal(self,other),self)
    def __ror__(self,other) : return OrExpr(_cvt2signal(self,other),self)
    def __rxor__(self,other) : return XorExpr(_cvt2signal(self,other),self)


class ExprMixin(AndOrXorMixin) : 
    ' expression mixin '
    def __eq__(self, other) : 
        ' == '
        return EqExpr(self,_cvt2signal(self,other))

    def __ne__(self, other) : 
        ' != '
        return NeExpr(self,_cvt2signal(self,other))

    def __gt__(self,other): return GtExpr(self,_cvt2signal(self,other))
    def __lt__(self,other): return LtExpr(self,_cvt2signal(self,other))

    def __invert__(self) :  # ~  
        return InvertOperator(self)

    def __neg__(self): # -
        return EqExpr(self,_cvt2signal(self,0))

    # arithmetic
    def __add__(self,other) : return AddExpr(self,_cvt2signal(self,other)) 
    def __sub__(self,other) : return SubExpr(self,_cvt2signal(self,other)) 
    def __mul__(self,other)  : return MultExpr(self,_cvt2signal(self,other)) 

    def __radd__(self,other) : return AddExpr(_cvt2signal(self,other),self) 
    def __rsub__(self,other) : return SubExpr(_cvt2signal(self,other),self) 
    def __rmul__(self,other) : return MultExpr(_cvt2signal(self,other),self) 



#-------------------------------------------------------------------------
# Signal class 
#-------------------------------------------------------------------------
class LogicMixin(ExprMixin, AssignMixin) : 
    ''
NAN = float('nan')
class LogicBase(LogicMixin) : 
    ''
    _inst_id = 0

    def __init__(self,*,name=None,init=NAN,delay=0,parent=None,  sig_type=SigType.logic) :
        ''
        # set attrs
        self._name = name

        self._add_to_pool()

        # assert type(init) is int or isinstance(init,State)
        self._reset_value = init

        #
        self.id = LogicBase._inst_id
        LogicBase._inst_id += 1    # increment instance number

        self.delay   = delay
        self.parent  = parent

        self.sig_type = sig_type
        self.io = None   # port에서는 io가 정의된다.

        self.unique_defined = False   # scode가 이름 정한 것임. 중복 check 해야 한다. 
        self.unique_candidate = name   # candidate name

        # verilog에서만 사용. default는 reg이다.   
        # CBlock, IModule output만 wire가 된다. 
        self.reg_wire = 1  

        self.num = None   # defined in array

        self.__width_not_defined = False

    def _add_to_pool(self):
        if self._name in signal_pool : 
            # print(self._name, self.width)
            del signal_pool[self._name]
        signal_pool[self._name] = self

    @property
    def name(self) : 
        try : 
            return self._name
        except AttributeError : 
            print(self)
            assert 0

    @name.setter
    def name(self,n)  : 
        self._name = n
        self._add_to_pool()

    @property
    def init(self)    : return self._reset_value

    @init.setter
    def init(self,n)  : self._reset_value = n

    def __hash__(self) : 
        return id(self)

    # inst_id method
    @classmethod
    def get_inst_id(self) : 
        return LogicBase._inst_id

    @classmethod
    def set_inst_id(self,value) : 
        LogicBase._inst_id = value

    @property
    def isignals(self) : 
        return [self]

    @property
    def width_not_defined(self) : return self.__width_not_defined
    @width_not_defined.setter
    def width_not_defined(self,value)  : self.__width_not_defined = value

    @property
    def base(self) : return self

@contextmanager
def module_assigned_to_target(module):
    ''
    parent_saved = get_assign_target()
    set_assign_target(module, top_module=True)

    try:
        yield None
    finally:
        set_assign_target(parent_saved, top_module=True)


@contextmanager
def stay_signal_instancd_id():
    ''
    save_id = LogicBase.get_inst_id()
    save_uut_id = IModule.get_uut_id()
    try:
        yield None
    finally:
        LogicBase.set_inst_id(save_id)
        IModule.set_uut_id(save_uut_id)



#-------------------------------------------------------------------------
# BitVector, Vector, Array 
#-------------------------------------------------------------------------

class BitVector(LogicBase) : 
    ''
    def __init__(self,*,name=None,init=NAN, delay=0,parent=None) :
        # print(name)
        super().__init__(name=name,init=init,delay=delay,parent=parent)

    @property
    def width(self) : return 1

    @property
    def total_bits(self): return self.width


    def __len__(self): return self.width

    def islogic(self) : return True
    def isvector(self) : return False
    def isarray(self) : return False

    @property
    def init_defined(self) : 
        # return not math.isnan(self.init)
        return not _s2.check_nan(self.init)


class Vector(LogicBase) : 
    ''
    def __init__(self,width,*,name=None,start_bit=0,init=NAN,delay=0,parent=None,little_endian=True,sig_type=SigType.logic) :
        '' 
        super().__init__(name=name,init=init,delay=delay,parent=parent)

        self.start_bit = start_bit
        self._width = width
        self.sig_type = sig_type

        self.hdl_width_dict = {}   # vhdl에 generic 사용하는 경우 설정된다.
        self.little_endian = little_endian  # True : downto, False : to

        if type(width) is int : 
            assert width > 0 , 'Vector width should be larger than 0'

    def __getitem__(self,i) : 
        ' vector[i] '
        if type(i) == int : 
            
            if isinstance(self.width,GenericVar):
                return BitVectorSlice(self,i)

            # minus slicing
            if MINUS_INDEX : 
                if i < 0 : i = self.width + i

            # raise index error
            if self.width + self.start_bit <= i or i < self.start_bit:
                raise IndexError

            return BitVectorSlice(self,i)

        elif type(i) == slice : 
            if MINUS_INDEX and (i.start < 0 or i.stop < 0) : 
                start = i.start if i.start >= 0 else self.width + i.start
                stop  = i.stop if i.stop >= 0 else self.width + i.stop
                
                new_slice = slice(start,stop)
                return VectorSlice(self,new_slice)
            else : 
                return VectorSlice(self,i)

        # elif isinstance(i,Vector) : 
        elif isinstance(i,(Vector,VectorSlice)) : 
            return BitVectorSlice(self,i)

        elif isinstance(i,(ForVariable)) : 
            return BitVectorSlice(self,i)

        elif isinstance(i,(ArithmeticOperator)) : 
            return BitVectorSlice(self,i)

        # elif type(i) == slice : 
        assert 0,'Slice is unknown type : %s' % type(i)

    @property
    def width(self) : 
        return self._width
    @width.setter
    def width(self,value)  : self._width = value

    @property
    def total_bits(self): return self.width

    def __len__(self): return self.width

    def islogic(self) : return False
    def isvector(self) : return True
    def isarray(self) : return False

    @property
    def init_defined(self) : 
        # return not math.isnan(self.init)
        return not _s2.check_nan(self.init)

#-------------------------------------------------------------------------
# multi vector
#-------------------------------------------------------------------------
class MultiVector(Vector):
    ' Array를 없애고, MultiVector로 2D 포함하여 multi array 처리한다. 우선은 2차 vector를 지원한다. '
    def __init__(self,shape,*,name=None, parent=None,init=NAN) :
        '' 
        total_width = shape[0]*shape[1]  # tuple of (length, width)
        super().__init__(total_width,name=name,start_bit=0,init=NAN,
                        delay=0,parent=parent,little_endian=True,sig_type=SigType.logic)

        self.ndim = len(shape)  
        assert self.ndim == 2

        self.shape = shape
        # self.init_defined = False

        self.init = init

    def __getitem__(self,idx) : 
        if type(idx) is int : 
            assert idx < len(self)

            if MINUS_INDEX : 
                if idx < 0 : idx = len(self) + idx

            s = slice((idx+1) * self.width - 1, idx * self.width)
            return VectorSlice(self,s)

        elif type(idx) == slice : 
            start, stop = idx.start, idx.stop

            if MINUS_INDEX and (start < 0 or stop < 0) : 
                start = start if start >= 0 else len(self) + start
                stop  = stop if stop >= 0 else len(self) + stop

            s = slice((start+1) * self.width - 1, (stop * self.width))
            return VectorSlice(self,s)
        else : 
            assert 0, '%s not supported in MultiVector slicing' % idx

    def __len__(self):
        return self.shape[0]

    @property
    def width(self): return self.shape[1]

    @property
    def total_bits(self): return self.shape[0] * self.shape[1]

    @property
    def init(self)    : return self._reset_value

    @init.setter
    def init(self,init_v)  : 
        if type(init_v) is np.ndarray : 
            init_v = list(init_v.flatten())

        if type(init_v) is list:
            num = len(self)

            # truncate or zero filling
            if len(init_v) > num : 
                init_v = init_v[:num]
            elif len(init_v) < num : 
                init_v = init_v + [0]*(num-len(init_v))

            # 
            # _sum = 0
            # for i,v in enumerate(reversed(init_v)) : 
            #     _sum = (_sum << (self.width)) | v

            # self._reset_value = _sum
            self._reset_value = init_v


    def init_to_vector_value(self,value) : 
        if _s2.check_nan(value) : return value

        _sum = 0
        for i,v in enumerate(reversed(value)) : 
            _sum = (_sum << (self.width)) | v
        return _sum



class Array(LogicBase) : 
    ''
    def __init__(self,n,width,*,name=None,delay=0,parent=None,little_endian=True,init=NAN) :
        super().__init__(name=name,delay=delay,parent=parent,init=init)

        self.num  = n       # vector의 #
        self.__width = width  # vector의 width 
        self.init_defined = False
        self.readonly = False
        self.little_endian = little_endian  # True : downto, False : to

        self.shape = (n,width)
        self.init = init

    @property
    def init(self)    : return self._reset_value

    @init.setter
    def init(self,init_v)  : 
        if type(init_v) is np.ndarray : 
            init_v = list(init_v.flatten())

        if type(init_v) is list:
            if len(init_v) > self.num : 
                self._reset_value = init_v[:self.num]
            else : # zero filling
                self._reset_value = init_v + [0]*(self.num-len(init_v))

            self.init_defined = True
        else : 
            self.init_defined = False

    def __getitem__(self,i) : 
        ' array[i] '
        if type(i) == int : 
            if self.num <= i:
                raise IndexError

            if MINUS_INDEX : 
                if i < 0 : i = self.num + i
            
            return VectorSlice(self,i)
        elif type(i) == slice : 
            # return ArraySlice(self,i)
            if MINUS_INDEX and (i.start < 0 or i.stop < 0) : 
                start = i.start if i.start >= 0 else self.num + i.start
                stop  = i.stop if i.stop >= 0 else self.num + i.stop
                
                new_slice = slice(start,stop)
                return ArraySlice(self,new_slice)
            else : 
                return ArraySlice(self,i)

        elif isinstance(i,(Vector,VectorSlice)):
            return VectorSlice(self,i)

    def __len__(self):
        return self.num

    @property
    def width(self): return self.__width

    @property
    def total_bits(self): return self.num * self.width

    def islogic(self) : return False
    def isvector(self) : return False
    def isarray(self) : return True


class SignalUnspecified(MultiVector) : 
    ''
    def __init__(self,name) :
        self._name = name
        self.num = 10000   # Array의 __getitem__ 에서 error 발생하지 않게 크게 설정한다.

        super().__init__((self.num, self.width), name=name)

    # 0이 아닌 값을 할당한다. 2nd run에서 제대로 된 값이 설정된다.
    # 0을 return하게 되면 Vector 선언에서 assertion이 발생할 수 있다.
    # 1보다 큰 값을 return하면 auto_define에서 LL(n)보다 width가 크게 설정되는 경우가 있다.
    @property
    def width(self): return 1


#-------------------------------------------------------------------------
# signal constant class 
#-------------------------------------------------------------------------
class SignalConstant : 
    ' value is integer, 0, 1, Z, X'
    def __init__(self,value,width,vector_1bit=False, array_flag=False) :
        self.value = value

        if width==0 : 
            assert type(value) is int
            self.width = min_bits(value)
        else : 
            self.width = width

        self.total_bits = width
        self.vector_1bit = vector_1bit  # 1bit vector임을 나타낸다.
        self.array_flag = array_flag  # destination이 array임을 나타낸다.

    @property
    def isignals(self) : return []

    def __getitem__(self,i) : 
        ' [i] '
        if type(i) == int : 
            # minus slicing
            if MINUS_INDEX : 
                if i < 0 : i = self.width + i

            # raise index error
            if self.width <= i :
                raise IndexError

            return SignalConstant((self.value & (1 << i)) >> i, 1)

        elif type(i) == slice : 
            if MINUS_INDEX and (i.start < 0 or i.stop < 0) : 
                start = i.start if i.start >= 0 else self.width + i.start
                stop  = i.stop if i.stop >= 0 else self.width + i.stop
                i = slice(start,stop)

            w = i.start - i.stop + 1
            k = int(2**w - 1)
            return SignalConstant((self.value & (k << i.stop)) >> i.stop, w)

 
#-------------------------------------------------------------------------
# convert integer to signal instance   
#-------------------------------------------------------------------------
def _cvt2signal(dst,src): 
    ''' 1. Integer(list, tuple에 있는 integer 포함)를 SignalConstant로 바꾼다. 
        2. 
        3. 다른 type은 그대로 return한다. 
    '''
    if (isinstance(src, ComparisonOperator) or isinstance(dst, ComparisonOperator) or 
        isinstance(src,SignalAssignment)):
        return src

    # boolean은 0,1로 변환한다.
    if type(src) == bool : 
        src = 1 if src else 0

    vector_1bit = True if dst.isvector() and dst.width == 1 else False
    array_flag = True if isinstance(dst,Array)  else False

    def _cvt(src,w):
        if type(src) == int : 
            # return SignalConstant(src,dst.width, vector_1bit,array_flag)
            return SignalConstant(src,w, vector_1bit,array_flag)
        elif type(src) == str : 
            assert 0, 'string type not accepted : %s' % src 
        else : 
            return src

    if type(src) is list :
        return [_cvt(s,dst.width) for s in src]
    elif type(src) is tuple :
        return tuple(_cvt(s,dst.width) for s in src)
    else:
        # check overflow
        # if type(src) is int and min_bits(src) > dst.width : 
        if not isinstance(dst.width,GenericVar) and type(src) is int and min_bits(src) > dst.width : 
            n = dst.argv.name if isinstance(dst,FunctionExpr) else dst.name
            print('WARNING : Overflow, %s is bigger than %s' % (src, n))
            return _cvt(src,min_bits(src))
        else : 
            return _cvt(src,dst.width)


#-------------------------------------------------------------------------
# slice 
#-------------------------------------------------------------------------
# class LogicSlice(ExprMixin, AssignMixin) : 
class LogicSlice(LogicMixin) : 
    ''
    def __init__(self,base_signal, slice1, slice2=None) :
        ''
        self.base_signal   = base_signal   
        self.slice1   = slice1   # integer,slice or logic    
        self.slice2   = slice2   # integer,slice or logic
        self.delay = 0

        self.unique_defined = self.base_signal.unique_defined

    @property
    def isignals(self) : 
        return [self.base_signal]

    @property
    def init_defined(self) : 
        return self.base_signal.init_defined

    @property
    def name(self) : 
        return self.base_signal.name

    @property
    def reg_wire(self) : return self.base_signal.reg_wire
    @reg_wire.setter
    def reg_wire(self,value)  : self.base_signal.reg_wire = value

    @property
    def width_not_defined(self) : return False

    @property
    def base(self) : return self.base_signal
    

class BitVectorSlice(LogicSlice) : 
    ' from vector[index]'
    def __init__(self,base_signal, slice_) :
        super().__init__(base_signal,slice_)

    @property
    def width(self) : return 1

    @property
    def total_bits(self): return self.width

    def __len__(self): return self.width

    def islogic(self) : return True
    def isvector(self): return False
    def isarray(self) : return False


class VectorSlice(LogicSlice) : 
    ' VectorSlice는 Array또는 Vector에서 만들어진다. from vector[slice] or array[index] '
    def __init__(self,base_signal, slice_) :
        super().__init__(base_signal,slice_)

        self.little_endian = True

        if type(slice_) is slice : 
            if slice_.start < slice_.stop :
                self.little_endian = False

    @property
    def width(self) : 
        if isinstance(self.base_signal, Array) : 
            if self.slice2 is None : 
                return self.base_signal.width
            else : 
                return slice_width(self.slice2.start , self.slice2.stop)
        elif isinstance(self.base_signal, Vector) : 
            return slice_width(self.slice1.start , self.slice1.stop)

        elif isinstance(self.base_signal, VectorSlice) : 
            return slice_width(self.slice2.start , self.slice2.stop)

    @property
    def total_bits(self): return self.width


    def __len__(self): return self.width

    def islogic(self) : return False
    def isvector(self): return True
    def isarray(self) : return False

    def __getitem__(self,i) :  
        ' '
        if type(i) == int : 
            # d = BitVectorSlice(self.base_signal,self.slice1)
            d = BitVectorSlice(self,self.slice1)
            d.slice2 = i
            return d

        elif type(i) == slice : 
            if isinstance(self.base_signal, Array) : 
                d = VectorSlice(self.base_signal,self.slice1)
                d.slice2 = i
                return d
            else :
                d = VectorSlice(self,self.slice1)
                d.slice2 = i
                return d

        elif isinstance(i,Vector) : 
            ''
            d = BitVectorSlice(self.base_signal,self.slice1)
            d.slice2 = i
            return d

    @property
    def sig_type(self) : return self.base_signal.sig_type        

class ArraySlice(LogicSlice) : 
    ' from array[slice] '
    def __init__(self,base_signal, slice_) :
        super().__init__(base_signal,slice_)

    @property
    def width(self) : return self.base_signal.width
    def __len__(self): return self.slice1.start - self.slice1.stop + 1

    @property
    def total_bits(self): return self.width * len(self)



    def islogic(self) : return False
    def isvector(self): return False
    def isarray(self) : return True

    def __getitem__(self,i) :  
        ' '
        if type(i) == int : 
            d = VectorSlice(self,i)
        elif type(i) == slice : 
            new_stop = self.slice1.stop
            d = ArraySlice(self,slice(new_stop + i.start,new_stop + i.stop,None))

        # elif isinstance(i,Vector) : 
        elif isinstance(i,VectorSlice) : 
            ''
            d = VectorSlice(self.base_signal,self.slice1)
            d.slice2 = i
            # print(d,'**********',file=sys.stderr)
            return d

        d.base_signal = self.base_signal
        return d


#-------------------------------------------------------------------------
# combine (concatenation) 
#-------------------------------------------------------------------------
class VectorCombine(ExprMixin):
    ' concatenation vector, assignment에서 destination으로 사용하지 않고 source로만 사용한다.'
    def __init__(self,s1=None,s2=None,*v) :
        ' {s1, s2} '
        if s1 is None and s2 is None : 
            self.vectors = []
        elif s2 is None : 
            self.vectors = [s1]
        else : 
            self.vectors = [s1, s2] + list(v)

    def append(self,s):
        self.vectors.append(s)

    @property
    def names(self) : 
        return [s.name for s in self.vectors if not isinstance(s, SignalConstant)
                and not isinstance(s, VectorCombine)]

    @property
    def width(self) : 
        return sum(s.width for s in self.vectors)

    def __len__(self):
        return self.width

    def islogic(self) : return False
    def isvector(self) : return True
    def isarray(self) : return False

    @property
    def isignals(self) : 
        sig_list = []
        for s in self.vectors : 
            if isinstance(s, LogicBase) : 
                sig_list.append(s)
            elif isinstance(s, LogicSlice) : 
                sig_list.append(s.base_signal)
            elif isinstance(s, VectorCombine) : # VectorCombine이 VectorCombin을 포함할 수 있다.
                sig_list += s.isignals
        return sig_list
 
 
#-------------------------------------------------------------------------
# state machine 
# StateType have StateItems
# StateLogic have a StateType
#-------------------------------------------------------------------------
class StateItem : 
    def __init__(self,state_type=None,*,name=None,encoding_value=0) :
        self.name = name
        self.encoding_value = encoding_value 
        self.state_type = state_type

    @property
    def value(self) : return self

    def set_name(self,name): self.name = name

    def islogic(self) : return False
    def isvector(self) : return False
    def isarray(self) : return False




class StateType :
    ''
    def __init__(self,state_enum,*,name=None,unique=False,encoding='binary') :
        ''
        mod = get_module()
        if unique : 
            self.name = '%s_%s' % (name,mod.hash_name(name)) 
        else : 
            self.name = name

        if state_enum == [] : # empty item
            self.state_items = []
        else : 
            self.state_items = [StateItem(self,name=e.name,encoding_value=e.value) for e in state_enum]

        self.unique_defined = unique
        self.unique_candidate = name
        self.encoding = 'binary'

        self.state_enum = None  # will be defined in _define_statetype_enum of post processing 


    @property
    def reset_item(self) : 
        if self.state_items : 
            return self.state_items[0]
        else : 
            return None

    @property
    def state_bits_width(self) : return max_bits_of_list([e.encoding_value for e in self.state_items]) 

    def __getattr__(self,name):
        # print('hello',name)
        for  n in self.state_items : 
            if n.name == name : 
                return n

        # add state item dynamically
        # calc max value
        max_value = -1 
        for e in self.state_items:
            if e.encoding_value > max_value : 
                max_value = e.encoding_value

        item = StateItem(self,name=name,encoding_value=max_value+1) 
        self.state_items.append(item)

        return item


        # raise AttributeError('%s not in state type' % name)

    def item(self,name):
        return self.__getattr__(name) 



class StateLogic(LogicBase):
    ''
    def __init__(self,state_type,*,name=None) :

        self.state_type = state_type
        super().__init__(name=name, init=self.state_type.reset_item)

        self.switch_block = None
        
    def islogic(self) : return False
    def isvector(self) : return False
    def isarray(self) : return False

    @property
    def width(self) : return 1  # dummy for assignment

    @property
    def items(self) : return [s.name for s in self.state_type.state_items]

    @property
    def reset_item(self) : return self.state_type.reset_item

    def item(self,name) : return self.state_type.item(name)


#-------------------------------------------------------------------------
# assignment
#-------------------------------------------------------------------------
class AssignmentBase: 
    ''
    def __init__(self,dst, data) :
        ''
        self.dst = dst  # destination signal

        if type(data) is not tuple : 
            # a <= b, simple assignmenet
            self.values = [data]
            self.conditions = []
        else : 
            # value가 tuple인 경우 recursive하게 logic value로 만든다.
            self.values = list(data[::2])
            self.conditions = list(data[1::2])

        self._cvt_2_logics_expression()

    def _cvt_2_logics_expression(self):
        for i,v in enumerate(self.values) :
            # recursive
            if type(v) is tuple : 
                self.values[i] = AssignmentBase(self.dst,v)
                continue

            # integer인 경우 logic으로 변경
            v = _cvt2signal(self.dst,v)

            # values의 width가 dst에 비해 적을 때는 0을 채운다.
            if not isinstance(self.dst, StateLogic): 
                if not isinstance(self.dst.width, GenericVar) : 
                    if not isinstance(v,(StateLogic,LogicExpr,StateItem)) and self.dst.width > v.width : 
                        k = self.dst.width - v.width
                        v = VectorCombine(SignalConstant(value=0,width=k),v)

            # a <= b, a, b의 width가 같음을 check한다.             
            # if isinstance(v, LogicBase) : 
            if isinstance(v, LogicBase) and get_module().is_2nd_run(): 
                assert self.dst.width == v.width, 'Width of destination[%s] and source[%s] should be same' % (self.dst.width, v.width)

            # value가 arithmetic인 경우 destination에 맞추어 type conversion 한다. 
            if isinstance(v, ArithmeticOperator):
                if self.dst.sig_type == SigType.logic : 
                    v = FunctionExpr('logic', v)

            # value에 BooleanOperator가 있는 경우 bitwise setting한다. 
            if isinstance(v,BooleanOperator):
                v.logical = False


            # store final value
            self.values[i] = v

        # condition이 expression이 아니면 active high로 변경한다.
        self.conditions = [_condition2ActiveHigh(c) for c in self.conditions] 

    @property
    def srcs(self) : 
        return [s for s in self.values + self.conditions 
                if isinstance(s,LogicBase) and not isinstance(s,SignalConstant)]

    @property
    def isignals(self) : 
        ''
        sig_list = []
        for v in itertools.chain(self.values,self.conditions) : 
            if isinstance(v, SignalConstant) : continue

            # expression 
            if isinstance(v, (LogicExpr,VectorCombine,LogicSlice,AssignmentBase)):
                sig_list += v.isignals
            elif isinstance(v, LogicBase):
                sig_list.append(v)

        return sig_list

    def is_simple_assign(self): # condition 없는 a <= b인지 check, a <= const는 제외된다.
        return len(self.conditions) == 0 and len(self.srcs) == 1
    

class SignalAssignment(AssignmentBase, AndOrXorMixin): 
    ''
    @property
    def osignals(self) : 
        return [self.dst.base]

    @property
    def variables(self) : 
        return []

   
class VariableAssignment(AssignmentBase): 
    ''
    @property
    def osignals(self) : 
        return []

    @property
    def variables(self) : 
        if isinstance(self.dst,LogicSlice) : 
            return [self.dst.base_signal]
        else : 
            return [self.dst]

def _cvt_assign_2_leexpr(statement):
    ''
    condition = LeExpr(statement.dst,statement.values[0])

    get_module().remove_assignment(statement)

    return condition

#-------------------------------------------------------------------------
# LogicExpr
#    Arithmetic : Add, Sub
#    Condition 
#        Comparison
#        Boolean  (and, or)
#-------------------------------------------------------------------------
class LogicExpr : 
    ''
    @property
    def isignals(self) : return []

class InvertOperator(LogicExpr) : 
    ' ~  bitwise invert (vhdl => not op) '
    def __init__(self,op1) :
        self.op1 = op1 
        self.operator = '~'

    @property
    def width(self) : return self.op1.width

    def islogic(self) : return self.op1.islogic()
    def isvector(self) : return self.op1.isvector()
    def isarray(self) : return self.op1.isarray()

    @property
    # def isignals(self) : return [self.op1]
    def isignals(self) : 
        if hasattr(self.op1,'isignals') : 
            return self.op1.isignals
        else : 
            return [self.op1]

#-------------------------------------------------------------------------
# function  
#-------------------------------------------------------------------------
class FunctionExpr(LogicExpr,ExprMixin) : 
    ''
    def __init__(self,func,argv) :
        self.func = func   # string : logic, unsigned
        self.argv = argv

    def islogic(self) : return self.argv.islogic()
    def isvector(self) : return self.argv.isvector()
    def isarray(self) : return self.argv.isarray()

    @property
    def width(self) : return self.argv.width

    @property
    def isignals(self) : return self.argv.isignals

#-------------------------------------------------------------------------
# Arithmetic
#-------------------------------------------------------------------------
class ArithmeticOperator(LogicExpr) : 
    ' + , -, *'
    def __init__(self,op1,op2,operator) :
        ''
        super().__init__()

        def _int_2_signal(op): 
            ''
            if type(op) is int : 
                return SignalConstant(op,0)
            else : 
                return op

        self.op1 = _int_2_signal(op1)
        self.op2 = _int_2_signal(op2)
        self.operator = operator
    
    @property
    def width(self) : return max(self.op1.width, self.op2.width)

    @property
    def isignals(self) : 
        return self.op1.isignals + self.op2.isignals


class AddExpr(ArithmeticOperator) : # ' op1 + op2 '
    def __init__(self,op1,op2) :
        super().__init__(op1,op2,'+')
        
    def __add__(self,other) : return AddExpr(self,other) 
    def __sub__(self,other) : return SubExpr(self,other) 

class SubExpr(ArithmeticOperator) : # ' op1 - op2 '
    def __init__(self,op1,op2) :
        super().__init__(op1,op2,'-')

    def __add__(self,other) : return AddExpr(self,other) 
    def __sub__(self,other) : return SubExpr(self,other) 

class MultExpr(ArithmeticOperator) : # ' op1 * op2 '
    def __init__(self,op1,op2) :
        super().__init__(op1,op2,'*')

    def __mul__(self,other) : return MultExpr(self,other) 

    @property
    def width(self) : return self.op1.width + self.op2.width


#-------------------------------------------------------------------------
# condition  
#-------------------------------------------------------------------------
class ConditionOperator(LogicExpr) : 
    ''

class AllTrue(ConditionOperator) : 
    ''

class AllFalse(ConditionOperator) : 
    ''

class ComparisonOperator(ConditionOperator,AndOrXorMixin) : 
    ' == , != , >, < , ... '
    def __init__(self,op1,op2,operator) :
        ''
        super().__init__()

        self.op1 = op1
        # self.op2 = op2
        if type(op2) is int : 
            self.op2 = _cvt2signal(op1,op2)
        else : 
            self.op2 = op2

        self.operator = operator

    def issimple(self): 
        ' a == 1, 1 == a '
        if isinstance(self.op1,BitVector) and isinstance(self.op2,SignalConstant) :  
            if self.op2.value == 1 and self.op2.width==1:
                return True
        elif isinstance(self.op2,BitVector) and isinstance(self.op1,SignalConstant) :  
            if self.op1.value == 1 and self.op1.width==1:
                return True
        else : 
            return False

    @property
    def isignals(self) : 
        def _op_sig(op):
            if isinstance(op, LogicBase):
                return [op]
            elif isinstance(op, LogicSlice):
                return [op.base_signal] 
            elif isinstance(op, FunctionExpr):
                return op.isignals
            else :
                return []

        s = []
        s += _op_sig(self.op1)
        s += _op_sig(self.op2)
        return s

    def __invert__(self) :  # ~  
        return InvertOperator(self)


class EqExpr(ComparisonOperator) : 
    def __init__(self,op1,op2) : 
        super().__init__(op1,op2,'==')

        # StateSignal은 State()와만 equal test를 할 수 있다.
        # if isinstance(op1, (StateSignal,StateLogic)) : 
        if isinstance(op1, StateLogic) : 
            assert isinstance(op2, StateItem), 'op2(%s) should be State variable' % op2


class NeExpr(ComparisonOperator) : 
    def __init__(self,op1,op2) : super().__init__(op1,op2,'!=')

class GtExpr(ComparisonOperator) : 
    def __init__(self,op1,op2) : super().__init__(op1,op2,'>')

class GeExpr(ComparisonOperator) : 
    def __init__(self,op1,op2) : super().__init__(op1,op2,'>=')

class LtExpr(ComparisonOperator) : 
    def __init__(self,op1,op2) : super().__init__(op1,op2,'<')

class LeExpr(ComparisonOperator) : 
    def __init__(self,op1,op2) : super().__init__(op1,op2,'<=')

# boolean 
class BooleanOperator(LogicExpr) : 
    ' (and , or, xor) => & , | ^ '
    def __init__(self,op1, op2, *expressions) :
        self.operands = [op1,op2] + list(expressions)

        self.logical = True   # logical인 경우 True bitwise인 경우 False

    @property
    def isignals(self) : 
        ''
        s = []
        for o in self.operands : 
            if isinstance(o, (LogicBase,LogicSlice)):
                s.append(o)
            elif isinstance(o, LogicExpr):
                s += o.isignals

        s = _s2.remove_same_item(s)
        return s

    def islogical(self) : return self.logical
    def isbitwise(self) : return not self.logical

    # width를 알려고 하는 곳은 모두 value이다. condition에서는 width를 알 필요가 없다.
    @property
    def width(self) : 
        return self.bitwise_width

    @property
    def bitwise_width(self) : 
        return max_bits_of_list(self.operands)

        
class AndExpr(BooleanOperator) : 
    ' and '

class OrExpr(BooleanOperator) : 
    ' or '

class XorExpr(BooleanOperator) :
    ' xor '


#-------------------------------------------------------------------------
# generic variable (VHDL generic)
#-------------------------------------------------------------------------
class GenericArithmetic:
    ' + , -, *'
    def __init__(self,op1,op2,operator) :
        self.op1 = op1
        self.op2 = op2
        self.operator = operator

class GenericAdd(GenericArithmetic) :
    def __init__(self,op1,op2) : super().__init__(op1,op2,'+')
    def __add__(self,other) : return GenericAdd(self,other)
    def __sub__(self,other) : return GenericSub(self,other)

class GenericSub(GenericArithmetic) :
    def __init__(self,op1,op2) : super().__init__(op1,op2,'-')
    def __add__(self,other) : return GenericAdd(self,other)
    def __sub__(self,other) : return GenericSub(self,other)

class GenericMul(GenericArithmetic) :
    def __init__(self,op1,op2) : super().__init__(op1,op2,'*')
    def __add__(self,other) : return GenericAdd(self,other)
    def __sub__(self,other) : return GenericSub(self,other)
    def __mul__(self,other) : return GenericMul(self,other)

class GenericVar :
    ' generic value class '
    def __init__(self,key,value) :
        self.key   = key
        self.value = value
    def __add__(self,other) : return GenericAdd(self,other)
    def __sub__(self,other) : return GenericSub(self,other)
    def __mul__(self,other) : return GenericMul(self,other)
    def __repr__(self): return self.key


#-------------------------------------------------------------------------
# for-generate variable (stays here because ForVariable.init calls get_module())
#-------------------------------------------------------------------------
class ForVariable :
    def __init__(self,name,seq_flag) :
        self.name = name
        get_module().forvar.append((seq_flag,self.name))
    def __add__(self,other) : return AddExpr(self,other)
    def __sub__(self,other) : return SubExpr(self,other)
    def __mul__(self,other) : return MultExpr(self,other)


#-------------------------------------------------------------------------
# HDL structure objects — moved to hstructure.py (Phase 5)
# Re-exported here so existing  import hsignal as hs  code keeps working.
#-------------------------------------------------------------------------
from hstructure import (
    HDLObject,
    BlankLine,
    RawCode, RawCodeDecl,
    LibraryDecl,
    IModule,
    CBlock,
    ForGenerate,
    IfBlock, IfBlockCondition,
    SwitchBlock, CaseCondition, SwitchAssignment,
    SeqBlock,
    _condition2ActiveHigh, _verilog_chg_reset,
    _remove_assignment, _get_assignment,
)
# GenericVar/ForVariable are defined above (used in this module too)

#-------------------------------------------------------------------------
# helper functions 
#-------------------------------------------------------------------------

def _mk_logic(mod,name,src,unique):

    if not isinstance(name, str):
        name = name.name

    logic_create = mod.logic_unique_define if unique else mod.logic_define
    array_create = mod.array_unique_define if unique else mod.array_define

    if isinstance(src, BitVector) :
        return logic_create(name,sig_type=SigType.logic)
    elif isinstance(src, Vector) :
        if isinstance(src, MultiVector) :
            return logic_create("%s[%s][%s]"%(name,len(src),src.width),sig_type=SigType.logic,init=src.init)
        else:
            return logic_create("%s[%s]"%(name,src.width),sig_type=SigType.logic,init=src.init)
    elif isinstance(src, Array) :
        return array_create("%s[%s][%s]"%(name,len(src),src.width),sig_type=SigType.logic,init=src.init)

    elif isinstance(src,StateLogic):
        dst = StateLogic(src.state_type,name=name)
        mod.namespace[dst.name]=dst
        return dst
    else : 
        assert 0, "%s is unknown type at mk_logic_like())" % src

def copy_logic_like(mod,name,src):
    ' src와 같은 형식으로 logic을 만든다. '
    return _mk_logic(mod,name,src,False)

def copy_logic_like_unique(mod,name,src):
    ''
    # print(mod,name,src)
    return _mk_logic(mod,name,src,True)






#-------------------------------------------------------------------------
# sub routines
#-------------------------------------------------------------------------
from sc_util import min_bits, max_bits_of_list


def _calc_max_width(data : tuple):
    ' data에는 integer와 Signal이 있다. '
    # 0,2,4,... 가 data 이다.  1,3,5는 condition
    return max_bits_of_list(data[0::2])



from sc_util import calc_hash_value



def HH(width): return SignalConstant(value=2**width-1, width=width)

def LL(width): return SignalConstant(value=0, width=width)

def FILL(v,width): 
    ' v must be 1 bit logic'
    assert v.width==1
    cc = VectorCombine()
    for i in range(width):
        cc.append(v)
    return cc

def ZZ(width): return SignalConstant(value='Z', width=width)

def XX(width): return SignalConstant(value='X', width=width)

def INT(value,width): return SignalConstant(value=value, width=width)



from sc_util import slice_width


def get_logic(name):
    ' get logic from name '
    namespace = get_module().namespace

    if name in namespace.keys() :
        v = namespace[name]
        if isinstance(v,LogicBase):
            return v

    return None




