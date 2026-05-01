'''
    latency calculator
    
    2016-09-20
'''
import collections
import pickle

import _s2

def run(mod,*args,**kwargs) : 
    ''
    with open('%s/_sc_module_info.pickle'%mod.outdir,'rb') as f : 
        mod_info = pickle.load(f)

        latency_dict = calc_latency(mod_info)

        fname = '%s/_sc_module_latency.txt'%mod.outdir
        disp_latency(latency_dict,fname)


def disp_latency(lat_dict,fname) : 
    with open(fname, "w") as f:
        with _s2.stdout_redirected(f):
            for dst,result in lat_dict.items() : 
                if len(result.keys()) == 0 : 
                    print('%s : no dependency' % (dst))
                else : 
                    ss = '%s : ' % dst
                    # for num in reversed(sorted(result.keys())) : 
                    for num in sorted(result.keys()) : 
                        ss += ','.join('%s(%s)' % (l,num) for l in result[num])
                    print(ss)


def calc_latency(mod_info):
    ''
    ldict = mod_info['logic_info']
    odict = mod_info['io_dependency']
    hdict = mod_info['hdl_info']

    # latency table (key : logic, value : latency of hdl 0 or 1)
    latency_table = collections.OrderedDict()
    for dst in odict.keys() :
        hdl_id, ilogics = odict[dst]
        latency_table[dst] = 1 if hdict[hdl_id].startswith('seqblock') else 0

    # latency dictionary
    def _calc_one_dst_latency(n,result,ilogics):
        for src in ilogics : 
            if src in already_scanned : continue 

            already_scanned.append(src)

            if src in odict.keys() : 
                _dummy, child_list = odict[src]
                result[n+latency_table[src]] += child_list
                _calc_one_dst_latency(n+latency_table[src],result,child_list)

    latency_dict = collections.OrderedDict()

    for dst in odict.keys() :
        result = collections.defaultdict(list)
        already_scanned = []

        _dummy, ilogics = odict[dst]
        n = latency_table[dst]
        result[n] = [i for i in ilogics]  # copy explicitly

        # a <= a + 1
        if dst in ilogics:
            ilogics.remove(dst)

        # print(dst,n,ilogics,result)

        already_scanned.append(dst)
        _calc_one_dst_latency(n,result,ilogics)

        # remove duplicate items
        for k,v in result.items():
            result[k] = list(collections.OrderedDict.fromkeys(v))

        latency_dict[dst] = result

    # print(latency_dict['e'])
    return latency_dict



