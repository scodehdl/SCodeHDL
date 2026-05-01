'''
    SCode Verification Environment
    Handles .sb (SCode Batch) simulation verification scripts.
'''
import os
import hsimulation as hv

_pre_cmd = '''
outdir  = "{outdir}"
verilog = {verilog}

def simulate(fname):
    """
    Run simulation on the specified .sc file.
    Automatically binds signals from the .sc file to the caller's namespace.
    """
    ns = globals()
    return simulate_main(fname, outdir, verilog, ns)
'''

def exec_simulation(fname, outdir, verilog):
    """
    Execute an .sb file in a controlled environment with path resolution.
    """
    abs_fname = os.path.abspath(fname)
    base_dir = os.path.dirname(abs_fname)
    
    # Prepare namespace
    namespace = {}
    code = compile(_pre_cmd.format(outdir=outdir, verilog=verilog), '', 'exec')
    exec(code, namespace)
    
    # Direct access to simulate_main
    namespace['simulate_main'] = hv.simulate_main
    
    # Standard Python functions that might be useful
    namespace['os'] = os
    
    # Read .sb content
    with open(abs_fname, encoding='latin-1') as fp:
        content = fp.read()
    
    # Change CWD to the script's directory so relative paths in simulate() work
    old_cwd = os.getcwd()
    os.chdir(base_dir)
    try:
        # Use abs_fname for traceback line numbering
        exec(compile(content, abs_fname, 'exec'), namespace)
    finally:
        os.chdir(old_cwd)
