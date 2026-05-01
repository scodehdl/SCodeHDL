'''
    JSON export for sc modules.

    Converts an HDLModule (after post-processing) into a fully structured
    dict and writes it to a .json file.  Every value is a JSON primitive,
    list, or dict — no Python-specific repr strings — so a C# reader can
    reconstruct typed objects from the output.

    Entry point:
        save_module_json(mod, outdir)

    Top-level JSON keys:
        module        — identity and file metadata
        generics      — generic parameters  (name -> default value)
        ports         — inputs / outputs / inouts
        signals       — internal (local) signals
        state_types   — FSM enumeration types
        state_logics  — FSM signal instances
        submodules    — instantiated child modules with port connections
        logic         — combinational blocks (CBlock)
        sequential    — clocked blocks (SeqBlock) with nested structure
'''
import json

import _s2
import hsignal as hs


def save_module_json(mod, outdir):
    '''Serialize mod to <outdir>/<module_name>.json.'''
    data = _make_mod_dict(mod)
    fname = '%s/%s.json' % (outdir, _s2.filename_only(mod.fname))
    with open(fname, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data, indent=4))


# ── top-level builder ─────────────────────────────────────────────────────

def _make_mod_dict(mod):
    return {
        'module'      : _module_meta(mod),
        'generics'    : _generics(mod),
        'ports'       : _ports(mod),
        'signals'     : _signals(mod),
        'state_types' : _state_types(mod),
        'state_logics': _state_logics(mod),
        'submodules'  : _submodules(mod),
        'logic'       : _cblocks(mod),
        'sequential'  : _seqblocks(mod),
    }


# ── module meta ──────────────────────────────────────────────────────────

def _module_meta(mod):
    return {
        'name'            : mod.mod_name,
        'source_file'     : mod.fname,
        'source_hash'     : _s2.file_hash_value(mod.fname),
        'dependent_files' : mod.dependent_files,
        'target'          : 'verilog' if mod.verilog else 'vhdl',
    }


# ── generics ─────────────────────────────────────────────────────────────

def _generics(mod):
    result = {}
    for name, val in mod.generic_dict.items():
        result[name] = int(val.default) if hasattr(val, 'default') and isinstance(val.default, int) else str(val)
    return result


# ── signals / ports ──────────────────────────────────────────────────────

def _sig_kind(sig):
    if isinstance(sig, hs.BitVector)   : return 'bit'
    if isinstance(sig, hs.MultiVector) : return 'multivector'
    if isinstance(sig, hs.Vector)      : return 'vector'
    if isinstance(sig, hs.Array)       : return 'array'
    return 'unknown'

def _sig_to_dict(sig):
    d = {
        'name'     : sig.name,
        'kind'     : _sig_kind(sig),
        'width'    : _width_val(sig.width),
        'sig_type' : sig.sig_type.name,   # "logic" / "unsigned" / "signed"
    }
    if isinstance(sig, hs.Vector) and sig.start_bit != 0:
        d['start_bit'] = sig.start_bit
    if isinstance(sig, (hs.MultiVector, hs.Array)):
        d['length'] = sig.num
    if not _s2.check_nan(sig.init):
        d['init'] = _const_val(sig.init)
    return d

def _width_val(w):
    if isinstance(w, int) : return w
    return str(w)

def _ports(mod):
    return {
        'inputs'  : [_sig_to_dict(p) for p in mod.inport_list],
        'outputs' : [_sig_to_dict(p) for p in mod.outport_list],
        'inouts'  : [_sig_to_dict(p) for p in mod.inoutport_list],
    }

def _signals(mod):
    '''Local (non-port) signals only.'''
    return [_sig_to_dict(v) for v in mod.post.local_logics_dict.values()
            if not isinstance(v, hs.StateLogic)]


# ── state machines ───────────────────────────────────────────────────────

def _state_types(mod):
    result = []
    for st in mod.state_types:
        result.append({
            'name'      : st.name,
            'encoding'  : st.encoding,
            'bits'      : st.state_bits_width,
            'items'     : [{'name': it.name, 'value': it.encoding_value}
                           for it in st.state_items],
        })
    return result

def _state_logics(mod):
    result = []
    for sl in mod.state_logics:
        result.append({
            'name'       : sl.name,
            'state_type' : sl.state_type.name,
            'width'      : sl.state_type.state_bits_width,
        })
    return result


# ── submodules ───────────────────────────────────────────────────────────

def _submodules(mod):
    result = []
    for hdl in mod.hdl_objects:
        if not isinstance(hdl, hs.IModule):
            continue
        connections = {}
        for port, sig in hdl.connection_dict.items():
            connections[port.name] = _expr_to_dict(sig)
        generics = {}
        if hdl.connection_generic:
            for k, v in hdl.connection_generic.items():
                generics[k] = _width_val(v)
        result.append({
            'module'      : hdl.module.mod_name,
            'source'      : hdl.module.fname,
            'instance_id' : hdl.uut_id,
            'connections' : connections,
            'generics'    : generics,
        })
    return result


# ── combinational blocks ──────────────────────────────────────────────────

def _cblocks(mod):
    return [_assignment_to_dict(hdl.statement)
            for hdl in mod.hdl_objects if isinstance(hdl, hs.CBlock)]


# ── sequential blocks ─────────────────────────────────────────────────────

def _seqblocks(mod):
    return [_seqblock_to_dict(hdl)
            for hdl in mod.hdl_objects if isinstance(hdl, hs.SeqBlock)]

def _seqblock_to_dict(sb):
    return {
        'clk'      : sb.clk.name,
        'clk_edge' : sb.clk_edge,
        'reset'    : _reset_to_dict(sb.reset),
        'body'     : [_hdlobj_to_dict(o) for o in sb.objects],
    }

def _reset_to_dict(reset):
    if reset is None:
        return None
    if isinstance(reset, hs.ComparisonOperator):
        return {
            'signal'   : _expr_to_dict(reset.op1),
            'active'   : _expr_to_dict(reset.op2),
            'operator' : reset.operator,
        }
    return _expr_to_dict(reset)


# ── HDL object dispatcher ─────────────────────────────────────────────────

def _hdlobj_to_dict(o):
    '''Recursively serialize any HDL object inside a block.'''
    if isinstance(o, (hs.SignalAssignment, hs.VariableAssignment)):
        return _assignment_to_dict(o)
    if isinstance(o, hs.IfBlock):
        return _ifblock_to_dict(o)
    if isinstance(o, hs.SwitchBlock):
        return _switchblock_to_dict(o)
    if isinstance(o, hs.CBlock):
        return _assignment_to_dict(o.statement)
    if isinstance(o, hs.ForGenerate):
        return _forgen_to_dict(o)
    return {'kind': 'unknown', 'type': type(o).__name__}


# ── assignment ────────────────────────────────────────────────────────────

def _assignment_to_dict(asmt):
    d = {
        'kind'   : 'assignment',
        'dst'    : _expr_to_dict(asmt.dst),
        'values' : [_expr_to_dict(v) for v in asmt.values],
    }
    if asmt.conditions:
        d['conditions'] = [_expr_to_dict(c) for c in asmt.conditions]
    return d


# ── if block ──────────────────────────────────────────────────────────────

def _ifblock_to_dict(ib):
    branches = []
    for cond, objects in ib.conditions.items():
        branches.append({
            'condition' : _expr_to_dict(cond),
            'body'      : [_hdlobj_to_dict(o) for o in objects],
        })
    return {'kind': 'if', 'branches': branches}


# ── switch / case block ───────────────────────────────────────────────────

def _switchblock_to_dict(sw):
    cases = []
    for cond, objects in sw.conditions.items():
        cases.append({
            'condition' : _expr_to_dict(cond),
            'body'      : [_hdlobj_to_dict(o) for o in objects],
        })
    return {
        'kind'     : 'switch',
        'case_sig' : _expr_to_dict(sw.case_sig),
        'cases'    : cases,
    }


# ── for-generate ─────────────────────────────────────────────────────────

def _forgen_to_dict(fg):
    return {
        'kind'  : 'for_generate',
        'name'  : fg.gen_name,
        'start' : _width_val(fg.start),
        'stop'  : _width_val(fg.stop),
        'body'  : [_hdlobj_to_dict(o) for o in fg.objects],
    }


# ── expression serializer ─────────────────────────────────────────────────

def _const_val(v):
    if isinstance(v, int)   : return v
    if isinstance(v, float) : return v
    return str(v)

def _expr_to_dict(expr):
    '''Recursively serialize any expression or signal reference.'''
    if expr is None:
        return None

    if isinstance(expr, hs.LogicBase):
        d = {'kind': 'signal', 'name': expr.name, 'width': _width_val(expr.width)}
        if expr.sig_type != hs.SigType.logic:
            d['sig_type'] = expr.sig_type.name
        return d

    if isinstance(expr, hs.VectorSlice):
        return {
            'kind'   : 'slice',
            'signal' : expr.base_signal.name,
            'high'   : _width_val(expr.slice1.start) if expr.slice1 else None,
            'low'    : _width_val(expr.slice1.stop)  if expr.slice1 else None,
        }
    if isinstance(expr, hs.BitVectorSlice):
        return {
            'kind'   : 'bit_select',
            'signal' : expr.base_signal.name,
            'index'  : _width_val(expr.slice1) if not isinstance(expr.slice1, slice) else str(expr.slice1),
        }

    if isinstance(expr, hs.SignalConstant):
        return {'kind': 'constant', 'value': _const_val(expr.value), 'width': expr.width}

    if isinstance(expr, hs.ComparisonOperator):
        return {
            'kind'     : 'compare',
            'operator' : expr.operator,
            'left'     : _expr_to_dict(expr.op1),
            'right'    : _expr_to_dict(expr.op2),
        }

    if isinstance(expr, hs.BooleanOperator):
        op = 'and' if isinstance(expr, hs.AndExpr) else \
             'or'  if isinstance(expr, hs.OrExpr)  else 'xor'
        return {
            'kind'     : 'bool',
            'operator' : op,
            'operands' : [_expr_to_dict(o) for o in expr.operands],
        }

    if isinstance(expr, hs.ArithmeticOperator):
        return {
            'kind'     : 'arithmetic',
            'operator' : expr.operator,
            'left'     : _expr_to_dict(expr.op1),
            'right'    : _expr_to_dict(expr.op2),
        }

    if isinstance(expr, hs.InvertOperator):
        return {'kind': 'invert', 'operand': _expr_to_dict(expr.op1)}

    if isinstance(expr, hs.FunctionExpr):
        return {'kind': 'cast', 'func': expr.func, 'operand': _expr_to_dict(expr.argv)}

    if isinstance(expr, hs.VectorCombine):
        return {'kind': 'concat', 'parts': [_expr_to_dict(p) for p in expr.vectors]}

    if isinstance(expr, hs.StateItem):
        return {'kind': 'state_item', 'name': expr.name, 'value': expr.encoding_value}

    if isinstance(expr, hs.AllTrue):
        return {'kind': 'always_true'}
    if isinstance(expr, hs.AllFalse):
        return {'kind': 'always_false'}

    if isinstance(expr, hs.AssignmentBase):
        return _assignment_to_dict(expr)

    return {'kind': 'unknown', 'type': type(expr).__name__, 'repr': str(expr)}
