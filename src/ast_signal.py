'''
    ast transformer
    2014-05-02
    2014-05-19 : if를 ifblock()으로 변경한다. 
    2014-05-28 : if가 nesting되어 있는 경우 지원
    2014-06-06 : input, output, inout, signal에서 signal name 추출하기
    2014-06-07 : SignalTransformer 사용하지 않음
    2014-06-17 : signal("a")==1  -> boolop에서 conversion
    2014-06-17 : portlist extractor
    2014-06-19 : logical/if transformer같이 필수적인 것만 남기고 모두 삭제
    2014-07-04 : transformer support group
    2014-07-29 : elif -> else : if로 처리
    2015-10-19 : sequence안에 있는 if만 if 처리한다. 
    2016-01-29 : function parameter에서도 and/or transform 처리한다.
    2016-05-22 : add astTransformCodeSCIf()
'''
import ast,copy

import _s2
import parser_common

# sc functions whose arguments are all signal spec strings.
_SIGNAL_DEF_FUNCS = {'inport', 'outport', 'inoutport', 'logic', 'logic_unique', 'array', 'array_unique', 'statetype', 'statetype_unique', 'stdefine', 'stdefine_unique'}

# sc functions where only the FIRST argument is a signal name string;
# remaining arguments are ordinary expressions and must not be rewritten.
_SIGNAL_FIRST_ARG_FUNCS = {'statelogic', 'statelogic_unique'}


def _ast_node_to_sigspec(node):
    '''Try to convert an AST argument node into a signal spec string.

    Signal spec strings are what parser_common.str2signals() understands:
      "clk"           -> 1-bit logic named clk
      "data[8]"       -> 8-bit vector named data
      "addr[N]"       -> vector of generic width N named addr
      "bus[15:0]"     -> vector bits 15 downto 0 named bus
      "arr[CH][N]"    -> 2D array port (multi-dimensional subscript)

    Returns the spec string, or None if the node is not a recognisable pattern
    (e.g. it is an arithmetic expression — leave it untouched).

    Note: Python slice notation a[start:stop] stores start in Slice.lower and
    stop in Slice.upper, which maps directly to the signal spec "name[start:stop]".
    '''
    if isinstance(node, ast.Name):
        # bare identifier: clk -> "clk"
        return node.id

    if not isinstance(node, ast.Subscript):
        return None

    # Recursively resolve the base (handles multi-dimensional: delay[CH][N_DATA])
    if isinstance(node.value, ast.Name):
        base = node.value.id
    elif isinstance(node.value, ast.Subscript):
        base = _ast_node_to_sigspec(node.value)
        if base is None:
            return None
    else:
        return None

    sl = node.slice

    if isinstance(sl, ast.Constant) and isinstance(sl.value, int):
        # data[8]  -> "data[8]"
        return '%s[%s]' % (base, sl.value)

    if isinstance(sl, ast.Name):
        # data[N_DATA]  -> "data[N_DATA]"  (generic width or dimension)
        return '%s[%s]' % (base, sl.id)

    if isinstance(sl, ast.Slice):
        # bus[15:0]  -> "bus[15:0]"
        # ast.unparse handles constant, name, and binary-expression cases uniformly
        left  = ast.unparse(sl.lower) if sl.lower is not None else ''
        right = ast.unparse(sl.upper) if sl.upper is not None else ''
        return '%s[%s:%s]' % (base, left, right)

    return None


class SignalSpecTransformer(ast.NodeTransformer):
    '''Rewrites unquoted signal specs in port/logic/array calls to string literals.

    The sc runtime (hmodule, parser_common) expects string arguments for all
    signal-definition functions. Without this transform, writing:

        inport(clk, data[8])

    would require clk and data to already be defined Python names — which they
    are not at parse time. Instead, this transformer converts the AST so that
    the above becomes equivalent to:

        inport("clk", "data[8]")

    The transform runs on the parsed AST before both the 1st and 2nd execution
    passes (see _transformCode in hmodule.py), so neither pass ever sees the
    bare-identifier form.

    Arguments that are already string constants, or that are non-trivial
    expressions (e.g. function calls, arithmetic), are left unchanged.
    '''
    def visit_Call(self, node):
        # visit children first so nested calls are handled bottom-up
        self.generic_visit(node)

        func_name = None
        if isinstance(node.func, ast.Name):
            func_name = node.func.id

        if func_name in _SIGNAL_DEF_FUNCS:
            # all arguments are signal specs — rewrite every one
            node.args = [self._rewrite_arg(a) for a in node.args]

        elif func_name in _SIGNAL_FIRST_ARG_FUNCS:
            # only the first argument is a signal name; leave the rest untouched
            # e.g. tb_reset(reset, clk) -> tb_reset("reset", clk)
            if node.args:
                node.args = [self._rewrite_arg(node.args[0])] + node.args[1:]

        return node

    def _rewrite_arg(self, arg):
        '''Convert a single argument to a string constant if it is a signal spec,
        otherwise return it unchanged.'''
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg  # already a string literal — keep as-is
        spec = _ast_node_to_sigspec(arg)
        if spec is not None:
            return ast.Constant(value=spec)
        return arg  # unrecognised expression — keep as-is


def applySignalSpecTransform(tree):
    '''Apply SignalSpecTransformer to an already-parsed AST tree.

    Must be called after astTransformCodeIf() so that the if->ifblock
    rewriting has already happened before signal specs are normalised.
    '''
    transformer = SignalSpecTransformer()
    tree = transformer.visit(tree)
    ast.fix_missing_locations(tree)
    return tree


class TupleAssignTransformer(ast.NodeTransformer):
    '''Rewrites multi-signal tuple assignment using <= syntax.

    Pattern 1 (preferred):  (a, b) <= expr
      AST: Compare(left=Tuple([a, b]), LtE, [expr])

    Pattern 2 (legacy):     a, b <= expr
      AST: Tuple([Name('a'), Compare(Name('b'), LtE, [expr])])

    Both transform to:
        _tb_multi_N = expr
        a <= _tb_multi_N[0]
        b <= _tb_multi_N[1]
    '''
    def __init__(self):
        self._counter = 0

    def visit_Expr(self, node):
        self.generic_visit(node)

        names = rhs = None

        # Pattern 1: (a, b) <= expr
        v = node.value
        if (isinstance(v, ast.Compare) and
                len(v.ops) == 1 and isinstance(v.ops[0], ast.LtE) and
                isinstance(v.left, ast.Tuple) and
                all(isinstance(e, ast.Name) for e in v.left.elts)):
            names = [e.id for e in v.left.elts]
            rhs   = v.comparators[0]

        # Pattern 2: a, b <= expr
        elif isinstance(v, ast.Tuple) and len(v.elts) >= 2:
            last = v.elts[-1]
            if (isinstance(last, ast.Compare) and
                    len(last.ops) == 1 and isinstance(last.ops[0], ast.LtE) and
                    isinstance(last.left, ast.Name) and
                    all(isinstance(e, ast.Name) for e in v.elts[:-1])):
                names = [e.id for e in v.elts[:-1]] + [last.left.id]
                rhs   = last.comparators[0]

        if names is None:
            return node

        return self._expand(names, rhs, node)

    def _expand(self, names, rhs, node):
        tmp = f'_tb_multi_{self._counter}'
        self._counter += 1

        assign = ast.copy_location(
            ast.Assign(targets=[ast.Name(id=tmp, ctx=ast.Store())], value=rhs),
            node,
        )
        ast.fix_missing_locations(assign)

        stmts = [assign]
        for i, name in enumerate(names):
            compare = ast.Compare(
                left=ast.Name(id=name, ctx=ast.Load()),
                ops=[ast.LtE()],
                comparators=[ast.Subscript(
                    value=ast.Name(id=tmp, ctx=ast.Load()),
                    slice=ast.Constant(value=i),
                    ctx=ast.Load(),
                )],
            )
            stmts.append(ast.fix_missing_locations(
                ast.copy_location(ast.Expr(value=compare), node)
            ))

        return stmts


def applyTupleAssignTransform(tree):
    '''Rewrite  a, b <= expr  into individual <= assignments.

    Must run before applySignalSpecTransform.
    '''
    transformer = TupleAssignTransformer()
    tree = transformer.visit(tree)
    ast.fix_missing_locations(tree)
    return tree


def astTransformCodeIf(code):
    ' sequence if transfomer '

    modified = ast.parse(code) # ast parsing

    transformer = SeqIfTransformer()
    modified = transformer.visit(modified)
    ast.fix_missing_locations(modified)

    return modified

# astTransformCode will be deleted
# def astTransformCode(code, signal_names):
#     ''
#     modified = ast.parse(code) # ast parsing
# 
#     # if 0 : ## old 
#     #     #-------------------------------------------------------------------------
#     #     # logical transformer  (and, or => sigand(), sigor())
#     #     #-------------------------------------------------------------------------
#     #     transformer = LogicalTransformer(signal_names,group_names=[])
#     #     modified = transformer.visit(modified)
#     #     ast.fix_missing_locations(modified)
# 
#     #     #-------------------------------------------------------------------------
#     #     # if transformer
#     #     #-------------------------------------------------------------------------
#     #     _s2.debug_view('Signal names:',signal_names)
# 
#     #     transformer = IfTransformer(signal_names,group_names=[])
#     #     modified = transformer.visit(modified)
#     #     ast.fix_missing_locations(modified)
# 
#     if 1  :
#         # and/or transformer
#         transformer = AndOrTransformer()
#         modified = transformer.visit(modified)
#         ast.fix_missing_locations(modified)
# 
#         transformer = AndOrTransformerFunction(signal_names)
#         modified = transformer.visit(modified)
#         ast.fix_missing_locations(modified)
# 
#     if 1 : 
#         # if transformer 
#         transformer = SeqIfTransformer()
#         modified = transformer.visit(modified)
#         ast.fix_missing_locations(modified)
# 
#     return modified


#-------------------------------------------------------------------------
# SeqIfTransformer 
#-------------------------------------------------------------------------
class SeqIfTransformer(ast.NodeTransformer):
    ' sequence context에 있는 모든 if를 변환한다. '
    def __init__(self) :
        ''
        self.flag = 0

    def visit_With(self, node):
        ''
        try : 
            # if node.items[0].context_expr.func.id == 'sequence':
            if node.items[0].context_expr.func.id in ['sequence','switch','case','others']:

                # sequence에 있는 condition은 and/or conversion이 필요
                # if node.items[0].context_expr.func.id == 'sequence':
                #     args = node.items[0].context_expr.args
                #     if len(args) > 1 and isinstance(args[1],ast.BoolOp) :
                #         node.items[0].context_expr.args[1] = _mk_slab_bool(args[1])
                
                # recursive run
                self.flag += 1

                newbody = [] 
                for child in ast.iter_child_nodes(node):
                    k = self.visit(child)
                    newbody.append(k)

                #-------------------------------------------------------------------------
                # node.body = [k]
                ##  newbody를 모두 치환하면 아래와 같이 최초의 with가 중복된다.
                # with sequence(pls_clk, (s_reset == 1)):sequence(pls_clk, (s_reset == 1))
                # with switch(tx_state):switch(tx_state)
                # with case(st_idle):case(st_idle)
                #-------------------------------------------------------------------------
                node.body = newbody[1:]
        except:
            self.flag = 0

        self.flag -= 1
        return node


    def recursive_if(func):
        """ decorator to make visitor work recursively """
        def wrapper(self,node):
            # child부터 수행시킨다. 
            for child in ast.iter_child_nodes(node):
                self.visit(child)
                
            node = func(self,node)
            return node
        return wrapper

    @recursive_if
    def visit_If(self, node):
        ' test, body, orelse '
        if self.flag >= 1: 
            node = self._check_and_convert(node)

        return node

    def _check_and_convert(self,node):

        if isinstance(node, ast.If):
            # condition에 pycond() 함수가 사용되면 python if로 간주한다.
            if isinstance(node.test, ast.Call) and node.test.func.id=='pycond': 
                return node

            # 
            new_body = []
            for b in node.body : 
                # print(b,'******2')
                new_body.append(self._check_and_convert(b))
            node.body = new_body

            # orelse conversion
            new_orelse = []
            for b in node.orelse : 
                new_orelse.append(self._check_and_convert(b))
            node.orelse = new_orelse

            # condition
            # if _s2.USE_AST_ANDOR : 
            #     if isinstance(node.test, ast.BoolOp): # and/or
            #         node.test = _mk_slab_bool(node.test)

            # ifblock
            node = self._mk_block_with_if(node)

        return node


    def _mk_block_with_if(self,ifnode):
        ''' 
            if,elif,if로 slab의 ifblock, If,Elif, Else를 만든다.

            with ifblock() : 
                with If(a==1) : 
                    ''
                with Elif(a==1) : 
                    ''
                with Else() : 
                    ''
        '''
        ln = ifnode.lineno

        withitem = ast.withitem()
        withitem.context_expr = ast.Call(func=_mk_name('ifblock',ln),lineno=ln,args=[],starargs=None,kwargs=None,keywords=[])
        withitem.optional_vars = None

        top = ast.With(items=[withitem])
        top.lineno = ln
        top.col_offset = getattr(ifnode, 'col_offset', 0)
        top.body = []

        # If()
        sub1 = ast.withitem()
        sub1.context_expr = ast.Call(func=_mk_name('If',ln),lineno=ln,args=[ifnode.test],starargs=None,kwargs=None,keywords=[])
        sub1.optional_vars = None
        sub1_with = ast.With(items=[sub1])
        sub1_with.lineno = ln
        sub1_with.col_offset = getattr(ifnode, 'col_offset', 0)
        sub1_with.body = ifnode.body
        top.body.append(sub1_with)  # ifblock()에 If() 추가

        # Else 추가
        # top.body += self._elif_else_block(ifnode.orelse)
        if len(ifnode.orelse) > 0 :
            else1 = ast.withitem()
            else1.context_expr = ast.Call(func=_mk_name('Else',ln),lineno=ln,args=[],starargs=None,kwargs=None,keywords=[])
            else1.optional_vars = None
            else1_with = ast.With(items=[else1])
            else1_with.lineno = ln
            else1_with.col_offset = getattr(ifnode, 'col_offset', 0)
            else1_with.body = ifnode.orelse
            top.body.append(else1_with)  # ifblock()에 Else() 추가

        return top


#-------------------------------------------------------------------------
# And/Or transfomer, 아래와 같은 scode conditional assignment만 and/or transform을 수행한다. 
# a <= (1,b==1 or b==2,0)
#-------------------------------------------------------------------------
class AndOrTransformer(ast.NodeTransformer):
    ' assignment에서 and, or를 And(), Or()로 변경한다. '
    def __init__(self) :
        ''

    def visit_Expr(self,node):
        # b <= (1,a==1 and b==2,0)
        if isinstance(node.value, ast.Compare) :
            if isinstance(node.value.ops[0], ast.LtE) : # a <= ()
                if isinstance(node.value.comparators[0], ast.Tuple):
                    ''
                    elts = node.value.comparators[0].elts
                    for i in range(len(elts)):
                        if isinstance(elts[i], ast.BoolOp): # and/or
                            node.value.comparators[0].elts[i] = _mk_slab_bool(elts[i])
                elif isinstance(node.value.comparators[0], ast.BoolOp):
                    'a <= (b or c)'
                    node.value.comparators[0] = _mk_slab_bool(node.value.comparators[0])

        return node

class AndOrTransformerFunction(ast.NodeTransformer):
    ' function parameter의 and/or를 logic이 사용되면 And/Or로 변경한다. '
    def __init__(self,signals) :
        self.signals = signals

    def visit_Call(self, node):
        ' check parameter '
        for i,arg in enumerate(node.args) : 
            # print(i,arg)
            if isinstance(arg, ast.BoolOp) :
                if isinstance(arg.op, (ast.And,ast.Or)) : 
                    if self._check_logic_boolean(arg):
                        node.args[i] = _mk_slab_bool(arg)

        return node

    def _check_logic_boolean(self, node):
        ' BoolOp의 values에서 한 개라도 slab expression이면 True를 return한다. '
        values = node.values

        for i,v in enumerate(values) : 
            if isinstance(v, ast.Compare) : 
                if isinstance(v.left, ast.Name) : 
                    'a==1'
                    if v.left.id in self.signals : 
                        return True
                elif isinstance(v.left, ast.Attribute) : 
                    'a.b==1  a:left.value.id,b:left.attr'
                    if isinstance(v.left.value, ast.Name) : 
                        if v.left.value.id in self.groups : 
                            return True
                elif isinstance(v.left, ast.Call) : 
                    ' logic("a")==1'
                    if v.left.func.id == 'logic' : 
                        return True
                elif isinstance(v.left, ast.Subscript) : 
                    if isinstance(v.left.value, ast.Name) : 
                        ' a[0] == 1'
                        if v.left.value.id in self.signals : 
                            return True
                    elif isinstance(v.left.value, ast.Subscript) : 
                        ' a[0][1] == 1'
                        if v.left.value.value.id in self.signals : 
                            return True

            # recursive하게 bool op 처리
            elif isinstance(v, ast.BoolOp) : 
                r = self._check_slab_boolean(v)
                if r : 
                    return True
            
            # compare없이 변수만 사용하는 경우
            # a or b or c  => n.value.values가 모두 Name
            # a or b and c => n.value.values  [Name, BoolOp] 
            elif isinstance(v, ast.Name):
                ' a or b '
                if v.id in self.signals : 
                    return True

            elif isinstance(v, ast.Subscript):
                ' a[3] or b[0][2] '
                if isinstance(v.value, ast.Name) : 
                    ' a[0] == 1'
                    if v.value.id in self.signals : 
                        return True
                elif isinstance(v.value, ast.Subscript) : 
                    ' a[0][1] == 1'
                    if v.value.value.id in self.signals : 
                        return True
 
        return False

#-------------------------------------------------------------------------
#  old IfTransformer
#-------------------------------------------------------------------------
# class IfTransformer(ast.NodeTransformer):
#     ' if -> ifblock() '
#     def __init__(self,signals, group_names=[]) :
#         ''
#         self.signals = signals
#         self.groups = group_names
# 
#         # self.ifconversion = False
# 
#     def recursive(func):
#         """ decorator to make visitor work recursively """
#         def wrapper(self,node):
#             # child부터 수행시킨다. 
#             for child in ast.iter_child_nodes(node):
#                 self.visit(child)
#                 
#             node = func(self,node)
#             return node
#         return wrapper
# 
#     '''
#         recursive : 아래와 같은 code를 처리하기 위해 필요 
#         if 1 : 
#             with sequence(clk):
#                 if a==1 : 
#                     m <=1 
#     '''
# 
#     @recursive
#     def visit_If(self, node):
#         ' test, body, orelse '
#         return self._check_and_convert(node)
# 
# 
#     def _check_and_convert(self,node):
# 
#         if isinstance(node, ast.If):
#             new_body = []
#             for b in node.body : 
#                 # print(b,'******2')
#                 new_body.append(self._check_and_convert(b))
#             node.body = new_body
# 
#             # orelse conversion
#             new_orelse = []
#             for b in node.orelse : 
#                 new_orelse.append(self._check_and_convert(b))
#             node.orelse = new_orelse
# 
#             # if conversion last
#             if self._check_iftest_signal(node) : 
#                 node = self._mk_block_with_if(node)
# 
#         return node
# 
# 
#     def _check_iftest_signal(self,node):
#         ''
#         ifconversion = False
#         if isinstance(node.test, ast.Compare) : 
#             name = ''
#             if isinstance(node.test.left,ast.Name):
#                 'a==1'
#                 name = node.test.left.id
#             elif isinstance(node.test.left,ast.Subscript):
#                 ' a[0]==1'
#                 if isinstance(node.test.left.value,ast.Subscript):  # [][]
#                     name = node.test.left.value.value.id
#                 else : 
#                     name = node.test.left.value.id
#             elif isinstance(node.test.left,ast.Attribute):
#                 'a.b==1  a:left.value.id,b:left.attr'
#                 if isinstance(node.test.left.value, ast.Name) : 
#                     name = node.test.left.value.id
# 
#             if name != '' : 
#                 if name in self.signals or name in self.groups:
#                     ' if block generation '
#                     ifconversion = True
# 
#         elif isinstance(node.test, ast.Call) and node.test.func.id in ['sigand','sigor']: 
#             ifconversion = True
# 
#         return ifconversion
# 
#     def _mk_block_with_if(self,ifnode):
#         ''' 
#             if,elif,if로 slab의 ifblock, If,Elif, Else를 만든다.
# 
#             with ifblock() : 
#                 with If(a==1) : 
#                     ''
#                 with Elif(a==1) : 
#                     ''
#                 with Else() : 
#                     ''
#         '''
#         withitem = ast.withitem()
#         # withitem.context_expr = ast.Call(func=_mk_name('ifblock',1), args=[],keywords=[]) 
#         withitem.context_expr = ast.Call(func=_mk_name('ifblock',1),lineno=1,args=[],starargs=None,kwargs=None,keywords=[]) 
# 
#         top = ast.With(items=[withitem])
#         top.body = []
# 
#         # If() 
#         sub1 = ast.withitem()
#         # sub1.context_expr = ast.Call(func=_mk_name('If',1), args=[ifnode.test],keywords=[]) 
#         sub1.context_expr = ast.Call(func=_mk_name('If',1),lineno=1,args=[ifnode.test],starargs=None,kwargs=None,keywords=[]) 
#         sub1_with = ast.With(items=[sub1])
#         sub1_with.body = ifnode.body
#         top.body.append(sub1_with)  # ifblock()에 If() 추가
# 
#         # Else 추가
#         # top.body += self._elif_else_block(ifnode.orelse)
#         if len(ifnode.orelse) > 0 : 
#             else1 = ast.withitem()
#             # else1.context_expr = ast.Call(func=_mk_name('Else',1),args=[],keywords=[]) 
#             else1.context_expr = ast.Call(func=_mk_name('Else',1),lineno=1,args=[],starargs=None,kwargs=None,keywords=[]) 
#             else1_with = ast.With(items=[else1])
#             else1_with.body = ifnode.orelse
#             top.body.append(else1_with)  # ifblock()에 If() 추가
# 
#         return top


class LogicalTransformer(ast.NodeTransformer):
    ' and, or -> And(), Or() '
    def __init__(self,signals,group_names) :
        ''
        self.signals = signals
        self.groups = group_names

    def visit_BoolOp(self, node):
        if isinstance(node.op, (ast.And,ast.Or)) : 
            ''
            # if self._check_slab_boolean(node.values):
            if self._check_slab_boolean(node):
                return _mk_slab_bool(node)
            
        return node

    # def _check_slab_boolean(self, values):
    def _check_slab_boolean(self, node):
        ' BoolOp의 values에서 한 개라도 slab expression이면 True를 return한다. '
        values = node.values
        # _s2.debug_view('***************>>>>>>>>',values)

        for i,v in enumerate(values) : 
            # _s2.debug_view('>>>>>>>>',i,v)
            if isinstance(v, ast.Compare) : 
                if isinstance(v.left, ast.Name) : 
                    'a==1'
                    if v.left.id in self.signals : 
                        return True
                elif isinstance(v.left, ast.Attribute) : 
                    'a.b==1  a:left.value.id,b:left.attr'
                    if isinstance(v.left.value, ast.Name) : 
                        if v.left.value.id in self.groups : 
                            return True
                elif isinstance(v.left, ast.Call) : 
                    ' logic("a")==1'
                    if v.left.func.id == 'logic' : 
                        return True
                elif isinstance(v.left, ast.Subscript) : 
                    if isinstance(v.left.value, ast.Name) : 
                        ' a[0] == 1'
                        if v.left.value.id in self.signals : 
                            return True
                    elif isinstance(v.left.value, ast.Subscript) : 
                        ' a[0][1] == 1'
                        if v.left.value.value.id in self.signals : 
                            return True

            # recursive하게 bool op 처리
            elif isinstance(v, ast.BoolOp) : 
                r = self._check_slab_boolean(v)
                if r : 
                    return True
            
            # compare없이 변수만 사용하는 경우
            # a or b or c  => n.value.values가 모두 Name
            # a or b and c => n.value.values  [Name, BoolOp] 
            elif isinstance(v, ast.Name):
                ' a or b '
                if v.id in self.signals : 
                    return True

            elif isinstance(v, ast.Subscript):
                ' a[3] or b[0][2] '
                if isinstance(v.value, ast.Name) : 
                    ' a[0] == 1'
                    if v.value.id in self.signals : 
                        return True
                elif isinstance(v.value, ast.Subscript) : 
                    ' a[0][1] == 1'
                    if v.value.value.id in self.signals : 
                        return True
 
        return False


#-------------------------------------------------------------------------
# sub procedures  
#-------------------------------------------------------------------------
def _check_keywords_exist(key, keywords):
    for k in keywords : 
        if k.arg == key : 
            return True
    return False

def _mk_assign_node(target,attr,value):
    ' target.attr = value '
    node = ast.Assign()
    node.targets = [_mk_attribute(target, attr)]  
    node.value = ast.Str(value)
    return node

def _mk_attribute(target,attr) : 
    a = ast.Attribute()
    a.attr = attr
    a.value = _mk_name(target,1)
    a.ctx = ast.Store()
    return a

def _mk_name(name,ctx):
    ' ctx => 0 : store, 1 : load '
    n = ast.Name()
    n.id = name
    n.ctx = ast.Store() if ctx==0 else ast.Load()
    return n



def _mk_slab_bool(node): 
    'node is BoolOp'
    if not isinstance(node,ast.BoolOp):
        return node

    op     = node.op
    values = node.values

    if all([isinstance(i, ast.Compare) for i in values]):
        ' 모두 같은 Compare '
        if isinstance(op, ast.And):
            # return ast.Call(func=_mk_name('And',1), args=values,keywords=[]) 
            return ast.Call(func=_mk_name('And',1), args=values,lineno=1,starargs=None,kwargs=None,keywords=[]) 
        elif isinstance(op, ast.Or):
            # return ast.Call(func=_mk_name('Or',1), args=values,keywords=[]) 
            return ast.Call(func=_mk_name('Or',1), args=values,lineno=1,starargs=None,kwargs=None,keywords=[]) 

    elif all([isinstance(i, (ast.Name, ast.Subscript)) for i in values]):
        ' 모두 name또는 subscript '
        if isinstance(op, ast.And):
            # return ast.Call(func=_mk_name('And',1), args=values,keywords=[]) 
            return ast.Call(func=_mk_name('And',1), args=values,lineno=1,starargs=None,kwargs=None,keywords=[]) 
        elif isinstance(op, ast.Or):
            # return ast.Call(func=_mk_name('Or',1), args=values,keywords=[]) 
            return ast.Call(func=_mk_name('Or',1), args=values,lineno=1,starargs=None,kwargs=None,keywords=[]) 

    else :  # and , or가 섞여 있음.
        args = [_mk_slab_bool(values[i]) for i in range(len(values))] 

        if isinstance(op, ast.And):
            # return ast.Call(func=_mk_name('And',1), args=args,keywords=[]) 
            return ast.Call(func=_mk_name('And',1), args=args,lineno=1,starargs=None,kwargs=None,keywords=[]) 
        elif isinstance(op, ast.Or):
            # return ast.Call(func=_mk_name('Or',1), args=args,keywords=[]) 
            return ast.Call(func=_mk_name('Or',1), args=args,lineno=1,starargs=None,kwargs=None,keywords=[]) 

    return node



