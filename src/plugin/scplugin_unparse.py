'''
    unparser plugin
    
    2015-10-20
'''
# import pickle
import unparser

def run(module,*args,**kwargs) : 
    ''
    # print(module.basepath,module.outdir,module,module.parsed)
    
    # unparse
    with open('%s/_sc_temp.sc_intermediate'%module.outdir,'w',encoding='utf-8') as f : 
        unparser.Unparser(module.parsed,file=f)

    # # pickling
    # with open('%s/_sc_temp.pickle'%module.outdir, 'wb') as f:
    #     module.namespace = None  # dump error occurred if namespace exists 
    # #     module.imodules = None
    #     pickle.dump(module, f)



