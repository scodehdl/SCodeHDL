'''
    Simulation 

    2013-06-14
    2013-06-20 : support restart , EventManager 자체가 iteration 지원할 수 있게.
    2013-06-21 : Make output of simulation result
    2013-07-19 : simulation output 간소화 (저장할때 deepcopy 사용하지 않음)

    later : simulation_output의 signals dictionary key를 module hierachy 지원할 수 있게 변경

    2016-12-02 : EventManager
    2017-06-06 : restarted
'''
import os,sys
import copy
import collections
# import pickle
import csv

import _s2
import hsignal as hs
import hmodule as hm
import htestbench as ht
import hpostproc as hp


def __parse_and_post(fname,outdir,verilog):
    mod = hm.parse_scfile(fname,parent=None,outdir=outdir,debug_log=True,verilog=verilog)
    mod = hp.run_post_processing(mod)
    return mod
 
def simulate_main(fname,outdir,verilog,namespace) :
    mod = __parse_and_post(fname,outdir,verilog)

    # mod의 namespace를 simulation namespace에 update
    namespace.update(mod.namespace)

    # custom module simulation
    # sim library에서 mod의 imodule 교체
    libsims = _s2.get_filelist_basename('./libsim','sc')
    for k in mod.hdl_objects :
        if isinstance(k, hs.IModule):
            mname = k.module.mod_name

            # module name이 libsim에 있는지 검사하고, 있으면 교체한다. 
            if mname in libsims : 
                m = __parse_and_post('libsim/%s.sc' % mname,outdir,verilog)
                k.replace_sim_module(m)

    #
    sim = VSimulate(mod)

    # copy logics, ModProperty into namespace
    namespace.update(mod.post.logics_dict)

    for k, v in mod.namespace.items():
        if isinstance(v,ModProperty):
            namespace[k] = v

    return sim



class ModProperty :
    def __init__(self,mod,kwargs) :
        ''
        self.mod = mod

        # set attributes
        for k,v in kwargs : 
            setattr(self,k.name,v)


class VSimulate :
    def __init__(self,sim_module) :
        ''
        self.sim_module = sim_module
        self.logic_list = [v for k,v in sim_module.namespace.items() if isinstance(v, hs.LogicBase)]
        self.initialized = False
        self.total_time  = 0
        self.result = None
        self.sim_events = None

        # get object list
        self.sim_objects = self._mk_sim_objects(self.sim_module)

        self.run_flag = False
        

    def add(self,*logic_list):
        ' add logic to capture '
        if hasattr(self, 'initialized') and self.initialized:
            # If signals are added after simulation started, 
            # we need to pad existing data_table rows to maintain alignment.
            current_logics = self.simulation_output.logics
            new_signals = []
            for s in logic_list:
                # Use identity check because LogicBase.__eq__ returns EqExpr
                if not any(s is cl for cl in current_logics):
                    new_signals.append(s)
            
            if new_signals:
                for s in new_signals:
                    current_logics.append(s)
                    for row in self.simulation_output.data_table:
                        row.append(hs.NAN)
        
        self.logic_list = logic_list


    def _addModProperty(self, where, mod): 
        ' make attributes of sub modules '

        imodules = [h for h in mod.hdl_objects if isinstance(h, hs.IModule)]
        for k in imodules : 
            mp = ModProperty(k.module,k.connection_dict.items())
            prop_name = k.module.mod_name
            if isinstance(where,dict) : 
                where[prop_name] = mp
            else : # ModProperty 
                if hasattr(where,prop_name) : 
                    # 여러개의 imodule이 있는 경우 list로 변경한다. 
                    setattr(where, prop_name, [getattr(where,prop_name)])
                    getattr(where,prop_name).append(mp)
                else : 
                    setattr(where, prop_name, mp)


            # recursive call
            self._addModProperty(mp, k.module)   # ModProperty에 child information을 기록해야 한다. 

    def _mk_sim_objects(self, mod) :
        hdl_objects  = [o for o in mod.hdl_objects if not isinstance(o, (ht.DelayedAssignment))]
        # hdl_objects = reorder_sim_objects(hdl_objects)

        # imodule recursively
        for h in hdl_objects : 
            if isinstance(h, hs.IModule):
                h.module.sim_objects = self._mk_sim_objects(h.module)

        return hdl_objects

    def __async_event(self,sim_objects):
        # ' combinational은 변경이 있으면 계속적으로 수행한다. '
        # for o in sim_objects :
        #     c = o.async_event()
        # return

        final = False
        count = 0
        while not final :  
            changed = False
            for o in sim_objects :
                c = o.async_event()
                if c : changed = True
            final = not changed
            
            count += 1
            if count > 100:
                raise Exception('Combinational loop detected')

    def _run_async_event(self,e=None):
        ''
        if e : 
            e.signal.curr_value = e.signal.next_value = e.value
        
        self.__async_event(self.sim_objects)

    def _run_sync_event(self,e):
        ''
        # toggle clock signal
        if isinstance(e, SyncEvent):
            old_val = e.signal.curr_value
            new_val = 1 if old_val == 0 else 0
            e.signal.curr_value = e.signal.next_value = new_val

            # [HOOK] Trigger clocked stimulus on rising edge
            if old_val == 0 and new_val == 1:
                self._trigger_clocked_stimulus(e.signal)

        for o in self.sim_objects :
            o.sync_event(e)

        # transit sync object's next value to value
        self._sync_transision(self.sim_objects)

        # update async objects
        self.__async_event(self.sim_objects)

    def _trigger_clocked_stimulus(self, clk_signal):
        ' Find and apply assignments for the current clock cycle '
        # Find the clock event object to get the cycle count
        clk_event = None
        for ce in self.sim_events.clock_events:
            if ce.clock is clk_signal:
                clk_event = ce
                break
        
        if clk_event:
            clk_event.cycle_count += 1
            cycle = clk_event.cycle_count
            
            # Find matching assignments in EventManager
            for ca in self.sim_events.clocked_assignments:
                if ca.clk is clk_signal and ca.cycle == cycle:
                    # Evaluate expr (supporting constants or signal values)
                    if isinstance(ca.expr, int):
                        val = ca.expr
                    elif hasattr(ca.expr, 'curr_value'):
                        val = ca.expr.curr_value
                    else:
                        val = ca.expr
                    
                    # Apply assignment (offset is ignored in basic sim for now, or could use DELTA)
                    ca.signal.curr_value = ca.signal.next_value = val

    def _sync_transision(self,sim_objects): 
        ''
        for o in sim_objects : 
            if isinstance(o, hs.IModule) : # recursive transition
                self._sync_transision(o.module.sim_objects)

            else : 
                for s in o.isignals + o.osignals : 
                    s.transition()

    def run(self,duration=0):
        ''
        sim_module = self.sim_module
        logic_list = self.logic_list

        if not self.initialized :
            self.init_sim(sim_module)
            self.simulation_output = _s2.dict2(
                logics = [s for s in logic_list],
                time_table = [],
                data_table = [],
                clk_table = [],
            )
            self.initialized = True
            self.stop_time = 0

            # t=0 초기값 기록
            self._run_async_event()
            self.simulation_output.time_table.append(0)
            self.simulation_output.clk_table.append('0')
            self.simulation_output.data_table.append([s.curr_value for s in logic_list])

        self.stop_time += duration

        # execute events 
        simulation_output = self.simulation_output

        if len(self.sim_events) == 0:
            ' 아무런 event가 없는 경우 초기값을 가지고, async만 처리 '
            self._run_async_event()

        else : 

            # async는 처리는 하지만 결과는 output table에 저장하지 않는다. 
            # async 처리는 다음 sync event 시점에 output에 저장한다. 
            # sync event 기준으로만 결과가 output에 저장한다. 
            clk_event_num = len(simulation_output.clk_table)

            for e in self.sim_events: 
                if e.time > self.stop_time:
                    self.sim_events.pending_event = e
                    break

                if isinstance(e, AsyncEvent): 
                    self._run_async_event(e)
                else : # sync
                    simulation_output.clk_table.append('%s' % clk_event_num)
                    # print(e.time,'------','sync')

                    # time
                    simulation_output.time_table.append(e.time)

                    self._run_sync_event(e)
                    self._run_async_event() # sync event 이후에 async 처리

                    self._sync_transision(self.sim_objects)

                    # output logic value (sync event 이후 값 기록)
                    data = []
                    for s in logic_list:
                        data.append(s.curr_value)
                    simulation_output.data_table.append(data)
                    clk_event_num += 1

        self.run_flag = True
        vsimout =  VsimOutput(simulation_output,sim_module)
        self.result = vsimout
        return vsimout

    # Add simulation property and method
    def init_sim(self,mod) : 
        ''
        _add_sim_property(mod)

        self.init_event_manager(mod)

    def init_event_manager(self,mod) : 
        self.sim_events = EventManager()

        # add event from stimulus objects
        for o in mod.hdl_objects :
            if isinstance(o, ht.DelayedAssignment):
                if o.repeat:
                    # clock: period = delay*2 (delay = half-period in sc_api.tb_clock)
                    self.sim_events.add_sync_event(o.signal, o.delay)
                else:
                    # one-shot: evaluate expr value at registration time
                    if isinstance(o.expr, int):
                        value = o.expr
                    elif hasattr(o.expr, 'curr_value'):
                        value = o.expr.curr_value
                    else:
                        value = o.expr
                    self.sim_events.add_async_event(o.delay, o.signal, value)

            elif isinstance(o, ht.ClockedAssignment):
                self.sim_events.add_clocked_stimulus(o)
            # elif isinstance(o,ht.StimulusWave) :
            #     ''
            #     current_time = 0
            #     for value, duration in o.value_time :
            #         self.sim_events.add_async_event(current_time,o.sig,value)
            #         current_time += duration



#-------------------------------------------------------------------------
# def reorder_sim_objects(obj_list):
#     ''
#     comb_objs  = _reorder_comb_out([o for o in obj_list if isinstance(o,hs.CBlock)])
#     other_objs = [o for o in obj_list if o not in comb_objs]
#     # seq, comb 순서는 관계없다.
#     obj_list = other_objs + comb_objs  
#     return obj_list


# def _reorder_comb_out(table) : 
#     'table의 output을 기준으로 reordering한다. '
#     out_dict = {}
#     for i,t in enumerate(table) : 
#         out_dict[table[i].statement.dst.name] = i
# 
#     # print(out_dict)
# 
#     order = list(range(len(table)))
#     for i in range(len(table)) : 
#         src_names = []
#         for s in table[i].statement.srcs : 
#             if isinstance(s, hs.VectorCombine):
#                 src_names += s.names
#             else : 
#                 src_names.append(s.name)
# 
#         for pi in src_names :  # sources
#             if pi in out_dict.keys(): 
#                 if i < out_dict[pi] : 
#                     # swap order
#                     j = out_dict[pi]
#                     order[i],order[j] = order[j],order[i]
# 
#     #                     
#     rtable = [table[i] for i in order] 
#     return rtable

#-------------------------------------------------------------------------
# outputs 
#-------------------------------------------------------------------------
class VsimOutput : 
    ''
    def __init__(self, simulation_output,sim_module,*,outdir='./') :
        ''
        self.sim_module = sim_module

        self.logic_names = [s.name for s in simulation_output.logics]
        self.time_table  = simulation_output.time_table
        self.clk_table   = simulation_output.clk_table
        self.data_table  = simulation_output.data_table

        self.csv_flag  = False
        self.csv_fname = ''
        self.outdir = outdir


    def _data_repr(self,k,w):
        ''
        if k is None :
            s = ('{:<%s}'%w).format('X')
        elif k == hs.SIG_UNDEFINED or k == hs.SIG_HIGH_IMPEDANCE :
            s = ('{:<%s}'%w).format(k.code)
        elif type(k) == int :
            s = ('{:<%sX}'%w).format(k)  # int -> hex
        elif type(k) == str :  # 'Z', 'X' string values
            s = ('{:<%s}'%w).format(k)
        elif type(k) is list :
            f = lambda i : '%X'%i if type(i)==int else 'X'
            s = '[%s]' % (' '.join([f(i) for i in k]))
        elif _s2.check_nan(k) :
            s = ('{:<%s}'%w).format('X')
        else : # State enum value
            s = ('{:<%s}'%w).format(k.name)
        return s

    def disp(self, start_idx=0):
        tstr = 'Time   '
        cstr = 'CLK    '
        x = [tstr,cstr] + [n for n in self.logic_names]
        fmt = ' '.join(['{:<%s}' % len(i) for i in x])
        print(fmt.format(*x))

        ltable = [len(n) for n in self.logic_names]
        # zip into a list to support indexing
        full_data = list(zip(self.time_table, self.clk_table, self.data_table))
        for tm,clk,data in full_data[start_idx:] :
            # time, clk 
            print(('{:<%s}'%(len(tstr)+1)).format(tm), end='')       # time
            print(('{:<%s}'%(len(tstr)+1)).format(clk), end='')       # clk

            # logic values
            for i,k in enumerate(data) :
                print(self._data_repr(k,ltable[i]), end=' ')

            print()

    def to_csv(self,fname=None) : 
        self.csv_flag = True
        # self.csv_fname = fname
        self.csv_fname = '%s/%s.csv' % (self.outdir,self.sim_module.mod_name)
        # print(self.csv_fname)
    def run_to_csv(self) : 
        ' header : time(ns), signal_names ... '
        import csv
        fname = self.csv_fname
        data = [['time(ns)'] + [s for s in self.logic_names]] 
        ltable = [len(s)+1 for s in self.logic_names]
        for t, d in zip(self.time_table,self.data_table) : 
            # data.append([t] + d)
            d2 = []
            for i,k in enumerate(d) :
                d2.append(self._data_repr(k,ltable[i]))
            data.append([t] + d2)

        with open(fname, 'w', newline='') as fp:
            a = csv.writer(fp, delimiter=',')
            a.writerows(data)

    
    # analyzer 
    def _logic_index(self,sig):
        try : 
            return self.logic_names.index(sig.name)
        except:
            return -1

    def _logic_values(self,sig):
        sidx = self._logic_index(sig)
        return [d[sidx] for d in self.data_table]


    # find clock index
    def find_index(self,sig,value,idx=0):
        if idx==0:
            return self._logic_values(sig).index(value)
        else :  # 주어진 idx 다음부터 찾는다. 
            return self._logic_values(sig).index(value,idx+1)

    # find value at index
    def find_value(self,sig,idx):
        ''
        sidx = self._logic_index(sig)
        return self.data_table[idx][sidx]

    def assert_eq(self, data, valid, expected, active=1, start=0):
        'capture 결과가 expected와 일치하는지 검증한다.'
        samples = self.capture(data, valid, active=active, start=start)
        expected = list(expected)
        if len(samples) != len(expected):
            raise AssertionError(
                f'assert_eq failed: length mismatch, expected={len(expected)}, got={len(samples)}')
        for i, (got, exp) in enumerate(zip(samples, expected)):
            if got != exp:
                raise AssertionError(
                    f'assert_eq failed: index={i}, expected={exp}, got={got}')

    def assert_when(self, trigger, check_fn, watch=None, active=1, start=0):
        'trigger가 active인 row에서 check_fn(curr, prev, time_ns)을 실행한다.'
        tidx = self._logic_index(trigger)
        if tidx == -1:
            raise ValueError(f'trigger signal not found: {trigger.name}')
        watch = watch or []
        widxs = {sig: self._logic_index(sig) for sig in watch}
        for sig, idx in widxs.items():
            if idx == -1:
                raise ValueError(f'watch signal not found: {sig.name}')
        prev_row = None
        for i in range(start, len(self.data_table)):
            row = self.data_table[i]
            try:
                is_active = int(row[tidx]) == int(active)
            except (TypeError, ValueError):
                prev_row = row
                continue
            if is_active and prev_row is not None:
                curr = {sig: row[idx] for sig, idx in widxs.items()}
                prev = {sig: prev_row[idx] for sig, idx in widxs.items()}
                if check_fn(curr, prev, self.time_table[i]) is False:
                    raise AssertionError(
                        f'assert_when failed at time={self.time_table[i]}ns, trigger={trigger.name}')
            prev_row = row

    def capture(self, data, valid, active=1, start=0, count=None, with_time=False):
        'valid==active인 row의 data 값을 수집하여 반환한다.'
        vidx = self._logic_index(valid)
        didx = self._logic_index(data)
        if vidx == -1 or didx == -1:
            return []
        result = []
        for i in range(start, len(self.data_table)):
            v = self.data_table[i][vidx]
            # X/Z/NaN/None 은 비활성으로 처리
            if v is None:
                continue
            try:
                if int(v) != int(active):
                    continue
            except (TypeError, ValueError):
                continue
            val = self.data_table[i][didx]
            result.append((self.time_table[i], val) if with_time else val)
            if count is not None and len(result) >= count:
                break
        return result

#-------------------------------------------------------------------------
# simulataion analyzer
#-------------------------------------------------------------------------
# class VsimAnalyzer : 
#     def __init__(self,vsimout) :
#         ' TODO later'
        


#-------------------------------------------------------------------------
# event manager for simulation 
#------------------------------------------------------------------------- 
AsyncEvent = collections.namedtuple('AsyncEvent', 'time,signal,value')
SyncEvent = collections.namedtuple('SyncEvent', 'time,signal')

class _ClockEvent: 
    ''
    def __init__(self,clk,period) :
        ''
        self.clock = clk        # Signal
        self.period = period
        self.cycle_count = 0    # Tracks rising edges
        self.restart()

    @property
    def next_event_time(self) : 
        ' 다음 event가 발생되는 시간을 return '
        # delay=10 ns인 경우, 10, 20, 30... 에서 event 발생 
        return self._event_num * self.period

    def advance_clock(self) : 
        ''
        self._event_num += 1

    def restart(self) :
        self._event_num = 1
        self.cycle_count = 0

class EventManager :
    ''
    def __init__(self) :
        ''
        self.sync_time_idx = 0
        self.async_time_idx = 0

        self.pending_event = None
        self.clock_events = []
        self.async_events = []  # time, sig, value
        self.clocked_assignments = [] # [ClockedAssignment]
        self.async_index = 0

    def __len__(self) : 
        return len(self.async_events) + len(self.clock_events)

    def add_async_event(self, time, sig, value):
        ' signal을 주어진 시간에 주어진 value로 setting한다. '
        # print(time,sig.name,value)
        self.async_events.append(AsyncEvent(time,sig,value))
        self.async_events.sort(key = lambda a : a.time)

    def add_sync_event(self,clk,period) :
        ''
        self.clock_events.append(_ClockEvent(clk,period))

    def add_clocked_stimulus(self, ca):
        self.clocked_assignments.append(ca)

    def _min_clock_event(self): 
        ' clock event 중 가장 먼저 일어날 clock을 찾는다.'
        ts = [c.next_event_time for c in self.clock_events]
        return self.clock_events[ts.index(min(ts))]
        
    def restart(self):
        ' simulation reset , event를 다시 처음부터 발생시킴 '
        self.async_index = 0

        for c in self.clock_events :
            c.restart()

    def _next_event(self) : 
        ''
        # select event
        if not self.clock_events : 
            ' doesnot exist clock events '
            if self.async_index >= len(self.async_events):
                raise StopIteration
            else : 
                e = self.async_events[self.async_index]
                # self.async_index += 1
                return e
        else : 
            ' clock event exists '
            clk = self._min_clock_event()

            if self.async_index >= len(self.async_events): 
                ' no more async event '
                return clk
            else : 
                ' clock and async exists, select one which is faster '
                clk_t = clk.next_event_time
                async_t = self.async_events[self.async_index].time

                if async_t < clk_t :  # 같은 경우는 회로 동작상 clock event가 먼저 진행되어야 한다.
                # if async_t <= clk_t :  # 같은 경우는 async event가 먼저 진행한다. Modelsim과 동일한 결과 얻기 위해.
                    ' async '
                    e = self.async_events[self.async_index]
                    return e
                else : 
                    ' clock event '
                    return clk


    def __iter__(self):
        ''
        return self

    def __next__(self):
        if self.pending_event:
            e = self.pending_event
            self.pending_event = None
            return e

        event = self._next_event()

        if isinstance(event, _ClockEvent) : 
            ''
            c = SyncEvent(event.next_event_time, event.clock)
            event.advance_clock()
            return c
        else :  # AsyncEvent
            self.async_index += 1
            return event



#-------------------------------------------------------------------------
# Event of HDL objects
# sync_event , async_event
#-------------------------------------------------------------------------
def sync_event(self,e) : return False
def async_event(self)  : return False 

def logic_transition(self):
    if type(self.next_value) is int :  # truncate
        self.curr_value = self.next_value & ((1 << self.width) - 1)
    else :  # nan
        self.curr_value = self.next_value


def assign_update(self):
    if not self.conditions: # condition이 없음 
        # print(self.dst,self.values[0].curr_value,'HHHHHHHHHH')
        self.dst.next_value = self.values[0].curr_value
    else : 
        for i,c in enumerate(self.conditions) : 
            if c.curr_value :
                self.dst.next_value = self.values[i].curr_value
                break
        else : # break 없이 for 문을 모두 수행한 후. 결국 condition이 맞지 않은 경우 수행된다.  
            if len(self.values) > i + 1:
                self.dst.next_value = self.values[i+1].curr_value

def cblock_async_event(self):
    ' curr과 next가 틀려 새로운 값으로 갱신되면 True를 return한다. '
    self.statement.update()

    # transition
    d = self.statement.dst
    next_value = d.next_value

    # print(d.name, d.curr_value, next_value)
    curr_is_nan = _s2.check_nan(d.curr_value)
    next_is_nan = _s2.check_nan(next_value)
    if curr_is_nan and next_is_nan:
        return False
    # If CBlock output is Z (high-impedance / not driving), preserve whatever is on the bus.
    # This allows testbench to drive an inout port without being overridden by the DUT's tristate.
    if next_value == hs.SIG_HIGH_IMPEDANCE.code :
        return False
    elif d.curr_value != next_value :
        self.statement.dst.transition()
        return True
    else :
        return False



def seqblock_sync_event(self,event) : 
    # 자신의 clock에 맞는 event 인 경우에만 수행한다. 
    ' self is SeqBlock'
    if event.signal.name != self.clk.name : 
        return 

    # Check edge triggering
    is_rising = (event.signal.curr_value == 1)
    if self.clk_edge == 'rising' and not is_rising:
        return
    if self.clk_edge == 'falling' and is_rising:
        return

    # Handle sync reset
    if self.reset_type == 'sync' and self.reset and self.reset.curr_value == 1:
        for s in self.osignals:
            s.next_value = s.init if s.init is not hs.NAN else 0
    else:
        for o in self.objects :
            o.update()

def seqblock_async_event(self):
    if self.reset_type == 'async' and self.reset and self.reset.curr_value == 1:
        changed = False
        for s in self.osignals:
            if s.init_defined:
                reset_val = s.init
            elif isinstance(s, hs.Array):
                reset_val = [0] * s.num
            else:
                reset_val = 0
            cv = s.curr_value
            # NaN-safe comparison: NaN != NaN in Python, so check explicitly
            # cv may be a list (Array), int, or float (NaN) — only call check_nan for scalars
            is_nan = not isinstance(cv, (list, str)) and _s2.check_nan(cv)
            if is_nan or cv != reset_val:
                s.curr_value = s.next_value = reset_val
                changed = True
        return changed
    return False

#-------------------------------------------------------------------------
# if block 
#-------------------------------------------------------------------------
def ifblock_update(self):
    ''
    for c,objects in self.conditions.items() : 
        # print(c.curr_value,c.op1.name, c.op2.value,c.curr_value,objects[0].dst.name)
        if c.curr_value : 
            for o in objects:
                o.update()
            break

def switchblock_update(self):
    ''
    for c,objects in self.conditions.items() : 
        if c.curr_value : 
            for o in objects:
                o.update()
            break



#-------------------------------------------------------------------------
# IModule 
#-------------------------------------------------------------------------
# _update_input, _update_output은 connection사이의 값을 동기화 하기 위한 목적이다.
def imodule__update_input(self): 
    ''
    for p in self.connection_dict : 
        if p.name in self._port_in_names : 
            p.curr_value = self.connection_dict[p].curr_value
            p.next_value = self.connection_dict[p].next_value
            # print('>>>>>>',p,p.name,p.curr_value)
        # else :
        #     p.curr_value = self.connection_dict[p].curr_value

def imodule__update_output(self): 
    ''
    for p in self.connection_dict : 
        if p.name in self._port_out_names : 
            # print('*****',self.connection_dict[p].name, p,p.name)
            self.connection_dict[p].curr_value = p.curr_value


def imodule_sync_event(self,e) :
    ' sync_event() 후에 transition()이 call되고 , 그 곳에서 _update_output()이 수행된다.'
    self._update_input()

    for o in self.module.sim_objects :
        o.sync_event(e)


def imodule_async_event(self) :
    self._update_input()

    changed = False
    for o in self.module.sim_objects :
        c = o.async_event()
        if c : changed = True

    self._update_output()
    return changed


#-------------------------------------------------------------------------
# curr_value  
#-------------------------------------------------------------------------
def _check_negative_value(v,w):
    return True if (1 << (w-1)) & v else False

def _cvt_2_negative_value(v,w):
    'pos -> neg'
    return -(2**w - v)

def _cvt_2_positive_value(v,w):
    ''
    if v < 0:
        return 2**w + v  # 2's complement
    else : 
        return v

@property
def logicbase_curr_value(self) : 
    w = self.width
    v = self._curr_value
 
    # print(v,self)

    if self.sig_type == hs.SigType.signed and _check_negative_value(v,w): 
        return _cvt_2_negative_value(v,w)
    else : 
        return v

@logicbase_curr_value.setter
def logicbase_curr_value(self,value)  : 
    # print(self.name, value, '>>>>')
    self._curr_value = value



@property
def logicslice_curr_value(self) : 

    assert type(self.slice1) is int
    start = stop = self.slice1

    # if type(self.slice1) is int : 
    #     start = stop = self.slice1
    # else : 
    #     start, stop = self.slice1.start, self.slice1.stop

    # if start > stop : 
    #     start,stop = stop, start

    v = 0
    try : 
        k = self.base_signal.curr_value

        for i in range(start,stop+1):
            v = v | (k & (1 << i)) >> start

    except TypeError : # SIG_UNDEFINED이 포함되어 있음
        return  hs.SIG_UNDEFINED
    return v

@logicslice_curr_value.setter
def logicslice_curr_value(self,value)  : 

    if type(self.slice1) is int : 
        start = stop = self.slice1
    else : 
        start, stop = self.slice1.start, self.slice1.stop
    
    if start > stop : 
        start,stop = stop, start


    v = 0
    value = value << start
    mask = 0
    for i in range(start,stop+1):
         v = v | ((1 << i) & value)
         mask = mask | (1 << i)

    if type(self.base_signal.curr_value) is int : 
        self.base_signal.curr_value = (self.base_signal.curr_value & ~mask) | v 
    else : 
        self.base_signal.curr_value = v 


@property
def array_curr_value(self) :
    # print(self,self._curr_value)

    if self._curr_value == hs.NAN :
        self._curr_value = list(self.init) if self.init_defined else [0]*self.num

    return self._curr_value

@array_curr_value.setter
def array_curr_value(self,value) :
    self._curr_value = value

@property
def array_next_value(self) :
    if self._next_value == hs.NAN :
        self._next_value = list(self.init) if self.init_defined else [0]*self.num

    return self._next_value

@array_next_value.setter
def array_next_value(self,value) : 
    self._next_value = value



def _slice_stop_start(slice1):
    if type(slice1) is int : 
        start = stop = slice1
    else : 
        start, stop = slice1.start, slice1.stop
 
    if start > stop : 
        start,stop = stop, start
    
    return start, stop


def _slice_value_mask(start,stop,value):
    v = 0
    value = value << start
    mask = 0
    for i in range(start,stop+1):
         v = v | ((1 << i) & value)
         mask = mask | (1 << i)

    return v,mask 

@property
def vectorslice_curr_value(self) : 
    ' vector에서 slice로 vector를 만듬 '
    if isinstance(self.base_signal, (hs.Array)) : 
        if type(self.slice1) is int:
            return self.base_signal.curr_value[self.slice1]
        else : # logic 
            if type(self.slice1.curr_value) is float : 
                return hs.NAN
            else : 
                # print(self.slice1.curr_value,'>>>')
                return self.base_signal.curr_value[self.slice1.curr_value]

    elif isinstance(self.base_signal, (hs.MultiVector)) : 
        i = self.slice1.stop//self.base_signal.width
        return self.base_signal.curr_value[i]
    else : 
        if isinstance(self.slice1,hs.LogicMixin):
            if type(self.slice1.curr_value) is float:
                return self.slice1.curr_value
            else : 
                return self.base_signal.curr_value[self.slice1.curr_value]
        else : # slice1 is slice
            # if self.
            # print(self.slice1, self.base_signal.curr_value,'>>>>>>>')
            bv = self.base_signal.curr_value
            if type(bv) is float : # hs.NAN 포함
                return hs.NAN
            elif type(bv) is not int : # 'Z', 'X' 등 non-int 값 → 그대로 전파
                return bv
            else :
                # return self.base_signal.curr_value[self.slice1]
                start,stop = _slice_stop_start(self.slice1)
                v, mask    = _slice_value_mask(start,stop,bv)
                return v

@vectorslice_curr_value.setter
def vectorslice_curr_value(self,value)  : 
    if isinstance(self.base_signal, (hs.Array)) : 
        if type(self.slice1) is int:
            self.base_signal.curr_value[self.slice1] = value
    elif isinstance(self.base_signal, (hs.MultiVector)) : 
        # multivector인 경우 slice1이 integer라 해도 start,stop을 conversion되어 전달된다.
        # 다시 integer slice로 변경한다. 
        # TODO : Multivector는 data[2:0]와 같은 slice는 금지한다. integer만 허용하자.
        i = self.slice1.stop//self.base_signal.width
        self.base_signal.curr_value[i] = value

    else : # base is vector (v[3:0])
        start,stop = _slice_stop_start(self.slice1)
        v, mask    = _slice_value_mask(start,stop,value)

        if type(self.base_signal.curr_value) is float : # hs.NAN 포함
            self.base_signal.curr_value = v 
        else : 
            self.base_signal.curr_value = (self.base_signal.curr_value & ~mask) | v 


@property
def logicslice_next_value(self):
    return self.curr_value  # next_value often derived from current state if not set, but getter should be consistent

@logicslice_next_value.setter
def logicslice_next_value(self, value):
    if type(self.slice1) is int:
        start = stop = self.slice1
    else:
        start, stop = self.slice1.start, self.slice1.stop
    if start > stop:
        start, stop = stop, start

    v, mask = _slice_value_mask(start, stop, value)
    
    # base_signal logic
    base = self.base_signal
    if type(base.next_value) is int:
        base.next_value = (base.next_value & ~mask) | v
    else:
        # if next_value is NAN, initialize with v (mask might be partial but we don't have previous next_value)
        # However, _assign_logic_property initializes next_value to init/0.
        base.next_value = v

@property
def vectorslice_next_value(self):
    return self.curr_value

@vectorslice_next_value.setter
def vectorslice_next_value(self, value):
    if isinstance(self.base_signal, (hs.Array)):
        if type(self.slice1) is int:
            self.base_signal.next_value[self.slice1] = value
    elif isinstance(self.base_signal, (hs.MultiVector)):
        i = self.slice1.stop // self.base_signal.width
        self.base_signal.next_value[i] = value
    else: # base is vector
        start, stop = _slice_stop_start(self.slice1)
        v, mask = _slice_value_mask(start, stop, value)
        
        base = self.base_signal
        if type(base.next_value) is int:
            base.next_value = (base.next_value & ~mask) | v
        else:
            base.next_value = v


@property 
def signalconstant_curr_value(self) : 
    return self.value

@property 
def vectorcombine_curr_value(self) : 
    # check valid
    if any(type(v.curr_value) is not int for v in self.vectors) : 
        return hs.SIG_UNDEFINED
    else : 
        total = 0
        for i,v in enumerate(self.vectors):
            k = sum(s.width for s in self.vectors[i+1:])
            total += v.curr_value << k
        return total


@property
def eqexpr_curr_value(self) : return self.op1.curr_value == self.op2.curr_value

@property
def neexpr_curr_value(self) : return self.op1.curr_value != self.op2.curr_value

@property
def gtexpr_curr_value(self) : return self.op1.curr_value > self.op2.curr_value

@property
def geexpr_curr_value(self) : return self.op1.curr_value >= self.op2.curr_value

@property
def ltexpr_curr_value(self) : return self.op1.curr_value < self.op2.curr_value

@property
def leexpr_curr_value(self) : return self.op1.curr_value <= self.op2.curr_value

@property
def andexpr_curr_value(self) : 
    if self.islogical():  
        return all([e.curr_value for e in self.operands])
    else : 
        k = self.operands[0].curr_value & self.operands[1].curr_value
        if len(self.operands) > 2 : 
            for e in self.operands[2:] : 
                k = k & e.curr_value
        return k

@property
def orexpr_curr_value(self) : 
    if self.islogical():  
        return any([e.curr_value for e in self.operands])
    else : 
        k = self.operands[0].curr_value | self.operands[1].curr_value
        if len(self.operands) > 2 : 
            for e in self.operands[2:] : 
                k = k | e.curr_value
        return k

@property
def xorexpr_curr_value(self) : 
    k = self.operands[0].curr_value ^ self.operands[1].curr_value
    if len(self.operands) > 2 : 
        for e in self.operands[2:] : 
            k = k ^ e.curr_value
    return k

@property
def invert_op_curr_value(self): 
    # print(self.op1, self.op1.name, self.op1.curr_value)
    if self.op1.curr_value is hs.NAN:
        return hs.NAN
    else : 
        # invert
        return ((1 << self.width) - 1) - self.op1.curr_value

@property
def funcexpr_curr_value(self) : 
    w = self.argv.width
    v = self.argv.curr_value

    if self.func == 'signed':
        if _check_negative_value(v,w) : 
            return _cvt_2_negative_value(v,w)
        else : 
            return v
    else : 
        return v

@property
def addexpr_curr_value(self) : return self.op1.curr_value + self.op2.curr_value


def _get_imodule_logics(mod) : 
    logics = []
    for h in mod.hdl_objects:
        if isinstance(h,hs.IModule):
            for k in h.connection_dict.keys():
                logics.append(k)

            # add sub imodule                
            logics += _get_imodule_logics(h.module)

    return logics

def _assign_logic_property(mod):
    logics = list(mod.post.logics_dict.values()) + _get_imodule_logics(mod)

    # make value property & init value
    for v in logics :
        if isinstance(v,(hs.Array,hs.MultiVector)):
            v.curr_value = [hs.NAN]*len(v)
            v.next_value = [hs.NAN]*len(v)

            if v.init is not hs.NAN : 
                for i in range(len(v.init)):
                    v.curr_value[i] = v.init[i]
                    v.next_value[i] = v.init[i]
        elif isinstance(v, hs.StateLogic):
            v.curr_value = v.next_value = v.init

            # state item : enum value로 할당. 나중에 StateLogic에 StateItem이 할당된다. 
            e = v.state_type.state_enum
            for it in v.state_type.state_items : 
                it.curr_value = it.next_value = getattr(e,it.name)

        else : # normal logics
            # print(v,v.name,'>>>>')
            v.curr_value = v.next_value = v.init

    # assign recursively            
    for k in mod.hdl_objects :
        if isinstance(k, hs.IModule):
            # parse_sc_file에서 post processing을 하지 않기 때문에 
            # 이 곳에서 imodule의 post processing을 수행해야 한다. 
            k.module = hp.run_post_processing(k.module)
            _assign_logic_property(k.module)


def _add_sim_property(mod):
    ''
    _assign_logic_property(mod)

    #-------------------------------------------------------------------------
    # event 
    #-------------------------------------------------------------------------
    # ht.StimulusObject.sync_event  = sync_event
    # ht.StimulusObject.async_event = async_event

    hs.HDLObject.sync_event = sync_event
    hs.HDLObject.async_event = async_event
    
    # assignment update
    hs.AssignmentBase.update = assign_update

    # cblock
    hs.CBlock.async_event = cblock_async_event

    # seqblock
    hs.SeqBlock.sync_event = seqblock_sync_event
    hs.SeqBlock.async_event = seqblock_async_event

    hs.IfBlock.update = ifblock_update
    hs.SwitchBlock.update = switchblock_update
    # hs.IfBlockCondition.update = ifblockcondition_update

    # IModule
    hs.IModule.sync_event = imodule_sync_event
    hs.IModule.async_event = imodule_async_event
    hs.IModule._update_input = imodule__update_input
    hs.IModule._update_output = imodule__update_output
    
    #-------------------------------------------------------------------------
    # transition 
    #-------------------------------------------------------------------------
    hs.LogicBase.transition = logic_transition
    hs.LogicSlice.transition = logic_transition

    #-------------------------------------------------------------------------
    # curr_value 
    #-------------------------------------------------------------------------
    hs.LogicSlice.curr_value = logicslice_curr_value
    hs.VectorSlice.curr_value = vectorslice_curr_value

    # next_value (Fix for slice assignment bug)
    hs.LogicSlice.next_value = logicslice_next_value
    hs.VectorSlice.next_value = vectorslice_next_value

    # 
    hs.SignalConstant.curr_value = signalconstant_curr_value
    hs.VectorCombine.curr_value  = vectorcombine_curr_value

    # expr
    hs.EqExpr.curr_value = eqexpr_curr_value
    hs.NeExpr.curr_value = neexpr_curr_value
    hs.GtExpr.curr_value = gtexpr_curr_value
    hs.GeExpr.curr_value = geexpr_curr_value
    hs.LtExpr.curr_value = ltexpr_curr_value
    hs.LeExpr.curr_value = leexpr_curr_value

    hs.AndExpr.curr_value      = andexpr_curr_value
    hs.OrExpr.curr_value       = orexpr_curr_value
    hs.XorExpr.curr_value      = xorexpr_curr_value

    hs.InvertOperator.curr_value = invert_op_curr_value

    hs.AllTrue.curr_value = True
    hs.AllFalse.curr_value = False

    hs.FunctionExpr.curr_value = funcexpr_curr_value
    hs.AddExpr.curr_value      = addexpr_curr_value


if __name__ == '__main__' : 
    ''


