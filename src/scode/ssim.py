import sys
import os
import argparse

# Ensure src/ is in the path so we can import the core modules
_src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import hsimulation as hv
import hsignal as hs
import hverification


def _resolve_signal(sim_module, path):
    '''Resolve a hierarchical signal path. Supports candidate name fallback.'''
    parts = path.split('/', 1)
    if len(parts) == 1:
        name = parts[0]
        # 1. Exact match in namespace
        sig = sim_module.namespace.get(name)
        if sig: return sig
        
        # 2. Candidate name fallback (for logic_unique signals)
        candidates = [v for v in sim_module.namespace.values()
                      if isinstance(v, hs.LogicBase) and getattr(v, 'unique_candidate', None) == name]
        if len(candidates) >= 1:
            return candidates[0]
        return None

    mod_name, rest = parts
    for h in sim_module.hdl_objects:
        if isinstance(h, hs.IModule) and h.module.mod_name == mod_name:
            return _resolve_signal(h.module, rest)
    return None


def _get_module_at_path(sim_module, path):
    '''Navigate to a submodule given a path like "a/b".'''
    if not path:
        return sim_module
    parts = path.split('/', 1)
    target = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    
    for h in sim_module.hdl_objects:
        if isinstance(h, hs.IModule) and h.module.mod_name == target:
            return _get_module_at_path(h.module, rest)
    return None


def _list_signals(mod):
    '''List signals and sub-modules in a module.'''
    signals = []
    # Collect all LogicBase objects that have a name
    for name, v in mod.namespace.items():
        if isinstance(v, hs.LogicBase):
            signals.append(name)
    
    modules = []
    for h in mod.hdl_objects:
        if isinstance(h, hs.IModule):
            modules.append(h.module.mod_name)
    
    return sorted(list(set(signals))), sorted(list(set(modules)))


def _print_tree(mod, depth=0, name="top"):
    '''Recursively print module hierarchy.'''
    indent = "  " * depth
    print(f"{indent}[{name}]")
    for h in mod.hdl_objects:
        if isinstance(h, hs.IModule):
            _print_tree(h.module, depth + 1, h.module.mod_name)


def main():
    parser = argparse.ArgumentParser(
        prog='ssim',
        description='Interactive SCode Simulation Tool (ssim)',
    )

    parser.add_argument('file', nargs='?', help='testbench .sc file')
    parser.add_argument('-o', '--outdir', default='.', help='output directory (default: current directory)')
    parser.add_argument('-t', '--time', type=int, default=200, help='initial simulation time in ns (default: 200)')
    parser.add_argument('-i', '--internal', metavar='PATH', action='append', default=[],
                        help='additional internal signal to capture, e.g. state/one_clk (repeatable)')

    args = parser.parse_args()

    fname = args.file
    if not fname:
        print("SCode Simulation Tool (ssim)")
        fname = input("Enter testbench .sc file path: ").strip()
        if not fname:
            print("Error: No file specified.")
            return

    if not os.path.exists(fname):
        print(f"Error: File not found: {fname}")
        return

    outdir = args.outdir
    if outdir != '.' and not os.path.exists(outdir):
        os.makedirs(outdir)

    # Check extension for mode selection
    _, ext = os.path.splitext(fname)
    if ext == '.sb':
        print(f"\n--- Running Verification Batch: {fname} ---")
        try:
            hverification.exec_simulation(fname, outdir, False)
        except Exception as e:
            print(f"Error during verification: {e}")
        return

    print(f"\n--- Loading Interactive Simulation: {fname} ---")
    namespace = {}
    try:
        sim = hv.simulate_main(fname, outdir, False, namespace)
    except Exception as e:
        print(f"Error during parsing/loading: {e}")
        return

    # Default: capture port signals only (inport / outport / inoutport)
    captured = [v for v in namespace.values()
                if isinstance(v, hs.LogicBase) and v.io is not None]

    # -i PATH: resolve and append additional signals
    captured_ids = {id(s) for s in captured}
    for path in args.internal:
        sig = _resolve_signal(sim.sim_module, path)
        if sig is None:
            print(f"Warning: signal '{path}' not found — skipped")
        elif id(sig) not in captured_ids:
            captured.append(sig)
            captured_ids.add(id(sig))
            print(f"  + capturing internal signal: {path}")

    if captured:
        sim.add(*captured)

    default_step = args.time
    last_idx = 0

    print("\n--- Simulation Ready ---")
    print("Commands:")
    print("  [Enter]  Advance simulation by current step")
    print("  <time>   Set new step and advance (e.g., 2000)")
    print("  ls [path] List signals/modules at path")
    print("  tree     Show module hierarchy tree")
    print("  add <path> Capture new internal signal")
    print("  csv      Trigger CSV generation")
    print("  q        Quit")

    while True:
        try:
            current_time = sim.stop_time if hasattr(sim, 'stop_time') else 0
            print(f"\n[Time: {current_time} ns]")
            user_in = input(f"Command? ([Enter]/{default_step}/ls/tree/add/q): ").strip()

            if user_in.lower() == 'q':
                break
            elif user_in.lower() == 'csv':
                if not getattr(sim, 'result', None):
                    print("Error: No simulation results to save. Run simulation first.")
                    continue
                try:
                    sim.result.to_csv()
                    sim.result.run_to_csv()
                    print(f"CSV generated: {sim.result.csv_fname}")
                except Exception as e:
                    print(f"Error generating CSV: {e}")
                continue
            elif user_in.lower() == 'tree':
                _print_tree(sim.sim_module)
                continue
            elif user_in.lower().startswith('ls'):
                p = user_in[2:].strip()
                target_mod = _get_module_at_path(sim.sim_module, p)
                if target_mod:
                    sigs, mods = _list_signals(target_mod)
                    print(f"--- Signals at '{p or 'top'}' ---")
                    print("  " + ", ".join(sigs) if sigs else "  (none)")
                    print(f"--- Modules at '{p or 'top'}' ---")
                    print("  " + ", ".join(mods) if mods else "  (none)")
                else:
                    print(f"Error: Module path '{p}' not found")
                continue
            elif user_in.lower().startswith('add'):
                p = user_in[3:].strip()
                sig = _resolve_signal(sim.sim_module, p)
                if sig is None:
                    print(f"Error: Signal '{p}' not found")
                elif id(sig) in captured_ids:
                    print(f"Signal '{p}' is already being captured")
                else:
                    captured.append(sig)
                    captured_ids.add(id(sig))
                    sim.add(*captured) # Pass the full list to avoid overwriting
                    print(f"  + capturing internal signal: {p}")
                continue
            elif user_in.isdigit():
                default_step = int(user_in)
            elif user_in == '':
                pass
            else:
                # Check for non-numeric input that isn't a known command
                if user_in.lower() not in ['q', 'csv', 'ls', 'tree', 'add']:
                    # Simple error but try to run if it looks like a number
                    try:
                        default_step = int(user_in)
                    except:
                        print(f"Unknown command: {user_in}")
                        continue
            
            result = sim.run(default_step)
            result.disp(start_idx=last_idx)
            last_idx = len(result.time_table)

        except KeyboardInterrupt:
            print("\nSimulation aborted.")
            break
        except Exception as e:
            print(f"Simulation error: {e}")
            break

        except KeyboardInterrupt:
            print("\nSimulation aborted.")
            break
        except Exception as e:
            print(f"Simulation error: {e}")
            break

    print("\n--- Simulation Finished ---")

if __name__ == "__main__":
    main()
