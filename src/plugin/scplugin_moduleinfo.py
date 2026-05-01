'''
    module information
    - port/logic
    - hdl statement
    
    2016-09-16
'''
import pickle
import json
import collections

def run(mod,*args,**kwargs) : 
    ''
    # save to pickle
    with open('%s/_sc_module_info.pickle'%mod.outdir,'wb') as f:
        pickle.dump(mod.mod_info_dict, f)

    # save to json
    with open('%s/_sc_module_info.json'%mod.outdir,'w',encoding='utf-8') as f : 
        f.write(json.dumps(mod.mod_info_dict))


