import os
import sys
import signal

def get_proc_info():
    proc_info = {}
    for filename in os.listdir('/proc'):
        if filename.isdigit():
            pid = int(filename)
            try:
                with open(f'/proc/{filename}/stat', 'rb') as f:
                    stat = f.read()
                # Find the last closing parenthesis to handle spaces in comm
                rpar = stat.rfind(b')')
                parts = stat[rpar+2:].split()
                ppid = int(parts[1])
                comm = stat[stat.find(b'(')+1 : rpar].decode('utf-8', errors='ignore')
                proc_info[pid] = {'ppid': ppid, 'comm': comm}
            except Exception:
                pass
    return proc_info

def get_cmdline(pid):
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            content = f.read()
        # Join by space, replacing null bytes
        parts = [p.decode('utf-8', errors='ignore') for p in content.split(b'\x00') if p]
        return ' '.join(parts).strip()
    except Exception:
        return ''

def get_descendants(parent_pid, proc_info):
    descendants = set()
    to_visit = [parent_pid]
    while to_visit:
        curr = to_visit.pop()
        for pid, info in proc_info.items():
            if info['ppid'] == curr and pid not in descendants:
                descendants.add(pid)
                to_visit.append(pid)
    return descendants

def get_ancestors(pid, proc_info):
    ancestors = set()
    curr = pid
    while curr in proc_info:
        ppid = proc_info[curr]['ppid']
        if ppid == 0 or ppid == curr:
            break
        ancestors.add(ppid)
        curr = ppid
    return ancestors

def main():
    proc_info = get_proc_info()
    
    # Collect all PIDs that are safe
    my_pid = os.getpid()
    safe_pids = {my_pid}
    safe_pids.update(get_ancestors(my_pid, proc_info))
    
    # 1. Gateway PID (dynamic resolution)
    gateway_pid = None
    for pid, info in proc_info.items():
        cmdline = get_cmdline(pid)
        if 'agentforge-gateway' in cmdline:
            gateway_pid = pid
            break
    if gateway_pid:
        safe_pids.add(gateway_pid)
        safe_pids.update(get_descendants(gateway_pid, proc_info))
        
    # 2. Tmux server PID (dynamic resolution)
    tmux_pid = None
    for pid, info in proc_info.items():
        if info['comm'] == 'tmux: server' or info['comm'] == 'tmux':
            tmux_pid = pid
            break
    if tmux_pid:
        safe_pids.add(tmux_pid)
        safe_pids.update(get_descendants(tmux_pid, proc_info))
        
    # 3. Antigravity worker PID (dynamic resolution)
    antigravity_pid = None
    for pid, info in proc_info.items():
        cmdline = get_cmdline(pid)
        if 'antigravity_worker.py' in cmdline:
            antigravity_pid = pid
            break
    if antigravity_pid:
        safe_pids.add(antigravity_pid)
        safe_pids.update(get_descendants(antigravity_pid, proc_info))

    print(f"Safe PIDs count: {len(safe_pids)}")
    
    # Identify processes to kill
    to_kill = []
    for pid, info in proc_info.items():
        if pid in safe_pids:
            continue
        
        # Don't kill PID 1, systemd, etc. (ppid 0 or very small pids)
        if pid < 100 or info['ppid'] == 0:
            continue
            
        cmdline = get_cmdline(pid)
        comm = info['comm']
        
        # We target processes related to grok or agentforge
        target = False
        if 'grok' in cmdline.lower() or 'grok' in comm.lower():
            target = True
        elif 'agentforge' in cmdline.lower() or 'agentforge' in comm.lower():
            target = True
            
        # Do not kill if it's our own tool runner shell or terminal proxy
        # (Though they should be covered by safe_pids ancestors)
        if target:
            to_kill.append((pid, comm, cmdline))
            
    print(f"Found {len(to_kill)} target processes to kill:")
    for pid, comm, cmdline in to_kill:
        print(f"  PID {pid} ({comm}): {cmdline[:120]}")
        
    if not to_kill:
        print("No processes to kill.")
        return

    # Kill them
    killed_count = 0
    for pid, comm, _ in to_kill:
        try:
            os.kill(pid, signal.SIGKILL)
            killed_count += 1
        except Exception as e:
            print(f"Failed to kill {pid}: {e}")
            
    print(f"Successfully killed {killed_count} processes.")

if __name__ == '__main__':
    main()
