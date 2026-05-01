'''
    testbench class/functions definition
    
    2013-06-27 
    2013-07-08 : StimulusSequence()
    2013-07-19 : StimulusObject는 @signals에서 항상 []를 return 해야 한다. 
    2013-11-11 : StimulusFileInput, StimulusFileOutput
    2015-08-13 : renamed to htestbench
'''

import hsignal as hs

class DelayedAssignment(hs.HDLObject):
    '''Testbench delayed assignment.

    signal <= expr  after delay ns
    repeat=True : fires repeatedly (clock), repeat=False : one-shot (reset/wave)
    c_hdl_repr is monkey-patched by hgenerator.
    '''
    def __init__(self, signal, expr, delay, repeat=False):
        super().__init__()
        self.signal = signal
        self.expr   = expr    # int constant  or  expression with .c_repr()
        self.delay  = delay   # ns
        self.repeat = repeat  # True → clock toggle, False → one-shot

    @property
    def osignals(self) : return [self.signal]
    @property
    def isignals(self) : return []
    @property
    def variables(self): return []


def tb_delay(signal, expr, delay, *, repeat=False):
    '''Low-level primitive: add a DelayedAssignment to the current module.'''
    mod = hs.get_module()
    mod._add_obj(DelayedAssignment(signal, expr, delay, repeat))


class ClockedAssignment(hs.HDLObject):
    '''Synchronous assignment triggered by clock edges.

    signal <= expr  at N-th cycle of clk
    group_id: when set, assignments sharing the same group_id and clk are
              emitted as a single combined process in VHDL/Verilog.
    '''
    def __init__(self, clk, signal, expr, cycle, offset=0, group_id=None):
        super().__init__()
        self.clk      = clk
        self.signal   = signal
        self.expr     = expr
        self.cycle    = cycle     # N-th cycle (event count)
        self.offset   = offset   # Optional additional delay after edge
        self.group_id = group_id # None → individual process; object() → grouped

    @property
    def osignals(self) : return [self.signal]
    @property
    def isignals(self) : return [self.clk]
    @property
    def variables(self): return []


def tb_clocked_assign(clk, signal, expr, cycle, offset=0, *, group_id=None):
    '''Low-level primitive: add a ClockedAssignment to the current module.'''
    mod = hs.get_module()
    mod._add_obj(ClockedAssignment(clk, signal, expr, cycle, offset, group_id))



if __name__ == '__main__' : 
    ''

