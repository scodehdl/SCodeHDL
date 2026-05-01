'''
    Verilog code generation

    2015-04-30 : restarted
    2015-10-24 : restarted again
    2016-09-08 : file stimulus complete 
'''
import io
import os,sys
import collections 
from string import Template
import itertools
import math

if __name__ == '__main__':
    sys.path.append('..')
    
import _s2
import hsignal as hs

TIME_SLACK = 0.0


#-------------------------------------------------------------------------
# type, declaration 
#-------------------------------------------------------------------------
def __vector_r(p):
    if p.sig_type is hs.SigType.logic : 
        type_name = 'std_logic_vector'
    else : # signed, unsigned 
        type_name = p.sig_type.name 

    if not isinstance(p.width, hs.GenericVar) : 
        _w = p.total_bits
        if type_name == 'std_logic_vector' : 
            if p.little_endian : 
                return '[%s:%s]'%((_w+p.start_bit-1),p.start_bit)
            else : # big
                return '[%s:%s]'%(p.start_bit,(_w+p.start_bit-1))
        else : 
            return '%s [%s:%s]'%(type_name,(_w+p.start_bit-1),p.start_bit)

    if not isinstance(p.width, hs.GenericVar) : 
        _w = p.total_bits
        if p.little_endian : 
            return '[%s:%s]'%((_w+p.start_bit-1),p.start_bit)
        else : # big
            return '[%s:%s]'%(p.start_bit,(_w+p.start_bit-1))

    else : # sc에서 generic사용하여 width 결정한 vector이다.
        return '[%s-1:%s]'%(p.width.key,p.start_bit)

def __array_r(p):
    return '[%s:0] %s[%s:0]' % (p.width-1, p.name, len(p)-1)


def c_type_def_logic(self): 
    return ''

def c_type_def_vector(self): 
    return __vector_r(self)

def c_type_def_array(self): 
    return __array_r(self)


def c_type_def_slice(self): # vector or array 
    if isinstance(self.base_signal,hs.Array):
        return __array_r(self.base_signal)
    else : 
        return __vector_r(self.base_signal)


# signal declaration
def c_signal_decl(self):
    p = self if not isinstance(self,hs.LogicSlice) else self.base_signal

    wire_reg_str = 'reg' if self.reg_wire else 'wire'

    if not p.isarray() : 
        if not p.init_defined : 
            return '    %s %s %s;' % (wire_reg_str, p.c_type_def(), p.name)
        else :  
            return '    %s %s %s=%s;' % (wire_reg_str, p.c_type_def(), p.name, p.c_value(p.init))
    else : # array 
        # array 초기화는 initial 문장을 이용한다.
        return '    %s %s;' % (wire_reg_str, p.c_type_def())



# state declaration
def c_signal_decl_state_logic(self):
    p = self

    n = p.state_type.state_bits_width
    result = '    reg [%s:0] %s;' % (n-1,p.name) 

    return result

#-------------------------------------------------------------------------
# value, value reset
#-------------------------------------------------------------------------
def _check_nan_to_zero(value) : 
    ' nan이면 0으로 return '
    # if math.isnan(value):
    if _s2.check_nan(value):
        return 0
    else : 
        return value


def c_logic_value(self,value) : 
    ' logic value : 0 or 1'
    value = _check_nan_to_zero(value)
    # return "%d" % value
    return _hex_formatting(value,self.width)

def c_vector_value(self,value) : 
    ' vector value '
    value = _check_nan_to_zero(value)
    return _hex_formatting(value,self.total_bits)

def c_mulitvector_value(self,value) : 
    ' multivector value '
    value = self.init_to_vector_value(value)
    value = _check_nan_to_zero(value)
    return _hex_formatting(value,self.total_bits)

def c_array_value(self,value) : 
    ''
    return "[!!! array not implemented]"


def c_signalslice_value(self,value) : 
    ' slice value '
    if isinstance(self, hs.ArraySlice):
        raise SyntaxError

    value = _check_nan_to_zero(value)
    return _hex_formatting(value,self.width)

def c_logic_value_reset(self,variable_flag=False) :
    symbol = '<=' if variable_flag==False else '='
    return '%s %s %s' % (self.name,symbol,self.c_value(self.init))

def c_vector_value_reset(self,variable_flag=False) :
    ' vector value '
    symbol = '<=' if variable_flag==False else '='

    value = _check_nan_to_zero(self.init)

    return "%s %s %s" % (self.name,symbol,_hex_formatting(value,self.total_bits))

def c_multivector_value_reset(self,variable_flag=False) :
    ' multi vector value '
    symbol = '<=' if variable_flag==False else '='

    value = self.init_to_vector_value(self.init)
    value = _check_nan_to_zero(value)

    return "%s %s %s" % (self.name,symbol,_hex_formatting(value,self.total_bits))


def c_array_value_reset(self,variable_flag=False) :
    symbol = '<=' if variable_flag==False else '='

    if self.init_defined : 
        s = ','.join(_hex_formatting(v,self.width) for v in self.init)
        return "%s %s (%s)" % (self.name,symbol,s)
    else : 
        return "%s %s %s" % (self.name,symbol, _hex_formatting(0,self.width*len(self)))




def c_statelogic_value_reset(self,variable_flag=False) :
    symbol = '<=' if variable_flag==False else '='
    return '%s %s %s' % (self.name,symbol,self.init.name)


def c_constant_high_impedance(self,dummy=None):
    "16'bZ"
    return "%s'hZ" % (self.width) 

#-------------------------------------------------------------------------
# representaion
#-------------------------------------------------------------------------
def c_repr(self): 
    return self.name

def c_repr_vector_combine(self): 
    # print(self.vectors)
    r = ','.join(v.c_repr() for v in self.vectors)
    return '{%s}' % r

def c_repr_signalslice(self):

    name= self.base_signal.name

    if isinstance(self, hs.ArraySlice): 
        ' Array에서 slice로 오는 경우만 있다. '
        return  '%s[%s:%s]'%(name, self.slice1.start, self.slice1.stop)

    elif isinstance(self, hs.VectorSlice): 
        ''
        if isinstance(self.base_signal,hs.Array) : 
            ' Array에서 파생된 VectorSlice'
            if type(self.slice1) == int : 
                # s = '%s[%s:%s]'%(name, (self.slice1+1)*self.width-1,self.slice1*self.width)
                s = '%s[%s]'%(name, self.slice1)
            elif type(self.slice1) == slice : 
                s = '%s[%s:%s]'%(name, self.slice1.start, self.slice1.stop)
            elif isinstance(self.slice1, hs.Vector):
                s = '%s[%s]'%(name,self.slice1.name)
            elif isinstance(self.slice1, hs.VectorSlice):
                s = '%s[%s]'%(name,c_repr_signalslice(self.slice1))
            else : 
                assert 0, '%s not supported' % self.slice1

            # slice2
            if self.slice2 is not None : 
                if type(self.slice2) == int : 
                    s += '[%s]'%(self.slice2)
                else : 
                    s += '[%s:%s]'%(self.slice2.start, self.slice2.stop)
            return s

        elif isinstance(self.base_signal,hs.Vector) : 
            'vector에서 온 경우에는 slice만 있다.'
            return  '%s[%s:%s]'%(name, self.slice1.start, self.slice1.stop)

        elif isinstance(self.base_signal,hs.VectorSlice) : 
            ' VectorSlice에서 다시 VectorSlice가 나온 경우 '
            return  '%s[%s:%s]'%(name, self.slice1.stop + self.slice2.start, self.slice1.stop + self.slice2.stop)

        else : 
            return 'c_repr_signalslice:',self.base_signal, isinstance(self.base_signal,hs.Vector)

    else : # BitVectorSlice
        if isinstance(self.base_signal,hs.Vector) : 
            if type(self.slice1) == int : 
                return '%s[%s]'%(name, self.slice1)
            elif isinstance(self.slice1, hs.Vector):
                return '%s[%s]'%(name,self.slice1.name)
            elif isinstance(self.slice1, hs.VectorSlice):
                return '%s[%s]'%(name,c_repr_signalslice(self.slice1))
            elif isinstance(self.slice1, hs.ForVariable):
                return '%s[%s]'%(name,self.slice1.name)
            elif isinstance(self.slice1, hs.ArithmeticOperator):
                return '%s[%s]'%(name,c_op_src_repr_arithmetic(self.slice1))
            else : 
                assert 0, '%s not supported' % self.slice1

        elif isinstance(self.base_signal.base_signal,hs.Array) : 
            def _index_str(a):
                if type(a) == int : 
                    s1 = '[%s]' % a
                else : # vector
                    s1 = '[%s]' % a.name
                return s1

            s1 = _index_str(self.slice1)
            s2 = _index_str(self.slice2)

            return '%s%s%s' % (name,s1,s2)
        
        elif isinstance(self.base_signal,hs.VectorSlice) : 
            if type(self.slice2) == int : 
                return '%s[%s]'%(name, self.slice1.stop + self.slice2)
            else : 
                assert 0, '%s not supported' % self.slice2


def c_repr_valuetype(self):
    # return self.code
    if self.code == 'open' :  # unconnected port
        return ""
    else : 
        return self.code

def c_repr_for_var(self): 
    return self.name


def c_repr_constant(self): 
    ''
    v = self.value

    mark = '"' if self.vector_1bit or isinstance(self.width, hs.GenericVar) or self.width > 1 else "'"  # vector : ", logic '
    if type(v) == str : # 'X', 'Z'
        return "%s'h%s" % (self.width,v) 
    else : # integer
        return _hex_formatting(v,self.width) 
    
def c_repr_signal_assignment(self):
    ' combinational assignement (assign 사용) '
    if 1 : 
        dst        = self.dst
        values     = self.values
        conditions = self.conditions

        if len(conditions) >= 1 : 
            cvt_code = 'assign %s = ' % dst.c_repr()
            for i, kk in enumerate(zip(values,conditions)) : 
                v, c = kk 
                cvt_code += '(%s) ? %s : ' % (c.c_repr(),v.c_repr())
 
            # last value : combination은 항상 value의 개수가 condition 개수보다 1개 많음
            cvt_code += '%s;' % values[i+1].c_repr() 
            return cvt_code

        else : # no condition
            return 'assign %s' % _simple_statement_comb(dst,values[0])

#-------------------------------------------------------------------------
# operator source representation 
#-------------------------------------------------------------------------
def c_op_src_repr(self):
    return repr(self)

def c_op_src_repr_function(self):
    if self.func == 'logic':
        return '%s' % (self.argv.c_repr())
    else : 
        return '$%s(%s)' % (self.func, self.argv.c_repr())

def c_op_src_repr_boolean(self):
    if isinstance(self, (hs.AndExpr)):
        k = ' && ' if self.islogical() else ' & '
        s = k.join([e.c_repr() for e in self.operands])
        return '(%s)' % s
    elif isinstance(self,(hs.OrExpr)):
        k = ' || ' if self.islogical() else ' | '
        s = k.join([e.c_repr() for e in self.operands])
        return '(%s)' % s
    elif isinstance(self,hs.XorExpr):
        s = ' ^ '.join([e.c_repr() for e in self.operands])
        return '(%s)' % s
    else : 
        return repr(self)

def c_op_src_repr_condition(self):
    condition = self

    op1,op2 = condition.op1, condition.op2

    if isinstance(op2, hs.SignalConstant):
        if op1.isvector() : # op2의 width로 표현한다.  
            op2 = _hex_formatting(op2.value,op2.width)
        else : 
            op2 = op1.c_value(op2.value)
    else : 
        op2 = op2.c_repr()

    op1 = op1.c_repr()

    if isinstance(condition, hs.ComparisonOperator):
        return _binary_operator(op1,op2, condition.operator)

def _arith_op_repr(op):
    ''
    if isinstance(op, hs.SignalConstant):
        op_r = op.value
    elif isinstance(op, hs.VectorCombine):
        op_r = '%s' % op.c_repr() 
    elif isinstance(op,hs.ArithmeticOperator):  # multiple operation : A + B + C
        op_r = '(%s %s %s)' % (_arith_op_repr(op.op1),op.operator,_arith_op_repr(op.op2))
    elif isinstance(op,(hs.LogicBase,hs.VectorSlice)) : 
        op_r = '%s' % op.c_repr()
    elif isinstance(op,(hs.BitVectorSlice)) : 
        op_r = '("" & %s)' % op.c_repr()
    else : 
        op_r = op.c_repr()

    return op_r

def c_op_src_repr_arithmetic(self):
    ' self.operator : + , - , *'

    assert self.operator in ['+', '-', '*']

    expr = self
    op1,op2 = expr.op1, expr.op2

    op1 = _arith_op_repr(op1)
    op2 = _arith_op_repr(op2)

    return '%s %s %s' % (op1,expr.operator,op2)


def c_op_src_repr_invert(self):
    if isinstance(self.op1, hs.LogicExpr):
        return '~(%s)' % (self.op1.c_repr())
    else : 
        return '~%s' % (self.op1.c_repr())

#-------------------------------------------------------------------------
#  HDLObject representation
#-------------------------------------------------------------------------
def c_cblock_repr(self): 
    return self.statement.c_repr()


def c_seqblock_repr(self): 
    seq = self


    edge = 'rising_edge' if seq.clk_edge != 'falling' else 'falling_edge'

    if seq.reset : 
        _sigs = []
        for s in seq.osignals : 
            _sigs.append(s)

        _vars = []
        for s in seq.variables : 
            _vars.append(s)
            
        # VectorSlice 중복을 피하기 위한 코드 추가
        _r_init = []
        for s in _vars : 
            k = '%s;' % s.c_value_reset(variable_flag=True)
            if k not in _r_init : 
                _r_init.append(k)

        for s in _sigs : 
            k = '%s;' % s.c_value_reset()
            if k not in _r_init : 
                _r_init.append(k)

        reset_init = '\n'.join(_r_init)
        reset_init = _s2.set_indentation(reset_init, 8).strip()
    
    # variable definition
    # block name should exist to define local variable
    variable_def = ''  
    if  seq.variables : 
        variable_def += ' : uut_%d' % seq.id
        for v in seq.variables : 
            wire_reg_str = 'reg' if v.reg_wire else 'wire'

            if not v.isarray() : 
                variable_def += '\n    %s %s %s;' % (wire_reg_str,v.c_type_def(),v.name)
            else : # array 
                variable_def += '\n    %s %s;' % (wire_reg_str,v.c_type_def())

    # body
    statements = ''
    if seq.objects :
        statements = __seqobject(seq.objects)

        indent_n = 8 if seq.reset else 4
        statements = _s2.set_indentation(statements,indent_n).strip()


    #-------------------------------------------------------------------------
    # code generation
    #-------------------------------------------------------------------------
    _tmpl_process = '''
always @(posedge $clk)
begin$variable_def
    $statements
end
'''

    _tmpl_process_areset = '''
always @(posedge $clk or $reset)
begin$variable_def
    if ($reset_expr) begin
        $reset_init
    end
    else begin
        $statements
    end
end
''' 
    _tmpl_process_sreset = '''
always @(posedge $clk)
begin$variable_def
    if ($reset_expr) begin
        $reset_init
    end
    else begin
        $statements
    end
end
''' 

    cvt_code = ''
    if seq.reset : 
        reset_str = ' or '.join('posedge %s' % i.name for i in self.reset.isignals)
        reset_expr = self.reset.c_repr()

        # 
        _tmpl_process_reset = _tmpl_process_sreset if self.reset_type=='sync' else _tmpl_process_areset 
        cvt_code += Template(_tmpl_process_reset).safe_substitute(
                    clk = seq.clk.name,
                    reset      = reset_str,
                    reset_expr = reset_expr,
                    reset_init = reset_init,
                    variable_def = variable_def,
                    statements = statements,
                    edge = edge,
                )
    else : # no reset
        cvt_code += Template(_tmpl_process).safe_substitute(
                    clk = seq.clk.name,
                    variable_def = variable_def,
                    statements = statements,
                    edge = edge,
                )
    return cvt_code



def c_module_repr(self): 
    ' imodule에 의해 include되는 module을 표현한다. '

    o = self

    __tmpl = '''
$entity_name $uut (
    $port_connection
);
'''
    __tmpl_generic = '''
$entity_name # (
    $generic_connection
) $uut (
    $port_connection
);
'''

    def _connect_sig(k,v) : 
        ''
        if type(v) == int : 
            s = k.c_value(v)
            result = '    .%-19s(%s)'%(k.name,s)
        else : 
            v1_ = v.c_repr()
            result = '    .%-19s(%s)'%(k.name,v1_)
        return result

    # port => connection
    clist = []
    for port_sig in o.module.port_list :
        conn_sig = o.connection_dict.get(port_sig,None)
        if conn_sig is None : conn_sig = hs.SIG_OPEN

        clist.append(_connect_sig(port_sig,conn_sig))
    port_conn = ',\n'.join(clist).strip()

    # generic
    if o.connection_generic is not None and len(o.connection_generic) >  0 :
        clist = []
        for port_sig in o.module.generic_dict :
            conn_sig = o.connection_generic.get(port_sig,None)
            if conn_sig is None : 
                continue
            
            if type(conn_sig) is str : 
                # check boolean
                if conn_sig.lower() in ['true','false'] : 
                    clist.append('    .%-19s("%s")'%(port_sig,conn_sig.upper()))
                else : 
                    clist.append('    .%-19s("%s")'%(port_sig,conn_sig))   # k, v
            else:
                clist.append('    .%-19s(%s)'%(port_sig,conn_sig))   # k, v
        gen_conn = ',\n'.join(clist).strip()


    #-------------------------------------------------------------------------
    # conversion 
    #-------------------------------------------------------------------------
    if o.connection_generic is None or len(o.connection_generic) == 0 :
        ''
        cvt_code = Template(__tmpl).safe_substitute(
                    uut             = 'u%s_%s' % (o.uut_id,o.module.mod_name),
                    entity_name     = o.module.mod_name,
                    port_connection = port_conn,
                )
    else : # generic 존재 
        cvt_code = Template(__tmpl_generic).safe_substitute(
                    uut             = 'u%s_%s' % (o.uut_id,o.module.mod_name),
                    entity_name     = o.module.mod_name,
                    generic_connection = gen_conn,
                    port_connection = port_conn,
                )

    return cvt_code 

def c_rawcode_repr(self) :
    return self.code

def c_blankline_repr(self) :
    # return "%s\n" % self.blank_line_num
    s = ""
    for i in range(self.blank_line_num) :
        s += "\n"
    return s

def c_switch_assign_repr(self) :
    # return repr(self)
    
    _tmpl_process = '''
always @ ($sensitivity)
begin
    $switch_statement
end
'''
    sensitivity = ','.join([i.c_repr() for i in [self.case_sig] + self.isignals])

    # 
    code = _s2.set_indentation(__switch_block(self),4).strip()
    cvt_code = Template(_tmpl_process).safe_substitute(
                switch_statement = code,
                sensitivity = sensitivity
            )
    return cvt_code

#-------------------------------------------------------------------------
# for loop 
#-------------------------------------------------------------------------
def _generic_arith_op_repr(op):
    ''
    if type(op) is int : 
        op_r = '%s' % op
    elif isinstance(op,hs.GenericArithmetic):
        op_r = '(%s %s %s)' % (_generic_arith_op_repr(op.op1),op.operator,_generic_arith_op_repr(op.op2))
    elif isinstance(op,hs.GenericVar):
        op_r = '%s' % op.key
    else : 
        op_r = op.c_repr()

    return op_r

def c_op_src_repr_generic_arithmetic(self):
    ' self.operator : + , - , *'

    assert self.operator in ['+', '-', '*']

    expr = self
    op1,op2 = expr.op1, expr.op2

    op1 = _generic_arith_op_repr(op1)
    op2 = _generic_arith_op_repr(op2)

    return '%s %s %s' % (op1,expr.operator,op2)

def c_forgen_repr(self): 
    _tmpl_forgen = '''
for ($name = $start; $name <= $stop; $name = $name + 1)
begin
    $statements
end
'''
    name = self.for_var.name

    def _ss_repr(s):
        if type(s) is int : 
            return '%s' % s
        elif isinstance(s, hs.GenericVar) :
            return '%s' % s.key
        elif isinstance(self.stop, hs.GenericArithmetic) : 
            return s.c_repr()
        else : 
            return s

    start = _ss_repr(self.start)
    stop  = _ss_repr(self.stop)

    statements = ''
    if self.objects :
        if self.seq_flag==0:
            for o in self.objects :
                statements += o.c_repr()  # combinational objects
        else : 
            statements = __seqobject(self.objects)

        statements = _s2.set_indentation(statements,4).strip()

    cvt_code = Template(_tmpl_forgen).safe_substitute(
                name = self.for_var.name,
                start = start,
                stop = stop,
                statements = statements,
            )
    return cvt_code


def c_stimulus_repr(self): 
    return repr(self)

def c_delayed_assignment_repr(self):
    '''Verilog:
    repeat=True  →  always #10 clk = ~clk;
    repeat=False →  initial begin #100; reset = 0; end
    '''
    o = self
    if o.repeat:
        if hasattr(o.expr, 'c_repr'):
            expr_str = o.expr.c_repr()
        else:
            expr_str = verilog_integer(o.expr, o.signal.width)
        return 'always #%d %s = %s;' % (o.delay, o.signal.c_repr(), expr_str)
    else:
        if hasattr(o.expr, 'c_repr'):
            expr_str = o.expr.c_repr()
        else:
            expr_str = verilog_integer(o.expr, o.signal.width)
        return 'initial begin\n    #%d;\n    %s = %s;\nend' % (o.delay, o.signal.c_repr(), expr_str)


def c_stimulus_clock_repr(self):
    o = self
    __tmpl = '''
always  // ${uut}
begin
    $clk = 1;
    #$half_period1;
    $clk = 0;
    #$half_period2;
end
'''

    cvt_code = ''
    cvt_code += Template(__tmpl).safe_substitute(
                clk = o.clk.name,
                uut = o.id,
                half_period1 = int(o.period/2),
                half_period2 = o.period - int(o.period/2)
            )
    return cvt_code


def c_clocked_assignment_repr(self):
    '''Verilog: Single-cycle clocked stimulus fallback.'''
    clk_name = self.clk.c_repr()
    sig_name = self.signal.c_repr()
    if hasattr(self.expr, 'c_repr'):
        expr_str = self.expr.c_repr()
    else:
        expr_str = verilog_integer(self.expr, self.signal.width)
    
    waits = "\n        ".join(["@(posedge %s);" % clk_name for _ in range(self.cycle)])
    
    res = f"""
initial begin
    {waits}
    {sig_name} = {expr_str};
end"""
    return res.strip()

def c_consolidated_clocked_assignment_repr(clk, signal, points):
    '''Verilog: Multi-cycle clocked stimulus for a signal.'''
    clk_name = clk.c_repr()
    sig_name = signal.c_repr()

    body = []
    last_cycle = 0
    for p in points:
        diff = p.cycle - last_cycle
        if diff > 0:
            if diff == 1:
                body.append(f"@(posedge {clk_name});")
            else:
                body.append(f"repeat ({diff}) @(posedge {clk_name});")

        if hasattr(p.expr, 'c_repr'):
            expr_str = p.expr.c_repr()
        else:
            expr_str = verilog_integer(p.expr, p.signal.width)
        body.append(f"{sig_name} = {expr_str};")
        last_cycle = p.cycle

    body_str = "\n    ".join(body)
    res = f"""
initial begin
    {body_str}
end"""
    return res.strip()


def c_consolidated_group_clocked_repr(clk, signal_points_groups):
    '''Verilog: Multiple signals driven together in one initial block.

    signal_points_groups: list of (signal, sorted_points)
    '''
    from itertools import groupby
    clk_name = clk.c_repr()

    all_points = []
    for signal, points in signal_points_groups:
        for p in points:
            all_points.append((p.cycle, signal, p.expr))
    all_points.sort(key=lambda x: x[0])

    body = []
    last_cycle = 0
    for cycle, group in groupby(all_points, key=lambda x: x[0]):
        diff = cycle - last_cycle
        if diff > 0:
            if diff == 1:
                body.append(f"@(posedge {clk_name});")
            else:
                body.append(f"repeat ({diff}) @(posedge {clk_name});")

        assign_strs = []
        for _, sig, expr in group:
            expr_str = expr.c_repr() if hasattr(expr, 'c_repr') else verilog_integer(expr, sig.width)
            assign_strs.append(f"{sig.c_repr()} = {expr_str};")
        body.append(" ".join(assign_strs))
        last_cycle = cycle

    body_str = "\n    ".join(body)
    return f"initial begin\n    {body_str}\nend"

def c_stimulus_reset_repr(self): 
    o = self
    __tmpl = '''
initial
begin
    $reset = 0;
    #$delay;
    @ (posedge $clk) $reset = 1;
    @ (posedge $clk) $reset = 0;
end
'''

    cvt_code = ''
    cvt_code += Template(__tmpl).safe_substitute(
                clk = o.clk.name,
                reset = o.reset.name,
                uut = o.id,
                delay = o.delay,
            )
    return cvt_code

def c_stimulus_wave_repr(self) : 
    ''' 
        (example)

        #0.1; reset = 0;
        reset = 0; #50;
        reset = 1; #50;
        reset = 0; #0;
    '''
    o = self

    __tmpl = '''
initial
begin
    #${time_slack}; $sig = 0;
    $wave
end
'''
    wave = ["%s = %s; #%s;"%(o.sig.name,verilog_integer(value,o.sig.width),time) for value,time in o.value_time]
    wave = _s2.list_to_indented_line(wave,4).strip()

    #
    cvt_code = ''
    cvt_code += Template(__tmpl).safe_substitute(
                sig = o.sig.name,
                uut = o.id,
                time_slack = TIME_SLACK,
                wave = wave,
            )

    return cvt_code 


def c_stimulus_file_input_repr(self):
    ''
    __tmpl_fin = '''
always @(*) begin : rfile_p_$uut
    integer  infile;

    infile = $fopen("$fname", "r");

    if (infile == 0) begin
        $display("$fname not exists");
        $finish;
    end
    $display("[$fname] input started");

    $init_statement

    wait($enable==1'h1);

    while (!$feof(infile))  // not eof
    begin
        @ (posedge $clk)  // wait clock
        $read_statement
    end

    $fclose(infile);
    $display("[$fname] input ended");
end
'''
    # init statement
    init_list = ['%s <= 0;'%s.name for s in self.ilist]

    # read statement 
    type_list = []
    for i,s in enumerate(self.ilist)  : 
        if isinstance(s,hs.BitVector) : 
            type_list.append("%b")
        elif isinstance(s,hs.Vector) : 
            type_list.append("%H")
        else : 
            assert 0, 'Un-supported type : %s' % s
    type_str = ' '.join(type_list) 
    name_str = ','.join(s.name for s in self.ilist)
    read_statement = '$fscanf(infile,"%s\\n",%s);' % (type_str,name_str)

    # conversion
    cvt_code = ''
    cvt_code += Template(__tmpl_fin).safe_substitute(
                clk = self.clk.name,
                uut = self.id,                
                enable = self.enable.name,
                fname = self.fname.replace('\\','/'),
                # var_list = _s2.list_to_indented_line(var_list,8).strip(),
                init_statement = _s2.list_to_indented_line(init_list,4).strip(),
                read_statement = read_statement,
            )

    return cvt_code


def c_stimulus_file_output_repr(self):
    ''
    __tmpl_fout = '''
always @(*) begin : wfile_p_$uut
    integer  n;
    integer  outfile;

    outfile = $fopen("$fname", "w");
    if (outfile == 0) begin
        $display("$fname open error");
        $finish;
    end
    $display("[$fname] output started");

    n = 0;
    while (n < $output_num) begin
        @ (posedge $clk)  // wait clock

        if ($enable==1'h1)
        begin
            $write_statement
            n = n + 1;
        end
    end

    $fclose(outfile);
    $display("[$fname] output ended");
    wait(0);
end
'''
    # write statement 
    type_list = []
    for i,s in enumerate(self.olist)  : 
        if isinstance(s,hs.BitVector) : 
            type_list.append("%b")
        elif isinstance(s,hs.Vector) : 
            type_list.append("%H")
        else : 
            assert 0, 'Un-supported type : %s' % s
    type_str = ' '.join(type_list) 
    name_str = ','.join(s.name for s in self.olist)
    write_statement = '$fwrite(outfile,"%s\\n",%s);' % (type_str,name_str)

    # conversion
    cvt_code = ''
    cvt_code += Template(__tmpl_fout).safe_substitute(
                clk = self.clk.name,
                uut = self.id,                
                enable = self.enable.name,
                fname = self.fname.replace('\\','/'),
                output_num = self.output_num,

                write_statement = write_statement,
            )

    return cvt_code


#-------------------------------------------------------------------------
#  simple statement 
#-------------------------------------------------------------------------
def _constant_to_array(dst,v):
    ''
    num = len(dst)
    s1 = ','.join(['%s[%s]' % (dst.name,i) for i in range(num)])

    k = v.c_repr()
    s2 = ','.join(k for i in range(num))
    return '{%s} = {%s};' % (s1,s2)

def _simple_statement(dst,v,mark):
    if dst.isarray() and isinstance(v,(hs.LogicBase,hs.LogicSlice)) and v.isarray() : 
        s1 = []
        s2 = []
        for i in range(len(dst)):
            s1.append('%s[%s]' % (dst.name,i))
            s2.append('%s[%s]' % (v.name,i))
        # return '{%s} <= {%s};' % (','.join(s1),','.join(s2))
        return '{%s} %s {%s};' % (','.join(s1),mark,','.join(s2))
    elif dst.isarray() and isinstance(v,(hs.SignalConstant)) : 
        return _constant_to_array(dst,v)
    else:
        # return '%s = %s;' % (dst.c_repr(),v.c_repr())
        return '%s %s %s;' % (dst.c_repr(),mark,v.c_repr())

def _simple_statement_comb(dst,v):
    return _simple_statement(dst,v,'=')

def _simple_statement_seq(dst,v):
    return _simple_statement(dst,v,'<=')

def _simple_statement_variable(dst,v):
    return _simple_statement(dst,v,'=')


#-------------------------------------------------------------------------
# sequential if statement 
#-------------------------------------------------------------------------
def __seq_statement(statement) : 
    if isinstance(statement,hs.SignalAssignment) : 
        return __seq_statement_(statement,_simple_statement_seq)
    elif isinstance(statement,hs.VariableAssignment) : 
        return __seq_statement_(statement,_simple_statement_variable) 

def __seq_statement_variable(statement) : 
    return __seq_statement_(statement,_simple_statement_variable)

def __seq_statement_(statement, conv_func) : 
    ' assignment and sequential if, elif, else '

    __tmpl_if = '''
if ($condition) begin
    $statement
end
'''
    __tmpl_elif = '''else if ($condition) begin
    $statement
end
'''

    dst        = statement.dst
    values     = statement.values
    conditions = statement.conditions
    
    #
    if len(conditions) >= 1 : 
        ''
        cvt_code = ''

        for i, kk in enumerate(zip(values, conditions)) : 
            v, c = kk 
            __tmpl = __tmpl_if if i==0 else __tmpl_elif 

            if isinstance(v, hs.AssignmentBase):
                statement = _s2.set_indentation(__seq_statement_(v,conv_func),4).strip()
            else : 
                statement = conv_func(dst,v)

            cvt_code += Template(__tmpl).safe_substitute(
                    condition  = c.c_repr(),
                    statement  = statement,
            )

        # else
        if len(values) > len(conditions) :
            cvt_code += 'else\n'
            v = values[i+1]
            if isinstance(v, hs.AssignmentBase):
                statement = _s2.set_indentation(__seq_statement_(v,conv_func),4).strip()
            else : 
                statement = conv_func(dst,v)

            cvt_code += '    %s\n' % statement

        # cvt_code += 'end'
        return cvt_code.lstrip()

    else : # no condition    
        return conv_func(dst,values[0])

#-------------------------------------------------------------------------
# combinational mux 
#-------------------------------------------------------------------------
def __comb_mux(dst,sel,src) : 
    ' selection이 하나의 signal이다. '
    # case1 : source is list 
    __tmpl_mux_case_1 = '''
always @($sel)
begin
    case ($sel)
        $when_statements
    endcase
end
'''
    __tmpl_mux_case_2 = '''
always @($sel or $source)
begin
    case ($sel)
        $when_statements
    endcase;
end
'''

    when_list = []
    for i in range(len(src)) : 
        # k = 'when %s => %s <= %s;' % (sel.c_value(i), dst.c_repr(), _cvt_value(dst,src[i]))
        k = '%s : %s = %s;' % (sel.c_value(i), dst.c_repr(), src[i].c_repr())
        when_list.append(k)

    cvt_code = ''
    if type(src) is list : 
        cvt_code += Template(__tmpl_mux_case_1).safe_substitute(
                    sel = sel.c_repr(),
                    when_statements = _s2.list_to_indented_line(when_list, 8).strip(),
                )
    else : 
        cvt_code += Template(__tmpl_mux_case_2).safe_substitute(
                    sel = sel.c_repr(),
                    source = src.c_repr(),
                    when_statements = _s2.list_to_indented_line(when_list, 8).strip(),
                )
    return cvt_code.strip()



#-------------------------------------------------------------------------
# sequential conversion 
#-------------------------------------------------------------------------
def _ifblock(ifblock):
    ''
    keys = ifblock.conditions
    # print(keys)

    cvt_code = ''
    for i,cond in enumerate(keys) : 
        if i == 0 : 
            m = 'if' 
        elif isinstance(cond,hs.AllTrue):
            m = 'else' 
        else : 
            m = 'else if'

        if m == 'else':
            cvt_code += '%s begin\n' % (m)   # else
        else : 
            cvt_code += '%s (%s) begin\n' % (m,cond.c_repr())

        # statements
        for s in ifblock.conditions[cond] : 
            # print(s,__seq_(s),'>>>>>>>')
            cvt_code += '    %s\n' % _s2.set_indentation(__seq_(s),4).strip()

        cvt_code += 'end\n'

    # print(cvt_code)
    return cvt_code


def __seq_(o):
    if isinstance(o,hs.SignalAssignment) : 
        cvt_code = '%s\n' % __seq_statement(o)
    elif isinstance(o,hs.VariableAssignment) : 
        cvt_code = '%s\n' % __seq_statement_variable(o)
    elif isinstance(o,hs.SwitchBlock) : 
        cvt_code = '%s\n' % __switch_block(o)
    elif isinstance(o,hs.ForGenerate) : 
        cvt_code = '%s\n' % o.c_hdl_repr()
    else :
        cvt_code = '%s' % _ifblock(o)
    return cvt_code

def __seqobject(objects):
    ''
    cvt_code = ''  

    for o in objects : 
        cvt_code += __seq_(o) 

    return cvt_code


def __switch_block(swb):
    ''
    cvt_code = ''
    if swb.conditions :
        cvt_code = __switch_case(swb.case_sig,swb.conditions)

    return cvt_code


def _check_simple_statement(s):
    ' condition이 없으면 simple statement'
    if len(s.values)==1 and len(s.conditions)==0 :
        return 1
    else:
        return 0


def __switch_case(case_sig,conditions) :  
    ''
    _tmpl_case_other = '''
case ($sel)
    $when_statements
endcase
'''
    _tmpl_case_process = '''
case ($sel)
    $when_statements
    $other_statements
endcase
'''
    
    other_exist = False

    def _when_cvt(k, objects):
        ''
        num = len(objects)
        if num == 1 and not isinstance(objects[0],hs.IfBlock) and _check_simple_statement(objects[0]) :
            t = '%s : %s' % (k, __seq_statement(objects[0]))
        else : 
            t = '%s : begin\n' % k
            t += '    %s\nend\n' % _s2.set_indentation(__seqobject(objects),4).strip()
        return t.rstrip()

    statements = []
    for cond in conditions : 
        ''
        if not isinstance(cond,hs.AllTrue) : 
            if type(cond.op2) is int :  
                k = case_sig.c_value(cond.op2)
            elif isinstance(cond.op2,hs.SignalConstant) :  
                k = case_sig.c_value(cond.op2.value)
            else : 
                k = '%s' % (cond.op2.value.name)

        else : 
            k = 'default'
            other_exist = True

        t = _when_cvt(k,conditions[cond])
        statements.append(t)

    statements = '\n'.join(statements)
    statements = _s2.set_indentation(statements, 4).strip()

    if other_exist : 
        cvt_code = Template(_tmpl_case_other).safe_substitute(
                    sel = case_sig.c_repr(),
                    when_statements = statements,
                )
    else : 
        cvt_code = Template(_tmpl_case_process).safe_substitute(
                    sel = case_sig.c_repr(),
                    when_statements = statements,
                    other_statements = '',
                )

    return cvt_code

#-------------------------------------------------------------------------
# sub functions 
#-------------------------------------------------------------------------
def _hex_formatting(value,n) : 
    ' 이 procedure는 vector를 표시하는 경우에만 call된다. '
    ' vector value를 hex로 표시한다. '

    # generic
    if isinstance(n,hs.GenericVar):
        return '%s' % (value)


    if value < 0 : # 음수는 2's complement로 변경한다. 
        value = 2**n + value

    return "%s'h%s" % (n, hex(value)[2:])


def _binary_operator(op1, op2, operator) : 
    ' =, >, < , >= '
    if operator == '==' : operator = '=='
    elif operator == '!=' : operator = '!='

    return '%s %s %s' % (op1,operator,op2)

def verilog_integer(value,n=1) :
    ''' 
        n : length of bits 
    '''
    assert type(value) is int

    # std_logic
    # if n==1 : 
    #     return "%s" % value

    return "{}'h{}".format(n,hex(value)[2:])



if __name__ == '__main__':
    ''






